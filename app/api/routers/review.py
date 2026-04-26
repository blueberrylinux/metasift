"""Review queue — Phase 3 slice 1.

Ports the Streamlit review panel (`app/main.py::_build_review_queue` +
`_render_review_card`) to REST. Three endpoints:

  * GET   /review                        list pending items (kind filter optional)
  * POST  /review/{item_id}/accept       apply as-is
  * POST  /review/{item_id}/accept-edited apply with user-edited value
  * POST  /review/{item_id}/reject       dismiss

Pending = item_id not yet present in `review_actions`. Unlike the Streamlit
session-scoped `review_dismissed` set, this is persistent across process
restarts: once a user rejects, it stays rejected. A re-scan that emits the
same key doesn't resurface.

The SQL is lifted verbatim from `_build_review_queue()` per PORT_ERRATA to
avoid divergence.

Known trade-offs (intentional for slice 1):
  * Apply + audit is not transactional. The OM PATCH fires first; if the
    subsequent review_actions INSERT fails, the patch is retained and
    `_record` logs + returns -1. Item resurfaces on next /review until the
    audit row lands — a duplicate PATCH on re-accept is possible but
    idempotent against OpenMetadata for description/tag writes.
  * Double-click race: a user who double-clicks Accept in the ~ms window
    before the mutation's `pending` flag disables the button could issue
    two concurrent POSTs. Both will find the item pending and both will
    PATCH. The UI's `disabled={pending}` in ReviewCard closes this to a
    sub-ms window; server-side idempotency comes later if it matters.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter
from loguru import logger

from app.api import errors, store
from app.api.deps import DuckOk
from app.api.schemas import (
    AcceptEditedRequest,
    ReviewAcceptResponse,
    ReviewItem,
    ReviewListResponse,
)
from app.clients import duck
from app.engines import stewardship
from app.engines.stewardship import Suggestion

router = APIRouter(prefix="/review", tags=["review"])


# Same tag options the Streamlit dropdown uses — app/main.py::27.
_PII_TAG_OPTIONS = ["PII.Sensitive", "PII.NonSensitive", "PII.None"]


def _resolved_keys() -> set[str]:
    """item_ids already actioned (accepted / rejected / accepted_edited).
    Pending items exclude these."""
    rows = store.get_conn().execute("SELECT DISTINCT item_id FROM review_actions").fetchall()
    return {r[0] for r in rows}


def _build_queue() -> list[dict[str, Any]]:
    """Collect pending suggestions from cleaning_results + doc_suggestions +
    pii_results. SQL lifted from app/main.py::_build_review_queue — same
    filters, same ordering, same dict shape per item."""
    items: list[dict[str, Any]] = []

    # Stale descriptions — cleaning_results rows with a non-empty correction.
    try:
        stale = duck.query("""
            SELECT
                c.fqn,
                c.stale_reason,
                c.stale_confidence,
                c.stale_corrected,
                t.description AS current_description
            FROM cleaning_results c
            LEFT JOIN om_tables t ON t.fullyQualifiedName = c.fqn
            WHERE c.stale = TRUE
              AND c.stale_corrected IS NOT NULL
              AND length(c.stale_corrected) > 0
            ORDER BY c.stale_confidence DESC
        """)
        for _, r in stale.iterrows():
            items.append(
                {
                    "kind": "description",
                    "key": f"desc::{r['fqn']}",
                    "fqn": r["fqn"],
                    "column": None,
                    "old": r["current_description"] or "",
                    "new": r["stale_corrected"] or "",
                    "confidence": float(r["stale_confidence"] or 0.0),
                    "reason": r["stale_reason"] or "",
                }
            )
    except Exception:
        pass  # no deep scan yet

    # Auto-drafted descriptions for undocumented tables. Join so that drafts
    # for tables that have since been documented drop out automatically.
    try:
        drafts = duck.query("""
            SELECT d.fqn, d.suggested, d.confidence, d.reasoning
            FROM doc_suggestions d
            JOIN om_tables t ON t.fullyQualifiedName = d.fqn
            WHERE (t.description IS NULL OR length(t.description) = 0)
              AND d.suggested IS NOT NULL
              AND length(d.suggested) > 0
            ORDER BY d.fqn
        """)
        for _, r in drafts.iterrows():
            items.append(
                {
                    "kind": "description",
                    "key": f"doc::{r['fqn']}",
                    "fqn": r["fqn"],
                    "column": None,
                    "old": "",
                    "new": r["suggested"] or "",
                    "confidence": float(r["confidence"] or 0.0),
                    "reason": r["reasoning"] or "auto-drafted for undocumented table",
                }
            )
    except Exception:
        pass

    # PII tag gaps.
    try:
        gaps = duck.query("""
            SELECT table_fqn, column_name, current_tag, suggested_tag, confidence, reason
            FROM pii_results
            WHERE suggested_tag IS NOT NULL
              AND (current_tag IS NULL OR current_tag != suggested_tag)
            ORDER BY
                CASE WHEN suggested_tag = 'PII.Sensitive' THEN 0 ELSE 1 END,
                confidence DESC
        """)
        for _, r in gaps.iterrows():
            items.append(
                {
                    "kind": "pii_tag",
                    "key": f"pii::{r['table_fqn']}::{r['column_name']}",
                    "fqn": r["table_fqn"],
                    "column": r["column_name"],
                    "old": r["current_tag"],
                    "new": r["suggested_tag"],
                    "confidence": float(r["confidence"] or 0.0),
                    "reason": r["reason"] or "",
                }
            )
    except Exception:
        pass

    resolved = _resolved_keys()
    return [i for i in items if i["key"] not in resolved]


def _find(item_id: str) -> dict[str, Any]:
    """Look up a pending item by key, or raise 404."""
    for item in _build_queue():
        if item["key"] == item_id:
            return item
    raise errors.review_item_not_found(item_id)


# Valid item_id keys: `desc::<fqn>`, `doc::<fqn>`, `pii::<fqn>::<col>`.
# FQNs can contain dots and hyphens; column names can contain underscores
# and dots too. Not strict — just enough to reject obvious garbage before
# hitting the expensive _build_queue() scan.
_KEY_RE = re.compile(r"^(desc|doc|pii)::[A-Za-z0-9_.:\-]+(::[A-Za-z0-9_.\-]+)?$")


def _validate_key(item_id: str) -> None:
    if not _KEY_RE.match(item_id):
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            f"item_id `{item_id}` is not a well-formed review key.",
        )


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("", response_model=ReviewListResponse)
def list_review(duck_ok: DuckOk, kind: str | None = None) -> ReviewListResponse:
    """Pending review items. Optional `?kind=description|pii_tag` filter.

    Empty list if the cleaning / PII scans haven't been run — callers render
    an empty-state hint pointing at the sidebar scan buttons (Phase 3 slice 2
    adds the scan endpoints)."""
    if not duck_ok:
        raise errors.no_metadata_loaded()
    items = _build_queue()
    if kind is not None:
        if kind not in {"description", "pii_tag"}:
            raise errors.ApiError(
                errors.ErrorCode.INVALID_REQUEST,
                "kind must be 'description' or 'pii_tag'",
            )
        items = [i for i in items if i["kind"] == kind]
    return ReviewListResponse(rows=[ReviewItem.model_validate(i) for i in items])


def _apply_description(item: dict[str, Any], value: str) -> None:
    s = Suggestion(
        fqn=item["fqn"],
        field="description",
        old=item["old"] or None,
        new=value.strip(),
        confidence=1.0,
        reasoning="User-approved via review queue",
    )
    if not stewardship.apply_suggestion(s):
        raise errors.ApiError(
            errors.ErrorCode.PATCH_FAILED,
            f"Failed to apply description to `{item['fqn']}`.",
            status_code=502,
        )


def _apply_pii_tag(item: dict[str, Any], tag: str) -> None:
    if tag not in _PII_TAG_OPTIONS:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            f"tag must be one of {_PII_TAG_OPTIONS}",
        )
    result = stewardship.apply_pii_tag(item["fqn"], item["column"], tag)
    if not result["ok"]:
        raise errors.ApiError(
            errors.ErrorCode.PATCH_FAILED,
            result["message"],
            status_code=502,
            detail={"status": result["status"]},
        )


def _record(item: dict[str, Any], *, status: str, after_val: str, reason: str | None) -> int:
    """Insert a row into review_actions. Separated so the accept/reject
    handlers can swallow-log an audit-write failure without unwinding an
    already-applied OpenMetadata PATCH (there's no compensating API). Returns
    -1 as a sentinel when the insert failed — the UI still sees success for
    the OM side and the item resurfaces on the next /review until the audit
    catches up."""
    try:
        return store.record_review_action(
            item_id=item["key"],
            kind=item["kind"],
            status=status,
            fqn=item["fqn"],
            column_name=item.get("column"),
            before_val=item["old"] or "",
            after_val=after_val,
            reason=reason,
        )
    except Exception as e:
        logger.exception(f"review_actions insert failed for {item['key']} (status={status}): {e}")
        return -1


@router.post("/{item_id}/accept", response_model=ReviewAcceptResponse)
def accept(item_id: str) -> ReviewAcceptResponse:
    """Apply the suggestion verbatim. Dispatches on item.kind:
    description → apply_suggestion, pii_tag → apply_pii_tag."""
    _validate_key(item_id)
    item = _find(item_id)
    if item["kind"] == "description":
        _apply_description(item, item["new"])
    else:
        _apply_pii_tag(item, item["new"])
    action_id = _record(item, status="accepted", after_val=item["new"], reason=None)
    logger.info(f"review accepted {item_id} (action #{action_id})")
    return ReviewAcceptResponse(action_id=action_id, status="accepted", after_val=item["new"])


@router.post("/{item_id}/accept-edited", response_model=ReviewAcceptResponse)
def accept_edited(item_id: str, req: AcceptEditedRequest) -> ReviewAcceptResponse:
    """Apply with a user-edited value. For descriptions the textarea content,
    for pii_tag one of PII.Sensitive / PII.NonSensitive / PII.None."""
    _validate_key(item_id)
    item = _find(item_id)
    edited = req.value.strip()
    if not edited:
        raise errors.ApiError(
            errors.ErrorCode.INVALID_REQUEST,
            "edited value must be non-empty.",
        )
    if item["kind"] == "description":
        _apply_description(item, edited)
    else:
        _apply_pii_tag(item, edited)
    action_id = _record(item, status="accepted_edited", after_val=edited, reason=None)
    logger.info(f"review accept-edited {item_id} (action #{action_id})")
    return ReviewAcceptResponse(action_id=action_id, status="accepted_edited", after_val=edited)


@router.post("/{item_id}/reject", response_model=ReviewAcceptResponse)
def reject(item_id: str) -> ReviewAcceptResponse:
    """Dismiss without applying. Persistent — won't resurface on subsequent
    /review calls unless review_actions is cleared (no UX for that yet)."""
    _validate_key(item_id)
    item = _find(item_id)
    action_id = _record(item, status="rejected", after_val="", reason=None)
    logger.info(f"review rejected {item_id} (action #{action_id})")
    return ReviewAcceptResponse(action_id=action_id, status="rejected", after_val="")
