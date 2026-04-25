"""Parity check between the direct-agent path (Streamlit) and the FastAPI
SSE adapter (React).

Asks the same question both ways, demuxes tool calls, and diffs the
tool-name sequence. Temperature is 0.2 so results aren't bit-deterministic,
but canonical questions ("what is metasift?") reliably fire the same tool
sequence on both paths. Mismatch → exit 1.

Caveat — the script and the FastAPI server are SEPARATE processes, and
the LLM override (`llm._override`) is a module-level singleton. If the
server's model has been changed via POST /llm/model but the script is
using `.env` defaults, the two paths will use different models and may
diverge. The script prints the active model on each side before running
so divergence is always visible. For a meaningful parity run, either
leave both at defaults, or call POST /llm/model first and ensure your
`.env` is set to the same model.

Usage:
    uv run python scripts/port_parity.py
    uv run python scripts/port_parity.py --question "list my tables"
    uv run python scripts/port_parity.py --host http://127.0.0.1:8000

Requires the FastAPI server to be running for the SSE path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

import httpx
from langchain_core.messages import (  # noqa: F401 (ToolMessage unused but kept for symmetry)
    AIMessage,
    HumanMessage,
)


def direct_trace(question: str) -> list[dict[str, Any]]:
    """Invoke the LangGraph agent in-process — what app/main.py does inline
    during a Streamlit turn."""
    from app.engines.agent import build_agent

    agent = build_agent()
    calls: dict[str, dict[str, Any]] = {}
    for chunk in agent.stream(
        {"messages": [HumanMessage(content=question)]},
        config={"recursion_limit": 15},
        stream_mode="updates",
    ):
        for node_data in chunk.values():
            if not isinstance(node_data, dict):
                continue
            for m in node_data.get("messages", []):
                if isinstance(m, AIMessage):
                    for tc in getattr(m, "tool_calls", None) or []:
                        tc_id = tc.get("id") or f"_anon_{len(calls)}"
                        if tc_id in calls:
                            continue
                        calls[tc_id] = {"name": tc.get("name"), "args": tc.get("args", {})}
    return list(calls.values())


_SSE_BLOCK_SPLIT = re.compile(r"\r\n\r\n|\n\n|\r\r")
_SSE_LINE_SPLIT = re.compile(r"\r\n|\n|\r")


def _parse_block(block: str) -> dict[str, Any] | None:
    data_lines = []
    for line in _SSE_LINE_SPLIT.split(block):
        if line.startswith("data: "):
            data_lines.append(line[6:])
        elif line.startswith("data:"):
            data_lines.append(line[5:])
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None


def sse_trace(question: str, host: str) -> list[dict[str, Any]]:
    """Invoke /chat/stream over HTTP and demux the SSE frames — what the
    React client does. Raises `RuntimeError` on an in-band `error` frame so
    the harness fails the run instead of silently passing on a 200 response
    that produced an error."""
    url = f"{host.rstrip('/')}/api/v1/chat/stream"
    calls: dict[str, dict[str, Any]] = {}

    def absorb(frame: dict[str, Any] | None) -> None:
        if not frame:
            return
        ftype = frame.get("type")
        if ftype == "error":
            raise RuntimeError(f"SSE error frame: {frame.get('message') or frame}")
        if ftype == "tool_call":
            tc_id = frame["id"]
            if tc_id not in calls:
                calls[tc_id] = {"name": frame["name"], "args": frame.get("args", {})}

    with httpx.stream(
        "POST",
        url,
        json={"question": question},
        headers={"Accept": "text/event-stream"},
        timeout=120.0,
    ) as r:
        r.raise_for_status()
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while True:
                m = _SSE_BLOCK_SPLIT.search(buf)
                if not m:
                    break
                block = buf[: m.start()]
                buf = buf[m.end() :]
                absorb(_parse_block(block))
        if buf.strip():
            absorb(_parse_block(buf))
    return list(calls.values())


def signature(trace: list[dict[str, Any]]) -> list[str]:
    """Compact comparable form — just the tool names in call order."""
    return [c["name"] for c in trace]


def _print_trace(label: str, trace: list[dict[str, Any]]) -> None:
    print(f"\n— {label} —")
    print(f"tools: {signature(trace)}")
    for c in trace:
        print(f"  {c['name']}({json.dumps(c['args'])})")


def _direct_model() -> str:
    """Active model in *this* Python process. Resolution matches llm._build —
    override wins, else .env toolcall default."""
    from app.clients import llm
    from app.config import settings

    o = llm.get_override()
    if o and o.model:
        return o.model
    return settings.model_toolcall


def _server_model(host: str) -> str | None:
    """Active model on the server. Pulled from /llm/catalog — the script
    prints both sides so divergence is visible before running the trace."""
    try:
        r = httpx.get(f"{host.rstrip('/')}/api/v1/llm/catalog", timeout=10.0)
        r.raise_for_status()
        return r.json().get("current")
    except Exception as e:
        print(f"warning: couldn't read server model: {e}", file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--question",
        default="what is metasift?",
        help="Prompt to send through both paths (default: %(default)r)",
    )
    p.add_argument(
        "--host",
        default="http://127.0.0.1:8000",
        help="FastAPI server base URL (default: %(default)s)",
    )
    args = p.parse_args()

    print(f"question: {args.question}")
    print(f"host:     {args.host}")

    direct_model = _direct_model()
    server_model = _server_model(args.host)
    print(f"direct process uses:  {direct_model}")
    print(f"server process uses:  {server_model}")
    if server_model and server_model != direct_model:
        print(
            "⚠ model mismatch between direct and server — parity can still "
            "pass for canonical questions but treat mismatches with suspicion."
        )

    dt = direct_trace(args.question)
    _print_trace("direct (Streamlit path)", dt)

    st = sse_trace(args.question, args.host)
    _print_trace("SSE (React path)", st)

    print()
    if signature(dt) == signature(st):
        print("PASS — tool-name sequence matches across both paths")
        return 0
    print("FAIL — tool-name sequence differs")
    print(f"  direct: {signature(dt)}")
    print(f"  sse:    {signature(st)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
