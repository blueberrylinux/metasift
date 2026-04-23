"""Visualization endpoints — Phase 3 slice 3.

One tab per entry in `app.engines.viz.ALL_VIZ`. The backend just serializes
the plotly Figure each builder returns and hands it to React via
`fig.to_dict()` (Plotly's canonical JSON shape — data + layout + frames).
React renders it with react-plotly.js.

Two endpoints:
  * GET /viz          list of tab metadata (slug, label, caption) in display order
  * GET /viz/{slug}   {figure: <plotly dict>} or {figure: null} when the
                      builder returned None (not enough data → empty state)

Slugs are URL-safe identifiers mapped from the emoji-ful Streamlit labels.
The mapping lives here so the engine module stays unchanged — it still
exposes `ALL_VIZ` for the Streamlit sidebar path. Keep the two in sync when
a new tab lands.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from loguru import logger

from app.api import errors
from app.api.deps import DuckOk
from app.api.schemas import VizFigureResponse, VizListResponse, VizTabMeta
from app.engines import viz

router = APIRouter(prefix="/viz", tags=["viz"])


# Ordered slug → builder mapping. Matches `viz.ALL_VIZ` ordering + captions
# so the React tab strip reads identically to the Streamlit st.tabs row.
_TABS: list[tuple[str, str, str, Any]] = [
    ("score-gauge", "🎯 Score gauge", "composite score as a speedometer", viz.composite_gauge),
    ("lineage", "🔗 Lineage", "catalog dependency graph", viz.lineage_dag),
    (
        "governance",
        "🛡️ Governance",
        "where does PII propagate? — origins, tainted downstream, and the edges that carry it",
        viz.governance_lineage_dag,
    ),
    (
        "blast-radius",
        "💥 Blast radius",
        "top tables ranked by downstream impact",
        viz.blast_radius_bars,
    ),
    (
        "stewardship",
        "👥 Stewardship",
        "per-team scorecard + orphan count",
        viz.stewardship_leaderboard,
    ),
    (
        "catalog-map",
        "🗺️ Catalog map",
        "treemap by schema / table / PII share",
        viz.catalog_treemap,
    ),
    (
        "tag-conflicts",
        "🔥 Tag conflicts",
        "column × table → tag heatmap",
        viz.tag_conflict_heatmap,
    ),
    (
        "quality",
        "📈 Quality",
        "per-table description scores with LLM rationale on hover",
        viz.quality_by_table,
    ),
    (
        "dq-failures",
        "🧪 DQ failures",
        "failed data quality checks with LLM-written plain-English explanations",
        viz.dq_failure_table,
    ),
    (
        "dq-gaps",
        "💡 DQ gaps",
        "recommended data quality tests that should exist but currently don't",
        viz.dq_recommendations_table,
    ),
    (
        "dq-risk",
        "🎯 DQ risk",
        "failing DQ tests ranked by downstream blast radius (PII-weighted)",
        viz.dq_risk_bars,
    ),
]

_BY_SLUG = {slug: (label, caption, builder) for slug, label, caption, builder in _TABS}


@router.get("", response_model=VizListResponse)
def list_tabs() -> VizListResponse:
    """Tab strip metadata in display order. Cheap — no DuckDB access. The UI
    uses this on /viz mount to render the tabs; each tab lazy-loads its own
    figure via GET /viz/{slug}."""
    return VizListResponse(
        tabs=[VizTabMeta(slug=s, label=lbl, caption=cap) for s, lbl, cap, _ in _TABS]
    )


@router.get("/{slug}", response_model=VizFigureResponse)
def get_figure(slug: str, duck_ok: DuckOk) -> VizFigureResponse:
    """Plotly figure JSON for one tab, or `figure: null` for the empty-state.

    The builders follow a uniform contract: return a `plotly.graph_objs.Figure`
    when there's enough data, else None. We forward that shape — React
    renders the empty-state hint in the `null` case (pointing the user at the
    sidebar scan that would populate it)."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    entry = _BY_SLUG.get(slug)
    if entry is None:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            f"Unknown viz slug `{slug}`. See GET /viz for valid options.",
            status_code=404,
        )
    _label, _caption, builder = entry
    try:
        fig = builder()
    except Exception as e:
        # Match the Streamlit error path (`st.error(f"Chart failed to render: {e}")`):
        # surface as 500 with a structured error so the UI can render a card.
        logger.exception(f"viz builder {slug} failed")
        raise errors.ApiError(
            errors.ErrorCode.INTERNAL_ERROR,
            f"Chart failed to render: {e}",
            status_code=500,
        ) from e
    if fig is None:
        return VizFigureResponse(figure=None)
    return VizFigureResponse(figure=fig.to_dict())
