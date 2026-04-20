"""Stewardship engine — generates and writes metadata improvements."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

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


# ── DQ test recommendations ───────────────────────────────────────────────────
#
# Given a table's columns, types, tags, and already-configured tests, propose
# the DQ checks that *should* exist but don't. Not every column needs a test —
# the LLM is instructed to be selective and prioritize high-value ones:
#   - not-null on identifiers / required business fields
#   - format / regex on emails, phones, URLs
#   - range checks on amounts, percentages, rates
#   - uniqueness on primary keys / natural keys
#   - set membership on enum-like columns
#   - table-level row-count ranges on operational tables


@dataclass
class DQTestRecommendation:
    table_fqn: str
    column_name: str | None
    test_definition: str
    parameters: list[dict] = field(default_factory=list)
    rationale: str = ""
    severity: str = "recommended"  # "critical" | "recommended" | "nice-to-have"


# Shortlist of common OpenMetadata test definitions the LLM can pick from.
# Keeping the allowlist explicit makes the outputs parseable and prevents
# the model from inventing test-definition names OM doesn't recognize.
_DQ_TEST_CATALOG = [
    # Column-level
    "columnValuesToBeNotNull",
    "columnValuesToBeUnique",
    "columnValuesToBeBetween",
    "columnValuesToBeInSet",
    "columnValuesToMatchRegex",
    "columnValueLengthsToBeBetween",
    "columnValuesToNotMatchRegex",
    "columnValuesMissingCount",
    # Table-level
    "tableRowCountToBeBetween",
    "tableRowCountToEqual",
    "tableColumnCountToBeBetween",
    "tableColumnToMatchSet",
]


def _build_dq_recommend_prompt(
    fqn: str,
    description: str,
    columns: list[dict],
    existing: list[dict],
) -> str:
    """Ground the LLM in the real columns + existing tests so it can pick
    high-value recommendations without recommending duplicates."""
    col_lines = []
    for c in columns[:40]:
        tags = c.get("tags") or []
        tag_str = f", tags={tags}" if tags else ""
        col_lines.append(f"  - {c.get('name')} ({c.get('dataType')}){tag_str}")
    existing_lines = []
    for t in existing[:40]:
        existing_lines.append(
            f"  - {t.get('column_name') or '(table-level)'}: {t.get('test_definition_name')}"
        )
    return (
        "You are a senior data engineer proposing data quality checks for a table. "
        "Select HIGH-VALUE tests the steward should add — not every possible test, "
        "just the ones that protect the column's integrity, uniqueness, or business "
        "meaning. Skip anything already configured.\n\n"
        "Allowed test definitions (pick from this list exactly — no others):\n"
        + "\n".join(f"  - {t}" for t in _DQ_TEST_CATALOG)
        + "\n\n"
        "Severity guidelines:\n"
        '  - "critical": failure breaks downstream analytics (missing PKs, missing PII, '
        "invalid currency amounts)\n"
        '  - "recommended": meaningful quality gate (format checks, sane ranges)\n'
        '  - "nice-to-have": catches rare edge cases\n\n'
        "Rules:\n"
        "1. DO NOT recommend a test that already exists on that column/table (see "
        "'Existing tests' below).\n"
        "2. Prefer at most 4 recommendations per table — quality over quantity.\n"
        "3. For columnValuesToMatchRegex, put the regex in parameters as "
        '{"name": "regex", "value": "..."}.\n'
        "4. For range tests, put minValue / maxValue in parameters.\n"
        "5. Ground every rationale in the column name, type, or tag — no vague "
        '"ensures data quality".\n\n'
        f"Table: {fqn}\n"
        f"Description: {description or '(no description)'}\n"
        f"Columns:\n" + "\n".join(col_lines) + "\n\n"
        "Existing tests:\n" + ("\n".join(existing_lines) if existing_lines else "  (none)") + "\n\n"
        "Respond with ONLY a JSON array (no prose, no code fences). Each element:\n"
        '{"column_name": str | null, "test_definition": str, '
        '"parameters": [{"name": str, "value": str}], '
        '"rationale": str, "severity": "critical" | "recommended" | "nice-to-have"}\n'
        "Empty array [] if the table already has sufficient coverage."
    )


def _parse_dq_recommend_json(text: str) -> list[dict] | None:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def recommend_dq_tests(fqn: str) -> list[DQTestRecommendation]:
    """Propose DQ tests that should exist on a table but currently don't.

    Reads the table's columns + existing om_test_cases rows, prompts the LLM
    to emit a ranked JSON array of recommendations, filters anything that
    duplicates an existing test (belt-and-braces — the prompt also instructs
    the model, but we enforce it in code).
    """
    if not fqn or not fqn.strip():
        return []

    df = duck.query(
        "SELECT description, columns FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn.strip()],
    )
    if df.empty:
        return []
    description = df["description"].iloc[0] or ""
    columns = _as_list(df["columns"].iloc[0])

    existing: list[dict] = []
    try:
        ex_df = duck.query(
            """
            SELECT column_name, test_definition_name
            FROM om_test_cases
            WHERE table_fqn = ?
            """,
            [fqn.strip()],
        )
        existing = ex_df.to_dict(orient="records")
    except Exception:
        pass
    existing_keys = {
        (e.get("column_name") or "", e.get("test_definition_name") or "") for e in existing
    }

    llm = get_llm("reasoning")
    prompt = _build_dq_recommend_prompt(fqn, description, columns, existing)
    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    parsed = _parse_dq_recommend_json(text)

    if parsed is None:
        retry = llm.invoke(
            prompt + "\n\nYour previous response was not a valid JSON array. Return ONLY a "
            "JSON array — no prose, no code fences. Empty array is fine if there "
            "are no recommendations."
        )
        text = retry.content if hasattr(retry, "content") else str(retry)
        parsed = _parse_dq_recommend_json(text)

    if parsed is None:
        logger.warning(f"DQ recommend parse failed for {fqn}: {text[:200]}")
        return []

    out: list[DQTestRecommendation] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        test_def = (item.get("test_definition") or "").strip()
        if test_def not in _DQ_TEST_CATALOG:
            continue
        column_name = item.get("column_name") or None
        if (column_name or "", test_def) in existing_keys:
            continue
        params = item.get("parameters") or []
        if not isinstance(params, list):
            params = []
        out.append(
            DQTestRecommendation(
                table_fqn=fqn,
                column_name=column_name,
                test_definition=test_def,
                parameters=params,
                rationale=(item.get("rationale") or "").strip(),
                severity=(item.get("severity") or "recommended").strip().lower(),
            )
        )
    return out


def run_dq_recommendations(progress_cb=None) -> dict[str, int]:
    """Scan every table, generate DQ recommendations, persist to `dq_recommendations`.

    Args:
        progress_cb: optional callable(step, total, label).

    Returns:
        Summary dict: analyzed tables, total recommendations, per-severity counts.
    """
    try:
        tables = duck.query("SELECT fullyQualifiedName AS fqn FROM om_tables ORDER BY fqn")
    except Exception:
        return {"analyzed": 0, "total": 0, "critical": 0, "recommended": 0, "nice": 0}
    total_tables = len(tables)
    if total_tables == 0:
        return {"analyzed": 0, "total": 0, "critical": 0, "recommended": 0, "nice": 0}

    conn = duck.get_conn()
    conn.execute("""
        CREATE OR REPLACE TABLE dq_recommendations (
            id VARCHAR,
            table_fqn VARCHAR,
            column_name VARCHAR,
            test_definition VARCHAR,
            parameters VARCHAR,
            rationale VARCHAR,
            severity VARCHAR
        )
    """)

    counts = {"analyzed": 0, "total": 0, "critical": 0, "recommended": 0, "nice": 0}
    sev_key = {"critical": "critical", "recommended": "recommended", "nice-to-have": "nice"}

    for idx, (_, row) in enumerate(tables.iterrows(), start=1):
        fqn = row["fqn"]
        if progress_cb:
            progress_cb(idx, total_tables, f"Recommending tests: {fqn}")
        try:
            recs = recommend_dq_tests(fqn)
        except Exception as e:
            logger.warning(f"recommend_dq_tests failed for {fqn}: {e}")
            continue
        counts["analyzed"] += 1
        for i, r in enumerate(recs):
            rec_id = f"{fqn}::{r.column_name or ''}::{r.test_definition}::{i}"
            conn.execute(
                "INSERT INTO dq_recommendations VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    rec_id,
                    r.table_fqn,
                    r.column_name,
                    r.test_definition,
                    json.dumps(r.parameters),
                    r.rationale,
                    r.severity,
                ],
            )
            counts["total"] += 1
            counts[sev_key.get(r.severity, "recommended")] = (
                counts.get(sev_key.get(r.severity, "recommended"), 0) + 1
            )

    logger.info(
        f"DQ recommendations done — {counts['analyzed']}/{total_tables} tables, "
        f"{counts['total']} recommendations "
        f"({counts['critical']} critical, {counts['recommended']} recommended, "
        f"{counts['nice']} nice-to-have)"
    )
    return counts
