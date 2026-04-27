"""FastAPI app factory.

Phase 0 shipped the skeleton (app + /health + SQLite migrations).
Phase 1 adds the analysis router (composite score + coverage + refresh).

Ports and lifespan are deliberately minimal. Nothing in this file imports or
rewrites app.main (Streamlit) or app.config — the two run side-by-side.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api import store
from app.api.config import api_settings
from app.api.routers import (
    analysis,
    chat,
    dq,
    health,
    llm,
    om,
    report,
    review,
    scans,
    viz,
)

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
    # Push any UI-saved OM connection overrides into the OM client before the
    # first request can hit /analysis/* / /chat/* / etc. — otherwise they'd
    # build httpx clients keyed off the stale .env token.
    om.load_overrides_into_clients()
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


# ── BYO-key middleware ────────────────────────────────────────────────────
#
# Pull `X-OpenRouter-Key` off every incoming request and bind it to the
# `app.clients.llm.request_api_key` ContextVar for the duration of the
# request task. Endpoints that build an LLM client (chat, scans) read the
# var via `get_llm()` and pick up the visitor's key automatically.
#
# Always-on: outside sandbox mode, callers normally don't send the header
# and the var stays None — `_build()` falls through to `.env` defaults
# unchanged. Sending the header in non-sandbox is also fine; it just
# overrides the .env key for that one request.
@app.middleware("http")
async def bind_request_api_key(request: Request, call_next):
    from app.clients.llm import request_api_key

    key = request.headers.get("x-openrouter-key")
    token = request_api_key.set(key) if key else None
    try:
        return await call_next(request)
    finally:
        if token is not None:
            request_api_key.reset(token)


# ── Session cookie middleware ─────────────────────────────────────────────
#
# Tag every visitor with a stable UUID4 cookie so /chat/conversations can
# filter by it under SANDBOX_MODE=1. Gated on sandbox_mode: outside
# sandbox, the middleware is a pass-through — no cookie is set, no
# request.state.session_id is assigned, no DB column gets populated.
# Local-install / self-hosted users see zero footprint.
#
# Cookie attrs (sandbox only):
#   * 30-day Max-Age — long enough for a returning visitor to find their
#     own past chats; nightly reset of the SQLite store wipes the rows
#     anyway, so longer doesn't help.
#   * SameSite=Lax — the React app shares an origin with the API in prod
#     (Caddy fronts both on the same hostname), so Lax is sufficient.
#   * HttpOnly=False — frontend doesn't need to read it, but keeping the
#     option open lets us debug from the browser console without changing
#     the cookie config later.
SESSION_COOKIE = "metasift_session_id"
_SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


@app.middleware("http")
async def bind_session_cookie(request: Request, call_next):
    if not api_settings.sandbox_mode:
        # Non-sandbox: no cookie, no session_id on request.state. The chat
        # routes guard reads with `getattr(request.state, "session_id", None)`
        # and `_session_filter` short-circuits on `not sandbox_mode` — so
        # absence here is a deliberate no-op, not a bug.
        return await call_next(request)

    existing = request.cookies.get(SESSION_COOKIE)
    session_id = existing or str(uuid.uuid4())
    request.state.session_id = session_id
    response = await call_next(request)
    if existing is None:
        response.set_cookie(
            SESSION_COOKIE,
            session_id,
            max_age=_SESSION_COOKIE_MAX_AGE,
            samesite="lax",
            httponly=False,
            secure=False,  # Caddy terminates TLS in prod; flip to True if API
            # is ever exposed directly. Local dev (HTTP) needs False.
        )
    return response


app.include_router(health.router, prefix=PREFIX)
app.include_router(analysis.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(llm.router, prefix=PREFIX)
app.include_router(review.router, prefix=PREFIX)
app.include_router(scans.router, prefix=PREFIX)
app.include_router(viz.router, prefix=PREFIX)
app.include_router(dq.router, prefix=PREFIX)
app.include_router(report.router, prefix=PREFIX)
app.include_router(om.router, prefix=PREFIX)

# Mount the built React bundle in prod (SERVE_STATIC=1 ./web/dist exists).
# Dev: Vite serves :5173 and proxies /api through to :8000 (see web/vite.config.ts).
if api_settings.serve_static:
    from pathlib import Path

    from starlette.exceptions import HTTPException as StarletteHTTPException

    class SPAStaticFiles(StaticFiles):
        """StaticFiles + client-side-route fallback. React Router uses
        /chat, /scans, /review, etc. — none of which exist as files in
        web/dist/. Without this fallback, direct navigation or browser
        refresh on those paths returns 404 (server-side route doesn't
        exist) instead of serving the SPA shell so the client router
        can take over.

        The fallback only fires for paths that AREN'T API routes or
        FastAPI's introspection endpoints — otherwise a malformed API
        call would silently get an HTML 200 with the SPA shell instead
        of a JSON 4xx. The path arg here has the leading slash stripped
        by the StaticFiles framing, so the comparisons are bare-prefix.
        """

        async def get_response(self, path, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as e:
                if e.status_code == 404 and not (
                    path.startswith("api/")
                    or path.startswith("docs")
                    or path.startswith("openapi")
                    or path.startswith("redoc")
                ):
                    return await super().get_response("index.html", scope)
                raise

    dist_path = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
    if dist_path.exists():
        app.mount("/", SPAStaticFiles(directory=str(dist_path), html=True), name="web")
        logger.info(f"Serving static bundle from {dist_path}")
    else:
        logger.warning(
            f"SERVE_STATIC=1 but {dist_path} does not exist. Run `make build-web` first."
        )
