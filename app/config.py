"""Central config. Reads .env and exposes typed settings."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _agent_recursion_limit_from_env() -> int:
    """Parse AGENT_RECURSION_LIMIT into a clamped int. A malformed value
    (non-numeric, negative, etc.) silently falls back to 25 instead of
    crashing the import — config parsing must not break the app boot."""
    raw = _env("AGENT_RECURSION_LIMIT", "25") or "25"
    try:
        return max(5, min(50, int(raw)))
    except (TypeError, ValueError):
        return 25


@dataclass(frozen=True)
class Settings:
    # OpenMetadata
    om_host: str = field(default_factory=lambda: _env("OPENMETADATA_HOST", "http://localhost:8585"))
    om_api: str = field(
        default_factory=lambda: _env("OPENMETADATA_API", "http://localhost:8585/api")
    )
    om_jwt: str = field(default_factory=lambda: _env("OPENMETADATA_JWT_TOKEN"))

    # AI SDK (MCP)
    ai_sdk_host: str = field(default_factory=lambda: _env("AI_SDK_HOST", "http://localhost:8585"))
    ai_sdk_token: str = field(default_factory=lambda: _env("AI_SDK_TOKEN"))

    # LLM provider (OpenRouter)
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    openrouter_base_url: str = field(
        default_factory=lambda: _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )

    # Model routing — OpenRouter model IDs, browse at openrouter.ai/models
    model_toolcall: str = field(
        default_factory=lambda: _env("MODEL_TOOLCALL", "meta-llama/llama-3.3-70b-instruct:free")
    )
    model_description: str = field(
        default_factory=lambda: _env("MODEL_DESCRIPTION", "meta-llama/llama-3.3-70b-instruct:free")
    )
    model_classification: str = field(
        default_factory=lambda: _env(
            "MODEL_CLASSIFICATION", "meta-llama/llama-3.3-70b-instruct:free"
        )
    )
    model_stale: str = field(
        default_factory=lambda: _env("MODEL_STALE_CHECK", "meta-llama/llama-3.3-70b-instruct:free")
    )
    model_scoring: str = field(
        default_factory=lambda: _env("MODEL_SCORING", "meta-llama/llama-3.3-70b-instruct:free")
    )
    model_reasoning: str = field(
        default_factory=lambda: _env("MODEL_REASONING", "meta-llama/llama-3.3-70b-instruct:free")
    )

    # App
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # Agent — caps how many LangGraph nodes a single chat turn can traverse
    # before raising GraphRecursionError. Mirrors api_settings.agent_recursion_limit
    # so the Streamlit app and the FastAPI port stay in lockstep.
    agent_recursion_limit: int = field(default_factory=lambda: _agent_recursion_limit_from_env())

    # Paths
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    def require_om_token(self) -> str:
        if not self.om_jwt:
            raise RuntimeError(
                "OPENMETADATA_JWT_TOKEN is not set. Run `make token` for instructions."
            )
        return self.om_jwt

    def require_llm_key(self) -> None:
        if not self.openrouter_api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Get a free key at "
                "https://openrouter.ai/keys and add it to .env."
            )


settings = Settings()
settings.data_dir.mkdir(exist_ok=True)
