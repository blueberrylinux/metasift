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


@dataclass(frozen=True)
class Settings:
    # OpenMetadata
    om_host: str = field(default_factory=lambda: _env("OPENMETADATA_HOST", "http://localhost:8585"))
    om_api: str = field(default_factory=lambda: _env("OPENMETADATA_API", "http://localhost:8585/api"))
    om_jwt: str = field(default_factory=lambda: _env("OPENMETADATA_JWT_TOKEN"))

    # AI SDK (MCP)
    ai_sdk_host: str = field(default_factory=lambda: _env("AI_SDK_HOST", "http://localhost:8585"))
    ai_sdk_token: str = field(default_factory=lambda: _env("AI_SDK_TOKEN"))

    # LLM providers
    google_api_key: str = field(default_factory=lambda: _env("GOOGLE_API_KEY"))
    openrouter_api_key: str = field(default_factory=lambda: _env("OPENROUTER_API_KEY"))
    openrouter_base_url: str = field(
        default_factory=lambda: _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )

    # Model routing
    model_toolcall: str = field(default_factory=lambda: _env("MODEL_TOOLCALL", "gemini-2.5-flash"))
    model_description: str = field(default_factory=lambda: _env("MODEL_DESCRIPTION", "gemini-2.5-flash"))
    model_classification: str = field(default_factory=lambda: _env("MODEL_CLASSIFICATION", "gemini-2.5-flash"))
    model_stale: str = field(default_factory=lambda: _env("MODEL_STALE_CHECK", "gemini-2.5-flash"))
    model_scoring: str = field(default_factory=lambda: _env("MODEL_SCORING", "gemini-2.5-flash"))
    model_reasoning: str = field(default_factory=lambda: _env("MODEL_REASONING", "gemini-2.5-flash"))

    # App
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))

    # Paths
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")

    def require_om_token(self) -> str:
        if not self.om_jwt:
            raise RuntimeError(
                "OPENMETADATA_JWT_TOKEN is not set. Run `make token` for instructions."
            )
        return self.om_jwt

    def require_llm_key(self) -> None:
        if not self.google_api_key and not self.openrouter_api_key:
            raise RuntimeError(
                "No LLM key configured. Set GOOGLE_API_KEY (recommended) in .env — "
                "get a free key at https://aistudio.google.com/apikey"
            )


settings = Settings()
settings.data_dir.mkdir(exist_ok=True)
