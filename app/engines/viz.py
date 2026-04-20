"""Interactive plotly visualizations for the catalog.

One builder per figure. Each returns a plotly.graph_objects.Figure ready
for st.plotly_chart — or None if the backing data isn't populated yet.
Keep these pure (no Streamlit imports) so they're testable in isolation.
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go

from app.clients import duck
from app.engines import analysis

# Shared Plotly palette — schemas get consistent colors across charts.
_SCHEMA_COLORS = {
    "sales": "#60a5fa",
    "marketing": "#f472b6",
    "users": "#4ade80",
    "finance": "#fbbf24",
}
_DEFAULT_COLOR = "#9ca3af"


def _schema_of(fqn: str) -> str:
    parts = fqn.split(".")
    return parts[2] if len(parts) >= 3 else "other"


def _short_of(fqn: str) -> str:
    parts = fqn.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else fqn


# ── 1. Composite score gauge ───────────────────────────────────────────────


def composite_gauge() -> go.Figure | None:
    """Big-number gauge for the headline composite score."""
    try:
        s = analysis.composite_score()
    except Exception:
        return None
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=s["composite"],
            number={"suffix": "%", "font": {"size": 48}},
            delta={"reference": 80, "increasing": {"color": "#4ade80"}},
            gauge={
                "axis": {"range": [0, 100], "tickwidth": 1},
                "bar": {"color": "#60a5fa"},
                "steps": [
                    {"range": [0, 40], "color": "#7f1d1d"},
                    {"range": [40, 70], "color": "#854d0e"},
                    {"range": [70, 100], "color": "#14532d"},
                ],
                "threshold": {
                    "line": {"color": "#f87171", "width": 3},
                    "thickness": 0.75,
                    "value": 80,
                },
            },
            title={"text": "Composite Score<br><sub>target: 80%</sub>"},
        )
    )
    fig.update_layout(height=380, margin={"t": 50, "b": 20, "l": 20, "r": 20})
    return fig


# ── 2. Lineage DAG (scatter + lines) ────────────────────────────────────────


def lineage_dag() -> go.Figure | None:
    """Force-style-ish DAG of the catalog's lineage edges."""
    try:
        tables = duck.query(
            "SELECT fullyQualifiedName AS fqn, description FROM om_tables ORDER BY fqn"
        )
        edges = duck.query("SELECT source_fqn, target_fqn FROM om_lineage")
    except Exception:
        return None
    if tables.empty or edges.empty:
        return None

    # Group nodes by schema, place them in vertical columns per schema so
    # the DAG reads left-to-right roughly by domain. Simple, deterministic,
    # avoids pulling networkx just for layout.
    schemas: dict[str, list[str]] = {}
    for _, r in tables.iterrows():
        schemas.setdefault(_schema_of(r["fqn"]), []).append(r["fqn"])

    positions: dict[str, tuple[float, float]] = {}
    schema_order = sorted(schemas.keys())
    for x_idx, schema in enumerate(schema_order):
        members = sorted(schemas[schema])
        n = len(members)
        for y_idx, fqn in enumerate(members):
            # Center each schema column vertically; spread tables by evenly
            y = (y_idx - (n - 1) / 2.0) * 1.5
            positions[fqn] = (float(x_idx) * 2.5, y)

    # Edge traces — one continuous scatter with None breaks between edges
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for _, r in edges.iterrows():
        if r["source_fqn"] in positions and r["target_fqn"] in positions:
            x0, y0 = positions[r["source_fqn"]]
            x1, y1 = positions[r["target_fqn"]]
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line={"color": "rgba(148,163,184,0.55)", "width": 1.6},
        hoverinfo="skip",
        showlegend=False,
    )

    # Node trace — color by schema, size by in+out degree, hover with description
    degrees: dict[str, int] = {}
    for _, r in edges.iterrows():
        degrees[r["source_fqn"]] = degrees.get(r["source_fqn"], 0) + 1
        degrees[r["target_fqn"]] = degrees.get(r["target_fqn"], 0) + 1

    node_x, node_y, node_text, node_colors, node_sizes, node_labels = [], [], [], [], [], []
    for _, r in tables.iterrows():
        fqn = r["fqn"]
        if fqn not in positions:
            continue
        x, y = positions[fqn]
        node_x.append(x)
        node_y.append(y)
        desc = (r["description"] or "").strip() or "<i>(no description)</i>"
        node_text.append(f"<b>{_short_of(fqn)}</b><br>{desc[:160]}")
        node_colors.append(_SCHEMA_COLORS.get(_schema_of(fqn), _DEFAULT_COLOR))
        deg = degrees.get(fqn, 0)
        node_sizes.append(18 + min(deg, 6) * 6)
        node_labels.append(_short_of(fqn).split(".")[-1])

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=node_labels,
        textposition="bottom center",
        textfont={"size": 11, "color": "rgba(226,232,240,0.9)"},
        hovertext=node_text,
        hoverinfo="text",
        marker={
            "size": node_sizes,
            "color": node_colors,
            "line": {"color": "rgba(15,23,42,0.8)", "width": 1.5},
        },
        showlegend=False,
    )

    # Schema labels at the top of each column
    annotations = [
        {
            "x": x_idx * 2.5,
            "y": max((positions[fqn][1] for fqn in schemas[schema]), default=0) + 1.2,
            "text": f"<b>{schema}</b>",
            "showarrow": False,
            "font": {"size": 13, "color": _SCHEMA_COLORS.get(schema, _DEFAULT_COLOR)},
        }
        for x_idx, schema in enumerate(schema_order)
    ]

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        height=520,
        margin={"t": 40, "b": 20, "l": 20, "r": 20},
        xaxis={"visible": False},
        yaxis={"visible": False},
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        annotations=annotations,
        title="Catalog lineage graph — nodes sized by # connections",
    )
    return fig


# ── 3. Catalog treemap (schema → table → columns) ───────────────────────────


def catalog_treemap() -> go.Figure | None:
    """Hierarchical view — tables sized by column count, colored by PII share."""
    try:
        tables = duck.query("""
            SELECT fullyQualifiedName AS fqn, length(columns) AS col_count
            FROM om_tables
            ORDER BY fqn
        """)
        cols = duck.query("""
            SELECT table_fqn, name,
                   CASE WHEN list_contains(tags, 'PII.Sensitive') THEN 'Sensitive'
                        WHEN list_contains(tags, 'PII.NonSensitive') THEN 'NonSensitive'
                        ELSE 'None' END AS pii_class
            FROM om_columns
        """)
    except Exception:
        return None
    if tables.empty:
        return None

    # Per-table PII ratio for color (higher = more sensitive columns)
    pii_by_table = (
        cols.groupby("table_fqn")
        .apply(
            lambda d: (d["pii_class"] == "Sensitive").sum() / max(len(d), 1),
            include_groups=False,
        )
        .to_dict()
    )

    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []
    hover: list[str] = []

    # Root
    ids.append("catalog")
    labels.append("Catalog")
    parents.append("")
    values.append(int(tables["col_count"].sum()))
    colors.append(0.0)
    hover.append(f"{len(tables)} tables · {int(tables['col_count'].sum())} columns")

    # Schemas
    schemas = sorted({_schema_of(f) for f in tables["fqn"]})
    for schema in schemas:
        schema_tables = tables[tables["fqn"].str.split(".").str[2] == schema]
        ids.append(f"schema::{schema}")
        labels.append(schema)
        parents.append("catalog")
        values.append(int(schema_tables["col_count"].sum()))
        colors.append(0.0)
        hover.append(f"{len(schema_tables)} tables")

    # Tables
    for _, r in tables.iterrows():
        fqn = r["fqn"]
        short_table = fqn.rsplit(".", 1)[-1]
        schema = _schema_of(fqn)
        pii_ratio = pii_by_table.get(fqn, 0.0)
        ids.append(f"table::{fqn}")
        labels.append(short_table)
        parents.append(f"schema::{schema}")
        values.append(int(r["col_count"]) or 1)
        colors.append(float(pii_ratio))
        hover.append(
            f"<b>{short_table}</b><br>"
            f"{r['col_count']} columns<br>"
            f"{pii_ratio:.0%} of columns tagged Sensitive"
        )

    fig = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels,
            parents=parents,
            values=values,
            branchvalues="total",
            marker={
                "colors": colors,
                "colorscale": [
                    [0.0, "#1e3a8a"],
                    [0.5, "#7c3aed"],
                    [1.0, "#be185d"],
                ],
                "cmin": 0,
                "cmax": 1,
                "showscale": True,
                "colorbar": {
                    "title": {"text": "% cols<br>Sensitive"},
                    "thickness": 14,
                },
            },
            hovertext=hover,
            hoverinfo="text",
            textinfo="label+value",
        )
    )
    fig.update_layout(
        height=520,
        margin={"t": 30, "b": 10, "l": 10, "r": 10},
        title="Catalog map — tiles sized by column count, colored by PII.Sensitive share",
    )
    return fig


# ── 4. Tag conflict heatmap ─────────────────────────────────────────────────


def tag_conflict_heatmap() -> go.Figure | None:
    """Columns (rows) × tables (cols) colored by tag state.

    0 = untagged, 1 = NonSensitive, 2 = Sensitive. Rows restricted to column
    names that appear in multiple tables so the heatmap surfaces actual
    conflicts rather than one-off tags.
    """
    try:
        cols = duck.query("""
            WITH multi AS (
                SELECT name FROM om_columns GROUP BY name HAVING COUNT(*) > 1
            )
            SELECT
                name,
                table_fqn,
                CASE WHEN list_contains(tags, 'PII.Sensitive') THEN 2
                     WHEN list_contains(tags, 'PII.NonSensitive') THEN 1
                     ELSE 0 END AS tag_code
            FROM om_columns
            WHERE name IN (SELECT name FROM multi)
            ORDER BY name, table_fqn
        """)
    except Exception:
        return None
    if cols.empty:
        return None

    # Pivot to a matrix: columns as rows, tables as columns
    matrix = cols.pivot_table(index="name", columns="table_fqn", values="tag_code", fill_value=-1)
    # Short labels for tables
    matrix.columns = [_short_of(c) for c in matrix.columns]
    z = matrix.values
    text = [[_tag_code_label(c) for c in row] for row in z]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=list(matrix.columns),
            y=list(matrix.index),
            text=text,
            hovertemplate="<b>%{y}</b> in <b>%{x}</b><br>Tag: %{text}<extra></extra>",
            colorscale=[
                [0.00, "#1f2937"],  # missing
                [0.33, "#374151"],  # untagged
                [0.66, "#2dd4bf"],  # non-sensitive
                [1.00, "#f43f5e"],  # sensitive
            ],
            zmin=-1,
            zmax=2,
            showscale=True,
            colorbar={
                "tickvals": [-1, 0, 1, 2],
                "ticktext": ["n/a", "untagged", "NonSens.", "Sensitive"],
                "thickness": 14,
            },
        )
    )
    fig.update_layout(
        height=max(320, 50 * len(matrix.index)),
        margin={"t": 50, "b": 60, "l": 120, "r": 20},
        title="Tag conflicts — column × table → PII tag",
        xaxis={"tickangle": -30},
    )
    return fig


def _tag_code_label(code: float) -> str:
    code = int(code) if not math.isnan(code) else -1
    return {-1: "—", 0: "untagged", 1: "NonSensitive", 2: "Sensitive"}.get(code, "—")


# ── Stewardship leaderboard (per-team dual-axis bars) ──────────────────────


def stewardship_leaderboard() -> go.Figure | None:
    """Per-team horizontal bars — tables owned + coverage %.

    Two-metric view: blue for tables-owned (absolute), green for coverage
    percent (0-100). Orphaned tables called out in the title.
    """
    df = analysis.ownership_breakdown()
    orphans_df = analysis.orphans()
    if df.empty:
        return None

    fig = go.Figure()
    fig.add_bar(
        y=df["team"],
        x=df["tables_owned"],
        name="Tables owned",
        orientation="h",
        marker={"color": "#60a5fa"},
        text=df["tables_owned"],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Tables owned: %{x}<extra></extra>",
        offsetgroup="a",
        xaxis="x",
    )
    fig.add_bar(
        y=df["team"],
        x=df["coverage_pct"],
        name="Coverage %",
        orientation="h",
        marker={"color": "#4ade80"},
        text=[f"{v}%" for v in df["coverage_pct"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Coverage: %{x}%<extra></extra>",
        offsetgroup="b",
        xaxis="x2",
    )

    orphan_note = (
        f" · {len(orphans_df)} orphan table(s) — see chat for `ownership_report`"
        if not orphans_df.empty
        else " · no orphans 🎉"
    )
    fig.update_layout(
        height=max(320, 70 * len(df) + 80),
        title=f"Stewardship leaderboard — tables owned vs coverage{orphan_note}",
        barmode="group",
        margin={"t": 60, "b": 40, "l": 140, "r": 80},
        xaxis={"title": "Tables owned", "side": "bottom"},
        xaxis2={"title": "Coverage %", "overlaying": "x", "side": "top", "range": [0, 110]},
        yaxis={"autorange": "reversed"},
        legend={"orientation": "h", "y": -0.18, "x": 0.5, "xanchor": "center"},
    )
    return fig


# ── 5. Blast radius bar chart ───────────────────────────────────────────────


def blast_radius_bars() -> go.Figure | None:
    """Top-N tables by downstream impact score — stacked bar chart."""
    df = analysis.top_blast_radius(limit=10)
    if df.empty or df["impact_score"].sum() == 0:
        return None

    # Keep only tables with any downstream impact — leaves clutter the chart
    df = df[df["impact_score"] > 0].reset_index(drop=True)
    if df.empty:
        return None

    short_labels = [_short_of(f) for f in df["fqn"]]
    # Stacked: direct, transitive-only (transitive - direct), PII downstream
    direct = df["direct"]
    transitive_only = df["transitive"] - df["direct"]
    pii = df["pii_downstream"]

    fig = go.Figure()
    fig.add_bar(
        y=short_labels,
        x=direct,
        name="Direct dependents",
        orientation="h",
        marker={"color": "#60a5fa"},
        hovertemplate="<b>%{y}</b><br>Direct: %{x}<extra></extra>",
    )
    fig.add_bar(
        y=short_labels,
        x=transitive_only,
        name="Transitive-only",
        orientation="h",
        marker={"color": "#a78bfa"},
        hovertemplate="<b>%{y}</b><br>Transitive-only: %{x}<extra></extra>",
    )
    fig.add_bar(
        y=short_labels,
        x=pii,
        name="PII downstream",
        orientation="h",
        marker={"color": "#f43f5e"},
        hovertemplate="<b>%{y}</b><br>PII downstream: %{x}<extra></extra>",
    )
    # Annotate the impact_score at the end of each stack
    annotations = [
        {
            "x": row["direct"] + (row["transitive"] - row["direct"]) + row["pii_downstream"] + 0.25,
            "y": short_labels[i],
            "text": f"<b>{row['impact_score']}</b>",
            "showarrow": False,
            "font": {"size": 11, "color": "#fbbf24"},
            "xanchor": "left",
        }
        for i, (_, row) in enumerate(df.iterrows())
    ]
    fig.update_layout(
        height=max(340, 40 * len(df) + 80),
        barmode="stack",
        margin={"t": 60, "b": 40, "l": 140, "r": 60},
        title="Blast radius — top tables by downstream impact (stack = counts, label = weighted score)",
        xaxis={"title": "Downstream count (stacked)"},
        yaxis={"autorange": "reversed"},
        legend={"orientation": "h", "y": -0.15, "x": 0.5, "xanchor": "center"},
        annotations=annotations,
    )
    return fig


# ── 6. Description quality histogram ────────────────────────────────────────


def quality_by_table() -> go.Figure | None:
    """Per-table description quality breakdown with LLM rationale on hover.

    Shows one bar per analyzed table (sorted worst → best) so users can see
    exactly which descriptions are dragging the mean score down, not just
    the overall distribution.
    """
    try:
        df = duck.query("""
            SELECT fqn, quality_score, quality_rationale
            FROM cleaning_results
            WHERE quality_score IS NOT NULL AND quality_score > 0
            ORDER BY quality_score ASC, fqn
        """)
    except Exception:
        return None
    if df.empty:
        return None

    bucket_colors = {1: "#ef4444", 2: "#f97316", 3: "#eab308", 4: "#84cc16", 5: "#22c55e"}
    colors = [bucket_colors.get(int(s), _DEFAULT_COLOR) for s in df["quality_score"]]
    short_labels = [_short_of(f) for f in df["fqn"]]

    def _fmt_rationale(r: str) -> str:
        r = (r or "").strip() or "<i>(no rationale recorded)</i>"
        return r if len(r) <= 220 else r[:217] + "…"

    hover = [
        f"<b>{sl}</b><br>Score: {int(s)}/5<br><br>{_fmt_rationale(r)}"
        for sl, s, r in zip(short_labels, df["quality_score"], df["quality_rationale"], strict=True)
    ]

    fig = go.Figure(
        go.Bar(
            y=short_labels,
            x=df["quality_score"],
            orientation="h",
            marker={"color": colors},
            text=[f"{int(s)}/5" for s in df["quality_score"]],
            textposition="outside",
            hovertext=hover,
            hoverinfo="text",
        )
    )
    total = int(df["quality_score"].sum())
    max_points = len(df) * 5
    mean_score = float(df["quality_score"].mean())
    fig.update_layout(
        height=max(320, 40 * len(df) + 100),
        margin={"t": 70, "b": 40, "l": 180, "r": 80},
        title=(
            f"Description quality — {total}/{max_points} points · "
            f"mean {mean_score:.2f}/5 · hover for LLM rationale"
        ),
        xaxis={
            "title": "Quality score (1 = useless, 5 = excellent)",
            "range": [0, 5.5],
            "dtick": 1,
        },
        yaxis={"autorange": "reversed"},
        showlegend=False,
    )
    return fig


# ── 7. DQ failure explanations ──────────────────────────────────────────────


def dq_failure_table() -> go.Figure | None:
    """Failing DQ tests joined with their LLM-written plain-English explanations.

    Rendered as a plotly Table so stewards can scan failures alongside the
    summary / likely cause / next-step guidance without clicking into each
    row. Missing explanation rows (user hasn't run the Explain DQ scan yet)
    render as "—" placeholders so the failure list still shows up.
    """
    try:
        df = duck.query("""
            SELECT
                COALESCE(f.test_name, '') AS test_name,
                COALESCE(f.table_fqn, '') AS table_fqn,
                COALESCE(f.column_name, '') AS column_name,
                COALESCE(f.test_definition_name, '') AS test_definition,
                COALESCE(f.result_message, '') AS result_message,
                COALESCE(e.summary, '') AS summary,
                COALESCE(e.likely_cause, '') AS likely_cause,
                COALESCE(e.next_step, '') AS next_step
            FROM om_test_cases f
            LEFT JOIN dq_explanations e ON e.test_id = f.id
            WHERE f.status = 'Failed'
            ORDER BY f.table_fqn, f.name
        """)
    except Exception:
        # dq_explanations may not exist yet — fall back to failures-only.
        try:
            df = duck.query("""
                SELECT
                    COALESCE(test_name, '') AS test_name,
                    COALESCE(table_fqn, '') AS table_fqn,
                    COALESCE(column_name, '') AS column_name,
                    COALESCE(test_definition_name, '') AS test_definition,
                    COALESCE(result_message, '') AS result_message,
                    '' AS summary,
                    '' AS likely_cause,
                    '' AS next_step
                FROM om_test_cases
                WHERE status = 'Failed'
                ORDER BY table_fqn, name
            """)
        except Exception:
            return None
    if df.empty:
        return None

    def _short(f: str) -> str:
        return ".".join(f.split(".")[-2:]) if f else ""

    def _dash(v: str) -> str:
        return v.strip() if v and v.strip() else "—"

    fig = go.Figure(
        go.Table(
            columnwidth=[80, 110, 70, 110, 180, 180, 180, 180],
            header={
                "values": [
                    "<b>Test</b>",
                    "<b>Table</b>",
                    "<b>Column</b>",
                    "<b>Definition</b>",
                    "<b>Failure message</b>",
                    "<b>Summary</b>",
                    "<b>Likely cause</b>",
                    "<b>Next step</b>",
                ],
                "fill_color": "#111827",
                "font": {"color": "#f9fafb", "size": 12},
                "align": "left",
                "height": 30,
            },
            cells={
                "values": [
                    df["test_name"],
                    [_short(f) for f in df["table_fqn"]],
                    [_dash(c) for c in df["column_name"]],
                    df["test_definition"],
                    df["result_message"],
                    [_dash(s) for s in df["summary"]],
                    [_dash(c) for c in df["likely_cause"]],
                    [_dash(n) for n in df["next_step"]],
                ],
                "fill_color": [["#1f2937" if i % 2 else "#111827" for i in range(len(df))]],
                "font": {"color": "#e5e7eb", "size": 11},
                "align": "left",
                "height": 64,
            },
        )
    )
    explained = int((df["summary"].str.strip() != "").sum())
    fig.update_layout(
        height=max(240, 80 * len(df) + 120),
        margin={"t": 60, "b": 20, "l": 10, "r": 10},
        title=(
            f"Failing DQ checks — {len(df)} total · {explained} explained "
            f"(click 🧪 Explain DQ in the sidebar to fill in the rest)"
        ),
    )
    return fig


# ── 8. DQ recommendation gaps ───────────────────────────────────────────────


def dq_recommendations_table() -> go.Figure | None:
    """Recommended DQ tests that don't exist yet, grouped by severity.

    Reads from the `dq_recommendations` cache populated by the "Recommend DQ
    tests" sidebar button. Shows table, column, test definition, severity,
    and rationale in a sortable plotly Table.
    """
    try:
        df = duck.query("""
            SELECT
                table_fqn,
                COALESCE(column_name, '(table-level)') AS column_name,
                test_definition,
                COALESCE(parameters, '[]') AS parameters,
                COALESCE(severity, 'recommended') AS severity,
                COALESCE(rationale, '') AS rationale
            FROM dq_recommendations
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'recommended' THEN 1
                    ELSE 2
                END,
                table_fqn,
                column_name
        """)
    except Exception:
        return None
    if df.empty:
        return None

    def _short(f: str) -> str:
        return ".".join(f.split(".")[-2:]) if f else ""

    severity_color = {
        "critical": "#7f1d1d",
        "recommended": "#854d0e",
        "nice-to-have": "#14532d",
    }
    row_fill = [severity_color.get(s, "#1f2937") for s in df["severity"]]

    severity_label = {
        "critical": "🚨 Critical",
        "recommended": "💡 Recommended",
        "nice-to-have": "✨ Nice-to-have",
    }

    fig = go.Figure(
        go.Table(
            columnwidth=[110, 90, 130, 100, 100, 220],
            header={
                "values": [
                    "<b>Table</b>",
                    "<b>Column</b>",
                    "<b>Test definition</b>",
                    "<b>Parameters</b>",
                    "<b>Severity</b>",
                    "<b>Rationale</b>",
                ],
                "fill_color": "#111827",
                "font": {"color": "#f9fafb", "size": 12},
                "align": "left",
                "height": 30,
            },
            cells={
                "values": [
                    [_short(f) for f in df["table_fqn"]],
                    df["column_name"],
                    df["test_definition"],
                    df["parameters"],
                    [severity_label.get(s, s) for s in df["severity"]],
                    df["rationale"],
                ],
                "fill_color": [row_fill],
                "font": {"color": "#f9fafb", "size": 11},
                "align": "left",
                "height": 56,
            },
        )
    )
    counts = df["severity"].value_counts().to_dict()
    fig.update_layout(
        height=max(260, 64 * len(df) + 120),
        margin={"t": 60, "b": 20, "l": 10, "r": 10},
        title=(
            f"DQ recommendation gaps — {len(df)} total · "
            f"{counts.get('critical', 0)} critical · "
            f"{counts.get('recommended', 0)} recommended · "
            f"{counts.get('nice-to-have', 0)} nice-to-have"
        ),
    )
    return fig


# ── 9. DQ × lineage risk ranking ────────────────────────────────────────────


def dq_risk_bars() -> go.Figure | None:
    """Horizontal bars ranking tables by DQ risk (failures × downstream weight).

    The risk score is zero when either side is zero — tables here all have
    at least one failing DQ test AND at least one downstream dependent.
    Bar color darkens with PII-downstream count so sensitive blast radii
    jump out visually.
    """
    try:
        df = analysis.dq_risk_ranking(limit=15)
    except Exception:
        return None
    if df.empty:
        return None

    short_labels = [_short_of(f) for f in df["fqn"]]

    # PII-aware color ramp: more downstream PII → more saturated red.
    max_pii = max(int(df["pii_downstream"].max() or 1), 1)

    def _color(pii: int) -> str:
        # Blend from amber (#f59e0b) → red (#dc2626) as pii_downstream grows.
        t = min(pii / max_pii, 1.0)
        r = int(245 + (220 - 245) * t)
        g = int(158 + (38 - 158) * t)
        b = int(11 + (38 - 11) * t)
        return f"rgb({r},{g},{b})"

    colors = [_color(int(v)) for v in df["pii_downstream"]]

    hover = [
        (
            f"<b>{sl}</b><br>"
            f"Failing tests: {int(ft)}<br>"
            f"Direct dependents: {int(d)}<br>"
            f"Transitive downstream: {int(t)}<br>"
            f"Downstream with PII: {int(p)}<br>"
            f"Risk score: {s}"
        )
        for sl, ft, d, t, p, s in zip(
            short_labels,
            df["failed_tests"],
            df["direct"],
            df["transitive"],
            df["pii_downstream"],
            df["risk_score"],
            strict=True,
        )
    ]

    fig = go.Figure(
        go.Bar(
            y=short_labels,
            x=df["risk_score"],
            orientation="h",
            marker={"color": colors},
            text=[
                f"{s} · {int(ft)}× failing, {int(t)} downstream, {int(p)} PII"
                for s, ft, t, p in zip(
                    df["risk_score"],
                    df["failed_tests"],
                    df["transitive"],
                    df["pii_downstream"],
                    strict=True,
                )
            ],
            textposition="outside",
            hovertext=hover,
            hoverinfo="text",
        )
    )
    fig.update_layout(
        height=max(320, 34 * len(df) + 120),
        margin={"t": 70, "b": 40, "l": 180, "r": 120},
        title=(
            "DQ risk — tables ranked by failures × downstream impact "
            f"({len(df)} at-risk table(s) · color intensifies with PII-downstream count)"
        ),
        xaxis={"title": "Risk score (failed_tests × (direct + 0.5·transitive + 2·pii_downstream))"},
        yaxis={"autorange": "reversed"},
        showlegend=False,
    )
    return fig


# ── Registry (kept flat so main.py can just iterate) ────────────────────────

ALL_VIZ: list[tuple[str, str, callable]] = [
    ("🎯 Score gauge", "composite score as a speedometer", composite_gauge),
    ("🔗 Lineage", "catalog dependency graph", lineage_dag),
    ("💥 Blast radius", "top tables ranked by downstream impact", blast_radius_bars),
    ("👥 Stewardship", "per-team scorecard + orphan count", stewardship_leaderboard),
    ("🗺️ Catalog map", "treemap by schema / table / PII share", catalog_treemap),
    ("🔥 Tag conflicts", "column × table → tag heatmap", tag_conflict_heatmap),
    ("📈 Quality", "per-table description scores with LLM rationale on hover", quality_by_table),
    (
        "🧪 DQ failures",
        "failed data quality checks with LLM-written plain-English explanations",
        dq_failure_table,
    ),
    (
        "💡 DQ gaps",
        "recommended data quality tests that should exist but currently don't",
        dq_recommendations_table,
    ),
    (
        "🎯 DQ risk",
        "failing DQ tests ranked by downstream blast radius (PII-weighted)",
        dq_risk_bars,
    ),
]


def has_any_data() -> bool:
    """Cheap check used by main.py to gate the sidebar button."""
    try:
        return bool(duck.query("SELECT 1 FROM om_tables LIMIT 1").size)
    except Exception:
        return False


# Silence pandas FutureWarning on groupby.apply in a forward-compatible way
_ = pd  # kept for typing / future helpers
