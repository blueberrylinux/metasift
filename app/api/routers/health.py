"""Liveness probe.

Used by the React sidebar status dots + the Phase 0 smoke test to confirm the
FastAPI layer is wired without booting OM or an LLM. Cheap — no external
network calls.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.config import api_settings
from app.api.deps import DuckOk, LlmOk, OmOk, SqliteOk
from app.api.schemas import HealthResponse

router = APIRouter(tags=["ops"])

_VERSION = "0.5.0-port.1"  # bumps per phase: 0.5.0-port.2 after Phase 2, etc.


@router.get("/health", response_model=HealthResponse)
def health(
    om: OmOk,
    llm: LlmOk,
    duck: DuckOk,
    sqlite: SqliteOk,
) -> HealthResponse:
    """Sidebar status-dot payload.

    `ok` is the AND across all subsystems — a single bit the UI can use for
    overall green/red. Individual flags let the UI render per-subsystem dots.
    Intentionally never 5xx — the UI wants the breakdown even when things are
    down.
    """
    return HealthResponse(
        # In sandbox mode, the LLM credential probe is meaningless — visitors
        # bring their own OpenRouter key per request. Don't let "no .env key"
        # paint the sidebar red.
        ok=all([om, sqlite]) if api_settings.sandbox_mode else all([om, llm, sqlite]),
        om=om,
        llm=llm,
        duck=duck,
        sqlite=sqlite,
        version=_VERSION,
        sandbox=api_settings.sandbox_mode,
    )
