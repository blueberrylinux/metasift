"""OpenMetadata connection config — Settings UI surface for the JWT.

The `.env`-only flow burned us every time `make stack-down` rotated the
ingestion-bot: stale token = blanket 401s, fix = manual edit + restart.
This router lets the user paste a fresh token in the Settings page and
hot-swap the OM client without bouncing the API.

Resolution at read time (in `app.clients.openmetadata`):
    1. SQLite override set via POST /om/config
    2. `.env` / `app.config.settings`
    3. unset

POST validates the new credentials against OM's `/v1/services/databaseServices?limit=1`
before persisting — `/v1/system/version` is unauthenticated on OM 1.9.4
and would silently accept any junk token. A failed validation returns
the OM error verbatim and writes nothing — saving a known-broken token
would leave the user worse off than before (the env token would be
ignored too).
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter
from loguru import logger

from app.api import errors, store
from app.api.deps import WritesEnabled, invalidate_probe_cache
from app.api.schemas import OMConfigRequest, OMConfigResponse
from app.clients import openmetadata as om_client
from app.config import settings

router = APIRouter(prefix="/om", tags=["om"])


# Storage keys — kept in one place so the router and bootstrap loader can't
# drift apart on a typo. Both must match between writes and reads.
_KEY_HOST = "om_host"
_KEY_JWT = "om_jwt"


def load_overrides_into_clients() -> None:
    """Read SQLite overrides at startup and push them into the OM client.

    Called from the lifespan hook in `app.api.main` after `apply_migrations`,
    so a token saved in a previous session is in effect before the first
    request lands. No-op when nothing's been saved."""
    host = store.get_runtime_config(_KEY_HOST)
    jwt = store.get_runtime_config(_KEY_JWT)
    if host or jwt:
        om_client.set_runtime_override(host=host, jwt=jwt)
        logger.info(
            f"OM runtime override loaded · host={'set' if host else 'env'} · jwt={'set' if jwt else 'env'}"
        )


def _validate(host: str, jwt: str) -> None:
    """Hit OM with the candidate credentials. Raises an `ApiError` shaped
    for the API layer if anything fails — the caller turns that into a 4xx
    response without mutating state.

    Probes `/v1/services/databaseServices?limit=1` rather than `/system/version`
    because the version endpoint is unauthenticated (returns 200 even for a
    junk bearer token), which would silently accept invalid JWTs and lock
    the user out of every authenticated route. databaseServices is permitted
    for the ingestion-bot and 401s on bad tokens — exactly what we need.
    """
    api_base = f"{host.rstrip('/')}/api"
    try:
        with httpx.Client(base_url=api_base, timeout=5.0) as c:
            r = c.get(
                "/v1/services/databaseServices",
                params={"limit": 1, "fields": "name"},
                headers={"Authorization": f"Bearer {jwt}"},
            )
    except httpx.RequestError as e:
        raise errors.ApiError(
            errors.ErrorCode.OM_UNREACHABLE,
            f"Couldn't reach OpenMetadata at {host} ({type(e).__name__}). "
            "Is the host correct and the stack running?",
            status_code=400,
        ) from e
    if r.status_code == 401:
        raise errors.ApiError(
            errors.ErrorCode.OM_UNREACHABLE,
            "OpenMetadata rejected the token (401). "
            "Generate a new one via Settings → Bots → ingestion-bot.",
            status_code=400,
        )
    if r.status_code != 200:
        raise errors.ApiError(
            errors.ErrorCode.OM_UNREACHABLE,
            f"OpenMetadata returned HTTP {r.status_code} — check the host and token.",
            status_code=400,
        )


def _current_response() -> OMConfigResponse:
    """Snapshot the active config without exposing the token itself."""
    override_jwt = store.get_runtime_config(_KEY_JWT)
    override_host = store.get_runtime_config(_KEY_HOST)
    if override_jwt:
        source = "sqlite"
    elif settings.om_jwt:
        source = "env"
    else:
        source = "unset"
    return OMConfigResponse(
        host=override_host or settings.om_host,
        has_token=bool(override_jwt or settings.om_jwt),
        source=source,
    )


@router.get("/config", response_model=OMConfigResponse)
def get_om_config() -> OMConfigResponse:
    """Active host + whether a token is configured. Never returns the token
    itself — the UI only needs `has_token` to decide between "paste new" and
    "replace existing"."""
    return _current_response()


@router.post("/config", response_model=OMConfigResponse)
def set_om_config(req: OMConfigRequest, _: WritesEnabled) -> OMConfigResponse:
    """Validate credentials against OM, then persist + hot-swap clients.
    Validation runs FIRST: a failed token doesn't get written, so a typo
    can't lock the user out of the UI by overriding their working `.env`."""
    host = req.host.strip()
    jwt = req.jwt.strip()
    _validate(host, jwt)
    store.set_runtime_config(_KEY_HOST, host)
    store.set_runtime_config(_KEY_JWT, jwt)
    om_client.set_runtime_override(host=host, jwt=jwt)
    invalidate_probe_cache("om")
    logger.info(f"OM config updated via UI · host={host} · jwt rotated")
    return _current_response()


@router.delete("/config", response_model=OMConfigResponse)
def reset_om_config(_: WritesEnabled) -> OMConfigResponse:
    """Drop the SQLite override and fall back to `.env`. Useful when the
    UI-saved creds are wrong and you want to re-bootstrap from `.env`
    without touching the database file."""
    store.delete_runtime_config(_KEY_HOST)
    store.delete_runtime_config(_KEY_JWT)
    om_client.set_runtime_override(host=None, jwt=None)
    invalidate_probe_cache("om")
    logger.info("OM config reset to .env")
    return _current_response()
