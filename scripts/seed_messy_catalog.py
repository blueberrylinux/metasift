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


def create_table(c: httpx.Client, schema: str, spec: dict) -> None:
    cols = [
        {
            "name": name,
            "dataType": dtype,
            "tags": [
                {
                    "tagFQN": tag,
                    "labelType": "Manual",
                    "state": "Confirmed",
                    "source": "Classification",
                }
            ]
            if tag
            else [],
        }
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
        create_lineage_edges(c)
    logger.success("Seeding complete.")
    logger.info("Open http://localhost:8585 → Explore → you'll see metasift_demo_db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
