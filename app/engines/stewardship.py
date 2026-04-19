"""Stewardship engine — generates and writes metadata improvements."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.clients import openmetadata
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
