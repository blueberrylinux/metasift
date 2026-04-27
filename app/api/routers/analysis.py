"""Analysis endpoints — dashboard vertical slice.

Phase 1 scope:
  * GET  /analysis/composite — serialize analysis.composite_score()
  * GET  /analysis/coverage  — serialize analysis.documentation_coverage() (optional ?schema= filter)
  * POST /analysis/refresh   — duck.refresh_all() synchronously, logged to scan_runs

No SSE here — refresh blocks until done. Phase 4 adds progress streaming for
the long scans. Sticking to sync for refresh keeps Phase 1 honest; the user
clicks once and sees the result.

Per PORT_ERRATA, we import engine modules directly. No DuckStore, no app.state
wiring — the engines' module-level singletons (duck.get_conn, etc.) are the
source of truth.
"""

from __future__ import annotations

import asyncio
import math
import time

from fastapi import APIRouter
from loguru import logger

from app.api import errors, store
from app.api.deps import DuckOk, WritesEnabled
from app.api.schemas import (
    CompositeScore,
    CoverageResponse,
    CoverageRow,
    DataSourceRow,
    DataSourcesResponse,
    RefreshResponse,
)
from app.clients import duck
from app.engines import analysis

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/composite", response_model=CompositeScore)
def get_composite(duck_ok: DuckOk) -> CompositeScore:
    """Headline metric: weighted combination of coverage, accuracy, consistency, quality.

    Precondition: DuckDB must be hydrated (POST /analysis/refresh at least once).
    Returns NO_METADATA_LOADED otherwise so the UI can show the empty-state CTA.
    """
    if not duck_ok:
        raise errors.no_metadata_loaded()
    raw = analysis.composite_score()
    return CompositeScore(
        coverage=raw["coverage"],
        accuracy=raw["accuracy"],
        consistency=raw["consistency"],
        quality=raw["quality"],
        composite=raw["composite"],
        scanned=bool(raw["_scanned"]),
    )


@router.get("/coverage", response_model=CoverageResponse)
def get_coverage(duck_ok: DuckOk, schema: str | None = None) -> CoverageResponse:
    """Per-schema documentation coverage. Optional ?schema= filter matches the
    `schema` column; case-sensitive, exact-match — the catalog's schema names
    are the identity used everywhere else in the UI."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    df = analysis.documentation_coverage()
    if schema is not None:
        df = df[df["schema"] == schema]
    records = df.to_dict(orient="records")
    rows = [CoverageRow.model_validate(r) for r in records]
    return CoverageResponse(rows=rows)


@router.get("/data-sources", response_model=DataSourcesResponse)
def get_data_sources(duck_ok: DuckOk) -> DataSourcesResponse:
    """List every service registered in OpenMetadata with its table count.

    Groups by service kind (database / dashboard / messaging / pipeline) and
    joins database services against `om_tables` for a rough "how much has
    actually been ingested" number. Mirrors what the `list_services` agent
    tool returns, for direct UI rendering."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    df = analysis.service_coverage()
    records = df.to_dict(orient="records")
    rows = [DataSourceRow.model_validate(r) for r in records]
    return DataSourcesResponse(rows=rows)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(_: WritesEnabled) -> RefreshResponse:
    """Pull fresh metadata from OpenMetadata into DuckDB. Blocks until done
    (typically 30s-2min depending on catalog size). Logs a `scan_runs` row
    so the sidebar's 'last scan N min ago' badge can pick it up.

    Single-worker FastAPI + in-memory DuckDB means only one refresh can run at
    a time — we guard with the scan_is_running check so a double-click doesn't
    corrupt in-flight writes."""
    run_id = store.try_start_scan("refresh")
    if run_id is None:
        raise errors.ApiError(
            errors.ErrorCode.SCAN_ALREADY_RUNNING,
            "A metadata refresh is already running. Wait for it to finish.",
            status_code=409,
        )
    started = time.perf_counter()
    try:
        # refresh_all is sync and touches OM over HTTP; push it off the event
        # loop so the server can keep serving /health etc. while it runs.
        counts = await asyncio.to_thread(duck.refresh_all)
    except Exception as exc:
        store.finish_scan(run_id, status="failed", error=str(exc))
        logger.exception("refresh_all failed")
        # `refresh_all` does both OM HTTP calls AND local DuckDB / pandas
        # work. Mapping every failure to OM_UNREACHABLE would report a
        # DuckDB binder bug or a pandas issue as an OpenMetadata outage —
        # catastrophic for diagnosis. Only translate clearly-OM errors
        # (httpx) to OM_UNREACHABLE; other failures surface as a generic
        # INTERNAL_ERROR so operators see the real cause.
        import httpx

        if isinstance(exc, (httpx.HTTPError, httpx.InvalidURL, ConnectionError)):
            raise errors.om_unreachable() from exc
        raise errors.ApiError(
            errors.ErrorCode.INTERNAL_ERROR,
            f"Refresh failed: {type(exc).__name__}. Check server logs.",
            status_code=500,
        ) from exc

    duration_ms = math.floor((time.perf_counter() - started) * 1000)
    store.finish_scan(run_id, status="completed", counts=counts)
    return RefreshResponse(run_id=run_id, counts=counts, duration_ms=duration_ms)
