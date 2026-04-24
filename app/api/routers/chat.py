"""Chat — Phase 2 slices 1 + 2.

* Slice 1: POST /chat/stream. Iterates the LangGraph agent via
  `agent.stream(..., stream_mode="updates")` and demuxes node-update dicts
  into SSE frame types `token`, `tool_call`, `tool_result`, `final`, `error`.
* Slice 2: Conversation CRUD + server-side history + persistence:
    - POST   /chat/conversations           create
    - GET    /chat/conversations           list (most recent first)
    - GET    /chat/conversations/{id}      full history including tool_trace
  When /chat/stream is called with a `conversation_id`, history is loaded
  from SQLite (request-supplied `history` is ignored) and both the user
  question and assistant reply are appended on the final frame.

No reload endpoint yet (slice 4). The agent is built lazily on the first
request and cached module-globally; an LLM-config change requires a server
restart until slice 4.

Reference for the stream demux: `app/main.py::1431-1488` (Streamlit sync).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.api import errors, store
from app.api.schemas import (
    ChatMessage,
    ChatStreamRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummary,
    CreateConversationRequest,
    PersistedMessage,
    RenameConversationRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])

# Dedicated pool so agent.stream() invocations — which can stall for tens of
# seconds on a slow LLM — never exhaust the default asyncio executor that
# FastAPI uses for `def` endpoints. A handful of concurrent chats is more
# than the demo usage pattern; sizing at 4 is deliberately conservative so
# a runaway burst can't spawn dozens of concurrent LLM sessions either.
_CHAT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-")

# Hard upper bound for a single agent turn. The ChatOpenAI client has its
# own 60s per-call timeout, but a tool-heavy turn can make many calls back
# to back — this caps the full turn so the UI never waits forever.
_CHAT_WATCHDOG_S = 180.0


# ── Agent singleton ────────────────────────────────────────────────────────

_agent: Any = None
_agent_lock = threading.Lock()


def _get_agent() -> Any:
    """Build once, cache until invalidated. `invalidate_agent()` drops the
    cache so an LLM-config change rebuilds with the new model on the next
    /chat/stream call."""
    global _agent
    with _agent_lock:
        if _agent is None:
            from app.engines.agent import build_agent

            logger.info("Building Stew agent (first /chat/stream request)")
            _agent = build_agent()
        return _agent


def invalidate_agent() -> None:
    """Drop the cached agent so the next request rebuilds. Called from the
    /llm router whenever the model (or eventually api_key / base_url) changes
    so the new config takes effect without a process restart."""
    global _agent
    with _agent_lock:
        _agent = None


# ── LangGraph → SSE frame adapter ─────────────────────────────────────────

# Mirror the Streamlit helper so inline tool-call JSON emitted as text gets
# stripped out of `token`/`final` frames. Same regex as app/main.py::196.
_TOOLCALL_JSON_RE = re.compile(
    r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"(?:parameters|arguments)"\s*:\s*\{[^}]*\}\s*\}',
    re.DOTALL,
)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    else:
        text = str(content)
    return _TOOLCALL_JSON_RE.sub("", text).strip()


def _history_to_lc(history: list[ChatMessage] | None) -> list[Any]:
    """Turn the request's `history` into LangChain message objects. User and
    assistant only — system prompt is baked into the agent already."""
    if not history:
        return []
    out: list[Any] = []
    for m in history:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
    return out


async def stream_agent_events(
    question: str,
    history: list[ChatMessage] | None,
) -> AsyncIterator[dict[str, Any]]:
    """Run the agent in a worker thread and yield SSE frames as asyncio events.

    Four frame types — `token`, `tool_call`, `tool_result`, `final` — plus
    `error` on uncaught exception. The sync `agent.stream()` call is pushed off
    the event loop with `run_in_executor`; events cross the thread boundary
    through `loop.call_soon_threadsafe` into an `asyncio.Queue` consumed here.
    """
    agent = _get_agent()
    lc_messages = _history_to_lc(history) + [HumanMessage(content=question)]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def emit(ev: dict[str, Any] | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def run() -> None:
        seen_tool_call_ids: set[str] = set()
        final_text: str | None = None
        last_tool_content: str | None = (
            None  # fallback if stream ends without a text-only AIMessage
        )
        try:
            for chunk in agent.stream(
                {"messages": lc_messages},
                config={"recursion_limit": 15},
                stream_mode="updates",
            ):
                for node_data in chunk.values():
                    if not isinstance(node_data, dict):
                        continue
                    for m in node_data.get("messages", []):
                        if isinstance(m, ToolMessage):
                            tc_id = getattr(m, "tool_call_id", None) or ""
                            content = m.content if isinstance(m.content, str) else str(m.content)
                            last_tool_content = content
                            emit(
                                {
                                    "type": "tool_result",
                                    "id": tc_id,
                                    "content": content,
                                }
                            )
                        elif isinstance(m, AIMessage):
                            tool_calls = getattr(m, "tool_calls", None) or []
                            for tc in tool_calls:
                                tc_id = tc.get("id") or f"_anon_{len(seen_tool_call_ids)}"
                                if tc_id in seen_tool_call_ids:
                                    continue
                                seen_tool_call_ids.add(tc_id)
                                emit(
                                    {
                                        "type": "tool_call",
                                        "id": tc_id,
                                        "name": tc.get("name", "unknown"),
                                        "args": tc.get("args", {}),
                                    }
                                )
                            text = _extract_text(m.content)
                            if text:
                                if tool_calls:
                                    # pre-tool reasoning — stream as token frame
                                    emit({"type": "token", "text": text})
                                else:
                                    # AIMessage with text and no tool_calls = final
                                    final_text = text
            # Parity with app/main.py::1462-1470: if the graph ended without a
            # text-only AIMessage, surface the last tool result so the UI isn't blank.
            emit({"type": "final", "text": final_text or last_tool_content or ""})
        except Exception as e:
            logger.exception("agent stream failed")
            emit({"type": "error", "message": str(e)})
        finally:
            emit(None)  # sentinel

    loop.run_in_executor(_CHAT_EXECUTOR, run)

    deadline = loop.time() + _CHAT_WATCHDOG_S
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            logger.warning("chat stream hit watchdog timeout")
            yield {
                "type": "error",
                "message": f"Agent turn exceeded {int(_CHAT_WATCHDOG_S)}s watchdog — check server logs.",
            }
            return
        try:
            ev = await asyncio.wait_for(queue.get(), timeout=remaining)
        except TimeoutError:
            continue
        if ev is None:
            return
        yield ev


# ── Conversation CRUD ─────────────────────────────────────────────────────


def _row_to_summary(row: dict[str, Any]) -> ConversationSummary:
    return ConversationSummary.model_validate(row)


@router.post("/conversations", response_model=ConversationSummary, status_code=201)
def create_conversation(req: CreateConversationRequest) -> ConversationSummary:
    """Start a new conversation. Empty by default — first message comes via
    /chat/stream with this id."""
    convo_id = store.new_conversation(title=req.title)
    detail = store.get_conversation(convo_id)
    assert detail is not None  # just created
    return _row_to_summary(detail["conversation"])


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(limit: int = 50) -> ConversationListResponse:
    """Most recently updated conversations first. Cheap — no messages joined."""
    rows = store.list_conversations(limit=limit)
    return ConversationListResponse(rows=[_row_to_summary(r) for r in rows])


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(conversation_id: str) -> ConversationDetailResponse:
    """Full transcript for a conversation, tool traces included."""
    detail = store.get_conversation(conversation_id)
    if detail is None:
        raise errors.conversation_not_found(conversation_id)
    return ConversationDetailResponse(
        conversation=_row_to_summary(detail["conversation"]),
        messages=[PersistedMessage.model_validate(m) for m in detail["messages"]],
    )


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def rename_conversation(
    conversation_id: str, req: RenameConversationRequest
) -> ConversationSummary:
    """Rename a conversation. An empty / whitespace-only title becomes NULL
    so the list falls back to the 'Untitled conversation' placeholder."""
    renamed = store.rename_conversation(conversation_id, req.title)
    if not renamed:
        raise errors.conversation_not_found(conversation_id)
    detail = store.get_conversation(conversation_id)
    assert detail is not None  # guaranteed by the rename returning True
    return _row_to_summary(detail["conversation"])


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str) -> None:
    """Delete a conversation and its messages. 204 on success, 404 if the id
    was already gone — messages cascade via the FK on `messages.conversation_id`."""
    deleted = store.delete_conversation(conversation_id)
    if not deleted:
        raise errors.conversation_not_found(conversation_id)
    return None


# ── Streaming chat ────────────────────────────────────────────────────────


def _history_from_store(convo_id: str) -> list[ChatMessage]:
    """Pull a conversation's prior user/assistant turns from SQLite and shape
    them for `stream_agent_events`. tool_trace is intentionally dropped here —
    the agent replays on content alone, just like the Streamlit session does."""
    detail = store.get_conversation(convo_id)
    if detail is None:
        raise errors.conversation_not_found(convo_id)
    return [ChatMessage(role=m["role"], content=m["content"]) for m in detail["messages"]]


@router.post("/stream")
async def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """SSE stream of the agent's response to a single user question.

    Body: `{question, conversation_id?, history?}`.

    If `conversation_id` is set, prior turns are loaded from SQLite and the
    user question + assistant reply (with tool_trace) are appended after the
    final frame. If it's unset, `history` is used as-is and nothing is saved.

    Emits SSE events with `event: <type>` where type is one of `token`,
    `tool_call`, `tool_result`, `final`, `error`. Stream ends after `final`
    or `error`.

    404 is raised before the stream starts if `conversation_id` doesn't exist.
    Errors after streaming has begun arrive as an `error` frame (status 200 —
    can't change HTTP status mid-stream).
    """
    if req.conversation_id is not None:
        history = _history_from_store(req.conversation_id)
    else:
        history = req.history or []

    convo_id = req.conversation_id
    question = req.question

    async def events() -> AsyncIterator[dict[str, str]]:
        # Collect frames so we can write a coherent tool_trace + assistant
        # message once the stream closes. Mirrors `app/main.py::1481-1488`'s
        # tool_calls_by_id / tool_results_by_id shape.
        calls_by_id: dict[str, dict[str, Any]] = {}
        results_by_id: dict[str, str] = {}
        final_text: str = ""
        errored = False

        async for ev in stream_agent_events(question, history):
            etype = ev["type"]
            if etype == "tool_call":
                calls_by_id[ev["id"]] = {"name": ev["name"], "args": ev["args"]}
            elif etype == "tool_result":
                results_by_id[ev["id"]] = ev["content"]
            elif etype == "final":
                final_text = ev["text"]
            elif etype == "error":
                errored = True
            yield {"event": etype, "data": json.dumps(ev)}

        # Persist only if a conversation is attached AND the stream succeeded.
        # Failed runs leave no trace — retrying them repopulates cleanly.
        # Empty `final_text` still persists so the user's question is recorded.
        if convo_id and not errored:
            traces = [
                {
                    "tool": info["name"],
                    "args": info["args"],
                    "result": results_by_id.get(tc_id, ""),
                }
                for tc_id, info in calls_by_id.items()
            ]
            try:
                store.append_exchange(
                    convo_id,
                    user_content=question,
                    assistant_content=final_text,
                    tool_trace=traces or None,
                )
            except Exception as e:
                logger.exception(f"failed to persist conversation {convo_id}: {e}")

    return EventSourceResponse(events())
