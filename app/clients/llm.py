"""LLM router — picks the right model per task type, with graceful fallback."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.config import settings

TaskType = Literal[
    "toolcall", "description", "classification", "stale", "scoring", "reasoning"
]


def _gemini(model: str) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key,
        temperature=0.2,
    )


def _openrouter(model: str) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        temperature=0.2,
    )


def _build(model_name: str) -> BaseChatModel:
    """Pick provider by model prefix. Gemini if starts with 'gemini-', else OpenRouter."""
    settings.require_llm_key()
    if model_name.startswith("gemini") and settings.google_api_key:
        return _gemini(model_name)
    if settings.openrouter_api_key:
        return _openrouter(model_name)
    # Last resort: try Gemini even without prefix match
    return _gemini(model_name)


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
    model_name = _TASK_MAP[task]()
    return _build(model_name)
