"""LLM config surface for the React port — slice 4 of Phase 2.

Two endpoints:
  * GET  /llm/catalog  — available OpenRouter models (dynamic, with curated
                         fallback) plus the currently selected model id.
  * POST /llm/model    — change the active model; clears the get_llm cache
                         via `llm.set_model()` and drops the cached agent so
                         the next /chat/stream rebuilds with the new model.

Slice-4 scope is deliberately narrow: only the shared `model` field changes.
api_key / base_url continue to come from `.env`; per-task routing isn't
exposed here yet. The Streamlit sidebar has a richer LLM-setup modal — we
port that in a later phase.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter
from loguru import logger

from app.api.routers import chat as chat_router
from app.api.schemas import LLMCatalogResponse, ModelConfig, SetModelRequest
from app.clients import llm
from app.config import settings

router = APIRouter(prefix="/llm", tags=["llm"])


# Hardcoded fallback used when the dynamic OpenRouter fetch fails (offline,
# rate-limited, etc.). Kept short — lifted from
# app/main.py::_MODEL_CATALOG['OpenRouter'].
_FALLBACK_MODELS: list[str] = [
    "meta-llama/llama-3.3-70b-instruct",
    "anthropic/claude-3.5-sonnet",
    "openai/gpt-4o-mini",
    "openai/gpt-4o",
    "google/gemini-2.0-flash",
    "mistralai/mistral-large",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemini-2.0-flash-exp:free",
]

# House favorites rank ahead of the rest so the dropdown's common picks are
# reachable without typing. Matches app/main.py::_fetch_openrouter_catalog.
_PRIORITY_ORDER = {
    "meta-llama/llama-3.3-70b-instruct": 0,
    "anthropic/claude-3.5-sonnet": 1,
    "openai/gpt-4o-mini": 2,
    "openai/gpt-4o": 3,
    "google/gemini-2.0-flash": 4,
}

# Module-level cache for the OpenRouter fetch — TTL'd to an hour so the
# dropdown doesn't hit the network on every page load but picks up new
# releases within a reasonable window. Mirrors Streamlit's @st.cache_data.
_CATALOG_TTL_SEC = 3600
_catalog_cache: tuple[float, list[str]] | None = None


def _fetch_openrouter_catalog() -> list[str]:
    """Pull OpenRouter's public model list. Returns [] on any failure so the
    caller can fall back to `_FALLBACK_MODELS` without the route blowing up."""
    global _catalog_cache
    now = time.time()
    if _catalog_cache and now - _catalog_cache[0] < _CATALOG_TTL_SEC:
        return _catalog_cache[1]
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=8.0)
        r.raise_for_status()
        body: dict[str, Any] = r.json()
    except Exception as e:
        logger.warning(f"openrouter catalog fetch failed: {e}")
        return []
    ids = [
        item["id"]
        for item in body.get("data") or []
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    ]
    ids.sort(key=lambda m: (_PRIORITY_ORDER.get(m, 1_000), m))
    _catalog_cache = (now, ids)
    return ids


def _current_model() -> str:
    """Active shared model — override takes priority; falls back to the
    .env-configured tool-call default which is the headline model."""
    override = llm.get_override()
    if override and override.model:
        return override.model
    return settings.model_toolcall


@router.get("/catalog", response_model=LLMCatalogResponse)
def get_catalog() -> LLMCatalogResponse:
    """Available models + the currently active one. `source` tells the UI
    whether it's looking at OpenRouter's full list or the offline fallback."""
    dynamic = _fetch_openrouter_catalog()
    if dynamic:
        return LLMCatalogResponse(
            models=dynamic,
            current=_current_model(),
            source="openrouter",
        )
    return LLMCatalogResponse(
        models=_FALLBACK_MODELS,
        current=_current_model(),
        source="fallback",
    )


@router.post("/model", response_model=ModelConfig)
def set_model(req: SetModelRequest) -> ModelConfig:
    """Switch the active model. Clears the get_llm() lru_cache via
    `llm.set_model` (preserves api_key / base_url / per-task overrides) AND
    drops the cached agent so the next /chat/stream call rebuilds with the
    new model. Session-scoped — not persisted across restarts."""
    llm.set_model(req.model)
    chat_router.invalidate_agent()
    logger.info(f"llm model switched to {req.model!r}, agent invalidated")
    return ModelConfig(model=_current_model())
