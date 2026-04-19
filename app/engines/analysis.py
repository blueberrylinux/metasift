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


def ownership_breakdown() -> pd.DataFrame:
    """Per-team stewardship scorecard.

    Aggregates each team's table count, documentation coverage, avg
    description quality (if deep scan has run), and PII-table footprint.
    Tables with no owner are excluded here — see `orphans()` for those.
    """
    try:
        has_cleaning = _has_cleaning_results()
        quality_join = ""
        quality_select = "NULL AS quality_avg"
        if has_cleaning:
            quality_join = """
                LEFT JOIN cleaning_results cr
                  ON cr.fqn = t.fullyQualifiedName
            """
            quality_select = "AVG(cr.quality_score) AS quality_avg"
        return duck.query(f"""
            WITH owned AS (
                SELECT
                    t.fullyQualifiedName AS fqn,
                    t.description,
                    CASE WHEN len(t.owners) > 0 THEN t.owners[1].displayName ELSE NULL END AS team,
                    CASE WHEN len(t.owners) > 0 THEN t.owners[1].name ELSE NULL END AS team_name,
                    CASE WHEN t.description IS NULL OR length(t.description) = 0 THEN 0 ELSE 1 END AS documented
                FROM om_tables t
            ),
            pii_tables AS (
                SELECT DISTINCT table_fqn
                FROM om_columns
                WHERE list_contains(tags, 'PII.Sensitive')
            )
            SELECT
                o.team AS team,
                o.team_name AS team_slug,
                COUNT(*) AS tables_owned,
                SUM(o.documented) AS documented,
                ROUND(100.0 * SUM(o.documented) / COUNT(*), 1) AS coverage_pct,
                COUNT(DISTINCT p.table_fqn) AS pii_tables,
                {quality_select}
            FROM owned o
            LEFT JOIN pii_tables p ON p.table_fqn = o.fqn
            {quality_join}
            WHERE o.team IS NOT NULL
            GROUP BY o.team, o.team_name
            ORDER BY coverage_pct DESC, tables_owned DESC
        """)
    except Exception:
        return pd.DataFrame(
            columns=[
                "team",
                "team_slug",
                "tables_owned",
                "documented",
                "coverage_pct",
                "pii_tables",
                "quality_avg",
            ]
        )


def orphans() -> pd.DataFrame:
    """Tables with no owner — metadata debt nobody's on the hook for."""
    try:
        return duck.query("""
            SELECT
                fullyQualifiedName AS fqn,
                CASE WHEN description IS NULL OR length(description) = 0 THEN FALSE ELSE TRUE END AS documented
            FROM om_tables
            WHERE len(owners) = 0
            ORDER BY fqn
        """)
    except Exception:
        return pd.DataFrame(columns=["fqn", "documented"])


def blast_radius(fqn: str, max_depth: int = 10) -> dict:
    """Downstream impact footprint for a single table.

    Walks om_lineage transitively and counts everything downstream of `fqn`,
    separating direct dependents from transitive ones. Also counts how many
    downstream tables carry at least one PII.Sensitive column — a weighted
    `impact_score` combines the two so high-blast-on-sensitive-data tables
    rank higher than high-blast-on-plain-data tables.

    Returns {fqn, direct, transitive, pii_downstream, impact_score,
    downstream_fqns}. If lineage data isn't loaded, all counts are 0.
    """
    try:
        direct_df = duck.query(
            "SELECT target_fqn FROM om_lineage WHERE source_fqn = ?",
            [fqn],
        )
    except Exception:
        return {
            "fqn": fqn,
            "direct": 0,
            "transitive": 0,
            "pii_downstream": 0,
            "impact_score": 0.0,
            "downstream_fqns": [],
        }

    direct_downstream = direct_df["target_fqn"].tolist() if not direct_df.empty else []

    # Transitive closure via a recursive CTE. max_depth bounds runaway on
    # accidental cycles — the catalog is a DAG but nothing enforces that.
    all_df = duck.query(
        """
        WITH RECURSIVE downstream(node, depth) AS (
            SELECT target_fqn, 1 FROM om_lineage WHERE source_fqn = ?
            UNION
            SELECT l.target_fqn, d.depth + 1
            FROM om_lineage l
            JOIN downstream d ON l.source_fqn = d.node
            WHERE d.depth < ?
        )
        SELECT DISTINCT node AS fqn FROM downstream
        """,
        [fqn, int(max_depth)],
    )
    all_downstream: list[str] = all_df["fqn"].tolist() if not all_df.empty else []

    # How many downstream tables have at least one PII.Sensitive column?
    pii_count = 0
    if all_downstream:
        placeholders = ",".join(["?"] * len(all_downstream))
        pii_df = duck.query(
            f"""
            SELECT COUNT(DISTINCT table_fqn) AS n
            FROM om_columns
            WHERE table_fqn IN ({placeholders})
              AND list_contains(tags, 'PII.Sensitive')
            """,
            all_downstream,
        )
        pii_count = int(pii_df["n"].iloc[0]) if not pii_df.empty else 0

    direct = len(direct_downstream)
    transitive = len(all_downstream)
    # Weighted score: direct deps count 1x, transitive 0.5x, PII downstream 2x.
    # Keep the ceiling loose so values read intuitively (0-ish to ~20+).
    impact = float(direct) + 0.5 * (transitive - direct) + 2.0 * pii_count
    return {
        "fqn": fqn,
        "direct": direct,
        "transitive": transitive,
        "pii_downstream": pii_count,
        "impact_score": round(impact, 2),
        "downstream_fqns": all_downstream,
    }


def top_blast_radius(limit: int = 10) -> pd.DataFrame:
    """Rank every table in the catalog by blast radius.

    Useful for the viz tab and for dashboards — one pass over om_tables,
    calls blast_radius() per FQN. N is small (dozens in a demo catalog),
    so the per-table recursive query is fine.
    """
    try:
        tables = duck.query("SELECT fullyQualifiedName AS fqn FROM om_tables")
    except Exception:
        return pd.DataFrame(
            columns=["fqn", "direct", "transitive", "pii_downstream", "impact_score"]
        )
    rows = []
    for fqn in tables["fqn"].tolist():
        r = blast_radius(fqn)
        rows.append(
            {
                "fqn": fqn,
                "direct": r["direct"],
                "transitive": r["transitive"],
                "pii_downstream": r["pii_downstream"],
                "impact_score": r["impact_score"],
            }
        )
    df = pd.DataFrame(rows).sort_values("impact_score", ascending=False).head(limit)
    return df.reset_index(drop=True)


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
