"""Shared FastAPI dependencies.

Thin wrappers over the existing singletons in app.clients / app.engines.
Phase 0 ships the minimum: typed dependency functions used by /health and
picked up by future routers as they come online.

No class facades — we import the modules directly, matching the existing
module-level-singleton pattern in app/clients/*.py.
"""

from __future__ import annotations

import threading
import time
from typing import Annotated

from fastapi import Depends
from loguru import logger

from app.api import store
from app.clients import duck, openmetadata

# ── Probe cache ────────────────────────────────────────────────────────────
#
# The React sidebar polls /health every 30s and TanStack Query invalidates
# on focus changes, so a single app can easily fire a half-dozen /health
# requests a minute. Each probe is a sync HTTP/DB call running in FastAPI's
# thread pool — under burst, the pool saturates and new requests queue.
#
# Cache each probe's last result for a short window. Keeps the visible
# status-dot behaviour responsive (sub-5s staleness) without hammering
# OpenMetadata / the LLM creds check / DuckDB / SQLite on every poll.

_PROBE_TTL_S = 5.0
_probe_cache: dict[str, tuple[float, bool]] = {}


def invalidate_probe_cache(name: str | None = None) -> None:
    """Drop a cached probe so the next /health call re-probes immediately.
    `name=None` drops everything. Used by /om/config and /llm/config when
    the user changes credentials — without this, the UI would show the old
    status for up to 5s after a successful save."""
    if name is None:
        _probe_cache.clear()
    else:
        _probe_cache.pop(name, None)


# Per-probe lock serializes the refresh path so concurrent missers (e.g.
# 40 threads hitting /health at the same moment) don't all fire httpx/
# DuckDB calls in parallel. The first caller computes, the rest wait on
# the lock, then fall through and read the freshly-cached value. Without
# this the probe cache was ineffective on burst cold-start.
_probe_locks: dict[str, threading.Lock] = {
    "om": threading.Lock(),
    "llm": threading.Lock(),
    "duck": threading.Lock(),
    "sqlite": threading.Lock(),
}


def _cached_probe(name: str, fn) -> bool:
    """Run `fn` at most once per TTL window per probe name. Concurrent
    callers coalesce onto a single refresh via a per-probe lock."""
    now = time.monotonic()
    cached = _probe_cache.get(name)
    if cached is not None and now - cached[0] < _PROBE_TTL_S:
        return cached[1]
    # Serialize refresh — if another thread is already computing, wait for
    # it to finish (cheap since the probe itself caps at a few seconds)
    # and read the value it wrote.
    with _probe_locks[name]:
        cached = _probe_cache.get(name)
        if cached is not None and time.monotonic() - cached[0] < _PROBE_TTL_S:
            return cached[1]
        result = fn()
        _probe_cache[name] = (time.monotonic(), result)
        return result


def duck_ok() -> bool:
    """True if DuckDB has been hydrated in THIS process (om_tables has rows).

    Must check DuckDB directly, not our SQLite audit trail — the audit
    survives process restarts, the in-memory DuckDB doesn't. If the server
    just restarted, SQLite still says "last refresh completed" but DuckDB
    is empty, and analysis endpoints would 500 until the user re-runs
    refresh.

    Not cached via `_cached_probe`: the probe is microseconds, and more
    importantly we need it to flip to True the instant a refresh completes.
    A 5s cache here leaves analysis endpoints rejecting requests for up to
    5 seconds after the user's refresh finishes. Safe to call on every
    request now that `duck.get_conn()` is thread-local.
    """
    try:
        row = (
            duck.get_conn()
            .execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'om_tables'"
            )
            .fetchone()
        )
        if not row or row[0] == 0:
            return False
        # Table exists — confirm it has rows (refresh actually ran, not
        # just schema bootstrap).
        rows = duck.get_conn().execute("SELECT COUNT(*) FROM om_tables").fetchone()
        return bool(rows and rows[0] > 0)
    except Exception:
        return False


def om_ok() -> bool:
    """OM reachability — pulls from app.clients.openmetadata.health_check()."""
    return _cached_probe("om", openmetadata.health_check)


def llm_ok() -> bool:
    """True if at least one LLM credential is available.

    Keeps it cheap — no actual network call. Matches the sidebar's 🟢/🔴 logic
    in the Streamlit version.
    """

    def probe() -> bool:
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

    return _cached_probe("llm", probe)


def sqlite_ok() -> bool:
    return _cached_probe("sqlite", store.ping)


# Annotated aliases keep route signatures tight:
#   def endpoint(duck: DuckOk): ...
DuckOk = Annotated[bool, Depends(duck_ok)]
OmOk = Annotated[bool, Depends(om_ok)]
LlmOk = Annotated[bool, Depends(llm_ok)]
SqliteOk = Annotated[bool, Depends(sqlite_ok)]
