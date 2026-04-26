"""DuckDB store — pulls metadata from OpenMetadata into in-process SQL tables."""

from __future__ import annotations

import json
import re
import threading
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd
from loguru import logger

from app.clients.openmetadata import get_http

# DuckDB connections are not thread-safe for concurrent `execute()` calls.
# On a shared `lru_cache`-held connection, `refresh_all()` in the scan
# executor would hold the internal mutex for the duration of each
# `CREATE TABLE AS SELECT` — seconds on the full catalog payload —
# while concurrent `duck.query()` calls from analysis endpoints and agent
# tools queued behind it. Enough queued threads drained FastAPI's anyio
# pool and wedged the whole server.
#
# `cursor()` is DuckDB's documented thread-safe pattern: cursors share
# the in-memory catalog but have independent execution contexts. Each
# thread gets its own cursor via `threading.local()`.
_tls = threading.local()


@lru_cache(maxsize=1)
def _root_conn() -> duckdb.DuckDBPyConnection:
    """The process-wide root connection. Never used for queries directly —
    only as the parent for per-thread cursors, so the in-memory database
    has a single persistent owner for its lifetime."""
    return duckdb.connect(":memory:")


def get_conn() -> duckdb.DuckDBPyConnection:
    """Return this thread's cursor into the shared in-memory DuckDB.

    Cursors from the same parent connection see the same catalog but can
    execute independently, which is what FastAPI's threaded request
    dispatch needs. The first call in a thread creates the cursor; later
    calls reuse it — similar to how `app.api.store.get_conn` threads SQLite.
    """
    cur = getattr(_tls, "cur", None)
    if cur is None:
        cur = _root_conn().cursor()
        _tls.cur = cur
    return cur


def refresh_all() -> dict[str, int]:
    """Pull fresh metadata from OpenMetadata and load into DuckDB tables.

    Populates three tables: om_tables, om_columns, om_lineage.
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

    # Lineage edges — one GET per table, then flatten + dedupe.
    # Small N (~dozens), so the extra calls are fine on refresh.
    lineage_rows = _fetch_lineage_edges(http, tables)
    lineage_df = pd.DataFrame(lineage_rows, columns=["source_fqn", "target_fqn"])
    conn.execute("CREATE OR REPLACE TABLE om_lineage AS SELECT * FROM lineage_df")
    counts["om_lineage"] = len(lineage_df)

    # Data quality test cases + latest results. Optional — catalog may have none.
    # Falls back to a committed demo fixture so the DQ-explanation feature
    # has real failures to work with when the OM DQ API is empty.
    test_rows = _fetch_test_cases(http)
    if not test_rows:
        test_rows = _load_synthetic_test_cases()
    tests_df = pd.DataFrame(test_rows, columns=_TEST_CASE_COLUMNS)
    conn.execute("CREATE OR REPLACE TABLE om_test_cases AS SELECT * FROM tests_df")
    counts["om_test_cases"] = len(tests_df)

    # Services — what data sources are actually connected to OM.
    # Force VARCHAR dtypes even on empty responses so the join in
    # analysis.service_coverage (om_services.name = om_tables... split_part)
    # doesn't hit an INT/VARCHAR type mismatch when no services come back.
    service_rows = _fetch_services(http)
    _service_cols = ["id", "name", "fqn", "kind", "service_type", "description"]
    services_df = pd.DataFrame(service_rows, columns=_service_cols).astype(
        dict.fromkeys(_service_cols, "string")
    )
    conn.execute("CREATE OR REPLACE TABLE om_services AS SELECT * FROM services_df")
    counts["om_services"] = len(services_df)

    logger.info(f"DuckDB refresh complete: {counts}")
    return counts


def _fetch_lineage_edges(http, tables: list[dict]) -> list[dict]:
    """Walk each table's lineage endpoint and collect downstream edges.

    Each call returns both the entity's UUID and a `nodes` list with UUID+FQN
    for every connected table, which lets us translate `downstreamEdges`
    (UUID→UUID) into (source_fqn, target_fqn) pairs. We dedupe across calls
    since the same edge shows up from both endpoints' perspectives.
    """
    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for t in tables:
        fqn = t.get("fullyQualifiedName")
        if not fqn:
            continue
        try:
            r = http.get(
                f"/v1/lineage/table/name/{fqn}",
                params={"upstreamDepth": 1, "downstreamDepth": 1},
            )
            if r.status_code != 200:
                continue
            body = r.json()
        except Exception as e:
            logger.warning(f"Lineage fetch failed for {fqn}: {e}")
            continue

        uuid_to_fqn: dict[str, str] = {}
        entity = body.get("entity") or {}
        if entity.get("id") and entity.get("fullyQualifiedName"):
            uuid_to_fqn[entity["id"]] = entity["fullyQualifiedName"]
        for node in body.get("nodes") or []:
            if node.get("id") and node.get("fullyQualifiedName"):
                uuid_to_fqn[node["id"]] = node["fullyQualifiedName"]

        for edge in body.get("downstreamEdges") or []:
            src = uuid_to_fqn.get(edge.get("fromEntity"))
            dst = uuid_to_fqn.get(edge.get("toEntity"))
            if src and dst and (src, dst) not in seen:
                seen.add((src, dst))
                rows.append({"source_fqn": src, "target_fqn": dst})
    return rows


_TEST_CASE_COLUMNS = [
    "id",
    "name",
    "fqn",
    "table_fqn",
    "column_name",
    "entity_link",
    "test_definition_name",
    "test_definition_fqn",
    "description",
    "parameter_values",
    "status",
    "result_message",
    "result_timestamp",
    "failed_rows_sample",
    "source",
]

_ENTITY_LINK_RE = re.compile(r"<#E::table::(?P<table>[^:>]+)(?:::columns::(?P<column>[^:>]+))?>")


def _parse_entity_link(link: str) -> tuple[str | None, str | None]:
    """Pull (table_fqn, column_name) out of an OpenMetadata entity link.

    Format is `<#E::table::<fqn>::columns::<name>>` for column-level tests
    and `<#E::table::<fqn>>` for table-level. Returns (None, None) if the
    link doesn't parse — defensive because tests can target other entities.
    """
    if not link:
        return None, None
    m = _ENTITY_LINK_RE.search(link)
    if not m:
        return None, None
    return m.group("table"), m.group("column")


def _fetch_test_cases(http) -> list[dict]:
    """Fetch every test case + its latest result from OpenMetadata.

    Requesting `fields=testDefinition,testCaseResult` inlines the latest
    run result so we don't need a second round-trip per test. Any error
    returns `[]` — DQ is optional and we don't want a misconfigured OM
    to break the whole refresh.
    """
    try:
        raw = _fetch_paginated(
            http,
            "/v1/dataQuality/testCases",
            fields="testDefinition,testCaseResult",
        )
    except Exception as e:
        logger.warning(f"DQ test case fetch failed ({e}); falling back to fixture")
        return []
    rows: list[dict] = []
    for t in raw:
        entity_link = t.get("entityLink") or ""
        table_fqn, column_name = _parse_entity_link(entity_link)
        result = t.get("testCaseResult") or {}
        test_def = t.get("testDefinition") or {}
        rows.append(
            {
                "id": t.get("id"),
                "name": t.get("name"),
                "fqn": t.get("fullyQualifiedName"),
                "table_fqn": table_fqn,
                "column_name": column_name,
                "entity_link": entity_link,
                "test_definition_name": test_def.get("name")
                or (test_def.get("fullyQualifiedName") or "").split(".")[-1],
                "test_definition_fqn": test_def.get("fullyQualifiedName"),
                "description": t.get("description"),
                "parameter_values": json.dumps(t.get("parameterValues") or []),
                "status": result.get("testCaseStatus"),
                "result_message": result.get("result"),
                "result_timestamp": result.get("timestamp"),
                "failed_rows_sample": json.dumps(result.get("sampleData") or []),
                "source": "openmetadata",
            }
        )
    return rows


def _load_synthetic_test_cases() -> list[dict]:
    """Read a committed demo fixture so the DQ feature has data when OM has none.

    The fixture is a JSON list of rows matching `_TEST_CASE_COLUMNS`. Missing
    fields default to None. If the file is absent or malformed we return an
    empty list — DQ just won't have anything to explain.
    """
    fixture_path = Path(__file__).parent.parent.parent / "scripts" / "dq_fixtures.json"
    if not fixture_path.exists():
        return []
    try:
        raw = json.loads(fixture_path.read_text())
    except Exception as e:
        logger.warning(f"DQ fixture parse failed: {e}")
        return []
    rows: list[dict] = []
    for item in raw:
        rows.append({col: item.get(col) for col in _TEST_CASE_COLUMNS})
    logger.info(f"Loaded {len(rows)} DQ test cases from synthetic fixture.")
    return rows


# OpenMetadata exposes one endpoint per service category. The four below cover
# every connector type the seed catalog uses; others return empty lists so
# hitting them is cheap. Failures per-kind fail soft so one 401/404 doesn't
# break the whole refresh.
_SERVICE_KINDS: list[tuple[str, str]] = [
    ("database", "/v1/services/databaseServices"),
    ("dashboard", "/v1/services/dashboardServices"),
    ("messaging", "/v1/services/messagingServices"),
    ("pipeline", "/v1/services/pipelineServices"),
]


def _fetch_services(http) -> list[dict]:
    """Pull every service registered in OpenMetadata, tagged by kind.

    Each entry is normalized to `{id, name, fqn, kind, service_type,
    description}` so downstream SQL doesn't need to know which endpoint
    produced which row.
    """
    rows: list[dict] = []
    for kind, path in _SERVICE_KINDS:
        try:
            raw = _fetch_paginated(http, path)
        except Exception as e:
            logger.warning(f"service fetch failed for {kind}: {e}")
            continue
        for s in raw:
            rows.append(
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "fqn": s.get("fullyQualifiedName"),
                    "kind": kind,
                    "service_type": s.get("serviceType"),
                    "description": s.get("description"),
                }
            )
    return rows


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
