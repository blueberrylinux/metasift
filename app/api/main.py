"""FastAPI app factory.

Phase 0 shipped the skeleton (app + /health + SQLite migrations).
Phase 1 adds the analysis router (composite score + coverage + refresh).

Ports and lifespan are deliberately minimal. Nothing in this file imports or
rewrites app.main (Streamlit) or app.config — the two run side-by-side.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api import store
from app.api.config import api_settings
from app.api.routers import analysis, chat, dq, health, llm, report, review, scans, viz

PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown hooks.

    On startup: apply pending SQLite migrations. Everything else is lazy —
    we don't pre-warm the agent or hydrate DuckDB here because those are
    expensive and user-initiated.

    On shutdown: nothing to do; SQLite and DuckDB are self-managed.
    """
    store.apply_migrations()
    reaped = store.reap_zombie_scans()
    if reaped:
        logger.warning(
            f"Reaped {reaped} zombie scan_runs row(s) left 'running' from a previous process"
        )
    logger.info(f"MetaSift API ready · sqlite={api_settings.sqlite_path}")
    yield
    logger.info("MetaSift API shutting down")
    # Drain the dedicated executors so stuck scan/chat workers can't hold
    # onto file handles after uvicorn stops. `cancel_futures=True` discards
    # anything still queued; in-flight work is allowed to return.
    from app.api.routers.chat import _CHAT_EXECUTOR
    from app.api.routers.scans import _SCAN_EXECUTOR

    _CHAT_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    _SCAN_EXECUTOR.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="MetaSift API",
    version="0.5.0-port.1",
    lifespan=lifespan,
    docs_url=f"{PREFIX}/docs",
    redoc_url=f"{PREFIX}/redoc",
    openapi_url=f"{PREFIX}/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=api_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=PREFIX)
app.include_router(analysis.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(llm.router, prefix=PREFIX)
app.include_router(review.router, prefix=PREFIX)
app.include_router(scans.router, prefix=PREFIX)
app.include_router(viz.router, prefix=PREFIX)
app.include_router(dq.router, prefix=PREFIX)
app.include_router(report.router, prefix=PREFIX)

# Mount the built React bundle in prod (SERVE_STATIC=1 ./web/dist exists).
# Dev: Vite serves :5173 and proxies /api through to :8000 (see web/vite.config.ts).
if api_settings.serve_static:
    from pathlib import Path

    dist_path = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="web")
        logger.info(f"Serving static bundle from {dist_path}")
    else:
        logger.warning(
            f"SERVE_STATIC=1 but {dist_path} does not exist. Run `make build-web` first."
        )
