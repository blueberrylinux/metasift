"""MetaSift — Streamlit entry point.

Layout: dashboard (left) + chat (right), unified view.
Run: `uv run streamlit run app/main.py`
"""
from __future__ import annotations

import streamlit as st

from app.clients import duck, openmetadata
from app.config import settings
from app.engines import analysis

st.set_page_config(page_title="MetaSift", page_icon="🧹", layout="wide")

# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🧹 MetaSift")
    st.caption("AI-powered metadata analyst & steward")

    om_ok = openmetadata.health_check()
    st.markdown(f"**OpenMetadata:** {'🟢 connected' if om_ok else '🔴 offline'}")
    st.markdown(
        f"**LLM:** {'🟢 Gemini' if settings.google_api_key else ('🟢 OpenRouter' if settings.openrouter_api_key else '🔴 no key')}"
    )

    if st.button("🔄 Refresh metadata", use_container_width=True):
        if not om_ok:
            st.error("Start OpenMetadata first: `make stack-up`")
        else:
            with st.spinner("Pulling metadata..."):
                counts = duck.refresh_all()
            st.success(f"Loaded {counts}")

    st.divider()
    st.caption("Wire up your .env to get started.")

# ── Main area ──────────────────────────────────────────────────────────────
col_dash, col_chat = st.columns([1.2, 1])

with col_dash:
    st.header("Health dashboard")
    if not om_ok:
        st.info("👋 Welcome. Start the OpenMetadata stack with `make stack-up`, "
                "then get a JWT token (`make token`) and click **Refresh metadata**.")
    else:
        try:
            score = analysis.composite_score()
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Coverage", f"{score['coverage']}%")
            c2.metric("Accuracy", f"{score['accuracy']}%", help="Non-stale descriptions")
            c3.metric("Consistency", f"{score['consistency']}%", help="Conflict-free tags")
            c4.metric("Composite", f"{score['composite']}%", help="Weighted overall quality")

            st.subheader("Documentation coverage by schema")
            cov_df = analysis.documentation_coverage()
            if len(cov_df):
                st.bar_chart(cov_df.set_index("schema")["coverage_pct"])
            else:
                st.caption("No data yet. Click **Refresh metadata**.")
        except Exception as e:
            st.warning(f"Refresh metadata to populate the dashboard. ({e})")

with col_chat:
    st.header("Chat with Stew")
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant",
             "content": "Hi, I'm Stew 🧙 — ask me anything about your catalog, "
                        "or try: _'which schemas have the worst documentation?'_"}
        ]

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Ask Stew…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            # TODO: wire agent.build_agent() and stream the response
            reply = "Agent not yet wired. Run `make stack-up` and connect your .env."
            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
