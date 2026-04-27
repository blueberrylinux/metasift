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
import contextlib
import contextvars
import json
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from app.api import errors, store
from app.api.deps import DuckOk, OmOk, WritesEnabled
from app.api.schemas import (
    ActiveScanResponse,
    BulkDocRequest,
    ScanRun,
    ScanStatusResponse,
)
from app.clients import duck
from app.engines import cleaning, stewardship

router = APIRouter(prefix="/scans", tags=["scans"])


# Dedicated thread pool for engine scans. Previously scan workers grabbed
# slots from asyncio's default executor — the same pool FastAPI uses for
# `def` endpoints like `/health`, `/review`, `/analysis/*`. A slow LLM call
# inside a scan could drain that pool and wedge every sync route. Sizing to
# match the number of distinct scan kinds (6) means one-per-kind plus a
# little headroom, with short-lived routes unaffected.
_SCAN_EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="scan-")

# Hard upper bound for a single scan's SSE stream. Even with per-LLM-call
# timeouts a chatty scan that makes 300 calls could still run long — this
# caps the caller's wait at something finite. When the watchdog fires, the
# client sees an `error` frame and the stream closes; the engine thread
# keeps running in the dedicated pool (Python can't force-kill a thread)
# but it can't impact the rest of the app because its pool is isolated.
_SCAN_WATCHDOG_S = 600.0  # 10 minutes


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
    ctx: contextvars.Context | None = None,
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
    # Bounded queue so a fast-emitting engine (or a stuck consumer post-
    # disconnect) can't grow an unbounded backlog of progress frames in memory.
    # 256 is generous — even a 1000-step scan only buffers a fraction.
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=256)
    # Set to True when the SSE generator's caller (FastAPI's response runner)
    # cancels us — typically because the client disconnected. The worker
    # thread checks this before emitting; once tripped, no more frames flow
    # into the queue, capping memory at whatever was already buffered.
    cancelled = False

    def _safe_put(ev: dict[str, Any] | None) -> None:
        # Runs ON the event loop via call_soon_threadsafe. Wrap put_nowait
        # so a full bounded queue (slow consumer, brief network hiccup)
        # drops the frame instead of bubbling QueueFull into the loop's
        # default exception handler. Progress frames are replaceable; the
        # final `done`/`error`/`None` frame is what matters for clean
        # stream termination, and that one fires after consumer draining.
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(ev)

    def emit(ev: dict[str, Any] | None) -> None:
        if cancelled:
            return
        # RuntimeError fires when the loop is closed (process shutting down)
        # — nothing to do at that point.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(_safe_put, ev)

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
        except Exception:
            # Engine errors can leak SQL fragments / provider details / file
            # paths. Log full trace server-side; surface a generic message to
            # client + scan_runs.error. Scan kind is enough for the UI to tell
            # the user which scan failed.
            logger.exception(f"scan {kind} failed")
            generic = f"Scan {kind!r} failed. Check the server logs for details."
            store.finish_scan(run_id, status="failed", error=generic)
            emit({"type": "error", "run_id": run_id, "message": generic})
        finally:
            emit(None)

    # Carry contextvars (notably app.clients.llm.request_api_key for sandbox
    # BYOK) into the worker thread so engine LLM calls pick up the visitor's
    # OpenRouter key. The caller MUST capture the snapshot synchronously in
    # the route handler — by the time this generator's body starts running
    # (first anext() from the SSE consumer) the BYO-key middleware has
    # already reset the request's ContextVar in its finally block. See
    # chat.py::stream_agent_events for the same constraint.
    if ctx is None:
        raise RuntimeError(
            "_stream_engine_scan requires `ctx=contextvars.copy_context()` "
            "captured by the calling route handler — see deep_scan / refresh / etc."
        )
    loop.run_in_executor(_SCAN_EXECUTOR, ctx.run, runner)
    deadline = loop.time() + _SCAN_WATCHDOG_S
    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                logger.warning(f"scan {kind} (run_id={run_id}) hit watchdog timeout")
                # Mark the row failed so the UI's 'running' state clears. The
                # worker thread may still be looping — it'll eventually finish
                # and its late finish_scan call is fine (harmless UPDATE).
                try:
                    store.finish_scan(
                        run_id,
                        status="failed",
                        error=f"Watchdog timeout after {int(_SCAN_WATCHDOG_S)}s",
                    )
                except Exception:
                    logger.exception("watchdog finish_scan failed")
                yield {
                    "type": "error",
                    "run_id": run_id,
                    "message": f"Scan exceeded {int(_SCAN_WATCHDOG_S)}s watchdog — check server logs.",
                }
                return
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=remaining)
            except TimeoutError:
                continue  # next loop iteration trips the watchdog branch above
            if ev is None:
                return
            yield ev
    finally:
        # Client disconnect / response complete fires GeneratorExit / cancel.
        # Flip the flag so the worker thread stops queueing — the thread itself
        # cannot be cancelled (engines have no abort API), but its frames are
        # no longer accumulating in memory.
        cancelled = True


def _sse_response(events_coro: AsyncIterator[dict[str, Any]]) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        async for ev in events_coro:
            yield {"event": ev["type"], "data": json.dumps(ev)}

    return EventSourceResponse(events())


# ── Routes ────────────────────────────────────────────────────────────────


def _capture_ctx() -> contextvars.Context:
    """Snapshot the caller's contextvars BEFORE the SSE response object is
    returned. Must be called synchronously in the route handler — once the
    BYO-key middleware's finally has fired, the snapshot will be empty.
    See `_stream_engine_scan` for the consumer."""
    return contextvars.copy_context()


@router.post("/deep-scan")
async def deep_scan(om_ok: OmOk, duck_ok: DuckOk) -> EventSourceResponse:
    """Stale-description + quality-scoring pass. LLM-heavy — typically 30-60s
    on the demo catalog. Populates cleaning_results."""
    if not om_ok:
        raise errors.om_unreachable()
    if not duck_ok:
        raise errors.no_metadata_loaded()
    run_id = _claim_run_slot("deep_scan")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan("deep_scan", run_id, cleaning.run_deep_scan, ctx=ctx)
    )


@router.post("/pii-scan")
async def pii_scan(om_ok: OmOk, duck_ok: DuckOk) -> EventSourceResponse:
    """Heuristic PII classification per column. Fast — no LLM calls.
    Populates pii_results. Single `done` frame with the summary."""
    if not om_ok:
        raise errors.om_unreachable()
    if not duck_ok:
        raise errors.no_metadata_loaded()
    run_id = _claim_run_slot("pii_scan")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan(
            "pii_scan", run_id, cleaning.run_pii_scan, accepts_progress=False, ctx=ctx
        )
    )


@router.post("/dq-explain")
async def dq_explain(om_ok: OmOk, duck_ok: DuckOk) -> EventSourceResponse:
    """LLM-written explanations for each failing DQ test. One LLM call per
    failure. Populates dq_explanations."""
    if not om_ok:
        raise errors.om_unreachable()
    if not duck_ok:
        raise errors.no_metadata_loaded()
    run_id = _claim_run_slot("dq_explain")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan("dq_explain", run_id, cleaning.run_dq_explanations, ctx=ctx)
    )


@router.post("/dq-recommend")
async def dq_recommend(om_ok: OmOk, duck_ok: DuckOk) -> EventSourceResponse:
    """Per-table recommendations for DQ tests that should exist. One LLM call
    per table. Populates dq_recommendations."""
    if not om_ok:
        raise errors.om_unreachable()
    if not duck_ok:
        raise errors.no_metadata_loaded()
    run_id = _claim_run_slot("dq_recommend")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan("dq_recommend", run_id, stewardship.run_dq_recommendations, ctx=ctx)
    )


@router.post("/bulk-doc")
async def bulk_doc(req: BulkDocRequest, om_ok: OmOk, duck_ok: DuckOk) -> EventSourceResponse:
    """Auto-document every undocumented table in a schema. Typically agent-
    triggered (`auto-document the sales schema`), exposed here for
    programmatic / UI-driven use. Writes drafts to doc_suggestions."""
    if not om_ok:
        raise errors.om_unreachable()
    if not duck_ok:
        raise errors.no_metadata_loaded()
    run_id = _claim_run_slot("bulk_doc")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan(
            "bulk_doc",
            run_id,
            stewardship.bulk_document_schema,
            schema_name=req.schema_name,
            max_tables=req.max_tables,
            ctx=ctx,
        )
    )


@router.post("/refresh")
async def refresh(om_ok: OmOk, _: WritesEnabled) -> EventSourceResponse:
    """Pull fresh metadata into DuckDB. Short (~1s on the demo catalog). No
    progress_cb in the engine, so the stream is just `done` or `error` — the
    SSE wrapper still lets the UI share the same scan-state plumbing as the
    heavier scans."""
    if not om_ok:
        raise errors.om_unreachable()
    run_id = _claim_run_slot("refresh")
    ctx = _capture_ctx()
    return _sse_response(
        _stream_engine_scan(
            "refresh", run_id, duck.refresh_all, accepts_progress=False, ctx=ctx
        )
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


@router.get("/active", response_model=ActiveScanResponse)
def active() -> ActiveScanResponse:
    """The currently-in-flight scan run, or None. Polled by the React app
    (5s cadence) to disable the per-kind scan buttons while another scan
    is running. Cheap — single indexed SQLite read, no DuckDB / OM calls."""
    row = store.active_scan()
    return ActiveScanResponse(active=ScanRun.model_validate(row) if row else None)


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
