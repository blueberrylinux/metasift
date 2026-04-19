"""Stewardship engine — generates and writes metadata improvements."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.clients import duck, openmetadata
from app.clients.llm import get_llm


@dataclass
class Suggestion:
    fqn: str
    field: str  # "description", "tag", etc.
    old: str | None
    new: str
    confidence: float
    reasoning: str


def generate_description(fqn: str, columns: list[dict], lineage_hint: str = "") -> Suggestion:
    """Draft a 1-2 sentence business description for a table."""
    llm = get_llm("description")
    col_summary = ", ".join(f"{c['name']} ({c['dataType']})" for c in columns[:20])
    prompt = (
        "You are a senior data engineer. Write a concise 1-2 sentence business description "
        "for a table based only on its column metadata. Be specific, avoid filler.\n\n"
        f"Table: {fqn}\nColumns: {col_summary}\n"
        f"{f'Lineage context: {lineage_hint}' if lineage_hint else ''}\n\n"
        "Description:"
    )
    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    return Suggestion(
        fqn=fqn,
        field="description",
        old=None,
        new=text.strip(),
        confidence=0.8,
        reasoning="Generated from column names and types.",
    )


def apply_suggestion(s: Suggestion) -> bool:
    """Write the suggestion back to OpenMetadata. Returns True on success."""
    try:
        if s.field == "description":
            openmetadata.patch_table_description(s.fqn, s.new)
            return True
        logger.warning(f"Unknown field: {s.field}")
        return False
    except Exception as e:
        logger.error(f"Apply failed for {s.fqn}: {e}")
        return False


def apply_pii_tag(table_fqn: str, column_name: str, tag_fqn: str) -> dict:
    """Apply a PII classification tag to a column via REST PATCH.

    Returns {"ok": bool, "status": str, "message": str}.
    """
    try:
        result = openmetadata.patch_column_tag(table_fqn, column_name, tag_fqn)
        return {
            "ok": True,
            "status": result.get("status", "applied"),
            "message": f"{result.get('status', 'applied')}: {column_name} -> {tag_fqn}",
        }
    except ValueError as e:
        logger.error(f"Column lookup failed for {table_fqn}.{column_name}: {e}")
        return {"ok": False, "status": "column_not_found", "message": str(e)}
    except Exception as e:
        logger.error(f"apply_pii_tag failed for {table_fqn}.{column_name}: {e}")
        return {"ok": False, "status": "error", "message": str(e)}


# ── Bulk: auto-document an entire schema ──────────────────────────────────────
#
# NL-triggered stewardship. The agent picks up "auto-document the sales schema",
# finds every undocumented table in that schema, drafts a description for each
# via generate_description(), and persists the drafts to `doc_suggestions` so
# the review queue can surface them for Accept/Edit/Reject.


def _as_list(value) -> list:
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value) if value else []


def bulk_document_schema(
    schema_name: str,
    max_tables: int = 20,
    progress_cb=None,
) -> dict:
    """Generate description drafts for every undocumented table in a schema.

    Args:
        schema_name: the schema segment of the FQN (e.g. "sales").
        max_tables: cap to avoid runaway LLM cost on huge schemas.
        progress_cb: optional callable(step, total, label) for UI feedback.

    Returns:
        Summary dict with schema, drafted count, failed count, total found.
        Drafts land in the `doc_suggestions` DuckDB table; the review queue
        reads from there.
    """
    if not schema_name or not schema_name.strip():
        return {"schema": "", "drafted": 0, "failed": 0, "total": 0, "error": "empty schema name"}

    pattern = f"%.{schema_name}.%"
    rows = duck.query(
        """
        SELECT fullyQualifiedName AS fqn, columns
        FROM om_tables
        WHERE fullyQualifiedName LIKE ?
          AND (description IS NULL OR length(description) = 0)
        ORDER BY fqn
        LIMIT ?
        """,
        [pattern, int(max_tables)],
    )
    total = len(rows)
    if total == 0:
        return {"schema": schema_name, "drafted": 0, "failed": 0, "total": 0}

    conn = duck.get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS doc_suggestions (
            fqn VARCHAR PRIMARY KEY,
            suggested VARCHAR,
            confidence DOUBLE,
            reasoning VARCHAR
        )
    """)

    drafted = 0
    failed = 0
    for idx, (_, row) in enumerate(rows.iterrows(), start=1):
        fqn = row["fqn"]
        if progress_cb:
            progress_cb(idx, total, f"Drafting: {fqn}")
        try:
            suggestion = generate_description(fqn, _as_list(row["columns"]))
            conn.execute(
                "INSERT OR REPLACE INTO doc_suggestions VALUES (?, ?, ?, ?)",
                [fqn, suggestion.new, suggestion.confidence, suggestion.reasoning],
            )
            drafted += 1
        except Exception as e:
            logger.warning(f"bulk_document: skipped {fqn} — {e}")
            failed += 1

    logger.info(f"bulk_document_schema({schema_name}) — drafted {drafted}/{total}, failed {failed}")
    return {"schema": schema_name, "drafted": drafted, "failed": failed, "total": total}
