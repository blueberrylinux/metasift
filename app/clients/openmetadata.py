"""Thin wrapper around the openmetadata-ingestion SDK + REST API."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
from loguru import logger

from app.config import settings


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

    token = settings.require_om_token()
    conn = OpenMetadataConnection(
        hostPort=settings.om_api,
        authProvider=AuthProvider.openmetadata,
        securityConfig=OpenMetadataJWTClientConfig(jwtToken=token),
    )
    return OpenMetadata(conn)


@lru_cache(maxsize=1)
def get_http() -> httpx.Client:
    """Plain authenticated HTTP client for endpoints the SDK doesn't expose well."""
    token = settings.require_om_token()
    return httpx.Client(
        base_url=settings.om_api,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def health_check() -> bool:
    """Quick ping — used on app startup."""
    try:
        r = httpx.get(f"{settings.om_host}/api/v1/system/version", timeout=5.0)
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
