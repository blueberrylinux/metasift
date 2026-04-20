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
    changes from the chat-area model picker)."""

    api_key: str | None = None
    base_url: str | None = None  # falls back to settings.openrouter_base_url
    model: str | None = None  # falls back to the per-task model from .env


# Module-level singleton set by set_override() / clear_override(). Read by
# get_llm() on every resolution. Not thread-safe — single-process Streamlit
# is the intended runtime, and Python's GIL makes a pointer swap atomic
# enough for the one-writer / many-readers pattern here.
_override: LLMOverride | None = None


def set_override(
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> None:
    """Activate a runtime override. Any field left as None is cleared from the
    override (falls back to .env config on next resolution). Invalidates the
    get_llm() cache so every subsequent call rebuilds with the new values."""
    global _override

    def _clean(v: str | None) -> str | None:
        return (v or "").strip() or None

    _override = LLMOverride(
        api_key=_clean(api_key),
        base_url=_clean(base_url),
        model=_clean(model),
    )
    get_llm.cache_clear()


def set_model(model: str | None) -> None:
    """Update just the model; preserve whatever api_key / base_url the current
    override has. Useful for a chat-area model picker that shouldn't require
    re-pasting the API key to swap models."""
    global _override
    current = _override or LLMOverride()
    _override = LLMOverride(
        api_key=current.api_key,
        base_url=current.base_url,
        model=(model or "").strip() or None,
    )
    get_llm.cache_clear()


def clear_override() -> None:
    """Drop the runtime override; get_llm() returns to .env-configured defaults."""
    global _override
    _override = None
    get_llm.cache_clear()


def get_override() -> LLMOverride | None:
    """Read the currently active override, or None if running on .env config."""
    return _override


def _build(model_name: str) -> BaseChatModel:
    """Construct a ChatOpenAI client — merges the runtime override with .env
    defaults, per field. Callers get override values where set and .env
    defaults where not. Raises if NO key is available from either source."""
    o = _override
    api_key = o.api_key if o and o.api_key else settings.openrouter_api_key
    base_url = o.base_url if o and o.base_url else settings.openrouter_base_url
    model = o.model if o and o.model else model_name

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
def get_llm(task: TaskType = "toolcall") -> BaseChatModel:
    """Return a configured chat model for a given task type.

    Cached so the same task reuses the same client. The cache is cleared by
    `set_override()` / `clear_override()` so credential changes take effect
    on the next call without a process restart.
    """
    return _build(_TASK_MAP[task]())
