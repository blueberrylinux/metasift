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
    """Same column name tagged with different tag sets across tables."""
    return duck.query("""
        WITH col_tags AS (
            SELECT name, table_fqn, list_sort(tags) AS tag_set
            FROM om_columns
            WHERE len(tags) > 0
        )
        SELECT name, COUNT(DISTINCT tag_set::VARCHAR) AS distinct_tag_sets,
               list(DISTINCT tag_set::VARCHAR) AS tag_variants,
               list(DISTINCT table_fqn) AS affected_tables
        FROM col_tags
        GROUP BY name
        HAVING COUNT(DISTINCT tag_set::VARCHAR) > 1
        ORDER BY distinct_tag_sets DESC
    """)


def composite_score() -> dict[str, float]:
    """Headline metric: weighted combination of coverage, accuracy, consistency, quality."""
    coverage_df = duck.query("""
        SELECT
            100.0 * SUM(CASE WHEN description IS NOT NULL AND length(description) > 0 THEN 1 ELSE 0 END) / COUNT(*)
            AS pct
        FROM om_tables
    """)
    coverage = float(coverage_df["pct"][0] or 0)

    # Placeholder — accuracy, consistency, quality get filled in as cleaning engine runs
    return {
        "coverage": round(coverage, 1),
        "accuracy": 0.0,  # % non-stale — needs stale detection run
        "consistency": 0.0,  # % conflict-free — needs conflict detection run
        "quality": 0.0,  # mean description quality 0-100 — needs scoring run
        "composite": round(coverage * 0.3, 1),  # partial until other engines run
    }
