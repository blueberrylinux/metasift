"""Executive report — Phase 3 slice 5.

Single endpoint: `GET /report`. Serializes the full markdown report from
`app.engines.report.generate_markdown_report()` — no params, no filters.
Port layer stays thin since the engine already emits a stakeholder-ready
document.

DuckDB must be hydrated (`/analysis/refresh` at least once). An empty
catalog would produce a report full of SQL error messages, so we gate on
`duck_ok` and return the structured `no_metadata_loaded` error otherwise.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from loguru import logger

from app.api import errors
from app.api.deps import DuckOk
from app.api.schemas import ReportResponse
from app.engines import report as engine_report

router = APIRouter(prefix="/report", tags=["report"])


@router.get("", response_model=ReportResponse)
def get_report(duck_ok: DuckOk) -> ReportResponse:
    """Full executive report as a single markdown string + generation
    timestamp. Cheap to generate (all in-memory SQL) so we don't bother
    caching."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    try:
        md = engine_report.generate_markdown_report()
    except Exception as e:
        # Engine errors can leak SQL fragments / file paths / provider details.
        # Log full trace server-side; surface a generic message to the client.
        logger.exception("report generation failed")
        raise errors.ApiError(
            errors.ErrorCode.INTERNAL_ERROR,
            "Report generation failed. Check the server logs for details.",
            status_code=500,
        ) from e
    return ReportResponse(
        markdown=md,
        generated_at=datetime.now(UTC).isoformat(),
    )
