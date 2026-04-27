"""LLM client — picks the right OpenAI-compatible model per task type.

Two config sources, checked in priority order:
  1. Runtime override — set by the UI (sidebar 🔑 API key modal) via
     `set_override(...)`. Session-scoped; never persisted. Overrides the
     api_key, base_url, and (optionally) the model for every task.
  2. `.env` settings via `app.config.settings` — OpenRouter defaults.

The override mechanism lets a user paste their own provider's key + URL
and use MetaSift without touching `.env`. Any OpenAI-compatible endpoint
works: OpenRouter, OpenAI, Gemini, Groq, Ollama, etc.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings

TaskType = Literal["toolcall", "description", "classification", "stale", "scoring", "reasoning"]


@dataclass(frozen=True)
class LLMOverride:
    """Runtime override set by the UI. Every field is optional — each one that
    isn't set falls back to .env-configured defaults. `api_key=None` means
    "keep using the .env key but swap another field" (useful for model-only
    changes from the chat-area model picker).

    `per_task_models` is the power-user surface: it maps a TaskType to a
    specific model that overrides `model` for that task only. Resolution
    precedence when building a client for a given task:
        per_task_models[task]  →  model (shared)  →  .env per-task default
    """

    api_key: str | None = None
    base_url: str | None = None  # falls back to settings.openrouter_base_url
    model: str | None = (
        None  # shared model — applies to every task unless per_task_models overrides
    )
    per_task_models: tuple[tuple[str, str], ...] = ()  # frozen tuple-of-pairs for hashability


# Module-level singleton set by set_override() / clear_override(). Read by
# get_llm() on every resolution. Not thread-safe — single-process Streamlit
# is the intended runtime, and Python's GIL makes a pointer swap atomic
# enough for the one-writer / many-readers pattern here.
_override: LLMOverride | None = None


# Per-request OpenRouter key for sandbox / BYO-key mode. Set by the
# `X-OpenRouter-Key` middleware in `app/api/main.py` on every incoming
# request that carries the header; read by `_build` below as the highest-
# priority credential source.
#
# ContextVar (not threading.local) because FastAPI requests run as asyncio
# tasks and contextvars propagate task-by-task. The chat/scan workers run
# the sync agent loop inside `_CHAT_EXECUTOR` / `_SCAN_EXECUTOR`; the
# dispatch sites must use `contextvars.copy_context()` + `ctx.run(fn)` to
# carry the value into the worker thread (see chat.py / scans.py).
#
# Default None means "no per-request key" — `_build` falls through to the
# legacy `_override.api_key` / `settings.openrouter_api_key` resolution
# unchanged. Local dev / non-sandbox installs see no behaviour change.
request_api_key: ContextVar[str | None] = ContextVar("openrouter_request_key", default=None)


def _clean(v: str | None) -> str | None:
    return (v or "").strip() or None


def set_override(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> None:
    """Activate a runtime override for the shared credentials + shared model.
    Any field left as None is cleared from the override (falls back to .env
    config on next resolution). Invalidates the get_llm() cache.

    Preserves any previously-configured per-task models — users who change
    the shared key/URL shouldn't silently lose their per-task routing. Use
    `clear_per_task_models()` or `clear_override()` to wipe per-task state."""
    global _override
    current = _override
    _override = LLMOverride(
        api_key=_clean(api_key),
        base_url=_clean(base_url),
        model=_clean(model),
        per_task_models=current.per_task_models if current else (),
    )
    get_llm.cache_clear()


def clear_per_task_models() -> None:
    """Wipe every per-task override, keep the shared credentials intact."""
    global _override
    if _override is None:
        return
    _override = LLMOverride(
        api_key=_override.api_key,
        base_url=_override.base_url,
        model=_override.model,
        per_task_models=(),
    )
    get_llm.cache_clear()


def set_model(model: str | None) -> None:
    """Update just the shared model; preserve api_key / base_url / per-task
    routing. Useful for a chat-area model picker that shouldn't require
    re-pasting the API key to swap models."""
    global _override
    current = _override or LLMOverride()
    _override = LLMOverride(
        api_key=current.api_key,
        base_url=current.base_url,
        model=_clean(model),
        per_task_models=current.per_task_models,
    )
    get_llm.cache_clear()


def set_task_model(task: TaskType, model: str | None) -> None:
    """Set (or clear, when model is None/empty) a per-task model override.
    Preserves every other field of the current override including other
    task entries."""
    global _override
    current = _override or LLMOverride()
    cleaned = _clean(model)
    # Rebuild the per-task mapping as a new tuple — drop the entry when
    # cleared, add/replace when set. Keeps the frozen dataclass hashable.
    existing = {k: v for k, v in current.per_task_models if k != task}
    if cleaned:
        existing[task] = cleaned
    new_pairs = tuple(sorted(existing.items()))
    _override = LLMOverride(
        api_key=current.api_key,
        base_url=current.base_url,
        model=current.model,
        per_task_models=new_pairs,
    )
    get_llm.cache_clear()


def get_task_model(task: TaskType) -> str | None:
    """Return the per-task model override for this task, or None if none set."""
    if _override is None:
        return None
    for k, v in _override.per_task_models:
        if k == task:
            return v
    return None


def clear_override() -> None:
    """Drop the runtime override entirely (including per-task routing);
    get_llm() returns to .env-configured defaults."""
    global _override
    _override = None
    get_llm.cache_clear()


def get_override() -> LLMOverride | None:
    """Read the currently active override, or None if running on .env config."""
    return _override


def _build(task: TaskType, env_default_model: str) -> BaseChatModel:
    """Construct a ChatOpenAI client — merges the runtime override with .env
    defaults, per field. Resolution precedence for the api_key:
        request_api_key (sandbox BYOK) → override.api_key → settings.openrouter_api_key
    For the model:
        per_task_models[task] → override.model (shared) → env_default_model

    Callers get override values where set and .env defaults where not.
    Raises if NO api_key is available from any source.

    The lru_cache on `get_llm` is *not* keyed on the request_api_key — its
    side-effect of returning a fresh ChatOpenAI is cheap, but if two
    sandbox visitors with different keys hit the same cached client they'd
    cross-leak credentials. `get_llm` is bypassed in sandbox mode below;
    we build a fresh client per call."""
    o = _override
    request_key = request_api_key.get()
    api_key = request_key or (o.api_key if o and o.api_key else settings.openrouter_api_key)
    base_url = o.base_url if o and o.base_url else settings.openrouter_base_url

    model = env_default_model
    if o is not None:
        per_task = next((v for k, v in o.per_task_models if k == task), None)
        if per_task:
            model = per_task
        elif o.model:
            model = o.model

    if not api_key:
        # Same error shape as settings.require_llm_key() — caller catches this
        # higher up and surfaces a "paste your API key" hint.
        settings.require_llm_key()

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.2,
        max_tokens=4096,  # headroom for JSON batch responses (e.g. scoring)
        timeout=60,  # seconds — fail fast instead of hanging
    )


_TASK_MAP = {
    "toolcall": lambda: settings.model_toolcall,
    "description": lambda: settings.model_description,
    "classification": lambda: settings.model_classification,
    "stale": lambda: settings.model_stale,
    "scoring": lambda: settings.model_scoring,
    "reasoning": lambda: settings.model_reasoning,
}


@lru_cache(maxsize=8)
def _get_llm_cached(task: TaskType) -> BaseChatModel:
    return _build(task, _TASK_MAP[task]())


def get_llm(task: TaskType = "toolcall") -> BaseChatModel:
    """Return a configured chat model for a given task type.

    Cached so the same task reuses the same client. The cache is cleared by
    `set_override()` / `set_model()` / `set_task_model()` / `clear_override()`
    so credential changes take effect on the next call without a process
    restart.

    BYO-key bypass: if a per-request key is set on the contextvar, build a
    fresh client without consulting the cache — otherwise visitor A's first
    request would warm a cache that visitor B then reads, leaking key A's
    creds into key B's calls. The fresh build is cheap (ChatOpenAI is just
    config + an httpx pool); the cache stays useful for non-sandbox runs."""
    if request_api_key.get() is not None:
        return _build(task, _TASK_MAP[task]())
    return _get_llm_cached(task)


# Preserve cache_clear() compat — set_override() / clear_override() / etc.
# still call get_llm.cache_clear() to invalidate after a credentials update.
# Forward to the underlying lru_cache.
get_llm.cache_clear = _get_llm_cached.cache_clear  # type: ignore[attr-defined]
