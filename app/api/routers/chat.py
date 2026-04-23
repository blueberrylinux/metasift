"""Chat streaming — Phase 2 slice 1.

Single endpoint: POST /chat/stream. Iterates the LangGraph agent via
`agent.stream(..., stream_mode="updates")` and demuxes node-update dicts into
four SSE frame types — `token`, `tool_call`, `tool_result`, `final` — plus an
`error` frame on failure.

No persistence yet (slice 2). No reload endpoint yet (slice 4). The agent is
built lazily on the first request and cached module-globally; an LLM-config
change in this slice would require a server restart.

Reference for the demux: `app/main.py::1431-1488` (Streamlit sync version).
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.api.schemas import ChatMessage, ChatStreamRequest

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Agent singleton ────────────────────────────────────────────────────────

_agent: Any = None
_agent_lock = threading.Lock()


def _get_agent() -> Any:
    """Build once, cache forever (for this slice). Slice 4 adds rebuild-on-config-change."""
    global _agent
    with _agent_lock:
        if _agent is None:
            from app.engines.agent import build_agent

            logger.info("Building Stew agent (first /chat/stream request)")
            _agent = build_agent()
        return _agent


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
        last_tool_content: str | None = None  # fallback if stream ends without a text-only AIMessage
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
                            content = (
                                m.content
                                if isinstance(m.content, str)
                                else str(m.content)
                            )
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

    loop.run_in_executor(None, run)

    while True:
        ev = await queue.get()
        if ev is None:
            return
        yield ev


# ── Route ──────────────────────────────────────────────────────────────────


@router.post("/stream")
async def chat_stream(req: ChatStreamRequest) -> EventSourceResponse:
    """SSE stream of the agent's response to a single user question.

    Body: `{question: str, history?: [{role, content}]}`.

    Each SSE event carries `event: <type>` and `data: <json>` where type is
    one of `token`, `tool_call`, `tool_result`, `final`, `error`. Stream ends
    after `final` or `error`.

    Slice 1 is stateless — `history` is echo-only, nothing is persisted.
    Slice 2 wires conversation IDs and SQLite writes.
    """

    async def events() -> AsyncIterator[dict[str, str]]:
        async for ev in stream_agent_events(req.question, req.history):
            yield {"event": ev["type"], "data": json.dumps(ev)}

    return EventSourceResponse(events())
