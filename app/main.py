"""MetaSift — Streamlit entry point.

Chat-first UX with a sidebar for metrics and controls.
Run: `uv run streamlit run app/main.py`
"""

from __future__ import annotations

import base64
import contextlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.clients import duck, llm, openmetadata
from app.config import settings
from app.engines import agent as agent_mod
from app.engines import analysis, cleaning, report, stewardship, viz
from app.engines.stewardship import Suggestion

_PII_TAG_OPTIONS = ["PII.Sensitive", "PII.NonSensitive", "PII.None"]

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
/* ── Compact sidebar — fit all controls in one frame ───────────────── */
section[data-testid="stSidebar"] hr {
    margin: 0.4rem 0 !important;
}
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] .stDownloadButton > button {
    padding: 0.25rem 0.75rem;
    min-height: 1.9rem;
    font-size: 0.88rem;
}
section[data-testid="stSidebar"] div[data-testid="stMetricValue"] {
    font-size: 1.1rem;
}
section[data-testid="stSidebar"] div[data-testid="stMetricLabel"] p {
    font-size: 0.72rem;
}
/* Pull sidebar content flush to the top of the panel — Streamlit defaults
   to ~6rem of top padding via nav/header spacing; kill it. */
section[data-testid="stSidebar"] > div:first-child,
section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding-top: 0 !important;
}
section[data-testid="stSidebarHeader"],
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
    padding: 0.15rem 0.5rem !important;
    min-height: 0 !important;
    height: auto !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] {
    padding-top: 0 !important;
}
/* MetaSift header — horizontal logo + text, flush to the very top */
.ms-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0 0 0.5rem 0;
    margin-top: -1.25rem;
}
.ms-header img {
    width: 58px;
    height: 58px;
    border-radius: 10px;
    flex-shrink: 0;
    object-fit: contain;
}
.ms-header .ms-title {
    font-size: 1.55rem;
    font-weight: 700;
    line-height: 1.1;
    letter-spacing: -0.01em;
}
.ms-header .ms-tag {
    opacity: 0.6;
    font-size: 0.72rem;
    line-height: 1.2;
    margin-top: 0.15rem;
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


_TRACE_RESULT_LIMIT = 2500


def _render_traces(traces: list[dict], key_prefix: str) -> None:
    """Render an expander listing the tool calls Stew made for this reply.

    Makes the agent's work inspectable: what tool, with what args, and the
    raw result. Long results are truncated to keep the UI tidy.
    """
    if not traces:
        return
    label = f"🔍 Show your work · {len(traces)} step{'s' if len(traces) != 1 else ''}"
    with st.expander(label, expanded=False):
        for i, t in enumerate(traces, start=1):
            st.markdown(f"**Step {i} — `{t['tool']}`**")
            args = t.get("args") or {}
            if args:
                st.code(json.dumps(args, indent=2, default=str), language="json")
            result = t.get("result") or ""
            if isinstance(result, list):
                result = "\n".join(
                    p.get("text", "") if isinstance(p, dict) else str(p) for p in result
                )
            result = str(result)
            truncated = len(result) > _TRACE_RESULT_LIMIT
            body = result[:_TRACE_RESULT_LIMIT] + ("…" if truncated else "")
            st.markdown(body or "_(empty result)_")
            if truncated:
                st.caption(f"_Truncated — full result was {len(result):,} chars._")
            if i < len(traces):
                st.divider()


def _render_assistant(text: str, traces: list[dict] | None = None) -> None:
    """Render an assistant message Claude-style: no avatar, no bubble, just
    text flowing left-aligned. Optionally follows with a 'show your work'
    expander listing the tool calls that produced this reply."""
    st.markdown(text)
    if traces:
        _render_traces(traces, key_prefix=str(id(text)))
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
    ("📊 What's my composite score?", "What's my composite score?"),
    ("🧹 Find stale descriptions", "Help me find stale descriptions in my catalog."),
    ("🏷️ Check for tag conflicts", "Are there any tag conflicts I should know about?"),
    ("📖 What is MetaSift?", "What is MetaSift and how does it work?"),
]


# ── Welcome / Guide dialog ─────────────────────────────────────────────────
# Shown automatically on first load of the session, and on-demand via the
# 📖 Guide sidebar button. "welcome_seen" is session-scoped (not persisted
# to disk) — a fresh browser session gets the intro again, which is the
# right default for a shared demo environment.


@st.dialog("Welcome to MetaSift", width="large")
def _welcome_dialog() -> None:
    st.markdown(
        """
**MetaSift** is an AI-powered metadata analyst and steward for OpenMetadata.

Documentation coverage is a lie — a catalog can be 100% documented and still
full of wrong, stale, or conflicting metadata. MetaSift introduces a **Composite Score** that measures what actually matters.

### The four engines

- **Analysis** — aggregate SQL analytics over your catalog (coverage, tag
  conflicts, lineage impact, composite score).
- **Stewardship** — auto-documents undocumented tables, detects PII, and
  recommends data quality tests that should exist but don't.
- **Cleaning** — detects stale descriptions, scores quality 1–5, explains
  failing DQ checks in plain English, and quantifies DQ blast radius
  across lineage.
- **Interface** — meet **Stew**, the AI steward you'll chat with. Ask
  anything in natural language.

### Quick start

1. Click **🔄 Refresh metadata** in the sidebar to pull your catalog into
   MetaSift's in-memory store.
2. Run **🔬 Deep scan** (stale detection + quality scoring),
   **🔐 PII scan**, or **🧪 Explain DQ failures** to populate the richer
   metrics.
3. Ask Stew things like _"what's my composite score?"_, _"find tag
   conflicts"_, or _"why is my email_not_null check failing?"_.

### Things worth trying

- Click **📊 Visualizations** once metadata is loaded — 9 interactive
  tabs including lineage DAG, blast radius, DQ risk, and DQ gaps.
- Click **📋 Review queue** to approve / edit / reject MetaSift's
  suggested descriptions and PII tags before anything is written back
  to OpenMetadata.
- Click **📄 Export report** to download a markdown summary of catalog
  health suitable for sharing with a data team.

_This guide is always reachable via the **📖 Guide** button in the sidebar._
        """
    )
    st.divider()
    _, right = st.columns([4, 1])
    with right:
        if st.button("Got it", type="primary", width="stretch"):
            st.session_state.welcome_seen = True
            st.session_state.show_guide = False
            st.rerun()


# ── API key override dialog ────────────────────────────────────────────────
# Lets a user paste their own provider's API key without touching .env.
# MetaSift's LLM client accepts any OpenAI-compatible endpoint, so users can
# pick from OpenRouter / OpenAI / Gemini / Groq / Ollama / Custom. Overrides
# are session-scoped (cleared on refresh) and never persisted to disk.


_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "OpenRouter (default)": {
        "base_url": "https://openrouter.ai/api/v1",
        "model_hint": "meta-llama/llama-3.3-70b-instruct:free",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model_hint": "gpt-4o-mini",
    },
    "Gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model_hint": "gemini-2.0-flash",
    },
    "Groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model_hint": "llama-3.3-70b-versatile",
    },
    "Ollama (local)": {
        "base_url": "http://localhost:11434/v1",
        "model_hint": "llama3:latest",
    },
    "Custom": {
        "base_url": "",
        "model_hint": "",
    },
}


# Curated model shortlist per provider — what the chat-area model picker
# shows in its dropdown. Free-tier / popular picks only; power users can
# type a custom id via the "Other…" option. Keep each list ≤ 10 entries so
# the dropdown doesn't turn into a scroll-scape.
_MODEL_CATALOG: dict[str, list[str]] = {
    "OpenRouter (default)": [
        "meta-llama/llama-3.3-70b-instruct:free",
        "mistralai/mistral-nemo:free",
        "google/gemini-2.0-flash-exp:free",
        "deepseek/deepseek-chat-v3:free",
        "qwen/qwen-2.5-72b-instruct:free",
        "meta-llama/llama-3.1-8b-instruct:free",
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o-mini",
    ],
    "OpenAI": [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1",
        "gpt-4.1-mini",
        "o3-mini",
    ],
    "Gemini": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ],
    "Groq": [
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    "Ollama (local)": [
        "llama3",
        "llama3.2",
        "qwen2.5",
        "mistral",
        "phi3",
    ],
    "Custom": [],
}

_CUSTOM_MODEL_SENTINEL = "Other — type a custom model id"


# One-line description per task type, rendered in the Advanced expander so
# power users understand what each per-task override actually routes.
_TASK_ROUTING_LABELS: dict[str, str] = {
    "toolcall": "Stew's tool-calling — agent picks which tool to invoke",
    "reasoning": "Complex analysis — DQ explanations, failure root-cause",
    "description": "Generating new table descriptions",
    "stale": "Stale-description detection (compares desc vs columns)",
    "scoring": "Description quality scoring (1–5)",
    "classification": "PII classification fallback (when heuristic misses)",
}


def _current_model_for_picker(override) -> str | None:
    """What the model picker should show as 'selected' given the override
    and the provider preset. Falls back to the preset's model hint when no
    override-model is set so the dropdown never shows an empty state."""
    if override and override.model:
        return override.model
    provider = _preset_for_url(override.base_url if override else None)
    return _PROVIDER_PRESETS.get(provider, {}).get("model_hint") or None


def _model_picker_bar() -> None:
    """Compact bar above the chat area — provider + model dropdown + status.

    Lets the user swap models without re-pasting the API key. Updates the
    session's LLM override via llm.set_model() on change; preserves whatever
    api_key / base_url the override already carries. When the catalog
    doesn't include the current model (e.g. a custom id from the API key
    modal), the 'Other…' sentinel shows that and a text input lets the user
    edit it in place.
    """
    override = llm.get_override()
    provider = _preset_for_url(override.base_url if override else None)
    catalog = _MODEL_CATALOG.get(provider, []) or []
    options = [*catalog, _CUSTOM_MODEL_SENTINEL]

    current = _current_model_for_picker(override)
    is_custom = bool(current) and current not in catalog
    default_idx = (
        options.index(current) if current in options else (len(options) - 1 if is_custom else 0)
    )

    icon_col, model_col, provider_col = st.columns([1, 6, 3])
    with icon_col:
        st.markdown(
            "<div style='font-size: 1.4rem; line-height: 2.1rem; text-align: center;'>🧠</div>",
            unsafe_allow_html=True,
        )
    with model_col:
        picked = st.selectbox(
            "Model",
            options=options,
            index=default_idx,
            label_visibility="collapsed",
            key="chat_model_picker",
            help="Switches the model Stew uses for this session. All six task types share it.",
        )
    with provider_col:
        st.markdown(
            f"<div style='text-align: right; opacity: 0.65; line-height: 2.1rem;'>"
            f"<small>{provider}</small></div>",
            unsafe_allow_html=True,
        )

    # If 'Other…' is selected, surface a text input inline and use its value
    # as the effective pick. Empty custom → keep current.
    if picked == _CUSTOM_MODEL_SENTINEL:
        custom = st.text_input(
            "Custom model id",
            value=(current if is_custom else ""),
            placeholder=(
                _PROVIDER_PRESETS.get(provider, {}).get("model_hint")
                or "provider-specific model id"
            ),
            key="chat_model_picker_custom",
            label_visibility="collapsed",
        )
        effective = (custom or "").strip() or None
    else:
        effective = picked

    # Apply only when the user has settled on a concrete model that differs
    # from what's currently active. Treating `effective=None` as "no change"
    # is load-bearing: when the user selects "Other…" but hasn't typed yet,
    # `effective` is None while `current` is the preset hint — without this
    # guard we'd set_model(None), rerun, recompute `current` from the hint,
    # and loop indefinitely (thrashing get_llm.cache_clear on every pass).
    if effective and effective != current:
        llm.set_model(effective)
        st.rerun()


def _preset_for_url(base_url: str | None) -> str:
    """Match a base URL to a preset name for the sidebar status indicator.
    Falls back to 'Custom' for unknown endpoints."""
    if not base_url:
        return "OpenRouter (default)"
    normalized = base_url.rstrip("/").lower()
    for name, preset in _PROVIDER_PRESETS.items():
        preset_url = preset["base_url"].rstrip("/").lower()
        if preset_url and normalized == preset_url:
            return name
    return "Custom"


@st.dialog("Use your own API key", width="medium")
def _api_key_dialog() -> None:
    st.markdown(
        "MetaSift's LLM client works with any **OpenAI-compatible endpoint** — "
        "paste your provider's API key, pick a preset (or go custom), and MetaSift "
        "uses your key instead of the one in `.env`.\n\n"
        "Overrides are **session-scoped** — they clear when you refresh the tab. "
        "Keys are never written to disk."
    )

    current = llm.get_override()
    default_preset = _preset_for_url(current.base_url) if current else "OpenRouter (default)"
    preset_names = list(_PROVIDER_PRESETS.keys())
    preset_idx = preset_names.index(default_preset) if default_preset in preset_names else 0

    preset = st.selectbox(
        "Provider",
        options=preset_names,
        index=preset_idx,
        help="Picks a base URL and a model hint. 'Custom' leaves both blank for you to fill in.",
    )
    preset_config = _PROVIDER_PRESETS[preset]

    api_key = st.text_input(
        "API key",
        type="password",
        value=(current.api_key if current else ""),
        placeholder="sk-...",
        help="Your provider's API key. Never leaves this browser session.",
    )
    base_url = st.text_input(
        "Base URL",
        value=(current.base_url if current and current.base_url else preset_config["base_url"]),
        placeholder=preset_config["base_url"] or "https://...",
        help="The OpenAI-compatible endpoint. Auto-filled from the preset.",
    )
    model = st.text_input(
        "Model (optional)",
        value=(current.model if current and current.model else ""),
        placeholder=preset_config["model_hint"] or "provider-specific model id",
        help=(
            "Overrides the per-task model IDs from `.env`. Leave blank to keep the "
            "defaults (useful if your provider accepts OpenRouter model strings)."
        ),
    )

    st.caption(
        "💡 **Tool-calling reliability varies by model.** Best results with "
        "`gpt-4o-mini`, `gemini-2.0-flash`, `claude-3.5-sonnet`, or `llama-3.3-70b-instruct`. "
        "Smaller or older models (e.g. `llama-3.1-8b`) can loop on tool selection — "
        "MetaSift's agent caps at 25 iterations so you'll see an error, not a frozen app, "
        "but expect degraded chat quality."
    )

    with st.expander("⚙️ Advanced — per-task model routing", expanded=False):
        st.caption(
            "Route individual agent tasks to different models. Leave a row blank to use "
            "the shared model above. Handy for pairing a fast cheap model for tool-calling "
            "with a stronger model for reasoning-heavy tasks (DQ explanations, "
            "test recommendations)."
        )
        for task, description in _TASK_ROUTING_LABELS.items():
            current_task_model = llm.get_task_model(task) if current else None
            col_label, col_input = st.columns([2, 3])
            with col_label:
                st.markdown(
                    f"<div style='padding-top: 0.4rem; font-size: 0.85rem;'>"
                    f"<b>{task}</b><br>"
                    f"<span style='opacity: 0.6; font-size: 0.75rem;'>{description}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with col_input:
                new_task_model = st.text_input(
                    task,
                    value=current_task_model or "",
                    placeholder="(same as shared model)",
                    label_visibility="collapsed",
                    key=f"task_model__{task}",
                )
                new_clean = (new_task_model or "").strip() or None
                if new_clean != current_task_model:
                    llm.set_task_model(task, new_clean)
                    st.rerun()

        if current and current.per_task_models:
            st.divider()
            if st.button(
                "Reset per-task routing",
                help="Clear every per-task override — shared model applies to all tasks.",
            ):
                llm.clear_per_task_models()
                # Widget session-state keys persist across reruns independent of
                # _override — pop them so the text_inputs re-initialize to empty
                # instead of echoing the old values back into set_task_model on
                # the next render.
                for task in _TASK_ROUTING_LABELS:
                    st.session_state.pop(f"task_model__{task}", None)
                st.rerun()

    st.divider()

    status_col, clear_col, apply_col = st.columns([3, 1, 1])
    with status_col:
        if current:
            preset_label = _preset_for_url(current.base_url)
            model_label = current.model or "per-task defaults"
            st.caption(f"Active override: **{preset_label}** · `{model_label}`")
        else:
            st.caption("Currently running on `.env` defaults.")
    with clear_col:
        if st.button(
            "Clear",
            width="stretch",
            disabled=current is None,
            help="Drop the override and go back to `.env` defaults.",
        ):
            llm.clear_override()
            # Also wipe the per-task text_input widget state so reopening the
            # modal doesn't echo stale values back into set_task_model.
            for task in _TASK_ROUTING_LABELS:
                st.session_state.pop(f"task_model__{task}", None)
            st.session_state.show_api_key = False
            st.rerun()
    with apply_col:
        if st.button(
            "Use key",
            type="primary",
            width="stretch",
            disabled=not (api_key and api_key.strip()),
        ):
            try:
                llm.set_override(
                    api_key=api_key,
                    base_url=base_url or None,
                    model=model or None,
                )
                st.session_state.show_api_key = False
                st.rerun()
            except ValueError as e:
                st.error(f"{e}")


def _reset_chat() -> None:
    st.session_state.messages = []
    st.session_state.pop("pending_prompt", None)
    st.session_state.show_review = False
    st.session_state.show_viz = False


if "messages" not in st.session_state:
    _reset_chat()

# ── Review queue ───────────────────────────────────────────────────────────
# Pending suggestions from the cleaning engine (stale descriptions, stored in
# `cleaning_results`) and the PII engine (gaps between current and suggested
# tags, stored in `pii_results`). Rendered as a card list with per-row
# Accept / Edit / Reject buttons. Rejections are session-scoped — a fresh scan
# rebuilds the queue from scratch.


def _build_review_queue() -> list[dict]:
    """Collect pending suggestions from cleaning_results + pii_results.

    Returns a list of dicts, each with a stable `key`, the suggestion `kind`
    (`description` or `pii_tag`), target FQN/column, old and new values, and
    confidence + reason for display.
    """
    items: list[dict] = []

    # Stale descriptions
    try:
        stale = duck.query("""
            SELECT
                c.fqn,
                c.stale_reason,
                c.stale_confidence,
                c.stale_corrected,
                t.description AS current_description
            FROM cleaning_results c
            LEFT JOIN om_tables t ON t.fullyQualifiedName = c.fqn
            WHERE c.stale = TRUE
              AND c.stale_corrected IS NOT NULL
              AND length(c.stale_corrected) > 0
            ORDER BY c.stale_confidence DESC
        """)
        for _, r in stale.iterrows():
            items.append(
                {
                    "kind": "description",
                    "key": f"desc::{r['fqn']}",
                    "fqn": r["fqn"],
                    "old": r["current_description"] or "",
                    "new": r["stale_corrected"] or "",
                    "confidence": float(r["stale_confidence"] or 0.0),
                    "reason": r["stale_reason"] or "",
                }
            )
    except Exception:
        pass  # table doesn't exist yet (no deep scan run)

    # Auto-drafted descriptions for undocumented tables. Join against om_tables
    # so drafts for tables that have since been documented (through any path)
    # drop out automatically.
    try:
        drafts = duck.query("""
            SELECT d.fqn, d.suggested, d.confidence, d.reasoning
            FROM doc_suggestions d
            JOIN om_tables t ON t.fullyQualifiedName = d.fqn
            WHERE (t.description IS NULL OR length(t.description) = 0)
              AND d.suggested IS NOT NULL
              AND length(d.suggested) > 0
            ORDER BY d.fqn
        """)
        for _, r in drafts.iterrows():
            items.append(
                {
                    "kind": "description",
                    "key": f"doc::{r['fqn']}",
                    "fqn": r["fqn"],
                    "old": "",
                    "new": r["suggested"] or "",
                    "confidence": float(r["confidence"] or 0.0),
                    "reason": r["reasoning"] or "auto-drafted for undocumented table",
                }
            )
    except Exception:
        pass  # doc_suggestions not yet populated

    # PII tag gaps
    try:
        gaps = duck.query("""
            SELECT table_fqn, column_name, current_tag, suggested_tag, confidence, reason
            FROM pii_results
            WHERE suggested_tag IS NOT NULL
              AND (current_tag IS NULL OR current_tag != suggested_tag)
            ORDER BY
                CASE WHEN suggested_tag = 'PII.Sensitive' THEN 0 ELSE 1 END,
                confidence DESC
        """)
        for _, r in gaps.iterrows():
            items.append(
                {
                    "kind": "pii_tag",
                    "key": f"pii::{r['table_fqn']}::{r['column_name']}",
                    "fqn": r["table_fqn"],
                    "column": r["column_name"],
                    "old": r["current_tag"],
                    "new": r["suggested_tag"],
                    "confidence": float(r["confidence"] or 0.0),
                    "reason": r["reason"] or "",
                }
            )
    except Exception:
        pass  # table doesn't exist yet (no PII scan run)

    dismissed = st.session_state.get("review_dismissed", set())
    return [i for i in items if i["key"] not in dismissed]


def _dismiss(key: str) -> None:
    st.session_state.setdefault("review_dismissed", set()).add(key)
    st.session_state.pop(f"review_edit::{key}", None)


def _accept_description(item: dict, text: str) -> None:
    s = Suggestion(
        fqn=item["fqn"],
        field="description",
        old=item["old"],
        new=text.strip(),
        confidence=1.0,
        reasoning="User-approved via review queue",
    )
    if stewardship.apply_suggestion(s):
        _dismiss(item["key"])
        with contextlib.suppress(Exception):
            duck.refresh_all()
        st.toast(f"Description applied to {item['fqn'].split('.')[-1]}", icon="✅")
        st.rerun()
    else:
        st.error(f"Failed to apply description to `{item['fqn']}` — check logs.")


def _accept_pii_tag(item: dict, tag: str) -> None:
    result = stewardship.apply_pii_tag(item["fqn"], item["column"], tag)
    if result["ok"]:
        _dismiss(item["key"])
        with contextlib.suppress(Exception):
            duck.refresh_all()
        st.toast(f"Tagged {item['column']} → {tag}", icon="✅")
        st.rerun()
    else:
        st.error(f"Failed: {result['message']}")


def _render_review_card(item: dict) -> None:
    key = item["key"]
    edit_key = f"review_edit::{key}"
    editing = st.session_state.get(edit_key, False)

    with st.container(border=True):
        if item["kind"] == "description":
            # Auto-drafts for undocumented tables use the `doc::` key prefix;
            # stale rewrites use `desc::`. Different icon/label per case.
            is_draft = key.startswith("doc::")
            header_icon = "✏️" if is_draft else "🧹"
            header_label = "New description" if is_draft else "Stale description"
            st.markdown(
                f"**{header_icon} {header_label}** · `{item['fqn']}` · "
                f"confidence {item['confidence']:.0%}"
            )
            if item["reason"]:
                st.caption(f"_Why:_ {item['reason']}")
            c1, c2 = st.columns(2)
            with c1:
                st.caption("**Current**")
                st.markdown(
                    f"> {item['old'] or '_(empty)_'}",
                )
            with c2:
                st.caption("**Suggested**")
                if editing:
                    st.text_area(
                        "Edit suggested description",
                        value=item["new"],
                        key=f"review_text::{key}",
                        label_visibility="collapsed",
                        height=120,
                    )
                else:
                    st.markdown(f"> {item['new']}")
        else:
            current_label = item["old"] if item["old"] else "_(untagged)_"
            st.markdown(
                f"**🔐 PII tag gap** · `{item['fqn']}` · "
                f"column `{item['column']}` · confidence {item['confidence']:.0%}"
            )
            if item["reason"]:
                st.caption(f"_Why:_ {item['reason']}")
            c1, c2 = st.columns(2)
            with c1:
                st.caption("**Current tag**")
                st.markdown(current_label)
            with c2:
                st.caption("**Suggested tag**")
                if editing:
                    default_idx = (
                        _PII_TAG_OPTIONS.index(item["new"])
                        if item["new"] in _PII_TAG_OPTIONS
                        else 0
                    )
                    st.selectbox(
                        "Edit suggested tag",
                        _PII_TAG_OPTIONS,
                        index=default_idx,
                        key=f"review_tag::{key}",
                        label_visibility="collapsed",
                    )
                else:
                    st.markdown(f"**{item['new']}**")

        b1, b2, b3, _ = st.columns([1, 1, 1, 2])
        if editing:
            if b1.button("💾 Save & apply", key=f"review_save::{key}", type="primary"):
                if item["kind"] == "description":
                    edited = st.session_state.get(f"review_text::{key}", item["new"])
                    _accept_description(item, edited)
                else:
                    edited = st.session_state.get(f"review_tag::{key}", item["new"])
                    _accept_pii_tag(item, edited)
            if b2.button("Cancel", key=f"review_cancel::{key}"):
                st.session_state.pop(edit_key, None)
                st.rerun()
        else:
            if b1.button("✔ Accept", key=f"review_accept::{key}", type="primary"):
                if item["kind"] == "description":
                    _accept_description(item, item["new"])
                else:
                    _accept_pii_tag(item, item["new"])
            if b2.button("✎ Edit", key=f"review_editbtn::{key}"):
                st.session_state[edit_key] = True
                st.rerun()
            if b3.button("✖ Reject", key=f"review_reject::{key}"):
                _dismiss(key)
                st.toast("Suggestion dismissed", icon="🗑️")
                st.rerun()


def _render_review_panel() -> None:
    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.markdown("## 📋 Review queue")
        st.caption(
            "Pending suggestions from the cleaning and PII engines. "
            "Accept applies the change via REST PATCH; Edit lets you tweak first; "
            "Reject dismisses until the next scan."
        )
    with top_r:
        if st.button("← Back to chat", width="stretch", key="review_back"):
            st.session_state.show_review = False
            st.rerun()

    items = _build_review_queue()
    if not items:
        st.info(
            "No pending suggestions. Run **🔬 Deep scan** or **🔐 PII scan** "
            "from the sidebar to populate the queue."
        )
        return

    kinds = {"description": 0, "pii_tag": 0}
    for i in items:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1

    filter_opt = st.radio(
        "Filter",
        [
            f"All ({len(items)})",
            f"Descriptions ({kinds['description']})",
            f"PII tags ({kinds['pii_tag']})",
        ],
        horizontal=True,
        label_visibility="collapsed",
        key="review_filter",
    )
    if filter_opt.startswith("Descriptions"):
        items = [i for i in items if i["kind"] == "description"]
    elif filter_opt.startswith("PII tags"):
        items = [i for i in items if i["kind"] == "pii_tag"]

    for item in items:
        _render_review_card(item)


# ── Visualizations panel ───────────────────────────────────────────────────
# Interactive plotly charts — each tab renders a different angle on the
# catalog (headline score, lineage DAG, hierarchy, tag conflicts, quality).
# Tabs whose backing data isn't ready show a hint so users know what to run.


def _render_viz_panel() -> None:
    top_l, top_r = st.columns([5, 1])
    with top_l:
        st.markdown("## 📊 Visualizations")
        st.caption(
            "Interactive views across your catalog. Charts update after each "
            "Refresh / Deep scan / PII scan — some tabs need specific scans run first."
        )
    with top_r:
        if st.button("← Back to chat", width="stretch", key="viz_back"):
            st.session_state.show_viz = False
            st.rerun()

    # One tab per entry in viz.ALL_VIZ. Tabs that return None get a hint
    # pointing the user at the sidebar scan that populates their data.
    tab_labels = [label for label, _, _ in viz.ALL_VIZ]
    tabs = st.tabs(tab_labels)
    for (label, caption, builder), tab in zip(viz.ALL_VIZ, tabs, strict=True):
        with tab:
            st.caption(caption)
            try:
                fig = builder()
            except Exception as e:
                st.error(f"Chart failed to render: {e}")
                continue
            if fig is None:
                st.info(
                    "Not enough data yet. "
                    "Run **🔄 Refresh metadata**, **🔬 Deep scan**, or **🔐 PII scan** "
                    "from the sidebar, then come back."
                )
                continue
            st.plotly_chart(
                fig,
                width="stretch",
                key=f"viz::{label}",
                config={"displaylogo": False},
            )


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    if LOGO_B64:
        st.markdown(
            f"""
            <div class="ms-header">
                <img src="data:image/png;base64,{LOGO_B64}" />
                <div>
                    <div class="ms-title">MetaSift</div>
                    <div class="ms-tag">AI-powered metadata analyst &amp; steward</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown("## 🧹 MetaSift")
        st.caption("AI-powered metadata analyst & steward")

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
            m4.metric(
                "Quality",
                f"{score['quality']}%",
                help="Mean description quality (1-5 score, normalized to 0-100 — populated by Deep scan)",
            )

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

    if st.button("🔄 Refresh metadata", width="stretch"):
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
        width="stretch",
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
        width="stretch",
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

    if st.button(
        "💡 Recommend DQ tests",
        width="stretch",
        help="Suggest data quality tests every table should have but currently doesn't (LLM calls — one per table)",
    ):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            progress = st.progress(0, text="Starting recommendations…")

            def _tick_rec(step: int, total: int, label: str) -> None:
                progress.progress(
                    min(step / max(total, 1), 1.0),
                    text=f"{label} ({step}/{total})",
                )

            try:
                summary = stewardship.run_dq_recommendations(progress_cb=_tick_rec)
                progress.empty()
                if summary["total"] == 0:
                    st.info("No DQ recommendations — coverage already looks solid.")
                else:
                    st.success(
                        f"{summary['total']} recommendation(s) across {summary['analyzed']} "
                        f"table(s) · 🚨 {summary['critical']} · 💡 {summary['recommended']} · "
                        f"✨ {summary['nice']}"
                    )
                    st.rerun()
            except Exception as e:
                progress.empty()
                st.error(f"DQ recommendations failed: {e}")

    if st.button(
        "🧪 Explain DQ failures",
        width="stretch",
        help="Generate plain-English explanations for every failed data quality check (LLM calls — one per failure)",
    ):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            progress = st.progress(0, text="Starting DQ explanations…")

            def _tick_dq(step: int, total: int, label: str) -> None:
                progress.progress(
                    min(step / max(total, 1), 1.0),
                    text=f"{label} ({step}/{total})",
                )

            try:
                summary = cleaning.run_dq_explanations(progress_cb=_tick_dq)
                progress.empty()
                if summary["total"] == 0:
                    st.info("No failing DQ checks to explain.")
                else:
                    st.success(f"Explained {summary['explained']}/{summary['total']} DQ failures")
                    st.rerun()
            except Exception as e:
                progress.empty()
                st.error(f"DQ explanations failed: {e}")

    st.divider()

    # Review queue toggle. The label carries the pending count so users don't
    # need to open the panel to know whether anything's waiting.
    pending = len(_build_review_queue())
    review_label = f"📋 Review queue ({pending})" if pending else "📋 Review queue"
    in_review = bool(st.session_state.get("show_review"))
    if st.button(
        "← Back to chat" if in_review else review_label,
        width="stretch",
        type="primary" if pending and not in_review else "secondary",
        help="Approve or reject suggestions from the cleaning and PII engines",
    ):
        st.session_state.show_review = not in_review
        st.session_state.show_viz = False
        st.rerun()

    # Visualizations toggle. Shows only once metadata is loaded — an empty
    # DuckDB would produce None-figures across every tab.
    in_viz = bool(st.session_state.get("show_viz"))
    if viz.has_any_data() and st.button(
        "← Back to chat" if in_viz else "📊 Visualizations",
        width="stretch",
        help="Interactive plotly charts — lineage, PII distribution, quality, and more",
    ):
        st.session_state.show_viz = not in_viz
        st.session_state.show_review = False
        st.rerun()

    # Executive report download. Generated eagerly on render (cheap — all
    # in-memory SQL against DuckDB) so the download_button has the bytes
    # ready on first click. Only offered once metadata is loaded, since an
    # empty DuckDB would produce a report full of SQL error messages.
    try:
        has_metadata = bool(duck.query("SELECT 1 FROM om_tables LIMIT 1").size)
    except Exception:
        has_metadata = False

    if has_metadata:
        try:
            report_md = report.generate_markdown_report()
            fname = f"metasift-report-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.md"
            st.download_button(
                "📄 Export report",
                data=report_md,
                file_name=fname,
                mime="text/markdown",
                width="stretch",
                help="Download a markdown summary of catalog health, stale docs, PII gaps, and more",
            )
        except Exception as e:
            st.caption(f"_Report unavailable: {e}_")

    gbtn, kbtn = st.columns(2)
    with gbtn:
        if st.button(
            "📖 Guide",
            width="stretch",
            help="Show the MetaSift intro and quick-start",
        ):
            st.session_state.show_guide = True
            st.rerun()
    with kbtn:
        override_active = llm.get_override() is not None
        if st.button(
            "🔑 API key" + (" ✓" if override_active else ""),
            width="stretch",
            type="secondary",
            help=(
                "Use your own OpenAI-compatible key (OpenRouter, OpenAI, Gemini, "
                "Groq, Ollama, or custom). Session-scoped; never persisted."
            ),
        ):
            st.session_state.show_api_key = True
            st.rerun()

    # Subtle status row at the bottom of the sidebar. The LLM indicator now
    # surfaces the active provider + model when an override is set — users
    # always see which key is live.
    st.divider()
    s1, s2 = st.columns(2)
    s1.caption(f"OpenMetadata {'🟢' if om_ok else '🔴'}")
    override = llm.get_override()
    if override:
        provider = _preset_for_url(override.base_url)
        model_short = (override.model or "default").split("/")[-1]
        s2.caption(f"LLM 🟢 ({provider} · {model_short})")
    else:
        s2.caption(f"LLM {'🟢' if settings.openrouter_api_key else '🔴'}")


# ── Main area ──────────────────────────────────────────────────────────────
# Welcome / Guide dialog fires on first session load and on-demand whenever
# the Guide sidebar button sets show_guide=True. Placed before the review /
# viz short-circuits so the dialog is reachable from any screen.
if not st.session_state.get("welcome_seen", False) or st.session_state.get("show_guide", False):
    _welcome_dialog()

# API-key override dialog — fires only on demand via the 🔑 API key sidebar
# button (show_api_key=True). Independent of the welcome flow.
if st.session_state.get("show_api_key", False):
    _api_key_dialog()

# When the review-queue toggle is on, the main area shows the approvals panel
# instead of the welcome / chat view. Chat state is preserved — toggling back
# returns the user to their conversation exactly as they left it.
if st.session_state.get("show_review"):
    _render_review_panel()
    st.stop()

if st.session_state.get("show_viz"):
    _render_viz_panel()
    st.stop()

# Model picker bar — pinned above the chat area. Always visible on the chat
# screen so the user sees + swaps the active model without leaving.
_model_picker_bar()

# Pending prompts come from suggestion-chip clicks; they short-circuit the
# normal chat_input flow on the next rerun. Call st.chat_input up front so
# we know whether the user has just submitted text — prevents the welcome
# hero from flashing underneath the streaming response on first submission.
pending_prompt = st.session_state.pop("pending_prompt", None)
typed_input = st.chat_input("Ask Stew…")
user_input = pending_prompt or typed_input
show_welcome = not st.session_state.messages and not user_input

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
        if col.button(label, width="stretch", key=f"suggest_{label}"):
            st.session_state.pending_prompt = prompt_text
            st.rerun()
else:
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            _render_user(msg["content"])
        else:
            _render_assistant(msg["content"], msg.get("traces"))

# Centered "New chat" pill rendered INSIDE Streamlit's fixed bottom container,
# directly under the chat input. Use the container's methods directly instead
# of a `with` block — `with st._bottom:` didn't propagate context to st.columns
# and was double-rendering during streaming.
_nc_cols = st._bottom.columns([3, 2, 3])
_nc_cols[1].button(
    "➕ New chat",
    width="stretch",
    key="new_chat_btn",
    help="Start a fresh chat",
    on_click=_reset_chat,
)

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
    # Tool calls stream in as AIMessage.tool_calls (one AIMessage can request
    # several at once); results stream back as ToolMessage with matching
    # tool_call_id. Keep insertion order so the expander reads top-to-bottom.
    tool_calls_by_id: dict[str, dict] = {}
    tool_results_by_id: dict[str, str | list] = {}
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
                        if isinstance(m, ToolMessage):
                            tc_id = getattr(m, "tool_call_id", None)
                            if tc_id:
                                tool_results_by_id[tc_id] = m.content
                            if m.content:
                                last_tool_content = (
                                    m.content if isinstance(m.content, str) else str(m.content)
                                )
                        elif isinstance(m, AIMessage):
                            for tc in getattr(m, "tool_calls", None) or []:
                                tc_id = tc.get("id") or f"_anon_{len(tool_calls_by_id)}"
                                if tc_id not in tool_calls_by_id:
                                    tool_calls_by_id[tc_id] = {
                                        "name": tc.get("name", "unknown"),
                                        "args": tc.get("args", {}),
                                    }
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

    traces = [
        {
            "tool": info["name"],
            "args": info["args"],
            "result": tool_results_by_id.get(tc_id, ""),
        }
        for tc_id, info in tool_calls_by_id.items()
    ]

    _render_assistant(reply, traces)
    st.session_state.messages.append({"role": "assistant", "content": reply, "traces": traces})

    # If the message came from a suggestion chip, re-render to swap the
    # welcome hero for the chat view cleanly.
    if pending_prompt:
        st.rerun()

# Auto-scroll to the newest message on every rerun that has history
if st.session_state.messages:
    _scroll_to_bottom()
