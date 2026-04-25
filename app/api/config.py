"""Port config — isolated from app/config.py to avoid regressing Streamlit.

Streamlit reads its settings from `app.config.settings` (a frozen dataclass).
The port reads from `app.api.config.api_settings` (pydantic-settings). They
share the same .env file but neither imports the other, so changes here
cannot break the Streamlit entry point.

Why isolation: app/config.py is on Streamlit's import path; any rewrite risks
breaking `from app.config import settings` in ~60 call sites. Keeping a
separate Pydantic config removes that class of risk entirely.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class ApiSettings(BaseSettings):
    """FastAPI-specific settings. Reads the same .env as Streamlit, but only
    consumes port-layer vars. Engine/client config still flows through
    app.config.settings untouched."""

    # CORS — Vite dev server lives on 5173; bundled prod serves same origin
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Allowed origins for CORS. Add your prod domain here.",
    )

    # Whether to mount web/dist as a static fallback. Set by `make run`.
    serve_static: bool = Field(default=False)

    # SQLite persistent store (conversations, review audit, scan runs).
    # Relative paths resolve from the project root, not CWD — pydantic-settings
    # passes env strings to Path() which leaves them relative to the current
    # working directory, so a relative `SQLITE_PATH` would silently land
    # wherever the user happened to launch from.
    sqlite_path: Path = Field(default=PROJECT_ROOT / "metasift.sqlite")

    # FastAPI bind. Defaults to loopback so a casual `make api` doesn't expose
    # the port on every interface. Override in production via API_HOST=0.0.0.0
    # or by changing the Makefile flag.
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    @field_validator("sqlite_path", mode="after")
    @classmethod
    def _resolve_relative_paths(cls, v: Path) -> Path:
        return v if v.is_absolute() else (PROJECT_ROOT / v).resolve()

    # Agent + scan behavior
    agent_recursion_limit: int = Field(default=15, ge=5, le=50)
    scan_max_concurrent: int = Field(
        default=1,
        description="Only one long-running scan at a time in single-worker mode.",
    )

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Don't choke on Streamlit's env vars — just ignore anything we don't declare
        extra="ignore",
    )


api_settings = ApiSettings()
