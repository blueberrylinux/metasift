"""Thin wrapper around the openmetadata-ingestion SDK + REST API."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
from loguru import logger

from app.config import settings

# Runtime overrides — populated by `app.api.routers.om` when the user saves
# a new host / JWT through the Settings UI, and at startup from SQLite via
# `app.api.store.all_runtime_config()`. These take priority over `.env` so
# the user can rotate the OM JWT without editing `.env` + restarting the
# API. None means "fall through to settings".
_override_host: str | None = None
_override_jwt: str | None = None


def set_runtime_override(*, host: str | None, jwt: str | None) -> None:
    """Replace the runtime override and drop every cached client so the next
    call rebuilds with the new credentials."""
    global _override_host, _override_jwt
    _override_host = host or None
    _override_jwt = jwt or None
    reload_clients()


def reload_clients() -> None:
    """Drop every cached SDK / httpx client. Next call rebuilds with whatever
    `_effective_*` resolves to (override → settings)."""
    get_om_client.cache_clear()
    get_http.cache_clear()
    _health_client.cache_clear()


def _effective_host() -> str:
    return _override_host or settings.om_host


def _effective_api() -> str:
    if _override_host:
        return f"{_override_host.rstrip('/')}/api"
    return settings.om_api


def _effective_token() -> str:
    if _override_jwt:
        return _override_jwt
    return settings.require_om_token()


@lru_cache(maxsize=1)
def get_om_client():
    """Return a configured OpenMetadata SDK client.

    The SDK is heavy — import lazily so tests that don't need it start fast.
    """
    from metadata.generated.schema.entity.services.connections.metadata.openMetadataConnection import (
        AuthProvider,
        OpenMetadataConnection,
    )
    from metadata.generated.schema.security.client.openMetadataJWTClientConfig import (
        OpenMetadataJWTClientConfig,
    )
    from metadata.ingestion.ometa.ometa_api import OpenMetadata

    token = _effective_token()
    conn = OpenMetadataConnection(
        hostPort=_effective_api(),
        authProvider=AuthProvider.openmetadata,
        securityConfig=OpenMetadataJWTClientConfig(jwtToken=token),
    )
    return OpenMetadata(conn)


@lru_cache(maxsize=1)
def get_http() -> httpx.Client:
    """Plain authenticated HTTP client for endpoints the SDK doesn't expose well."""
    token = _effective_token()
    return httpx.Client(
        base_url=_effective_api(),
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


@lru_cache(maxsize=1)
def _health_client() -> httpx.Client:
    """Dedicated short-timeout client for the /health probe. Separate from
    `get_http()` so an auth-token problem (which requires a valid token)
    doesn't break unauthenticated liveness checks, and so health calls
    reuse a persistent connection instead of TLS-handshaking every time."""
    return httpx.Client(base_url=_effective_host(), timeout=3.0)


def health_check() -> bool:
    """Quick ping — used by /health and on startup. Reuses a persistent
    httpx.Client so repeated polls don't re-establish TCP+TLS each call,
    and caps timeout at 3s so a slow OM never blocks the probe thread
    for long."""
    try:
        r = _health_client().get("/api/v1/system/version")
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"OpenMetadata not reachable: {e}")
        return False


def patch_table_description(fqn: str, description: str) -> dict[str, Any]:
    """JSON Merge Patch a table description via REST."""
    client = get_http()
    r = client.patch(
        f"/v1/tables/name/{fqn}",
        headers={"Content-Type": "application/json-patch+json"},
        json=[{"op": "add", "path": "/description", "value": description}],
    )
    r.raise_for_status()
    return r.json()


def patch_column_tag(table_fqn: str, column_name: str, tag_fqn: str) -> dict[str, Any]:
    """Add a PII (or other classification) tag to a specific column.

    Fetches the table's current columns to locate the column's array index,
    then applies a JSON Patch that REPLACES the column's tags array with
    existing-tags + the new tag. Non-destructive to other tags already set.

    Raises ValueError if the column isn't found.
    Raises httpx.HTTPStatusError if the PATCH fails.
    """
    client = get_http()

    # Step 1 — fetch current table with columns to find the column index
    r = client.get(f"/v1/tables/name/{table_fqn}", params={"fields": "columns,tags"})
    r.raise_for_status()
    table = r.json()

    columns = table.get("columns") or []
    col_idx = next(
        (i for i, c in enumerate(columns) if c.get("name") == column_name),
        None,
    )
    if col_idx is None:
        raise ValueError(
            f"Column '{column_name}' not found in table '{table_fqn}'. "
            f"Available: {[c.get('name') for c in columns]}"
        )

    # Step 2 — compose new tag list, skip if already present
    existing = columns[col_idx].get("tags") or []
    if any(t.get("tagFQN") == tag_fqn for t in existing):
        return {"status": "already_tagged", "tag": tag_fqn, "column": column_name}

    new_tags = existing + [
        {
            "tagFQN": tag_fqn,
            "labelType": "Manual",
            "state": "Confirmed",
            "source": "Classification",
        }
    ]

    # Step 3 — PATCH the column's tags array at its index
    patch = [{"op": "replace", "path": f"/columns/{col_idx}/tags", "value": new_tags}]
    r = client.patch(
        f"/v1/tables/name/{table_fqn}",
        headers={"Content-Type": "application/json-patch+json"},
        json=patch,
    )
    r.raise_for_status()
    return {"status": "applied", "tag": tag_fqn, "column": column_name}
