"""DQ endpoints — Phase 3 slice 4.

Ports the DQ trio (failures + recommendations + impact/risk) out of the
Streamlit agent tools into plain REST so the React side can render rich,
interactive cards instead of the read-only plotly tables exposed in slice 3.

Five endpoints:
  * GET /dq/summary                — counts (total/failed/passed/failing_tables)
  * GET /dq/failures?schema=       — failing tests LEFT JOINed with LLM
                                     explanations (summary / likely_cause /
                                     next_step / fix_type) when the
                                     explain-scan has run
  * GET /dq/recommendations?severity=  — suggested tests grouped by
                                         critical / recommended / nice-to-have
  * GET /dq/risk?limit=             — catalog-wide ranking by risk_score
                                     (failed_tests × blast-radius, PII-weighted)
  * GET /dq/impact/{fqn}            — per-table drilldown: failing tests,
                                     direct / transitive / pii_downstream counts

All reads are cache-driven — no LLM calls on the hot path. The underlying
tables are populated by the slice-2 SSE scans (`/scans/dq-explain` ,
`/scans/dq-recommend`) and by catalog sync (`/scans/refresh`). Empty-state
hints in responses point the UI at the scan that populates each table.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from loguru import logger

from app.api import errors
from app.api.deps import DuckOk
from app.api.schemas import (
    DQExplanation,
    DQFailure,
    DQFailuresResponse,
    DQImpactResponse,
    DQRecommendation,
    DQRecommendationsResponse,
    DQRiskResponse,
    DQRiskRow,
    DQSummaryResponse,
)
from app.clients import duck
from app.engines import analysis

router = APIRouter(prefix="/dq", tags=["dq"])


_VALID_SEVERITIES = {"critical", "recommended", "nice-to-have"}
_VALID_FIX_TYPES = {
    "schema_change",
    "etl_investigation",
    "data_correction",
    "upstream_fix",
    "other",
}


@router.get("/summary", response_model=DQSummaryResponse)
def summary(duck_ok: DuckOk) -> DQSummaryResponse:
    """Headline counts across om_test_cases. Safe when the table is empty —
    returns zeros rather than erroring."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    s = analysis.dq_summary()
    return DQSummaryResponse(**s)


@router.get("/failures", response_model=DQFailuresResponse)
def failures(duck_ok: DuckOk) -> DQFailuresResponse:
    """Every failing DQ test joined with its explanation. `explanation` is
    null per-row if the explain-scan hasn't been run (or failed for that row).

    The schema filter used to live here as a `?schema=` query param but
    moved entirely client-side — the server-filter-then-client-count
    pattern made the per-schema chip counts go to zero whenever a schema
    was selected (client was counting against an already-filtered list).
    Catalog size keeps one-shot fetch cheap."""
    if not duck_ok:
        raise errors.no_metadata_loaded()

    # Left-join to dq_explanations so missing explanations survive as nulls.
    # `dq_explanations` may not exist yet — catch and fall back to failures-only.
    # `SELECT 1 LIMIT 1` on an empty existing table returns zero rows (no
    # exception), so table-existence alone doesn't tell us the scan
    # produced useful content — we recompute `explanations_loaded` below
    # from whether any row's explanation survived.
    try:
        duck.query("SELECT 1 FROM dq_explanations LIMIT 1")
        has_explanations_table = True
    except Exception:
        has_explanations_table = False

    if has_explanations_table:
        df = duck.query("""
            SELECT
                tc.id                        AS test_id,
                tc.name                      AS test_name,
                tc.table_fqn,
                tc.column_name,
                tc.test_definition_name,
                tc.result_message,
                e.summary                    AS exp_summary,
                e.likely_cause               AS exp_likely_cause,
                e.next_step                  AS exp_next_step,
                e.fix_type                   AS exp_fix_type
            FROM om_test_cases tc
            LEFT JOIN dq_explanations e ON e.test_id = tc.id
            WHERE tc.status = 'Failed'
            ORDER BY tc.table_fqn, tc.name
        """)
    else:
        df = duck.query("""
            SELECT
                tc.id                  AS test_id,
                tc.name                AS test_name,
                tc.table_fqn,
                tc.column_name,
                tc.test_definition_name,
                tc.result_message,
                NULL AS exp_summary,
                NULL AS exp_likely_cause,
                NULL AS exp_next_step,
                NULL AS exp_fix_type
            FROM om_test_cases tc
            WHERE tc.status = 'Failed'
            ORDER BY tc.table_fqn, tc.name
        """)

    rows: list[DQFailure] = []
    any_explanation = False
    for _, r in df.iterrows():
        # Explicit str-check — a NULL `exp_summary` arrives as NaN under pandas
        # and `float('nan')` is truthy, so `if r['exp_summary']:` would build
        # a DQExplanation for every failure regardless of whether the scan ran.
        summary_val = r.get("exp_summary")
        exp: DQExplanation | None = None
        if isinstance(summary_val, str) and summary_val:
            any_explanation = True
            fix_type = r.get("exp_fix_type") if isinstance(r.get("exp_fix_type"), str) else None
            exp = DQExplanation(
                summary=summary_val,
                likely_cause=_str_or_empty(r.get("exp_likely_cause")),
                next_step=_str_or_empty(r.get("exp_next_step")),
                fix_type=fix_type if fix_type in _VALID_FIX_TYPES else "other",
            )
        rows.append(
            DQFailure(
                test_id=str(r["test_id"] or ""),
                test_name=str(r["test_name"] or ""),
                table_fqn=str(r["table_fqn"] or ""),
                column_name=r["column_name"] if isinstance(r["column_name"], str) else None,
                test_definition_name=(
                    r["test_definition_name"]
                    if isinstance(r["test_definition_name"], str)
                    else None
                ),
                result_message=(
                    r["result_message"] if isinstance(r["result_message"], str) else None
                ),
                explanation=exp,
            )
        )
    return DQFailuresResponse(
        summary=DQSummaryResponse(**analysis.dq_summary()),
        rows=rows,
        # Flag reflects "usable explanations exist" — not just table existence.
        # A scan that ran but produced zero rows leaves the table present but
        # every exp_summary null, which we still want flagged as "not loaded"
        # so the UI keeps showing the Explain-DQ CTA.
        explanations_loaded=any_explanation,
    )


@router.get("/recommendations", response_model=DQRecommendationsResponse)
def recommendations(
    duck_ok: DuckOk,
    severity: str | None = None,
) -> DQRecommendationsResponse:
    """Per-table DQ test recommendations. `severity` filters to
    'critical' | 'recommended' | 'nice-to-have'. Empty list when the
    `dq_recommend` scan hasn't been run."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    if severity is not None and severity not in _VALID_SEVERITIES:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            f"severity must be one of {sorted(_VALID_SEVERITIES)}.",
        )

    try:
        duck.query("SELECT 1 FROM dq_recommendations LIMIT 1")
    except Exception:
        # Scan hasn't run — empty list plus a hint field so the UI can render a CTA.
        return DQRecommendationsResponse(rows=[], scan_run=False)

    sql = (
        "SELECT table_fqn, column_name, test_definition, parameters, rationale, severity "
        "FROM dq_recommendations"
    )
    params: list[Any] = []
    if severity is not None:
        sql += " WHERE severity = ?"
        params.append(severity)
    sql += (
        " ORDER BY CASE severity "
        "WHEN 'critical' THEN 0 WHEN 'recommended' THEN 1 WHEN 'nice-to-have' THEN 2 ELSE 3 END, "
        "table_fqn, column_name"
    )
    df = duck.query(sql, params) if params else duck.query(sql)

    rows: list[DQRecommendation] = []
    for _, r in df.iterrows():
        try:
            params_parsed = json.loads(r["parameters"]) if r.get("parameters") else []
        except (TypeError, json.JSONDecodeError) as e:
            # Silent fallback hid data-loss in an earlier iteration — log loud
            # so a broken engine writer shows up in the server log without
            # breaking the route.
            logger.warning(
                f"dq_recommendations.parameters parse failed for "
                f"{r.get('table_fqn')}/{r.get('column_name')}: {e}; got {r.get('parameters')!r}"
            )
            params_parsed = []
        rows.append(
            DQRecommendation(
                table_fqn=str(r["table_fqn"]),
                column_name=r["column_name"] if isinstance(r["column_name"], str) else None,
                test_definition=str(r["test_definition"]),
                parameters=params_parsed if isinstance(params_parsed, list) else [],
                rationale=str(r.get("rationale") or ""),
                severity=str(r["severity"]),
            )
        )
    return DQRecommendationsResponse(rows=rows, scan_run=True)


@router.get("/risk", response_model=DQRiskResponse)
def risk(duck_ok: DuckOk, limit: int = 20) -> DQRiskResponse:
    """Catalog-wide DQ risk ranking — tables with failing tests sorted by
    risk_score (failed_tests × weighted downstream footprint, PII-amplified)."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    if limit < 1 or limit > 200:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            "limit must be between 1 and 200.",
        )
    df = analysis.dq_risk_ranking(limit=limit)
    rows = [
        DQRiskRow(
            fqn=str(r["fqn"]),
            failed_tests=int(r["failed_tests"]),
            direct=int(r["direct"]),
            transitive=int(r["transitive"]),
            pii_downstream=int(r["pii_downstream"]),
            risk_score=float(r["risk_score"]),
        )
        for _, r in df.iterrows()
    ]
    return DQRiskResponse(rows=rows)


@router.get("/impact/{fqn:path}", response_model=DQImpactResponse)
def impact(fqn: str, duck_ok: DuckOk) -> DQImpactResponse:
    """Per-table drilldown: currently failing tests plus their downstream
    blast radius. Returns zero-counts (not 404) for a valid FQN with no
    failing tests so the UI can render a "clean" empty state without a
    second HTTP status to handle."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    if not fqn.strip():
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            "fqn must be non-empty.",
        )
    try:
        data = analysis.dq_impact(fqn)
    except Exception as e:
        logger.exception(f"dq_impact failed for {fqn}: {e}")
        raise errors.ApiError(
            errors.ErrorCode.INTERNAL_ERROR,
            f"Couldn't compute impact for {fqn}: {e}",
            status_code=500,
        ) from e
    return DQImpactResponse(**data)


# ── helpers ───────────────────────────────────────────────────────────────


def _schema_of(fqn: str) -> str:
    """Mirror `viz._schema_of` exactly — third segment of the FQN
    (service.database.schema.table), falling back to 'other' when the FQN
    is shorter. Keeps the sentinel aligned across the two helpers so the
    viz and dq screens would agree on which bucket a malformed FQN lands in."""
    parts = fqn.split(".")
    return parts[2] if len(parts) >= 3 else "other"


def _str_or_empty(v: Any) -> str:
    """Coerce nullable pandas cell to a clean string — `None` / NaN / bytes
    all become "" rather than propagating as the literal string 'nan'."""
    return v if isinstance(v, str) else ""
