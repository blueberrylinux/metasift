"""Analysis engine — catalog-wide aggregate analytics via DuckDB."""

from __future__ import annotations

import pandas as pd

from app.clients import duck


def documentation_coverage() -> pd.DataFrame:
    """% of tables with a non-empty description, per schema."""
    return duck.query("""
        SELECT
            split_part(fullyQualifiedName, '.', 2) AS database,
            split_part(fullyQualifiedName, '.', 3) AS schema,
            COUNT(*) AS total,
            SUM(CASE WHEN description IS NOT NULL AND length(description) > 0 THEN 1 ELSE 0 END) AS documented,
            ROUND(100.0 * SUM(CASE WHEN description IS NOT NULL AND length(description) > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS coverage_pct
        FROM om_tables
        GROUP BY database, schema
        ORDER BY coverage_pct ASC
    """)


def tag_conflicts() -> pd.DataFrame:
    """Column names whose tag assignment varies across tables.

    Includes the common case where a column is tagged in some tables but
    untagged in others (e.g. `email` tagged `PII.Sensitive` in one schema
    but untagged in another). A name only counts if it's tagged somewhere —
    a column that's untagged everywhere isn't a "conflict", just untagged.
    """
    return duck.query("""
        WITH all_col_tags AS (
            SELECT name, table_fqn, list_sort(tags) AS tag_set
            FROM om_columns
        ),
        names_with_any_tag AS (
            SELECT DISTINCT name FROM om_columns WHERE len(tags) > 0
        )
        SELECT name,
               COUNT(DISTINCT tag_set::VARCHAR) AS distinct_tag_sets,
               list(DISTINCT tag_set::VARCHAR) AS tag_variants,
               list(DISTINCT table_fqn) AS affected_tables
        FROM all_col_tags
        WHERE name IN (SELECT name FROM names_with_any_tag)
        GROUP BY name
        HAVING COUNT(DISTINCT tag_set::VARCHAR) > 1
        ORDER BY distinct_tag_sets DESC
    """)


def _coverage_pct() -> float:
    """% of tables with a non-empty description."""
    df = duck.query("""
        SELECT
            100.0 * SUM(CASE WHEN description IS NOT NULL AND length(description) > 0 THEN 1 ELSE 0 END)
            / NULLIF(COUNT(*), 0) AS pct
        FROM om_tables
    """)
    raw = df["pct"].iloc[0]
    return 0.0 if pd.isna(raw) else round(float(raw), 1)


def _consistency_pct() -> float:
    """% of columns NOT involved in a tag conflict.

    A column is in conflict if its name is tagged inconsistently across tables
    (tagged differently, or tagged in some tables and untagged in others).
    """
    total = duck.query("SELECT COUNT(*) AS n FROM om_columns")["n"].iloc[0]
    if total == 0:
        return 100.0
    conflicts = tag_conflicts()
    if conflicts.empty:
        return 100.0
    conflicting_names = set(conflicts["name"].tolist())
    placeholders = ",".join(["?"] * len(conflicting_names))
    conflict_count = duck.query(
        f"SELECT COUNT(*) AS n FROM om_columns WHERE name IN ({placeholders})",
        list(conflicting_names),
    )["n"].iloc[0]
    return round(100.0 * (total - conflict_count) / total, 1)


def _has_cleaning_results() -> bool:
    try:
        duck.query("SELECT 1 FROM cleaning_results LIMIT 1")
        return True
    except Exception:
        return False


def _accuracy_pct() -> float | None:
    """% of analyzed descriptions that are NOT stale. None if not scanned."""
    if not _has_cleaning_results():
        return None
    df = duck.query("""
        SELECT
            100.0 * SUM(CASE WHEN stale = FALSE THEN 1 ELSE 0 END)
            / NULLIF(COUNT(*), 0) AS pct
        FROM cleaning_results
        WHERE stale IS NOT NULL
    """)
    raw = df["pct"].iloc[0]
    return None if pd.isna(raw) else round(float(raw), 1)


def _quality_pct() -> float | None:
    """Mean description quality, normalized 0-100 (from 1-5 scoring)."""
    if not _has_cleaning_results():
        return None
    df = duck.query("""
        SELECT AVG(quality_score) AS avg_q
        FROM cleaning_results
        WHERE quality_score > 0
    """)
    raw = df["avg_q"].iloc[0]
    if pd.isna(raw):
        return None
    # Normalize 1-5 → 0-100
    return round(float(raw) * 20.0, 1)


def composite_score() -> dict[str, float]:
    """Headline metric: weighted combination of coverage, accuracy, consistency, quality.

    Accuracy and quality come from the `cleaning_results` cache (populated by
    the cleaning engine's deep scan). If the scan hasn't been run, those two
    show as 0 and the composite reflects that honestly — it's a known-partial.
    """
    coverage = _coverage_pct()
    consistency = _consistency_pct()
    accuracy = _accuracy_pct()
    quality = _quality_pct()

    # Missing values count as 0 in the composite but we surface them separately
    # so the UI can show "—" instead of "0%" when the scan hasn't run yet.
    composite = round(
        coverage * 0.30 + (accuracy or 0.0) * 0.30 + consistency * 0.20 + (quality or 0.0) * 0.20,
        1,
    )
    return {
        "coverage": coverage,
        "accuracy": accuracy if accuracy is not None else 0.0,
        "consistency": consistency,
        "quality": quality if quality is not None else 0.0,
        "composite": composite,
        "_scanned": accuracy is not None,
    }
