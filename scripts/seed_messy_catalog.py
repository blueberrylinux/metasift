"""Populate OpenMetadata with sample catalog data for testing.

Creates tables across multiple schemas with varying levels of metadata
quality — some well-documented, some with gaps or inconsistencies.

Run:
    uv run python scripts/seed_messy_catalog.py
"""

from __future__ import annotations

import random
import sys

import httpx
from loguru import logger

from app.config import settings

SERVICE_NAME = "metasift_demo_db"
DATABASE_NAME = "analytics"

# ── Table specs ───────────────────────────────────────────────────────────

MESSY_SCHEMAS: dict[str, list[dict]] = {
    "sales": [
        {
            "name": "orders",
            "description": "Customer order transactions with payment and fulfillment status.",
            "columns": [
                ("order_id", "BIGINT", None),
                ("customer_id", "BIGINT", "PII.NonSensitive"),
                ("total_amount", "DECIMAL", None),
                ("created_at", "TIMESTAMP", None),
            ],
        },
        {
            "name": "refund_events",
            "description": "Daily sales aggregates by region and product.",
            "columns": [
                ("refund_id", "BIGINT", None),
                ("order_id", "BIGINT", None),
                ("reason_code", "STRING", None),
                ("refunded_at", "TIMESTAMP", None),
            ],
        },
        {
            "name": "cart_abandonments",
            "description": "",
            "columns": [
                ("session_id", "STRING", None),
                ("cust_id", "BIGINT", None),
                ("abandoned_at", "TIMESTAMP", None),
            ],
        },
    ],
    "marketing": [
        {
            "name": "campaign_attr",
            "description": "table for campaigns",
            "columns": [
                ("campaign_id", "BIGINT", None),
                ("CustomerID", "BIGINT", None),
                ("channel", "STRING", None),
                ("email", "STRING", None),
            ],
        },
        {
            "name": "email_sends",
            "description": "Outbound email campaign send events with delivery status.",
            "columns": [
                ("send_id", "BIGINT", None),
                ("email", "STRING", "PII.Sensitive"),
                ("campaign_id", "BIGINT", None),
            ],
        },
    ],
    "users": [
        {
            "name": "customer_profiles",
            "description": "Master customer dimension with demographic attributes.",
            "columns": [
                ("id", "BIGINT", None),
                ("email", "STRING", "PII.Sensitive"),
                ("first_name", "STRING", "PII.Sensitive"),
                ("phone", "STRING", None),
            ],
        },
        {
            "name": "user_sessions",
            "description": "",
            "columns": [
                ("session_id", "STRING", None),
                ("cid", "BIGINT", None),
                ("started_at", "TIMESTAMP", None),
            ],
        },
    ],
    "finance": [
        {
            "name": "invoices",
            "description": "Accounts receivable invoice line items.",
            "columns": [
                ("invoice_id", "BIGINT", None),
                ("customer_id", "BIGINT", None),
                ("amount", "DECIMAL", None),
            ],
        },
        {
            "name": "payments",
            "description": "t",
            "columns": [
                ("payment_id", "BIGINT", None),
                ("invoice_id", "BIGINT", None),
                ("phone", "STRING", "PII.Sensitive"),
            ],
        },
    ],
}


def _client() -> httpx.Client:
    token = settings.require_om_token()
    return httpx.Client(
        base_url=settings.om_api,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def ensure_service(c: httpx.Client) -> None:
    # Create a Custom database service for seeding
    payload = {
        "name": SERVICE_NAME,
        "serviceType": "CustomDatabase",
        "connection": {
            "config": {
                "type": "CustomDatabase",
                "sourcePythonClass": "metadata.ingestion.source.database.customdatabase.CustomDatabaseSource",
                "connectionOptions": {},
            }
        },
    }
    r = c.put("/v1/services/databaseServices", json=payload)
    logger.info(f"service: {r.status_code}")


def ensure_database(c: httpx.Client) -> None:
    r = c.put(
        "/v1/databases",
        json={
            "name": DATABASE_NAME,
            "service": SERVICE_NAME,
        },
    )
    logger.info(f"database: {r.status_code}")


def ensure_schema(c: httpx.Client, schema: str) -> None:
    r = c.put(
        "/v1/databaseSchemas",
        json={
            "name": schema,
            "database": f"{SERVICE_NAME}.{DATABASE_NAME}",
        },
    )
    logger.info(f"schema {schema}: {r.status_code}")


def _column_tags(tag: str | None) -> list[dict]:
    if not tag:
        return []
    return [
        {
            "tagFQN": tag,
            "labelType": "Manual",
            "state": "Confirmed",
            "source": "Classification",
        }
    ]


def create_table(c: httpx.Client, schema: str, spec: dict) -> None:
    cols = [
        {"name": name, "dataType": dtype, "tags": _column_tags(tag)}
        for name, dtype, tag in spec["columns"]
    ]
    payload = {
        "name": spec["name"],
        "databaseSchema": f"{SERVICE_NAME}.{DATABASE_NAME}.{schema}",
        "columns": cols,
        "description": spec["description"],
    }
    r = c.put("/v1/tables", json=payload)
    status = "✔" if r.status_code in (200, 201) else f"✘ {r.status_code}"
    logger.info(f"  {status} {schema}.{spec['name']}")


def force_reset_table(c: httpx.Client, schema: str, spec: dict) -> None:
    """Force description + column tags back to seed values via JSON-patch.

    PUT /v1/tables has merge semantics in OpenMetadata — empty-string
    descriptions and missing tag arrays don't clear previously-applied
    values. This re-fetches the table after PUT and emits explicit
    replace/remove ops so `make seed` is truly idempotent regardless of
    whatever accepts/edits happened in prior sessions.
    """
    fqn = _table_fqn(schema, spec["name"])
    # `fields=columns,tags` is load-bearing — without it OM strips column tags
    # from the response and the diff below sees every column as untagged,
    # turning real cleanup ops into no-ops.
    r = c.get(f"/v1/tables/name/{fqn}", params={"fields": "columns,tags"})
    if r.status_code != 200:
        logger.warning(f"    reset ✘ can't fetch {fqn}: {r.status_code}")
        return
    current = r.json()

    patches: list[dict] = []

    # Description: remove when target is empty, replace otherwise. OM rejects
    # empty-string values on some string fields (Pydantic min_length=1), so
    # `remove` is the safe way to express "clear this".
    current_desc = current.get("description") or ""
    target_desc = spec["description"] or ""
    if current_desc != target_desc:
        if target_desc:
            patches.append({"op": "replace", "path": "/description", "value": target_desc})
        elif current_desc:
            patches.append({"op": "remove", "path": "/description"})

    # Column tags — replace each column's tags array by index. Rely on OM
    # preserving column order across PUT, which it does for named columns.
    target_tags_by_name = {name: _column_tags(tag) for name, _dtype, tag in spec["columns"]}
    for idx, col in enumerate(current.get("columns") or []):
        name = col.get("name")
        target = target_tags_by_name.get(name, [])
        current_fqns = sorted(t.get("tagFQN", "") for t in (col.get("tags") or []))
        target_fqns = sorted(t.get("tagFQN", "") for t in target)
        if current_fqns != target_fqns:
            patches.append({"op": "replace", "path": f"/columns/{idx}/tags", "value": target})

    if not patches:
        return
    r = c.patch(
        f"/v1/tables/name/{fqn}",
        headers={"Content-Type": "application/json-patch+json"},
        json=patches,
    )
    status = "✔" if r.status_code == 200 else f"✘ {r.status_code}"
    logger.info(f"    reset {status} {schema}.{spec['name']} ({len(patches)} op(s))")


# Lineage edges (source_schema.source_table → target_schema.target_table).
# Seeded relationships that reflect typical e-commerce data flow so the
# agent's "what depends on X?" queries have real answers to traverse.
LINEAGE_EDGES: list[tuple[str, str]] = [
    # customer_profiles is the master dim — three downstream dependents
    ("users.customer_profiles", "sales.orders"),
    ("users.customer_profiles", "users.user_sessions"),
    ("users.customer_profiles", "sales.cart_abandonments"),
    # orders feed refunds and invoices
    ("sales.orders", "sales.refund_events"),
    ("sales.orders", "finance.invoices"),
    # invoices settle into payments
    ("finance.invoices", "finance.payments"),
    # marketing: campaigns send emails, emails drive orders
    ("marketing.campaign_attr", "marketing.email_sends"),
    ("marketing.email_sends", "sales.orders"),
]


def _table_fqn(schema: str, table: str) -> str:
    return f"{SERVICE_NAME}.{DATABASE_NAME}.{schema}.{table}"


def create_lineage_edges(c: httpx.Client) -> None:
    """Resolve table IDs and PUT one lineage edge per entry in LINEAGE_EDGES.

    Uses OM's `PUT /v1/lineage` — idempotent, re-running simply no-ops on
    existing edges. Missing endpoints log a warning but don't abort the seed.
    """
    logger.info(f"Seeding {len(LINEAGE_EDGES)} lineage edge(s)...")
    id_cache: dict[str, str] = {}

    def resolve(short: str) -> str | None:
        schema, table = short.split(".", 1)
        fqn = _table_fqn(schema, table)
        if fqn in id_cache:
            return id_cache[fqn]
        r = c.get(f"/v1/tables/name/{fqn}")
        if r.status_code != 200:
            logger.warning(f"  ✘ can't resolve {fqn}: {r.status_code}")
            return None
        tid = r.json().get("id")
        if tid:
            id_cache[fqn] = tid
        return tid

    for src_short, dst_short in LINEAGE_EDGES:
        src_id = resolve(src_short)
        dst_id = resolve(dst_short)
        if not (src_id and dst_id):
            continue
        payload = {
            "edge": {
                "fromEntity": {"id": src_id, "type": "table"},
                "toEntity": {"id": dst_id, "type": "table"},
            }
        }
        r = c.put("/v1/lineage", json=payload)
        status = "✔" if r.status_code in (200, 201) else f"✘ {r.status_code}"
        logger.info(f"  {status} {src_short} → {dst_short}")


# Team assignments. Two tables left intentionally without an owner so MetaSift
# has real "orphan" findings to surface in stewardship views.
TEAMS: list[dict] = [
    {
        "name": "revenue-team",
        "displayName": "Revenue Team",
        "description": "Owns sales and finance pipelines end-to-end.",
        "owns": [
            "sales.orders",
            "sales.refund_events",
            "finance.invoices",
            "finance.payments",
        ],
    },
    {
        "name": "marketing-team",
        "displayName": "Marketing Team",
        "description": "Owns campaign attribution and email delivery surfaces.",
        "owns": ["marketing.campaign_attr", "marketing.email_sends"],
    },
    {
        "name": "platform-team",
        "displayName": "Platform Team",
        "description": "Owns shared customer dimensions and identity.",
        "owns": ["users.customer_profiles"],
    },
]
# `sales.cart_abandonments` and `users.user_sessions` deliberately have no
# owner — gives MetaSift's orphan-detection something real to flag.


# ── DQ test cases + failing results ───────────────────────────────────────
#
# Each entry seeds one OpenMetadata test case + one test result so MetaSift's
# DQ surfaces (failures viz, recommendations, risk ranking, agent tools) all
# have real catalog state to read from. Mix of fix_types to cover every
# branch in `cleaning.explain_dq_failure` / the action-chip dispatch in DQ.tsx.
#
# `column` is None for table-level tests. `parameter_values` shape mirrors
# OpenMetadata's testDefinition contract — empty list for parameterless tests
# like columnValuesToBeNotNull / columnValuesToBeUnique.

DQ_TEST_CASES: list[dict] = [
    {
        # null_constraint — null_count fix_type
        "table": "users.customer_profiles",
        "column": "email",
        "name": "email_not_null",
        "definition": "columnValuesToBeNotNull",
        "description": "Customer profiles must always have an email on file.",
        "parameter_values": [],
        "status": "Failed",
        "result": "Found 47 NULL values out of 2,841 rows (1.65%) — expected 0.",
    },
    {
        # null_constraint on a different column to give the action-chip
        # disambiguation something to choose between
        "table": "sales.refund_events",
        "column": "refunded_at",
        "name": "refunded_at_not_null",
        "definition": "columnValuesToBeNotNull",
        "description": "Every refund row must record when the refund happened.",
        "parameter_values": [],
        "status": "Failed",
        "result": "Found 12 NULL refunded_at values out of 1,402 rows.",
    },
    {
        # unique_constraint — duplicate_count fix_type
        "table": "users.customer_profiles",
        "column": "phone",
        "name": "phone_unique",
        "definition": "columnValuesToBeUnique",
        "description": "Phone numbers should be unique per customer.",
        "parameter_values": [],
        "status": "Failed",
        "result": "12 duplicate values across 28 rows — expected 0 duplicates.",
    },
    {
        # range_check / out_of_range — fix_type bounds_check.
        # Targets finance.invoices.amount because finance.payments doesn't
        # have an amount column (it has payment_id/invoice_id/phone — see
        # MESSY_SCHEMAS).
        "table": "finance.invoices",
        "column": "amount",
        "name": "invoice_amount_strictly_positive",
        "definition": "columnValuesToBeBetween",
        "description": "Invoice amounts must be strictly positive.",
        "parameter_values": [
            {"name": "minValue", "value": "0.01"},
            {"name": "maxValue", "value": "100000.00"},
        ],
        "status": "Failed",
        "result": "8 rows with amount <= 0 (min observed: -47.50).",
    },
    {
        # regex — schema_drift fix_type
        "table": "marketing.email_sends",
        "column": "email",
        "name": "email_format_valid",
        "definition": "columnValuesToMatchRegex",
        "description": "Recipient emails must match a basic RFC-5322-ish regex.",
        "parameter_values": [
            {"name": "regex", "value": r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$"}
        ],
        "status": "Failed",
        "result": "143 rows have malformed email values (no @ or no TLD).",
    },
    {
        # range, but PASSING — gives the dashboard a non-100%-failing mix and
        # exercises the "passing test" path through analysis.dq_failures()
        "table": "sales.orders",
        "column": "total_amount",
        "name": "order_total_in_expected_range",
        "definition": "columnValuesToBeBetween",
        "description": "Order totals fall within expected sane bounds.",
        "parameter_values": [
            {"name": "minValue", "value": "0.01"},
            {"name": "maxValue", "value": "50000.00"},
        ],
        "status": "Success",
        "result": "All 18,304 rows within bounds.",
    },
    {
        # table-level — row count, gives table_check fix_type something to bite
        "table": "marketing.campaign_attr",
        "column": None,
        "name": "campaign_attr_row_count_nonzero",
        "definition": "tableRowCountToBeBetween",
        "description": "Campaign attribution should never go fully empty mid-day.",
        "parameter_values": [
            {"name": "minValue", "value": "1"},
            {"name": "maxValue", "value": "1000000"},
        ],
        "status": "Failed",
        "result": "Found 0 rows — campaign attribution is empty.",
    },
]


def seed_dq_test_cases(c: httpx.Client) -> None:
    """Create test cases + write a single failing/passing result for each.

    POST /v1/dataQuality/testCases is idempotent on `name` per entityLink —
    a re-run gets 409, which we treat as "already there, fine, write a fresh
    result on top". Test results are timestamped, so re-running the seed
    pushes the failure date forward and the dashboards show the latest.
    """
    import time

    logger.info(f"Seeding {len(DQ_TEST_CASES)} DQ test case(s)...")
    now_ms = int(time.time() * 1000)
    for spec in DQ_TEST_CASES:
        schema, table = spec["table"].split(".", 1)
        table_fqn = _table_fqn(schema, table)
        column = spec["column"]
        if column:
            entity_link = f"<#E::table::{table_fqn}::columns::{column}>"
        else:
            entity_link = f"<#E::table::{table_fqn}>"

        case_payload = {
            "name": spec["name"],
            "description": spec["description"],
            "entityLink": entity_link,
            "testDefinition": spec["definition"],
            "parameterValues": spec["parameter_values"],
        }
        r = c.post("/v1/dataQuality/testCases", json=case_payload)
        if r.status_code == 201:
            case_fqn = r.json().get("fullyQualifiedName")
            logger.info(f"  ✔ test case created: {spec['name']}")
        elif r.status_code == 409:
            # Already exists from a previous run — derive the FQN from the
            # naming convention (testCase FQN = <table_fqn>.<column>?.<name>)
            # rather than refetching, since OM's GET-by-name uses the same
            # schema and we'd just round-trip the same string.
            case_fqn = (
                f"{table_fqn}.{column}.{spec['name']}" if column else f"{table_fqn}.{spec['name']}"
            )
            logger.info(f"  ↻ test case exists: {spec['name']}")
        else:
            logger.warning(f"  ✘ {spec['name']} → {r.status_code}: {r.text[:200]}")
            continue

        result_payload = {
            "timestamp": now_ms,
            "testCaseStatus": spec["status"],
            "result": spec["result"],
        }
        r2 = c.post(
            f"/v1/dataQuality/testCases/testCaseResults/{case_fqn}",
            json=result_payload,
        )
        if r2.status_code in (200, 201):
            logger.info(f"    ✔ result written: {spec['status']}")
        else:
            logger.warning(f"    ✘ result for {spec['name']} → {r2.status_code}: {r2.text[:200]}")


def ensure_teams_and_ownership(c: httpx.Client) -> None:
    """Create each team (idempotent) then PATCH `owners` on the named tables.

    Uses JSON Patch on `/v1/tables/name/{fqn}`. Re-running the seed overwrites
    any owner overrides the user has applied manually — acceptable, since the
    seed is meant to reset demo state.
    """
    logger.info(f"Seeding {len(TEAMS)} team(s) + ownership assignments...")
    for team in TEAMS:
        # Create or update the team
        payload = {
            "name": team["name"],
            "displayName": team["displayName"],
            "description": team["description"],
            "teamType": "Group",
        }
        r = c.put("/v1/teams", json=payload)
        if r.status_code not in (200, 201):
            logger.warning(f"  ✘ team {team['name']}: {r.status_code}")
            continue
        team_id = r.json().get("id")
        logger.info(f"  ✔ team {team['displayName']} ({team_id[:8]}…)")

        # Assign ownership on each table
        for short in team["owns"]:
            schema, table = short.split(".", 1)
            fqn = _table_fqn(schema, table)
            patch = [
                {
                    "op": "add",
                    "path": "/owners",
                    "value": [{"id": team_id, "type": "team"}],
                }
            ]
            r2 = c.patch(
                f"/v1/tables/name/{fqn}",
                headers={"Content-Type": "application/json-patch+json"},
                json=patch,
            )
            status = "✔" if r2.status_code == 200 else f"✘ {r2.status_code}"
            logger.info(f"    {status} {short} ← {team['name']}")


def main() -> int:
    logger.info("Seeding sample catalog into OpenMetadata...")
    random.seed(42)
    with _client() as c:
        ensure_service(c)
        ensure_database(c)
        for schema, tables in MESSY_SCHEMAS.items():
            ensure_schema(c, schema)
            for spec in tables:
                create_table(c, schema, spec)
                force_reset_table(c, schema, spec)
        create_lineage_edges(c)
        ensure_teams_and_ownership(c)
        seed_dq_test_cases(c)
    logger.success("Seeding complete.")
    logger.info("Open http://localhost:8585 → Explore → you'll see metasift_demo_db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
