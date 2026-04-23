"""Shared FastAPI dependencies.

Thin wrappers over the existing singletons in app.clients / app.engines.
Phase 0 ships the minimum: typed dependency functions used by /health and
picked up by future routers as they come online.

No class facades — we import the modules directly, matching the existing
module-level-singleton pattern in app/clients/*.py.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from loguru import logger

from app.api import store
from app.clients import duck, openmetadata


def duck_ok() -> bool:
    """True if DuckDB has been hydrated (om_tables has rows)."""
    try:
        rows = duck.query("SELECT COUNT(*) AS n FROM om_tables").iloc[0]["n"]
        return int(rows) > 0
    except Exception:
        return False


def om_ok() -> bool:
    """OM reachability — pulls from app.clients.openmetadata.health_check()."""
    return openmetadata.health_check()


def llm_ok() -> bool:
    """True if at least one LLM credential is available.

    Keeps it cheap — no actual network call. Matches the sidebar's 🟢/🔴 logic
    in the Streamlit version.
    """
    try:
        from app.clients.llm import get_override
        from app.config import settings

        override = get_override()
        if override and override.api_key:
            return True
        return bool(settings.openrouter_api_key)
    except Exception as e:
        logger.warning(f"llm_ok probe failed: {e}")
        return False


def sqlite_ok() -> bool:
    return store.ping()


# Annotated aliases keep route signatures tight:
#   def endpoint(duck: DuckOk): ...
DuckOk = Annotated[bool, Depends(duck_ok)]
OmOk = Annotated[bool, Depends(om_ok)]
LlmOk = Annotated[bool, Depends(llm_ok)]
SqliteOk = Annotated[bool, Depends(sqlite_ok)]
