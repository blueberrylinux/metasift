"""LLM client — picks the right OpenRouter model per task type."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import settings

TaskType = Literal["toolcall", "description", "classification", "stale", "scoring", "reasoning"]


def _build(model_name: str) -> BaseChatModel:
    """Construct a ChatOpenAI client pointed at OpenRouter."""
    settings.require_llm_key()
    return ChatOpenAI(
        model=model_name,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
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

    Cached so the same task reuses the same client.
    """
    return _build(_TASK_MAP[task]())
