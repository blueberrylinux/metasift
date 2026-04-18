"""DuckDB store — pulls metadata from OpenMetadata into in-process SQL tables."""

from __future__ import annotations

from functools import lru_cache

import duckdb
import pandas as pd
from loguru import logger

from app.clients.openmetadata import get_http


@lru_cache(maxsize=1)
def get_conn() -> duckdb.DuckDBPyConnection:
    """Single shared in-memory DuckDB connection for the app session."""
    return duckdb.connect(":memory:")


def refresh_all() -> dict[str, int]:
    """Pull fresh metadata from OpenMetadata and load into DuckDB tables.

    Returns row counts per table.
    """
    http = get_http()
    conn = get_conn()

    counts: dict[str, int] = {}

    # Tables
    tables = _fetch_paginated(http, "/v1/tables", fields="columns,tags,owners,description,profile")
    tables_df = pd.json_normalize(tables, max_level=1)
    conn.execute("CREATE OR REPLACE TABLE om_tables AS SELECT * FROM tables_df")
    counts["om_tables"] = len(tables_df)

    # Columns (exploded from tables)
    col_rows = []
    for t in tables:
        fqn = t.get("fullyQualifiedName")
        for col in t.get("columns", []):
            col_rows.append(
                {
                    "table_fqn": fqn,
                    "name": col.get("name"),
                    "dataType": col.get("dataType"),
                    "description": col.get("description"),
                    "tags": [tag.get("tagFQN") for tag in col.get("tags", [])],
                }
            )
    cols_df = pd.DataFrame(col_rows)
    conn.execute("CREATE OR REPLACE TABLE om_columns AS SELECT * FROM cols_df")
    counts["om_columns"] = len(cols_df)

    logger.info(f"DuckDB refresh complete: {counts}")
    return counts


def _fetch_paginated(http, path: str, fields: str = "", limit: int = 100) -> list[dict]:
    out: list[dict] = []
    after: str | None = None
    while True:
        params = {"limit": limit}
        if fields:
            params["fields"] = fields
        if after:
            params["after"] = after
        r = http.get(path, params=params)
        r.raise_for_status()
        body = r.json()
        out.extend(body.get("data", []))
        after = body.get("paging", {}).get("after")
        if not after:
            break
    return out


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    """Run SQL against the loaded metadata tables.

    Pass `params` when the SQL includes `?` placeholders — use this for any
    value that comes from the agent or user input to avoid injection.
    """
    return get_conn().execute(sql, params or []).df()
