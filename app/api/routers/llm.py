"""LLM config surface for the React port.

Phase 2 slice 4 shipped /llm/catalog + /llm/model. Phase 3.5 slice 2b adds
the rest of the settings surface so the LLMSetup screen can drive:

  * GET  /llm/catalog     — available OpenRouter models + currently-active one
  * GET  /llm/config      — current override state (api_key mask + base_url
                            + shared model + per-task overrides)
  * POST /llm/model       — shared model only (legacy, used by ModelQuickPicker)
  * POST /llm/config      — full override: api_key + base_url + model +
                            per_task_models. Unknown fields pass through as
                            "keep current" (omit to change just model, for
                            example). Triggers the same agent rebuild as
                            /llm/model.
  * DELETE /llm/config    — clear the override entirely; fall back to .env
  * POST /llm/test        — ping the LLM with the current override (or with
                            a candidate config passed in the body) and
                            return latency + a short canned completion

Key handling: the API never echoes the full key back. `GET /llm/config`
returns a short preview (last 4 chars) + boolean `api_key_set`. The frontend
relies on the preview to signal that a key is active without leaking it.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from loguru import logger

from app.api import errors
from app.api.deps import WritesEnabled
from app.api.routers import chat as chat_router
from app.api.schemas import (
    LLMCatalogResponse,
    LLMConfigResponse,
    LLMTestRequest,
    LLMTestResponse,
    ModelConfig,
    SetLLMConfigRequest,
    SetModelRequest,
    TaskModelMap,
)
from app.clients import llm
from app.clients.llm import TaskType
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
# Shorter negative TTL so a transient OpenRouter outage doesn't permanently
# shadow the live list, but every catalog request doesn't pay the full 8s
# fetch timeout while OpenRouter is down.
_CATALOG_NEG_TTL_SEC = 60
_catalog_cache: tuple[float, list[str]] | None = None


def _fetch_openrouter_catalog() -> list[str]:
    """Pull OpenRouter's public model list. Returns [] on any failure so the
    caller can fall back to `_FALLBACK_MODELS` without the route blowing up.
    Failures negative-cache for `_CATALOG_NEG_TTL_SEC` so we don't block every
    /catalog request on the slow fetch path while OpenRouter is unavailable."""
    global _catalog_cache
    now = time.time()
    if _catalog_cache:
        age = now - _catalog_cache[0]
        ttl = _CATALOG_TTL_SEC if _catalog_cache[1] else _CATALOG_NEG_TTL_SEC
        if age < ttl:
            return _catalog_cache[1]
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=8.0)
        r.raise_for_status()
        body: dict[str, Any] = r.json()
    except Exception as e:
        logger.warning(f"openrouter catalog fetch failed: {e}")
        _catalog_cache = (now, [])
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
    whether it's looking at OpenRouter's full list or the offline fallback.
    Always splices the active model into the response so the UI can show a
    valid selection even when the user is on a custom/deprecated id missing
    from the catalog or fallback."""
    dynamic = _fetch_openrouter_catalog()
    current = _current_model()
    if dynamic:
        models = dynamic if current in dynamic else [current, *dynamic]
        return LLMCatalogResponse(models=models, current=current, source="openrouter")
    models = _FALLBACK_MODELS if current in _FALLBACK_MODELS else [current, *_FALLBACK_MODELS]
    return LLMCatalogResponse(models=models, current=current, source="fallback")


@router.post("/model", response_model=ModelConfig)
def set_model(req: SetModelRequest, _: WritesEnabled) -> ModelConfig:
    """Switch the active model. Clears the get_llm() lru_cache via
    `llm.set_model` (preserves api_key / base_url / per-task overrides) AND
    drops the cached agent so the next /chat/stream call rebuilds with the
    new model. Session-scoped — not persisted across restarts."""
    llm.set_model(req.model)
    chat_router.invalidate_agent()
    logger.info(f"llm model switched to {req.model!r}, agent invalidated")
    return ModelConfig(model=_current_model())


# ── Full config surface (Phase 3.5 slice 2b) ──────────────────────────────


_TASK_KEYS: tuple[TaskType, ...] = (
    "toolcall",
    "reasoning",
    "description",
    "stale",
    "scoring",
    "classification",
)


def _mask_key(key: str | None) -> str:
    """Return a last-4-chars preview for UI display. Never echo the full key."""
    if not key:
        return ""
    cleaned = key.strip()
    if len(cleaned) <= 4:
        return "•" * len(cleaned)
    return "•" * 8 + cleaned[-4:]


def _active_base_url() -> str:
    o = llm.get_override()
    return (o.base_url if o and o.base_url else settings.openrouter_base_url) or ""


def _active_api_key() -> str:
    o = llm.get_override()
    return (o.api_key if o and o.api_key else settings.openrouter_api_key) or ""


def _collect_per_task_overrides() -> dict[str, str]:
    o = llm.get_override()
    if o is None:
        return {}
    return dict(o.per_task_models)


@router.get("/config", response_model=LLMConfigResponse)
def get_config() -> LLMConfigResponse:
    """Snapshot of the current override + fallback values so the Settings
    UI can preload without leaking the API key. `per_task_models` includes
    every task the engines route on, with an empty string when no override
    is set (falls back to `.env`-configured default)."""
    overrides = _collect_per_task_overrides()
    per_task = TaskModelMap(
        toolcall=overrides.get("toolcall", ""),
        reasoning=overrides.get("reasoning", ""),
        description=overrides.get("description", ""),
        stale=overrides.get("stale", ""),
        scoring=overrides.get("scoring", ""),
        classification=overrides.get("classification", ""),
    )
    env_per_task = TaskModelMap(
        toolcall=settings.model_toolcall,
        reasoning=settings.model_reasoning,
        description=settings.model_description,
        stale=settings.model_stale,
        scoring=settings.model_scoring,
        classification=settings.model_classification,
    )
    key = _active_api_key()
    return LLMConfigResponse(
        api_key_set=bool(key),
        api_key_preview=_mask_key(key),
        base_url=_active_base_url(),
        model=_current_model(),
        per_task_models=per_task,
        env_defaults=env_per_task,
    )


@router.post("/config", response_model=LLMConfigResponse)
def set_config(req: SetLLMConfigRequest, _: WritesEnabled) -> LLMConfigResponse:
    """Apply a full override. Each top-level field is optional — omit to
    keep the current value for that field.

    Per-task semantics — careful: `per_task_models` is treated as an
    authoritative replacement. Pydantic defaults all six keys to "", so
    sending `{}` materialises six empty strings and CLEARS every task
    override (since empty string → None via `_clean`). If you want to
    change just one task, send the other five as their current values
    (the Settings UI does this by spreading the full 6-key `routes`
    object). To leave ALL per-task routing untouched, omit the field
    entirely (set to `null`).

    Triggers an agent rebuild so the next /chat/stream picks up the new
    config. Session-scoped — config doesn't persist across restarts.
    """
    current = llm.get_override()

    # Shared creds: preserve unspecified fields. Sentinel `None` means
    # "don't change"; empty string "" means "clear".
    new_key = req.api_key if req.api_key is not None else (current.api_key if current else None)
    new_base = req.base_url if req.base_url is not None else (current.base_url if current else None)
    new_model = req.model if req.model is not None else (current.model if current else None)

    llm.set_override(api_key=new_key, base_url=new_base, model=new_model)

    if req.per_task_models is not None:
        incoming = req.per_task_models.model_dump()
        for task_key in _TASK_KEYS:
            val = incoming.get(task_key)
            if val is None:
                continue  # not touched
            # Empty string clears, else set.
            llm.set_task_model(task_key, val or None)

    chat_router.invalidate_agent()
    per_task_keys = list((req.per_task_models.model_dump() if req.per_task_models else {}).keys())
    logger.info(
        f"llm config updated · model={new_model!r} base_url={new_base!r} "
        f"api_key_set={bool(new_key)} per_task_keys={per_task_keys}"
    )
    return get_config()


@router.delete("/config", response_model=LLMConfigResponse)
def reset_config(_: WritesEnabled) -> LLMConfigResponse:
    """Wipe the session override; subsequent calls fall back to `.env`."""
    llm.clear_override()
    chat_router.invalidate_agent()
    logger.info("llm override cleared, agent invalidated")
    return get_config()


@router.post("/test", response_model=LLMTestResponse)
def test_connection(req: LLMTestRequest | None = None) -> LLMTestResponse:
    """Ping the configured provider with a deterministic prompt and return
    latency + the raw response. If `req.model` / `req.api_key` /
    `req.base_url` is provided, the test uses those values WITHOUT
    persisting them — lets the Settings UI verify credentials before the
    user hits Save. Omit the body to test the currently active config.

    The prompt is intentionally tight ("respond with exactly: MetaSift
    ready") so the round-trip stays under 1-2s on most providers.
    """
    body = req or LLMTestRequest()
    model = (body.model or _current_model()).strip()
    base_url = (body.base_url or _active_base_url()).strip()
    api_key = body.api_key if body.api_key is not None else _active_api_key()

    if not api_key:
        raise errors.ApiError(
            errors.ErrorCode.LLM_UNAVAILABLE,
            "No API key configured. Paste one in the Settings screen or set OPENROUTER_API_KEY.",
            status_code=400,
        )
    if not model:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            "model must resolve to a non-empty string.",
        )

    prompt = "respond with exactly: MetaSift ready"
    started = time.perf_counter()
    try:
        client = ChatOpenAI(
            model=model,
            base_url=base_url or None,
            api_key=api_key,
            temperature=0.0,
            max_tokens=32,
            timeout=15,
        )
        result = client.invoke([HumanMessage(content=prompt)])
    except Exception as e:
        logger.warning(f"llm connection test failed: {e}")
        return LLMTestResponse(
            ok=False,
            model=model,
            base_url=base_url,
            latency_ms=int((time.perf_counter() - started) * 1000),
            response="",
            error=str(e),
        )

    text = result.content if hasattr(result, "content") else str(result)
    if isinstance(text, list):
        text = " ".join(
            part.get("text", "") for part in text if isinstance(part, dict) and "text" in part
        )
    return LLMTestResponse(
        ok=True,
        model=model,
        base_url=base_url,
        latency_ms=int((time.perf_counter() - started) * 1000),
        response=str(text).strip()[:200],
        error=None,
    )
