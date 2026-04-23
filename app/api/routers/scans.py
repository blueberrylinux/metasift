"""Scan endpoints — Phase 3 slice 2.

Generalizes Phase 2's LangGraph→SSE adapter to the sync engine scan functions
(`cleaning.run_deep_scan`, `cleaning.run_pii_scan`, `cleaning.run_dq_explanations`,
`stewardship.run_dq_recommendations`, `stewardship.bulk_document_schema`).

Three SSE frame types per stream:
  * {type: "progress", step, total, label}  — from the engine's progress_cb
  * {type: "done", run_id, counts}           — summary dict from the run fn
  * {type: "error", run_id, message}         — uncaught exception

run_pii_scan has no progress_cb, so its stream is just `done` or `error`.
Each run creates a row in `scan_runs` via `store.start_scan` / `finish_scan`
so the sidebar "last scan N min ago" badges can read from SQLite without
holding an SSE connection.

Concurrency: one scan per kind at a time. A 409 fires if the same kind is
already running — different kinds run in parallel unimpeded. Engines are
append-only against DuckDB, so cross-kind races haven't shown up in the
Streamlit reference; we preserve the same policy.

Reference for the pattern: PORT_ERRATA.md §"Engines (scan) — sync vs async".
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.api import errors, store
from app.api.deps import OmOk
from app.api.schemas import (
    BulkDocRequest,
    ScanRun,
    ScanStatusResponse,
)
from app.clients import duck
from app.engines import cleaning, stewardship

router = APIRouter(prefix="/scans", tags=["scans"])


# ── Adapter ───────────────────────────────────────────────────────────────


def _claim_run_slot(kind: str) -> int:
    """Atomically start a run or raise 409. Single SQL transaction via
    `store.try_start_scan` so two concurrent requests on the same kind can't
    both pass — unlike the check-then-insert pair that preceded this."""
    run_id = store.try_start_scan(kind)
    if run_id is None:
        raise errors.ApiError(
            errors.ErrorCode.SCAN_ALREADY_RUNNING,
            f"A {kind} scan is already running. Wait for it to finish.",
            status_code=409,
        )
    return run_id


async def _stream_engine_scan(
    kind: str,
    run_id: int,
    run_fn: Callable[..., dict[str, Any]],
    *,
    accepts_progress: bool = True,
    **kwargs: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Run a sync engine function in a worker thread and yield `progress`,
    `done`, and `error` frames. Follows the pattern from
    `app.api.routers.chat.stream_agent_events` — emit through an
    `asyncio.Queue` via `call_soon_threadsafe`, which is safe from the
    thread but cheap on the event loop.

    Caller must have already claimed the run slot via `_claim_run_slot` —
    keeps the slot-claim and the HTTP route tied together so a 409 can
    surface before the SSE connection opens.

    Known limitation: a client disconnect mid-scan leaves the worker thread
    running to completion. The scan_runs row still closes correctly via the
    `finally: emit(None)` path below, but the engine functions have no abort
    API — cancellation would require engine-level refactoring out of slice-2
    scope."""

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def emit(ev: dict[str, Any] | None) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    def progress_cb(step: int, total: int, label: str) -> None:
        emit(
            {
                "type": "progress",
                "run_id": run_id,
                "step": int(step),
                "total": int(total),
                "label": str(label),
            }
        )

    def runner() -> None:
        try:
            if accepts_progress:
                summary = run_fn(progress_cb=progress_cb, **kwargs)
            else:
                summary = run_fn(**kwargs)
            # Serialize whatever the engine returned — engines emit int / float /
            # str keys, so json.dumps round-trips cleanly. On the off-chance an
            # engine grows a non-serializable value, str() it so the frame stays
            # well-formed rather than blowing up mid-stream.
            try:
                json.dumps(summary)
                counts = summary
            except TypeError:
                counts = {k: str(v) for k, v in summary.items()}
            store.finish_scan(run_id, status="completed", counts=counts)
            emit({"type": "done", "run_id": run_id, "counts": counts})
        except Exception as e:
            logger.exception(f"scan {kind} failed")
            store.finish_scan(run_id, status="failed", error=str(e))
            emit({"type": "error", "run_id": run_id, "message": str(e)})
        finally:
            emit(None)

    loop.run_in_executor(None, runner)
    while True:
        ev = await queue.get()
        if ev is None:
            return
        yield ev


def _sse_response(events_coro: AsyncIterator[dict[str, Any]]) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        async for ev in events_coro:
            yield {"event": ev["type"], "data": json.dumps(ev)}

    return EventSourceResponse(events())


# ── Routes ────────────────────────────────────────────────────────────────


@router.post("/deep-scan")
async def deep_scan(om_ok: OmOk) -> EventSourceResponse:
    """Stale-description + quality-scoring pass. LLM-heavy — typically 30-60s
    on the demo catalog. Populates cleaning_results."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("deep_scan")
    return _sse_response(_stream_engine_scan("deep_scan", run_id, cleaning.run_deep_scan))


@router.post("/pii-scan")
async def pii_scan(om_ok: OmOk) -> EventSourceResponse:
    """Heuristic PII classification per column. Fast — no LLM calls.
    Populates pii_results. Single `done` frame with the summary."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("pii_scan")
    return _sse_response(
        _stream_engine_scan("pii_scan", run_id, cleaning.run_pii_scan, accepts_progress=False)
    )


@router.post("/dq-explain")
async def dq_explain(om_ok: OmOk) -> EventSourceResponse:
    """LLM-written explanations for each failing DQ test. One LLM call per
    failure. Populates dq_explanations."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("dq_explain")
    return _sse_response(
        _stream_engine_scan("dq_explain", run_id, cleaning.run_dq_explanations)
    )


@router.post("/dq-recommend")
async def dq_recommend(om_ok: OmOk) -> EventSourceResponse:
    """Per-table recommendations for DQ tests that should exist. One LLM call
    per table. Populates dq_recommendations."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("dq_recommend")
    return _sse_response(
        _stream_engine_scan("dq_recommend", run_id, stewardship.run_dq_recommendations)
    )


@router.post("/bulk-doc")
async def bulk_doc(req: BulkDocRequest, om_ok: OmOk) -> EventSourceResponse:
    """Auto-document every undocumented table in a schema. Typically agent-
    triggered (`auto-document the sales schema`), exposed here for
    programmatic / UI-driven use. Writes drafts to doc_suggestions."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("bulk_doc")
    return _sse_response(
        _stream_engine_scan(
            "bulk_doc",
            run_id,
            stewardship.bulk_document_schema,
            schema_name=req.schema_name,
            max_tables=req.max_tables,
        )
    )


@router.post("/refresh")
async def refresh(om_ok: OmOk) -> EventSourceResponse:
    """Pull fresh metadata into DuckDB. Short (~1s on the demo catalog). No
    progress_cb in the engine, so the stream is just `done` or `error` — the
    SSE wrapper still lets the UI share the same scan-state plumbing as the
    heavier scans."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("refresh")
    return _sse_response(
        _stream_engine_scan("refresh", run_id, duck.refresh_all, accepts_progress=False)
    )


# ── Status ────────────────────────────────────────────────────────────────


_TRACKED_KINDS = (
    "refresh",
    "deep_scan",
    "pii_scan",
    "dq_explain",
    "dq_recommend",
    "bulk_doc",
)


@router.get("/status", response_model=ScanStatusResponse)
def status() -> ScanStatusResponse:
    """Most recent run per scan kind, or null if never run. Drives the
    sidebar's 'last scan N min ago' badges and disables the button when a
    scan of that kind is still in-flight."""
    raw = store.last_scans(kinds=_TRACKED_KINDS)
    out: dict[str, ScanRun | None] = {}
    for kind, row in raw.items():
        if row is None:
            out[kind] = None
        else:
            out[kind] = ScanRun.model_validate(row)
    return ScanStatusResponse(kinds=out)
