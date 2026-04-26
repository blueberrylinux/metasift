"""Analysis engine — catalog-wide aggregate analytics via DuckDB."""

from __future__ import annotations

import pandas as pd
from loguru import logger

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


def service_coverage() -> pd.DataFrame:
    """Per-service inventory with table counts derived from om_tables.

    FQNs in om_tables are `service.database.schema.table`, so the first
    dotted segment is the service name. Left-join keeps zero-table
    services visible so the user can see connectors that are registered
    but haven't been ingested yet.
    """
    try:
        return duck.query("""
            WITH table_counts AS (
                SELECT split_part(fullyQualifiedName, '.', 1) AS service_name,
                       COUNT(*) AS tables
                FROM om_tables
                GROUP BY service_name
            )
            SELECT
                s.name AS service,
                s.kind,
                s.service_type AS type,
                COALESCE(tc.tables, 0) AS tables
            FROM om_services s
            LEFT JOIN table_counts tc ON tc.service_name = s.name
            ORDER BY tables DESC, s.kind, s.name
        """)
    except Exception as e:
        logger.warning(f"service_coverage query failed: {e}")
        return pd.DataFrame(columns=["service", "kind", "type", "tables"])


def ownership_breakdown() -> pd.DataFrame:
    """Per-team stewardship scorecard.

    Aggregates each team's table count, documentation coverage, avg
    description quality (if deep scan has run), and PII-table footprint.
    Tables with no owner are excluded here — see `orphans()` for those.

    Uses `struct_extract` instead of dot-access on the owners struct so a
    missing `displayName` or `name` field returns NULL instead of raising
    a binder error. OpenMetadata's `/v1/tables?fields=owners` response
    usually expands both, but ingestion-bot owners or certain legacy rows
    can be missing `displayName`, which previously crashed the whole query
    and silently returned an empty leaderboard.
    """
    empty = pd.DataFrame(
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
    try:
        has_cleaning = _has_cleaning_results()
        quality_join = ""
        quality_select = "NULL AS quality_avg"
        if has_cleaning:
            # Join on `o.fqn` (the outer CTE alias) — not `t.fullyQualifiedName`.
            # The `t` alias only exists inside the `owned` CTE; the outer query
            # can't reference it, and DuckDB raises a Binder Error the moment
            # cleaning_results exists and this branch fires.
            quality_join = """
                LEFT JOIN cleaning_results cr
                  ON cr.fqn = o.fqn
            """
            quality_select = "AVG(cr.quality_score) AS quality_avg"
        return duck.query(f"""
            WITH owned AS (
                SELECT
                    t.fullyQualifiedName AS fqn,
                    t.description,
                    CASE
                        WHEN len(t.owners) = 0 THEN NULL
                        ELSE COALESCE(
                            CAST(struct_extract(t.owners[1], 'displayName') AS VARCHAR),
                            CAST(struct_extract(t.owners[1], 'name') AS VARCHAR),
                            CAST(struct_extract(t.owners[1], 'id') AS VARCHAR)
                        )
                    END AS team,
                    CASE
                        WHEN len(t.owners) = 0 THEN NULL
                        ELSE COALESCE(
                            CAST(struct_extract(t.owners[1], 'name') AS VARCHAR),
                            CAST(struct_extract(t.owners[1], 'id') AS VARCHAR)
                        )
                    END AS team_slug,
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
                o.team_slug AS team_slug,
                COUNT(*) AS tables_owned,
                SUM(o.documented) AS documented,
                ROUND(100.0 * SUM(o.documented) / COUNT(*), 1) AS coverage_pct,
                COUNT(DISTINCT p.table_fqn) AS pii_tables,
                {quality_select}
            FROM owned o
            LEFT JOIN pii_tables p ON p.table_fqn = o.fqn
            {quality_join}
            WHERE o.team IS NOT NULL
            GROUP BY o.team, o.team_slug
            ORDER BY coverage_pct DESC, tables_owned DESC
        """)
    except Exception as e:
        # Surface the actual error so "Stewardship tab is empty" doesn't look
        # like a data-missing state when it's really a SQL / schema issue.
        logger.warning(f"ownership_breakdown query failed: {e}")
        return empty


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


def dq_impact(fqn: str, max_depth: int = 10) -> dict:
    """Compute the downstream blast radius of a table's CURRENTLY FAILING DQ tests.

    A failing DQ test on `fqn` doesn't just taint `fqn` — it taints everything
    downstream that reads from it. This joins:
      - `om_test_cases` — how many tests on `fqn` are failing right now
      - `om_lineage`     — transitive downstream tables
      - `om_columns`     — which of those carry PII.Sensitive

    Returns a dict that's safe to render directly:
      - fqn, failed_tests, failing_test_names
      - direct / transitive downstream counts
      - pii_downstream       — downstream tables with ≥1 PII.Sensitive column
      - downstream_fqns      — full list
      - risk_score           — failed_tests × (direct + 0.5·transitive + 2·pii_downstream)
        (zero when either side is zero; failures with no lineage = 0 risk,
         lineage with no failures = 0 risk — the multiplier is intentional)
    """
    empty = {
        "fqn": fqn,
        "failed_tests": 0,
        "failing_test_names": [],
        "direct": 0,
        "transitive": 0,
        "pii_downstream": 0,
        "downstream_fqns": [],
        "risk_score": 0.0,
    }
    try:
        fail_df = duck.query(
            """
            SELECT name, test_definition_name, column_name
            FROM om_test_cases
            WHERE table_fqn = ? AND status = 'Failed'
            ORDER BY name
            """,
            [fqn],
        )
    except Exception:
        return empty
    if fail_df.empty:
        return empty

    # Reuse the existing weighted lineage routine — don't duplicate the
    # recursive CTE or the PII-downstream query.
    radius = blast_radius(fqn, max_depth=max_depth)
    failed_tests = len(fail_df)
    base = (
        radius["direct"]
        + 0.5 * (radius["transitive"] - radius["direct"])
        + 2.0 * radius["pii_downstream"]
    )
    return {
        "fqn": fqn,
        "failed_tests": failed_tests,
        "failing_test_names": fail_df["name"].tolist(),
        "direct": radius["direct"],
        "transitive": radius["transitive"],
        "pii_downstream": radius["pii_downstream"],
        "downstream_fqns": radius["downstream_fqns"],
        "risk_score": round(failed_tests * base, 2),
    }


def dq_risk_ranking(limit: int = 20) -> pd.DataFrame:
    """Rank every table that has at least one failing DQ test by risk score.

    Risk score combines the number of failing tests on the table with the
    weighted downstream footprint (PII-amplified). Useful for answering
    _"where are broken data quality checks hurting the most?"_ in one query.

    Returns columns: fqn, failed_tests, direct, transitive, pii_downstream,
    risk_score — sorted desc. Empty frame if `om_test_cases` isn't loaded.
    """
    empty_cols = [
        "fqn",
        "failed_tests",
        "direct",
        "transitive",
        "pii_downstream",
        "risk_score",
    ]
    try:
        tables = duck.query(
            """
            SELECT table_fqn AS fqn, COUNT(*) AS failed_tests
            FROM om_test_cases
            WHERE status = 'Failed' AND table_fqn IS NOT NULL
            GROUP BY table_fqn
            ORDER BY fqn
            """
        )
    except Exception:
        return pd.DataFrame(columns=empty_cols)
    if tables.empty:
        return pd.DataFrame(columns=empty_cols)

    rows = []
    for _, r in tables.iterrows():
        impact = dq_impact(r["fqn"])
        rows.append(
            {
                "fqn": r["fqn"],
                "failed_tests": impact["failed_tests"],
                "direct": impact["direct"],
                "transitive": impact["transitive"],
                "pii_downstream": impact["pii_downstream"],
                "risk_score": impact["risk_score"],
            }
        )
    df = pd.DataFrame(rows).sort_values(["risk_score", "failed_tests"], ascending=[False, False])
    return df.head(limit).reset_index(drop=True)


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


def dq_failures() -> pd.DataFrame:
    """Every DQ test whose latest result is `Failed`, one row per test.

    Joined with om_tables so we can carry table description / column count
    into the explanation prompt without a second query per failure.
    """
    try:
        return duck.query("""
            SELECT
                tc.id AS test_id,
                tc.name AS test_name,
                tc.fqn AS test_fqn,
                tc.table_fqn,
                tc.column_name,
                tc.test_definition_name,
                tc.description AS test_description,
                tc.parameter_values,
                tc.status,
                tc.result_message,
                tc.result_timestamp,
                tc.failed_rows_sample,
                tc.source,
                t.description AS table_description
            FROM om_test_cases tc
            LEFT JOIN om_tables t ON t.fullyQualifiedName = tc.table_fqn
            WHERE tc.status = 'Failed'
            ORDER BY tc.result_timestamp DESC NULLS LAST, tc.table_fqn, tc.name
        """)
    except Exception:
        return pd.DataFrame(
            columns=[
                "test_id",
                "test_name",
                "test_fqn",
                "table_fqn",
                "column_name",
                "test_definition_name",
                "test_description",
                "parameter_values",
                "status",
                "result_message",
                "result_timestamp",
                "failed_rows_sample",
                "source",
                "table_description",
            ]
        )


def dq_summary() -> dict[str, int]:
    """Headline counts for the DQ failure card."""
    try:
        df = duck.query("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN status = 'Success' THEN 1 ELSE 0 END) AS passed,
                COUNT(DISTINCT table_fqn) FILTER (WHERE status = 'Failed') AS failing_tables
            FROM om_test_cases
        """)
    except Exception:
        return {"total": 0, "failed": 0, "passed": 0, "failing_tables": 0}
    if df.empty:
        return {"total": 0, "failed": 0, "passed": 0, "failing_tables": 0}
    row = df.iloc[0]

    def _int(v) -> int:
        return 0 if pd.isna(v) else int(v)

    return {
        "total": _int(row["total"]),
        "failed": _int(row["failed"]),
        "passed": _int(row["passed"]),
        "failing_tables": _int(row["failing_tables"]),
    }


def pii_propagation(max_depth: int = 10) -> dict:
    """Classify every table by PII governance status, surface propagation edges.

    "Origin" tables have at least one PII.Sensitive column directly on them.
    "Tainted" tables don't carry PII themselves but are reachable downstream
    from an origin via lineage — so a compliance officer asking *"where does
    PII reach?"* needs to know about them. Everything else is "clean".

    Returns:
      {
        'origins':            dict[fqn, list[str]],  # fqn → its PII column names
        'tainted':            list[fqn],             # fqn reachable from some origin
        'clean':              list[fqn],             # everything else
        'all_tables':         list[fqn],
        'edges':              list[(src, dst)],      # every om_lineage edge
        'propagation_edges':  list[(src, dst)],      # edges whose src is origin|tainted
      }
    Empty lists everywhere if lineage/columns aren't loaded.
    """
    empty = {
        "origins": {},
        "tainted": [],
        "clean": [],
        "all_tables": [],
        "edges": [],
        "propagation_edges": [],
    }

    try:
        tables_df = duck.query("SELECT fullyQualifiedName AS fqn FROM om_tables ORDER BY fqn")
    except Exception:
        return empty
    all_tables = tables_df["fqn"].tolist() if not tables_df.empty else []
    if not all_tables:
        return empty

    # Origins: one row per (table_fqn, column_name) that carries PII.Sensitive.
    try:
        origin_df = duck.query(
            """
            SELECT table_fqn, name AS column_name
            FROM om_columns
            WHERE list_contains(tags, 'PII.Sensitive')
              AND table_fqn IS NOT NULL
            ORDER BY table_fqn, column_name
            """
        )
    except Exception:
        origin_df = pd.DataFrame(columns=["table_fqn", "column_name"])

    origins: dict[str, list[str]] = {}
    for _, r in origin_df.iterrows():
        origins.setdefault(r["table_fqn"], []).append(r["column_name"])

    # Edges — may be empty.
    try:
        edges_df = duck.query("SELECT source_fqn, target_fqn FROM om_lineage")
    except Exception:
        edges_df = pd.DataFrame(columns=["source_fqn", "target_fqn"])
    edges: list[tuple[str, str]] = [
        (r["source_fqn"], r["target_fqn"]) for _, r in edges_df.iterrows()
    ]

    # Recursive downstream closure starting from every origin. The initial set
    # carries depth=0; any node appearing only with depth>0 is "tainted". We
    # still need origins as the starting set so the CTE is well-formed, but
    # classify them back out below.
    reachable: set[str] = set()
    if origins and edges:
        origin_list = list(origins.keys())
        placeholders = ",".join(["?"] * len(origin_list))
        try:
            reach_df = duck.query(
                f"""
                WITH RECURSIVE downstream(node, depth) AS (
                    SELECT node, 0
                    FROM (SELECT unnest([{placeholders}]) AS node) seed
                    UNION
                    SELECT l.target_fqn, d.depth + 1
                    FROM om_lineage l
                    JOIN downstream d ON l.source_fqn = d.node
                    WHERE d.depth < ?
                )
                SELECT DISTINCT node FROM downstream
                """,
                [*origin_list, int(max_depth)],
            )
            reachable = set(reach_df["node"].tolist()) if not reach_df.empty else set()
        except Exception:
            reachable = set(origins.keys())  # no lineage → only origins are "reached"

    origin_set = set(origins.keys())
    tainted_set = reachable - origin_set

    # Propagation edges: any edge whose source is in origins ∪ tainted. (Edges
    # from clean→tainted can't exist — tainted is reachable-from-origin, so
    # its predecessor set lives inside origin∪tainted too.)
    propagating = origin_set | tainted_set
    propagation_edges = [(s, t) for (s, t) in edges if s in propagating]

    clean = [fqn for fqn in all_tables if fqn not in origin_set and fqn not in tainted_set]

    return {
        "origins": origins,
        "tainted": sorted(tainted_set),
        "clean": sorted(clean),
        "all_tables": all_tables,
        "edges": edges,
        "propagation_edges": propagation_edges,
    }


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
