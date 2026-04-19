"""MetaSift — Streamlit entry point.

Chat-first UX with a sidebar for metrics and controls.
Run: `uv run streamlit run app/main.py`
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.clients import duck, openmetadata
from app.config import settings
from app.engines import agent as agent_mod
from app.engines import analysis, cleaning

LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
PAGE_ICON = str(LOGO_PATH) if LOGO_PATH.exists() else "🧹"
LOGO_B64 = base64.b64encode(LOGO_PATH.read_bytes()).decode() if LOGO_PATH.exists() else ""

st.set_page_config(page_title="MetaSift", page_icon=PAGE_ICON, layout="wide")

# Claude-style chat: user messages right-aligned bubbles, assistant on the left
# with avatar. We render user messages as custom HTML and leave assistant
# messages to st.chat_message.
st.markdown(
    """
<style>
.user-bubble {
    display: flex;
    justify-content: flex-end;
    margin: 0.55rem 0 0.25rem 0;
}
.user-bubble > div {
    background: rgba(255, 255, 255, 0.06);
    color: inherit;
    padding: 0.7rem 1rem;
    border-radius: 1.1rem 1.1rem 0.25rem 1.1rem;
    max-width: 78%;
    word-wrap: break-word;
    white-space: pre-wrap;
    line-height: 1.45;
    font-size: 0.98rem;
}
</style>
    """,
    unsafe_allow_html=True,
)


def _render_user(text: str) -> None:
    """Render a user message as a right-aligned bubble (Claude-style)."""
    safe = html.escape(text).replace("\n", "<br>")
    st.markdown(
        f'<div class="user-bubble"><div>{safe}</div></div>',
        unsafe_allow_html=True,
    )


def _render_assistant(text: str) -> None:
    """Render an assistant message Claude-style: no avatar, no bubble, just
    text flowing left-aligned. A small bottom spacer gives breathing room."""
    st.markdown(text)
    st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)


def _scroll_to_bottom() -> None:
    """Inject a tiny component that forces the page to scroll to the latest
    message. Uses components.html because inline <script> is sanitized."""
    components.html(
        """
        <script>
            const doc = window.parent.document;
            const scroller = doc.querySelector('section[tabindex="0"]') ||
                             doc.querySelector('section.main') ||
                             doc.scrollingElement;
            if (scroller) {
                scroller.scrollTo({top: scroller.scrollHeight, behavior: 'smooth'});
            }
        </script>
        """,
        height=0,
    )


# Strip inline tool-call JSON that some models emit as text instead of a
# structured tool call. Matches `{"name": "...", "parameters": {...}}` and
# the `arguments` variant.
_TOOLCALL_JSON_RE = re.compile(
    r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"(?:parameters|arguments)"\s*:\s*\{[^}]*\}\s*\}',
    re.DOTALL,
)


def _extract_text(content) -> str:
    """Normalize LangChain message content to plain text and strip any leaked
    tool-call JSON fragments."""
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


SUGGESTIONS: list[tuple[str, str]] = [
    ("📊 What's my composite quality score?", "What's my composite quality score?"),
    ("🧹 Find stale descriptions", "Help me find stale descriptions in my catalog."),
    ("🏷️ Check for tag conflicts", "Are there any tag conflicts I should know about?"),
    ("📖 What is MetaSift?", "What is MetaSift and how does it work?"),
]


def _reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pop("pending_prompt", None)


if "messages" not in st.session_state:
    _reset_chat()

# Handle a stop request (button was clicked during a previous run).
# Clicking Stop in Streamlit triggers a rerun which cancels the in-flight
# stream; here we clean up the dangling user message so the UI doesn't
# look broken.
if st.session_state.pop("stop_requested", False):
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        st.session_state.messages.append({"role": "assistant", "content": "_⏹ Stopped._"})
    st.session_state.pop("pending_prompt", None)


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    if LOGO_B64:
        st.markdown(
            f"""
            <div style="text-align: center; margin: -0.9rem 0 0.25rem 0;">
                <img src="data:image/png;base64,{LOGO_B64}" width="92"
                     style="border-radius: 10px;" />
                <h2 style="margin: 0.35rem 0 0 0; font-size: 1.55rem;">MetaSift</h2>
                <p style="margin: 0.15rem 0 0.6rem 0; opacity: 0.55; font-size: 0.82rem;">
                    AI-powered metadata analyst &amp; steward
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("## 🧹 MetaSift")
        st.caption("AI-powered metadata analyst & steward")

    if st.button("➕ New chat", use_container_width=True, help="Start a fresh chat"):
        _reset_chat()
        st.rerun()

    st.divider()

    # Live health check (drives metric rendering)
    om_ok = openmetadata.health_check()

    if om_ok:
        try:
            score = analysis.composite_score()
            st.metric("Composite score", f"{score['composite']}%")
            m1, m2 = st.columns(2)
            m1.metric("Coverage", f"{score['coverage']}%")
            m2.metric("Accuracy", f"{score['accuracy']}%", help="Non-stale descriptions")
            m3, m4 = st.columns(2)
            m3.metric("Consistency", f"{score['consistency']}%", help="Conflict-free tags")
            m4.metric("Quality", f"{score['quality']}%", help="Mean description quality")

            with st.expander("📊 Coverage by schema", expanded=False):
                cov_df = analysis.documentation_coverage()
                if len(cov_df):
                    st.bar_chart(
                        cov_df.set_index("schema")["coverage_pct"],
                        height=220,
                    )
                else:
                    st.caption("_No data yet — click Refresh metadata._")
        except Exception:
            st.caption("_Click Refresh metadata to populate metrics._")
    else:
        st.caption("_Metrics appear once OpenMetadata is connected._")

    st.divider()

    if st.button("🔄 Refresh metadata", use_container_width=True):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            with st.spinner("Pulling metadata..."):
                counts = duck.refresh_all()
            st.success(
                f"Loaded {counts.get('om_tables', 0)} tables, {counts.get('om_columns', 0)} columns"
            )
            st.rerun()

    if st.button(
        "🔬 Deep scan",
        use_container_width=True,
        help="Run stale-description + quality-scoring analysis (LLM calls — takes ~30s)",
    ):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            progress = st.progress(0, text="Starting deep scan…")

            def _tick(step: int, total: int, label: str) -> None:
                progress.progress(
                    min(step / max(total, 1), 1.0),
                    text=f"{label} ({step}/{total})",
                )

            try:
                summary = cleaning.run_deep_scan(progress_cb=_tick)
                progress.empty()
                st.success(
                    f"Analyzed {summary['analyzed']} tables · "
                    f"accuracy {summary['accuracy_pct']}% · "
                    f"quality {summary['quality_avg_1_5']}/5"
                )
                st.rerun()
            except Exception as e:
                progress.empty()
                st.error(f"Deep scan failed: {e}")

    if st.button(
        "🔐 PII scan",
        use_container_width=True,
        help="Heuristic classification of all columns (fast — no LLM calls)",
    ):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            try:
                with st.spinner("Scanning columns for PII…"):
                    summary = cleaning.run_pii_scan()
                st.success(
                    f"{summary['scanned']} columns · "
                    f"{summary['sensitive']} sensitive · "
                    f"{summary['nonsensitive']} non-sensitive · "
                    f"**{summary['gaps']} gap(s)**"
                )
            except Exception as e:
                st.error(f"PII scan failed: {e}")

    # Subtle status row at the bottom of the sidebar
    st.divider()
    s1, s2 = st.columns(2)
    s1.caption(f"OpenMetadata {'🟢' if om_ok else '🔴'}")
    s2.caption(f"LLM {'🟢' if settings.openrouter_api_key else '🔴'}")


# ── Main area ──────────────────────────────────────────────────────────────
# Pending prompts come from suggestion-chip clicks; they short-circuit the
# normal chat_input flow on the next rerun.
pending_prompt = st.session_state.pop("pending_prompt", None)
show_welcome = not st.session_state.messages and not pending_prompt

if show_welcome:
    # Centered hero
    st.markdown("<div style='height: 10vh'></div>", unsafe_allow_html=True)
    st.markdown(
        "<h1 style='text-align: center; font-size: 2.6rem; margin-bottom: 0.2rem;'>"
        "🧙 Meet Stew</h1>"
        "<p style='text-align: center; opacity: 0.65; font-size: 1.05rem;'>"
        "your metadata wizard — ask anything about your catalog</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='height: 2rem'></div>", unsafe_allow_html=True)

    # 2×2 suggestion grid
    sc1, sc2 = st.columns(2)
    sc3, sc4 = st.columns(2)
    columns = [sc1, sc2, sc3, sc4]
    for (label, prompt_text), col in zip(SUGGESTIONS, columns, strict=True):
        if col.button(label, use_container_width=True, key=f"suggest_{label}"):
            st.session_state.pending_prompt = prompt_text
            st.rerun()
else:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            _render_user(msg["content"])
        else:
            _render_assistant(msg["content"])

# Small stop button — sits right above the chat input, right-aligned.
# Visible only once a conversation has started (nothing to stop on welcome).
if st.session_state.messages:
    _, stop_slot = st.columns([7, 1])
    with stop_slot:
        if st.button(
            "⏹ Stop",
            use_container_width=True,
            key="chat_stop_btn",
            help="Stop Stew mid-reply",
        ):
            st.session_state.stop_requested = True
            st.rerun()

# Always-present chat input (lives at the bottom)
user_input = pending_prompt or st.chat_input("Ask Stew…")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    _render_user(user_input)

    if "agent" not in st.session_state:
        try:
            with st.spinner("Summoning Stew…"):
                st.session_state.agent = agent_mod.build_agent()
        except Exception as e:
            err = f"Couldn't build the agent: {e}. Check your LLM API key in `.env`."
            st.error(err)
            st.session_state.messages.append({"role": "assistant", "content": err})
            st.stop()

    lc_messages = [
        HumanMessage(content=m["content"])
        if m["role"] == "user"
        else AIMessage(content=m["content"])
        for m in st.session_state.messages
    ]

    last_tool_content: str | None = None
    final_reply: str | None = None
    try:
        with st.spinner("Stew is thinking…"):
            for chunk in st.session_state.agent.stream(
                {"messages": lc_messages},
                config={"recursion_limit": 15},
                stream_mode="updates",
            ):
                for node_data in chunk.values():
                    if not isinstance(node_data, dict):
                        continue
                    for m in node_data.get("messages", []):
                        if isinstance(m, ToolMessage) and m.content:
                            last_tool_content = (
                                m.content if isinstance(m.content, str) else str(m.content)
                            )
                        elif isinstance(m, AIMessage):
                            text = _extract_text(m.content)
                            tool_calls = getattr(m, "tool_calls", None) or []
                            if text and not tool_calls:
                                final_reply = text
        if final_reply:
            reply = final_reply
        elif last_tool_content:
            reply = (
                f"{last_tool_content}\n\n"
                f"_(Tip: I got into a thinking loop — showing you the info I gathered.)_"
            )
        else:
            reply = "_(empty response)_"
    except Exception as e:
        # Recursion / timeout: fall back to the last tool result we saw
        if last_tool_content:
            reply = (
                f"{last_tool_content}\n\n"
                f"_(I hit a thinking loop — here's the info I gathered before stopping.)_"
            )
        else:
            reply = f"⚠️ Something went wrong: `{e}`"

    _render_assistant(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})

    # If the message came from a suggestion chip, re-render to swap the
    # welcome hero for the chat view cleanly.
    if pending_prompt:
        st.rerun()

# Auto-scroll to the newest message on every rerun that has history
if st.session_state.messages:
    _scroll_to_bottom()
