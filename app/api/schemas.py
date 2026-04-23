"""Pydantic response models for the FastAPI layer.

Phase 0 shipped /health. Phase 1 adds composite score + coverage + refresh —
the dashboard's vertical slice. Subsequent phases fill in conversation,
review, viz, and report shapes as they're implemented.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Sidebar status-dot payload."""

    ok: bool
    om: bool
    llm: bool
    duck: bool
    sqlite: bool
    version: str


# ── /analysis ─────────────────────────────────────────────────────────────────


class CompositeScore(BaseModel):
    """Dashboard headline metric. `scanned` is False until the deep scan has
    populated `cleaning_results` — the UI should render accuracy/quality as
    "—" in that state rather than "0%"."""

    coverage: float
    accuracy: float
    consistency: float
    quality: float
    composite: float
    scanned: bool = Field(
        description="True once the deep scan has run. When False, accuracy and "
        "quality are still in the payload as 0.0 so the composite math works, "
        "but the UI should show '—' for those two tiles."
    )


class CoverageRow(BaseModel):
    """One row of documentation coverage, keyed by (database, schema)."""

    database: str
    schema_: str = Field(alias="schema", serialization_alias="schema")
    total: int
    documented: int
    coverage_pct: float

    model_config = {"populate_by_name": True}


class CoverageResponse(BaseModel):
    rows: list[CoverageRow]


class RefreshResponse(BaseModel):
    """Payload returned after a synchronous `/analysis/refresh`. Counts mirror
    `duck.refresh_all()`; `run_id` ties back to the `scan_runs` row we logged
    so the sidebar's 'last scan N min ago' can pick it up."""

    run_id: int
    counts: dict[str, int]
    duration_ms: int
