"""LangChain tools exposing MetaSift engines + DuckDB to the agent.

These wrappers turn MetaSift's analysis, cleaning, and stewardship functions into
tools the agent can call. Each @tool docstring is the signal the LLM uses to
decide when to invoke it — keep them descriptive.

Tools read from DuckDB (`om_tables`, `om_columns`) populated by
`app.clients.duck.refresh_all()`. If DuckDB is empty, tools return a friendly
hint telling the user to click "Refresh metadata".
"""

from __future__ import annotations

import pandas as pd
from langchain_core.tools import tool
from loguru import logger

from app.clients import duck
from app.engines import analysis, cleaning, stewardship

_EMPTY_HINT = (
    "No metadata loaded yet. Ask the user to click the "
    "'🔄 Refresh metadata' button in the sidebar first."
)


def _has_data() -> bool:
    try:
        return bool(duck.query("SELECT COUNT(*) AS n FROM om_tables")["n"].iloc[0])
    except Exception:
        return False


def _as_list(value) -> list:
    """Coerce a DuckDB/pandas cell to a plain list.

    List-typed columns come back as numpy arrays, and `arr or []` raises
    a truth-value-ambiguous error. This handles None, arrays, and lists.
    """
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value) if value else []


def _as_str(value, default: str = "") -> str:
    """Coerce a DuckDB/pandas cell to a string, treating NaN/None as empty.

    Needed because `nan or ""` returns nan (NaN is truthy in Python).
    """
    if value is None or pd.isna(value):
        return default
    return str(value)


# ── Discovery tools ────────────────────────────────────────────────────────────


@tool
def list_schemas() -> str:
    """List all databases and schemas in the catalog with table counts.

    Use this when the user asks what's in their catalog, what schemas exist,
    or wants an overview. Returns a markdown table.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = duck.query("""
        SELECT
            split_part(fullyQualifiedName, '.', 2) AS database,
            split_part(fullyQualifiedName, '.', 3) AS schema,
            COUNT(*) AS tables
        FROM om_tables
        GROUP BY database, schema
        ORDER BY database, schema
    """)
    if df.empty:
        return "No schemas found."
    return df.to_markdown(index=False)


@tool
def list_tables(schema_name: str = "") -> str:
    """List tables in the catalog, optionally filtered by schema name.

    Pass an empty string for `schema_name` to list every table. Returns a
    markdown table with fully qualified name, description length, and column count.
    """
    if not _has_data():
        return _EMPTY_HINT
    pattern = f"%.{schema_name}.%" if schema_name else "%"
    df = duck.query(
        """
        SELECT
            fullyQualifiedName AS fqn,
            COALESCE(length(description), 0) AS desc_length,
            length(columns) AS column_count
        FROM om_tables
        WHERE fullyQualifiedName LIKE ?
        ORDER BY fqn
        LIMIT 50
        """,
        [pattern],
    )
    if df.empty:
        return f"No tables found{' in schema ' + schema_name if schema_name else ''}."
    return df.to_markdown(index=False)


# ── Analysis tools ─────────────────────────────────────────────────────────────


@tool
def documentation_coverage() -> str:
    """Compute documentation coverage (percent of tables with descriptions) per schema.

    Use when the user asks about documentation, coverage, which schemas are
    under-documented, or the overall state of docs. Returns a markdown table
    sorted from worst to best coverage.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = analysis.documentation_coverage()
    if df.empty:
        return "No tables found."
    return df.to_markdown(index=False)


@tool
def find_tag_conflicts() -> str:
    """Find columns with the same name tagged differently across tables.

    A tag conflict is when (e.g.) `email` is tagged `PII.Sensitive` in one table
    but untagged in another, or tagged differently. Use when the user asks
    about consistency, conflicts, or tag hygiene.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = analysis.tag_conflicts()
    if df.empty:
        return "No tag conflicts detected — tagging is consistent."
    return df.to_markdown(index=False)


@tool
def composite_score() -> str:
    """Compute MetaSift's composite metadata quality score (0-100).

    Weighted combination of coverage (30%), accuracy (30%), consistency (20%),
    and description quality (20%). Use when the user asks for the headline
    number, the overall score, or the health of their catalog.
    """
    if not _has_data():
        return _EMPTY_HINT
    s = analysis.composite_score()
    return (
        f"**Composite score: {s['composite']}%**\n\n"
        f"- Documentation coverage: {s['coverage']}%\n"
        f"- Accuracy (non-stale): {s['accuracy']}% *(needs cleaning engine run)*\n"
        f"- Consistency (conflict-free): {s['consistency']}% *(needs conflict scan)*\n"
        f"- Description quality: {s['quality']}% *(needs scoring run)*\n"
    )


# ── Cleaning tools ─────────────────────────────────────────────────────────────


@tool
def find_naming_inconsistencies(similarity_threshold: int = 75) -> str:
    """Find clusters of similar column names that likely mean the same thing.

    Uses fuzzy Levenshtein matching to detect naming drift like `customer_id`
    vs `cust_id` vs `cid`. Higher threshold = stricter matches (default 75).
    Use when the user asks about naming, consistency, or standardization.
    """
    if not _has_data():
        return _EMPTY_HINT
    clusters = cleaning.detect_naming_clusters(similarity_threshold)
    if not clusters:
        return "No naming inconsistencies detected above the similarity threshold."
    lines = [f"Found **{len(clusters)}** naming variant clusters:"]
    for c in clusters[:10]:
        lines.append(f"- **{c['canonical']}** ↔ {', '.join(c['variants'][1:])}")
    return "\n".join(lines)


@tool
def check_description_staleness(fqn: str) -> str:
    """Compare a table's stored description against its actual columns using an LLM.

    Pass the EXACT fully-qualified name from the catalog (4 dot-separated parts:
    service.database.schema.table). If you don't know the real FQN, call
    `list_tables` first — do NOT guess or construct one from context.
    Returns whether the description is stale, why, and a corrected draft.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = duck.query(
        "SELECT description, columns FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn],
    )
    if df.empty:
        return f"Table `{fqn}` not found. Try `list_tables` first."
    current_desc = _as_str(df["description"].iloc[0])
    columns = _as_list(df["columns"].iloc[0])
    report = cleaning.detect_stale(fqn, current_desc, columns)
    verdict = "🔴 STALE" if report.stale else "🟢 OK"
    return (
        f"**{verdict}** — confidence {report.confidence:.0%}\n\n"
        f"- **Current:** {report.old or '_(empty)_'}\n"
        f"- **Reason:** {report.reason}\n"
        f"- **Suggested correction:** {report.corrected or '_(no change needed)_'}"
    )


@tool
def score_descriptions(limit: int = 10) -> str:
    """Score the quality of table descriptions (1-5) for the first N tables with descriptions.

    1 = useless ('data table'), 5 = excellent (specific, complete, accurate).
    Use when the user asks about description quality, or which docs are weak.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = duck.query(f"""
        SELECT fullyQualifiedName AS fqn, description, columns
        FROM om_tables
        WHERE description IS NOT NULL AND length(description) > 0
        LIMIT {max(1, min(limit, 25))}
    """)
    if df.empty:
        return "No tables with descriptions found."
    items = [
        {
            "fqn": row["fqn"],
            "description": row["description"],
            "columns": [c.get("name") for c in _as_list(row["columns"])],
        }
        for _, row in df.iterrows()
    ]
    results = cleaning.score_descriptions_batch(items)
    if not results:
        return "Scoring failed — LLM returned unparseable output."
    lines = ["| Table | Score | Rationale |", "|---|---|---|"]
    for r in results:
        lines.append(f"| `{r['fqn']}` | {r['score']}/5 | {r['rationale']} |")
    return "\n".join(lines)


# ── About MetaSift (project guide) ─────────────────────────────────────────────

_ABOUT_TOPICS = {
    "overview": """**MetaSift** is an AI-powered metadata analyst and steward for OpenMetadata.

The core thesis: _documentation coverage is a lie._ A catalog can be 100%
documented and still full of **wrong, stale, and conflicting** metadata.
MetaSift introduces a composite score that measures what actually matters.

It sits on top of an OpenMetadata deployment, pulls catalog metadata via REST,
analyzes it with four specialized engines, and writes improvements back.""",
    "composite_score": """**Composite Score** — MetaSift's headline metric (0-100).

Weighted combination of four sub-metrics:

| Component | Weight | What it measures |
|---|---|---|
| Documentation coverage | **30%** | % of tables with descriptions |
| Description accuracy | **30%** | % of descriptions that aren't stale (per cleaning engine) |
| Classification consistency | **20%** | % of columns without tag conflicts |
| Description quality | **20%** | Mean 1-5 quality score normalized to 0-100 |

Why this weighting: coverage is necessary but not sufficient. A catalog can be
100% covered and still worthless if descriptions are wrong or tags conflict.
Accuracy and coverage get equal weight because wrong docs hurt as much as missing docs.""",
    "engines": """**The four engines:**

1. **Analysis** (`app/engines/analysis.py`) — Pulls metadata into DuckDB and
   runs aggregate SQL analytics (coverage, tag conflicts, composite score).
   No LLM needed.

2. **Stewardship** (`app/engines/stewardship.py`) — Auto-documents undocumented
   tables, detects/classifies PII, writes improvements back via REST PATCH.
   Uses Llama 3.3 70B.

3. **Cleaning** (`app/engines/cleaning.py`) — The differentiator. Detects
   stale descriptions (LLM compares description against actual columns),
   finds tag conflicts across schemas, scores description quality 1-5,
   surfaces naming inconsistencies via fuzzy matching, and turns raw DQ
   test failures into plain-English explanations with root-cause guesses
   and next-step recommendations.

4. **Interface** (`app/engines/agent.py`) — That's me, Stew. LangChain agent
   wired to 11 tools over the other engines. Chat in natural language.""",
    "architecture": """**Stack:**

- **OpenMetadata 1.9.4** — Docker Compose stack (MySQL + Elasticsearch + server)
- **DuckDB** — in-process SQL on metadata (loaded via REST pagination)
- **LangChain 1.x** — agent orchestration (new `create_agent` / LangGraph)
- **OpenRouter (Llama 3.3 70B)** — the LLM
- **Streamlit + Plotly** — dashboard + chat UI

**Data flow:**

OpenMetadata REST → DuckDB (in-memory) → engines → agent tools → chat reply.
Write-backs go agent tool → REST PATCH → OpenMetadata.

**Integration depth:** REST API for reads, JSON-Merge-Patch for writes,
openmetadata-ingestion SDK for entity work. MCP endpoint is available but
MetaSift uses local tools that expose its own engines directly.""",
    "differentiators": """**What MetaSift adds over plain OpenMetadata:**

- **Stale description detection** — LLM compares stored description against
  actual columns. OpenMetadata can't do this natively.
- **Tag conflict detection** — finds when `email` is tagged `PII.Sensitive`
  in one table but untagged in another across schemas.
- **Description quality scoring** — rates each description 1-5 on specificity,
  accuracy, completeness. "Sales data" scores a 1; "Daily refund events with
  per-order breakdown and reason codes" scores a 5.
- **Fuzzy naming clusters** — surfaces inconsistencies like `customer_id` vs
  `cust_id` vs `cid` using Levenshtein matching.
- **Composite quality score** — weighted metric that penalizes *wrong* docs
  as heavily as *missing* docs. OpenMetadata only reports coverage.
- **Active stewardship** — auto-generates descriptions and writes them back,
  not just passive analysis.""",
    "setup": """**Setup steps** (~5 min):

```bash
make install      # create venv + install deps
make stack-up     # start OpenMetadata Docker stack (~2 min first boot)
# → open http://localhost:8585, log in admin/admin
# → Settings → Bots → ingestion-bot → Generate new token
# → paste into .env as OPENMETADATA_JWT_TOKEN and AI_SDK_TOKEN
make seed         # populate demo catalog with sample metadata
make run          # launch Streamlit app at http://localhost:8501
```

Also needed in `.env`: an OpenRouter API key (free at openrouter.ai/keys).""",
    "tech_stack": """**Tech stack:**

- Python 3.11 on WSL Ubuntu 24.04
- uv for package management
- OpenMetadata 1.9.4
- openmetadata-ingestion SDK
- LangChain 1.x (unified `create_agent`)
- OpenRouter (default: `meta-llama/llama-3.3-70b-instruct`)
- DuckDB for in-process analytical SQL
- Streamlit (dashboard + chat UI)
- Plotly for charts
- thefuzz for Levenshtein matching
- Docker Compose for the OpenMetadata stack""",
    "capabilities": """**Here's what I can actually do for you:**

**Discovery**
- See what databases and schemas exist in your catalog
- List tables, optionally filtered to a specific schema

**Quality analysis**
- Measure documentation coverage per schema
- Spot columns tagged inconsistently across tables (tag conflicts)
- Compute the composite score (0-100)
- Surface naming drift (`customer_id` vs `cust_id` vs `cid`)

**Description cleaning**
- Check whether a specific description is still accurate vs its columns
- Rate description quality on a 1-5 scale

**Active stewardship** _(writes to OpenMetadata)_
- Draft a new description for an undocumented table
- Auto-document an entire schema in one pass — drafts go to the review queue
- Apply an approved description back to the catalog

**Impact analysis**
- Compute blast radius for a table (direct + transitive downstream, weighted by PII)
- Rank the whole catalog by downstream impact

**Data quality explanations**
- List every failing DQ check and turn each into plain English: what it checks,
  what the likely root cause is, and the single next step to take
- Explain every failure on a specific table on demand

**Data quality recommendations**
- Propose DQ tests that should exist on a specific table but don't (skips duplicates)
- Summarize catalog-wide DQ gaps by severity: critical / recommended / nice-to-have

**Data quality × lineage risk**
- Compute the downstream blast radius of failing DQ tests on one table
- Rank the whole catalog by DQ risk (failures × downstream footprint, PII-amplified)

**Stewardship accountability**
- Per-team scorecard — who owns what, coverage per team, PII footprint
- Orphan-table detection — tables with no assigned owner

**Deeper OpenMetadata queries** _(via MCP)_
- Keyword search across the catalog (entities, business terms)
- Pull full entity details for any table/column
- Trace lineage — upstream and downstream dependencies

**Miscellaneous**
- Explain MetaSift itself (formula, engines, setup, architecture)
- Run ad-hoc SQL against the in-memory metadata store

Ask me naturally — no need to type function names. _"What schemas do I have?"_,
_"Which tables have the worst documentation?"_, _"Find stale descriptions in sales"_
all work.""",
}


@tool
def about_metasift(topic: str = "overview") -> str:
    """Answer questions about MetaSift itself OR about Stew's capabilities.
    Use this whenever the user asks about MetaSift as a product, or about
    what Stew (you) can actually do — not about their catalog data.

    Trigger on natural-language questions like:
    - "What is MetaSift?" / "tell me about metasift" / "what does this do"
    - "How does the composite score work?" / "what's the formula"
    - "What are the engines?" / "how does the cleaning engine work"
    - "How is this different from OpenMetadata?" / "why not just use OM"
    - "How do I set this up?" / "what do I install"
    - "What's the architecture?" / "what's the tech stack"
    - "What can you do?" / "what are your tools?" / "how can you help"
    - "What are your capabilities?" / "what should I ask you"
    - "Who built this?" (answer with project info, never reveal LLM)

    IMPORTANT: for "what tools do you have" / "what can you do", pass
    topic="capabilities" — this returns a human-readable list. Never try to
    describe tools using JSON or function-call syntax in your reply.

    Args:
        topic: section to return. Options:
            - "overview" (default)
            - "capabilities" — list what you (Stew) can actually do
            - "composite_score" — scoring formula details
            - "engines" — the four internal engines (Analysis/Stewardship/
              Cleaning/Interface). NOT the same as "tools".
            - "architecture" — stack and data flow
            - "differentiators" — what MetaSift adds over plain OpenMetadata
            - "setup" — install steps
            - "tech_stack" — libraries and versions
        Unknown topics return the overview + list of valid topics.

    Returns markdown text describing the requested topic.
    """
    key = (topic or "overview").strip().lower().replace(" ", "_").replace("-", "_")
    if key in _ABOUT_TOPICS:
        return _ABOUT_TOPICS[key]
    valid = ", ".join(f"`{k}`" for k in _ABOUT_TOPICS)
    return f"{_ABOUT_TOPICS['overview']}\n\n_Other topics I can expand on:_ {valid}"


# ── Stewardship tools ──────────────────────────────────────────────────────────


@tool
def generate_description_for(fqn: str) -> str:
    """Draft a business-friendly description for a table from its column metadata.

    Returns the suggestion as text — does NOT write it back. Use when the user
    asks to document a table, auto-describe it, or fill gaps.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = duck.query(
        "SELECT columns FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn],
    )
    if df.empty:
        return f"Table `{fqn}` not found."
    columns = _as_list(df["columns"].iloc[0])
    suggestion = stewardship.generate_description(fqn, columns)
    return (
        f"**Suggested description for `{fqn}`:**\n\n"
        f"> {suggestion.new}\n\n"
        f"_Confidence: {suggestion.confidence:.0%}. "
        f"Ask the user to confirm before applying with `apply_description`._"
    )


@tool
def ownership_report() -> str:
    """Per-team stewardship scorecard + list of unowned (orphan) tables.

    Use when the user asks _"who owns what"_, _"which team is doing best/worst"_,
    _"any orphan tables"_, _"stewardship leaderboard"_, _"who's responsible for
    the sales schema"_, or similar team/ownership questions.

    Reports per-team: tables owned, documentation coverage, PII-table count,
    average quality (if deep scan has run). Separately lists tables with
    no owner — those are accountability gaps worth flagging.
    """
    if not _has_data():
        return _EMPTY_HINT
    breakdown = analysis.ownership_breakdown()
    orphan_df = analysis.orphans()

    lines: list[str] = ["**Stewardship scorecard**", ""]
    if breakdown.empty:
        lines.append("_No owned tables yet — every catalog entity is orphaned._")
    else:
        lines.append("| Team | Tables | Coverage | PII tables | Quality |")
        lines.append("|---|---|---|---|---|")
        for _, r in breakdown.iterrows():
            q = r["quality_avg"]
            q_text = f"{float(q):.1f}/5" if pd.notna(q) else "_—_"
            lines.append(
                f"| **{r['team']}** | {r['tables_owned']} | "
                f"{r['coverage_pct']}% | {r['pii_tables']} | {q_text} |"
            )
        lines.append("")

    if orphan_df.empty:
        lines.append("✔ **No orphan tables** — every table has an owner.")
    else:
        lines.append(f"⚠️ **{len(orphan_df)} orphan table(s)** — no team is accountable:")
        lines.append("")
        for _, r in orphan_df.iterrows():
            short = ".".join(r["fqn"].split(".")[-2:])
            doc_marker = "📝" if r["documented"] else "❌"
            lines.append(f"- {doc_marker} `{short}`")

    return "\n".join(lines)


_SEVERITY_EMOJI = {"critical": "🚨", "recommended": "💡", "nice-to-have": "✨"}


# Fix-type chips for DQ failure explanations — mirror viz.dq_failure_table's
# `_FIX_CHIP` table. Defined here so tool markdown output stays in sync with
# the dashboard's visual labels.
_FIX_TYPE_CHIPS = {
    "schema_change": "`🔷 schema change`",
    "etl_investigation": "`🔍 ETL investigation`",
    "data_correction": "`⚠️ data correction`",
    "upstream_fix": "`🔄 upstream fix`",
    "other": "`🛠 other`",
}


def _fix_type_chip(fix_type: str) -> str:
    """Return the markdown chip for a fix_type, or empty string if unknown."""
    return _FIX_TYPE_CHIPS.get((fix_type or "").strip().lower(), "")


def _render_dq_recommendation(r, *, include_table: bool = False) -> list[str]:
    """Shared formatter for both on-demand and cached DQ recommendations."""
    emoji = _SEVERITY_EMOJI.get(str(r.get("severity") or "").lower(), "💡")
    column = r.get("column_name") or "(table-level)"
    heading = f"{emoji} **{r.get('test_definition')}** on `{column}`"
    if include_table:
        short = ".".join((r.get("table_fqn") or "").split(".")[-2:])
        heading += f" _(table `{short}`)_"
    lines = [heading]
    # Parameters may be a JSON string (from the cache) or a list (from on-demand).
    raw_params = r.get("parameters")
    if isinstance(raw_params, str):
        try:
            import json as _json

            raw_params = _json.loads(raw_params)
        except Exception:
            raw_params = []
    if raw_params:
        param_text = ", ".join(f"{p.get('name')}=`{p.get('value')}`" for p in raw_params)
        lines.append(f"- **Parameters:** {param_text}")
    if r.get("rationale"):
        lines.append(f"- **Why:** {r['rationale']}")
    return lines


@tool
def recommend_dq_tests(fqn: str) -> str:
    """Propose data quality checks that SHOULD exist on a table but currently don't.

    ★ Use this for any "what DQ tests should I add?", "recommend data quality
      checks for X", "what's missing from the DQ coverage on this table?",
      or "suggest tests for <table>" question. ★

    Reads the table's columns, types, tags, and already-configured tests, then
    emits a ranked list of recommended tests with parameters and a plain-English
    rationale. Skips anything already configured. Pass the FULL 4-part FQN
    (service.database.schema.table) — silently call `list_tables` first if the
    user gave a short name.

    Output is markdown: each recommendation shows the test definition, the
    target column (or `(table-level)`), parameters, severity, and rationale.
    """
    if not _has_data():
        return _EMPTY_HINT
    if not fqn or not fqn.strip():
        return "Tell me which table to scan. Use `list_tables` if you need the FQN."

    # Validate the FQN up front so we don't waste an LLM call on a wrong name.
    check = duck.query(
        "SELECT 1 FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn.strip()],
    )
    if check.empty:
        return (
            f"Table `{fqn}` doesn't exist in the catalog. "
            f"Use `list_tables` to find the real 4-part FQN."
        )

    recs = stewardship.recommend_dq_tests(fqn.strip())
    if not recs:
        return (
            f"No new DQ tests recommended for `{fqn}` — either the existing "
            f"coverage is already solid or the columns don't warrant additional "
            f"checks right now."
        )

    # Sort: critical first, then recommended, then nice-to-have
    order = {"critical": 0, "recommended": 1, "nice-to-have": 2}
    recs.sort(key=lambda r: order.get(r.severity.lower(), 3))

    lines: list[str] = [f"**{len(recs)} recommended DQ test(s) for `{fqn}`**", ""]
    for r in recs:
        lines.extend(
            _render_dq_recommendation(
                {
                    "table_fqn": r.table_fqn,
                    "column_name": r.column_name,
                    "test_definition": r.test_definition,
                    "parameters": r.parameters,
                    "rationale": r.rationale,
                    "severity": r.severity,
                }
            )
        )
        lines.append("")
    return "\n".join(lines)


@tool
def find_dq_gaps(severity: str = "") -> str:
    """Catalog-wide summary of recommended DQ tests from the cached scan.

    Use when the user asks _"what DQ tests are missing across the catalog?"_,
    _"show me the DQ gaps"_, _"which tables need more tests?"_, or similar
    catalog-wide questions. This reads from the `dq_recommendations` cache,
    populated by the "💡 Recommend DQ tests" sidebar button.

    Optional `severity` filter: "critical", "recommended", or "nice-to-have"
    (empty string = all). If the cache is empty, tell the user to click the
    sidebar button to populate it.
    """
    if not _has_data():
        return _EMPTY_HINT
    try:
        duck.query("SELECT 1 FROM dq_recommendations LIMIT 1")
    except Exception:
        return (
            "No DQ recommendations cached yet. Click **💡 Recommend DQ tests** in "
            "the sidebar to scan the catalog — that populates the gap summary."
        )

    severity = (severity or "").strip().lower()
    valid = {"critical", "recommended", "nice-to-have"}
    sql = "SELECT table_fqn, column_name, test_definition, parameters, rationale, severity FROM dq_recommendations"
    params: list = []
    if severity:
        if severity not in valid:
            return f"Unknown severity `{severity}`. Valid options: {', '.join(sorted(valid))}."
        sql += " WHERE severity = ?"
        params.append(severity)
    sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'recommended' THEN 1 ELSE 2 END, table_fqn, column_name"

    df = duck.query(sql, params)
    if df.empty:
        return (
            f"No DQ gaps found{' for severity ' + severity if severity else ''}. "
            "Either the cache is empty or every table has sufficient coverage."
        )

    # Group by table so the output reads top-down rather than as a flat list.
    totals = {"critical": 0, "recommended": 0, "nice-to-have": 0}
    grouped: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        totals[row["severity"]] = totals.get(row["severity"], 0) + 1
        grouped.setdefault(row["table_fqn"], []).append(row.to_dict())

    header = (
        f"**DQ gaps — {len(df)} recommendation(s) across {len(grouped)} table(s)**\n"
        f"🚨 {totals.get('critical', 0)} critical · "
        f"💡 {totals.get('recommended', 0)} recommended · "
        f"✨ {totals.get('nice-to-have', 0)} nice-to-have"
    )
    lines: list[str] = [header, ""]
    for table_fqn, rows in grouped.items():
        short = ".".join(table_fqn.split(".")[-2:])
        lines.append(f"### `{short}` — {len(rows)} gap(s)")
        for r in rows:
            lines.extend(_render_dq_recommendation(r))
        lines.append("")

    return "\n".join(lines)


@tool
def dq_impact(fqn: str) -> str:
    """Downstream BLAST RADIUS of currently-failing DQ tests on a single table.

    ★ Use this for _"what's the downstream impact of these DQ failures?"_,
      _"who's affected by the broken tests on <table>?"_, _"risk of the failing
      checks on <table>"_, _"DQ blast radius"_, _"if these tests keep failing,
      who's hurt?"_ ★

    Reports: how many tests are failing on the table, direct + transitive
    downstream table counts, how many downstream tables carry PII.Sensitive,
    and a weighted risk score (failed_tests × (direct + 0.5·transitive +
    2·pii_downstream)). Risk is zero if either the table has no failing
    tests OR no downstream lineage.

    Pass the FULL 4-part FQN (service.database.schema.table). If you don't
    know it, silently call `list_tables` first.
    """
    if not _has_data():
        return _EMPTY_HINT
    if not fqn or not fqn.strip():
        return "Tell me which table to assess. Use `list_tables` if you need the FQN."

    check = duck.query(
        "SELECT 1 FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn.strip()],
    )
    if check.empty:
        return (
            f"Table `{fqn}` doesn't exist in the catalog. "
            f"Use `list_tables` to find the real 4-part FQN."
        )

    r = analysis.dq_impact(fqn.strip())
    if r["failed_tests"] == 0:
        return (
            f"**`{fqn}`** has no failing DQ tests right now — nothing broken "
            "means no downstream blast radius from DQ.\n\n"
            "_If the catalog has no DQ tests configured at all, click_ "
            "**🧪 Explain DQ failures** _in the sidebar — it'll load the demo "
            "fixture so you have something to reason about._"
        )
    if r["transitive"] == 0:
        return (
            f"**`{fqn}`** has **{r['failed_tests']}** failing DQ test(s), but "
            "it's a leaf table — nothing downstream. The breakage is contained "
            "to this table's own readers.\n\n"
            f"_Failing tests:_ {', '.join(f'`{t}`' for t in r['failing_test_names'])}"
        )

    lines = [
        f"**DQ blast radius for `{fqn}`**",
        "",
        f"- **Failing tests:** {r['failed_tests']} "
        + ("(" + ", ".join(f"`{t}`" for t in r["failing_test_names"]) + ")")
        if r["failing_test_names"]
        else f"- **Failing tests:** {r['failed_tests']}",
        f"- **Direct dependents:** {r['direct']}",
        f"- **Transitive downstream:** {r['transitive']} table(s)",
        f"- **Downstream with PII.Sensitive:** {r['pii_downstream']}",
        f"- **Weighted risk score:** **{r['risk_score']}** "
        f"_(failed_tests × (direct + 0.5·transitive + 2·pii_downstream))_",
        "",
        "Downstream tables at risk:",
    ]
    for t in r["downstream_fqns"][:10]:
        short = ".".join(t.split(".")[-2:])
        lines.append(f"- `{short}`")
    if len(r["downstream_fqns"]) > 10:
        lines.append(f"- _…and {len(r['downstream_fqns']) - 10} more_")
    return "\n".join(lines)


@tool
def dq_risk_catalog(limit: int = 10) -> str:
    """Catalog-wide ranking of tables by DQ risk (failures × downstream weight).

    ★ Use this for _"where should I fix DQ first?"_, _"which broken tests hurt
      the most?"_, _"rank DQ risk"_, _"top DQ risks"_, _"where are failing
      checks having the biggest blast radius?"_ ★

    Returns a ranked list of tables that have at least one failing DQ test,
    sorted by the composite risk score (failed_tests × weighted downstream
    footprint, PII-amplified). Use this before recommending where a steward
    should spend triage time.
    """
    if not _has_data():
        return _EMPTY_HINT
    df = analysis.dq_risk_ranking(limit=int(limit) if limit else 10)
    if df.empty:
        return (
            "No failing DQ tests with downstream impact right now — either "
            "there are no failures, or the failing tables are leaves."
        )

    lines: list[str] = [
        f"**Top {len(df)} DQ risks** — failing tests × downstream blast radius",
        "",
        "| Rank | Table | Failed tests | Downstream | PII downstream | Risk score |",
        "|---|---|---|---|---|---|",
    ]
    for i, (_, r) in enumerate(df.iterrows(), start=1):
        short = ".".join(r["fqn"].split(".")[-2:])
        lines.append(
            f"| {i} | `{short}` | {int(r['failed_tests'])} | "
            f"{int(r['transitive'])} | {int(r['pii_downstream'])} | "
            f"**{r['risk_score']}** |"
        )
    return "\n".join(lines)


@tool
def dq_failures_summary(schema_name: str = "") -> str:
    """List every FAILING data quality check with LLM plain-English explanations.

    ★ Use this for any "why is my DQ check failing?", "what data quality
      issues do I have?", "explain the failed tests", "which tables have
      quality problems?", or "summarize failures" question. ★

    Pass an empty string for `schema_name` to scan the entire catalog, or a
    schema name (e.g. `sales`, `users`) to filter. Returns a markdown list of
    failures with the test definition, the raw failure message, and — when
    the user has already clicked "🧪 Explain DQ failures" in the sidebar —
    the LLM's summary / likely cause / next-step guidance per test.

    If no explanations exist yet, the tool still lists the raw failures and
    reminds the user to run the explain scan for the enriched output.
    """
    if not _has_data():
        return _EMPTY_HINT

    failures = analysis.dq_failures()
    if failures.empty:
        return (
            "No failing data quality checks found. "
            "Either the catalog has no DQ tests configured, or every test is "
            "currently passing."
        )

    if schema_name:
        s = schema_name.strip().lower()
        failures = failures[
            failures["table_fqn"].str.lower().str.contains(f".{s}.", regex=False, na=False)
        ]
        if failures.empty:
            return f"No failing DQ checks in schema `{schema_name}`."

    # Left-join to dq_explanations so we carry summary/cause/fix inline
    # when available. Fall back to raw failures if the explanation cache
    # hasn't been populated yet.
    have_explanations = False
    try:
        duck.query("SELECT 1 FROM dq_explanations LIMIT 1")
        have_explanations = True
    except Exception:
        pass

    explanations: dict[str, dict] = {}
    if have_explanations:
        try:
            exp_df = duck.query(
                "SELECT test_id, summary, likely_cause, next_step, fix_type FROM dq_explanations"
            )
        except Exception:
            # Cache exists from an older schema without fix_type — read what we can.
            exp_df = duck.query(
                "SELECT test_id, summary, likely_cause, next_step FROM dq_explanations"
            )
            exp_df["fix_type"] = ""
        for _, r in exp_df.iterrows():
            explanations[str(r["test_id"])] = {
                "summary": _as_str(r["summary"]),
                "likely_cause": _as_str(r["likely_cause"]),
                "next_step": _as_str(r["next_step"]),
                "fix_type": _as_str(r["fix_type"]),
            }

    lines: list[str] = [f"**{len(failures)} failing DQ check(s)**", ""]
    for _, row in failures.iterrows():
        short = ".".join((row["table_fqn"] or "").split(".")[-2:])
        col_part = f".{row['column_name']}" if row.get("column_name") else ""
        lines.append(f"### 🔴 `{short}{col_part}` — {row['test_name']}")
        lines.append(
            f"_Definition:_ `{row['test_definition_name']}` · _Message:_ {row['result_message']}"
        )
        exp = explanations.get(str(row["test_id"]))
        if exp:
            lines.append(f"- **Summary:** {exp['summary']}")
            lines.append(f"- **Likely cause:** {exp['likely_cause']}")
            chip = _fix_type_chip(exp.get("fix_type", ""))
            lines.append(f"- **Suggested fix** {chip} {exp['next_step']}")
        lines.append("")

    if not have_explanations or not explanations:
        lines.append(
            "_Tip: click **🧪 Explain DQ failures** in the sidebar to get "
            "plain-English summaries and suggested fixes for each failure._"
        )

    return "\n".join(lines)


@tool
def dq_explain(fqn: str) -> str:
    """Explain EVERY failing DQ check on a single table in plain English.

    Use when the user asks _"explain the DQ failures on <table>"_, _"why is the
    test on <column> failing?"_, or _"what's wrong with <table>'s data quality"_.

    Pass the FULL 4-part FQN (service.database.schema.table). Generates a
    fresh LLM explanation per failure on this table — separate from the
    catalog-wide cached explanations used by `dq_failures_summary`. Returns
    markdown with one section per failure.
    """
    if not _has_data():
        return _EMPTY_HINT
    if not fqn or not fqn.strip():
        return "Tell me which table to explain. Use `list_tables` if you need the FQN."

    failures = analysis.dq_failures()
    if failures.empty:
        return "No failing DQ checks in the catalog right now."
    scoped = failures[failures["table_fqn"] == fqn.strip()]
    if scoped.empty:
        return f"No failing DQ checks on `{fqn}` — either it has no tests or they're all passing."

    lines: list[str] = [f"**DQ failures on `{fqn}` ({len(scoped)} test(s))**", ""]
    for _, row in scoped.iterrows():
        try:
            exp = cleaning.explain_dq_failure(row.to_dict())
        except Exception as e:
            logger.warning(f"Ad-hoc DQ explanation failed for {row['test_name']}: {e}")
            lines.append(f"### 🔴 {row['test_name']}")
            lines.append(f"Couldn't generate an explanation — raw failure: {row['result_message']}")
            lines.append("")
            continue
        col_part = f".{row['column_name']}" if row.get("column_name") else ""
        lines.append(
            f"### 🔴 `{(row['table_fqn'] or '').split('.')[-1]}{col_part}` — {exp.test_name}"
        )
        lines.append(f"- **Summary:** {exp.summary}")
        lines.append(f"- **Likely cause:** {exp.likely_cause}")
        chip = _fix_type_chip(exp.fix_type)
        lines.append(f"- **Suggested fix** {chip} {exp.next_step}")
        lines.append("")

    return "\n".join(lines)


@tool
def impact_check(fqn: str) -> str:
    """BLAST RADIUS — weighted downstream impact analysis for a single table.

    ★ PREFER THIS TOOL for any "blast radius", "impact", "criticality",
      "what breaks if I change X", "ripple effect", "downstream footprint",
      "weighted impact", or "how important is X" question. ★

    Unlike `get_entity_lineage` (which only returns the lineage subgraph),
    this tool computes real impact analytics on top of lineage:
      - Direct dependents (depth-1)
      - Full transitive downstream count (recursive closure)
      - PII.Sensitive downstream count (cross-references column tags)
      - Weighted impact score: direct×1 + transitive_only×0.5 + pii×2

    Use `get_entity_lineage` ONLY when the user explicitly wants to see the
    graph / subgraph / edges / nodes — not for impact/blast-radius questions.

    Pass the FULL 4-part FQN — e.g. `metasift_demo_db.analytics.users.customer_profiles`.
    If you don't know it, call `list_tables` or `search_metadata` first.
    """
    if not _has_data():
        return _EMPTY_HINT
    if not fqn or not fqn.strip():
        return "Tell me which table to check. Use `list_tables` if you need to find the FQN."
    # Validate the FQN exists — catches hallucinated / short names up front.
    check = duck.query(
        "SELECT 1 FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn.strip()],
    )
    if check.empty:
        return (
            f"Table `{fqn}` doesn't exist in the catalog. "
            f"Use `list_tables` to find the real 4-part FQN."
        )
    r = analysis.blast_radius(fqn.strip())
    if r["transitive"] == 0:
        return (
            f"**`{fqn}`** is a leaf table — no downstream dependents.\n\n"
            f"_Changes here won't ripple anywhere. Impact score: 0._"
        )
    lines = [
        f"**Blast radius for `{fqn}`**",
        "",
        f"- **Direct dependents:** {r['direct']}",
        f"- **Transitive downstream:** {r['transitive']} table(s)",
        f"- **Downstream with PII.Sensitive:** {r['pii_downstream']}",
        f"- **Weighted impact score:** **{r['impact_score']}** "
        f"_(direct × 1 + transitive × 0.5 + PII downstream × 2)_",
        "",
        "Downstream tables:",
    ]
    for t in r["downstream_fqns"][:10]:
        short = ".".join(t.split(".")[-2:])
        lines.append(f"- `{short}`")
    if len(r["downstream_fqns"]) > 10:
        lines.append(f"- _…and {len(r['downstream_fqns']) - 10} more_")
    return "\n".join(lines)


@tool
def auto_document_schema(schema_name: str) -> str:
    """Draft descriptions for EVERY undocumented table in a schema at once.

    Use this when the user asks to document a whole schema or fill every gap
    in one go — e.g. _"auto-document the sales schema"_, _"draft descriptions
    for marketing"_, _"fill in the missing docs in users"_.

    Runs one LLM call per undocumented table (capped at 20) and persists the
    drafts to the review queue — nothing is written to OpenMetadata until the
    user clicks Accept on each. Returns a summary with counts.
    """
    if not _has_data():
        return _EMPTY_HINT
    schema_name = (schema_name or "").strip()
    if not schema_name:
        return "Tell me which schema to document. Try `list_schemas` first if you're not sure."
    summary = stewardship.bulk_document_schema(schema_name)
    if summary.get("error"):
        return f"Couldn't auto-document `{schema_name}`: {summary['error']}"
    if summary["total"] == 0:
        return (
            f"Schema `{schema_name}` has no undocumented tables — every table "
            f"already has a description. Nothing to draft."
        )
    tail = ""
    if summary["failed"]:
        tail = f" ({summary['failed']} failed — likely LLM timeouts)"
    return (
        f"✏️ Drafted **{summary['drafted']}** description(s) for schema "
        f"`{summary['schema']}`{tail}.\n\n"
        f"_Review and approve each one in the **📋 Review queue** in the sidebar. "
        f"Nothing was written to OpenMetadata yet._"
    )


@tool
def apply_description(fqn: str, description: str) -> str:
    """Write a description back to OpenMetadata via REST PATCH.

    Only call this AFTER the user has explicitly approved the text. The `fqn`
    MUST be a real fully-qualified name that exists in the catalog — use
    `list_tables` first if you're not certain. Never guess or construct an FQN.
    """
    from app.engines.stewardship import Suggestion

    # Validate FQN exists before attempting the PATCH — prevents 404s from
    # hallucinated service/database names.
    if not _has_data():
        return (
            "Can't verify the FQN because metadata isn't loaded. "
            "Ask the user to click '🔄 Refresh metadata' first."
        )
    check = duck.query(
        "SELECT 1 FROM om_tables WHERE fullyQualifiedName = ?",
        [fqn],
    )
    if check.empty:
        sample = duck.query("SELECT fullyQualifiedName AS fqn FROM om_tables ORDER BY fqn LIMIT 8")[
            "fqn"
        ].tolist()
        return (
            f"Table `{fqn}` doesn't exist in the catalog. "
            f"Use `list_tables` to find the real FQN. A few valid examples:\n"
            + "\n".join(f"- `{f}`" for f in sample)
        )

    s = Suggestion(
        fqn=fqn,
        field="description",
        old=None,
        new=description,
        confidence=1.0,
        reasoning="User-approved",
    )
    if stewardship.apply_suggestion(s):
        return f"✔ Description applied to `{fqn}`."
    return f"✖ Failed to apply description to `{fqn}` — check logs."


# ── PII tools ──────────────────────────────────────────────────────────────────


@tool
def scan_pii() -> str:
    """Scan every column in the catalog for PII sensitivity and store the results.

    Uses a heuristic rule set (no LLM) to classify columns as `PII.Sensitive`,
    `PII.NonSensitive`, or non-PII. Stores results in the `pii_results` table
    so follow-up queries like `find_pii_gaps` are fast.

    Use this when the user asks to:
    - "Scan for PII", "find PII", "classify sensitive columns"
    - "What sensitive data do I have?", "check PII coverage"
    - "Audit tags", "find untagged PII"

    Returns a summary: scanned, sensitive count, non-sensitive count, and gaps
    (columns where the suggested tag differs from the current tag).
    """
    if not _has_data():
        return _EMPTY_HINT
    summary = cleaning.run_pii_scan()
    if summary["scanned"] == 0:
        return "No columns found to scan. Refresh metadata first."
    return (
        f"**PII scan complete** — {summary['scanned']} columns analyzed.\n\n"
        f"- 🔴 **Sensitive:** {summary['sensitive']} columns\n"
        f"- 🟡 **Non-sensitive person identifiers:** {summary['nonsensitive']} columns\n"
        f"- ⚠️ **Gaps** (missing or wrong tag): {summary['gaps']} columns\n\n"
        f"_Call `find_pii_gaps` to see which specific columns need attention._"
    )


@tool
def find_pii_gaps(min_confidence: float = 0.8) -> str:
    """List columns where the heuristic suggests a PII tag different from the current tag.

    Requires `scan_pii` to have been run first (reads from the `pii_results` table).
    Filters to gaps at or above the given confidence threshold (default 0.8 —
    high-confidence suggestions only). Lower the threshold to see more.

    Use this when the user asks:
    - "Show me the PII gaps", "what's untagged?"
    - "Which columns should I tag?", "what PII is missing a tag?"

    Returns a markdown table with column, table, suggested tag, confidence, and reason.
    """
    if not _has_data():
        return _EMPTY_HINT
    try:
        df = duck.query(
            """
            SELECT column_name, table_fqn, current_tag, suggested_tag, confidence, reason
            FROM pii_results
            WHERE suggested_tag IS NOT NULL
              AND (current_tag IS NULL OR current_tag != suggested_tag)
              AND confidence >= ?
            ORDER BY
              CASE WHEN suggested_tag = 'PII.Sensitive' THEN 0 ELSE 1 END,
              confidence DESC
            """,
            [float(min_confidence)],
        )
    except Exception:
        return "No PII scan results yet. Run `scan_pii` first, then ask again."
    if df.empty:
        return (
            f"No PII gaps found above confidence {min_confidence:.2f}. "
            f"Either everything's tagged correctly, or no scan has been run."
        )
    lines = [f"**Found {len(df)} PII gap(s)** (confidence ≥ {min_confidence:.2f}):", ""]
    lines.append("| Column | Table | Suggested tag | Confidence | Current | Reason |")
    lines.append("|---|---|---|---|---|---|")
    for _, r in df.iterrows():
        current = r["current_tag"] if r["current_tag"] else "_(none)_"
        schema_table = ".".join(r["table_fqn"].split(".")[-2:])
        lines.append(
            f"| `{r['column_name']}` | `{schema_table}` | **{r['suggested_tag']}** | "
            f"{r['confidence']:.2f} | {current} | {r['reason']} |"
        )
    lines.append("")
    lines.append(
        "_To apply: ask the user to confirm, then call `apply_pii_tag(table_fqn, column_name, tag)`._"
    )
    return "\n".join(lines)


@tool
def apply_pii_tag(table_fqn: str, column_name: str, tag_fqn: str) -> str:
    """Apply a PII classification tag to a specific column in OpenMetadata.

    Writes to the catalog via REST PATCH. Non-destructive: if the column
    already has other tags, those are preserved; the new tag is added.

    REQUIRES user approval before calling. The FQN and column name must be
    real — use `list_tables` or `find_pii_gaps` to find them first.

    Valid `tag_fqn` values: `PII.Sensitive`, `PII.NonSensitive`, `PII.None`.

    Returns success/error message.
    """
    # Validate the FQN exists in our catalog cache to catch hallucination early.
    if not _has_data():
        return (
            "Can't verify the FQN because metadata isn't loaded. "
            "Ask the user to click '🔄 Refresh metadata' first."
        )
    check = duck.query(
        "SELECT 1 FROM om_columns WHERE table_fqn = ? AND name = ?",
        [table_fqn, column_name],
    )
    if check.empty:
        return (
            f"Column `{column_name}` not found in table `{table_fqn}`. "
            f"Call `find_pii_gaps` or `list_tables` to find real FQN + column names."
        )
    result = stewardship.apply_pii_tag(table_fqn, column_name, tag_fqn)
    icon = "✔" if result["ok"] else "✖"
    return f"{icon} {result['message']}"


# ── Escape hatch ───────────────────────────────────────────────────────────────


@tool
def run_sql(query: str) -> str:
    """Run arbitrary read-only SQL against the DuckDB metadata store.

    Available tables:
      - `om_tables` (fullyQualifiedName, description, columns, tags, owners, profile)
      - `om_columns` (table_fqn, name, dataType, description, tags)

    Use for ad-hoc questions not covered by the other tools. Read-only —
    do NOT use for INSERT/UPDATE/DELETE. Returns up to 50 rows as a markdown table.
    """
    if not _has_data():
        return _EMPTY_HINT
    lowered = query.lower().strip()
    if any(kw in lowered for kw in ("insert ", "update ", "delete ", "drop ", "create ", "alter ")):
        return "Refused: run_sql is read-only."
    try:
        df = duck.query(query)
    except Exception as e:
        return f"SQL error: {e}"
    if df.empty:
        return "Query returned no rows."
    return df.head(50).to_markdown(index=False)


# ── Registry ───────────────────────────────────────────────────────────────────

ALL_TOOLS = [
    list_schemas,
    list_tables,
    documentation_coverage,
    find_tag_conflicts,
    composite_score,
    find_naming_inconsistencies,
    check_description_staleness,
    score_descriptions,
    about_metasift,
    ownership_report,
    impact_check,
    dq_impact,
    dq_risk_catalog,
    dq_failures_summary,
    dq_explain,
    recommend_dq_tests,
    find_dq_gaps,
    generate_description_for,
    auto_document_schema,
    apply_description,
    scan_pii,
    find_pii_gaps,
    apply_pii_tag,
    run_sql,
]


def _wrap_for_safety(t):
    """One-time wrap: convert tool exceptions into text error messages so the
    agent can recover and try a different approach instead of crashing."""
    if getattr(t, "_wrapped_for_safety", False):
        return t
    original = t.func
    name = t.name

    def safe(*args, _orig=original, _name=name, **kwargs):
        try:
            return _orig(*args, **kwargs)
        except Exception as e:
            logger.warning(f"Tool '{_name}' errored: {e}")
            return (
                f"Tool '{_name}' failed with error: {e}. "
                "Try a different approach or report this to the user."
            )

    t.func = safe
    t._wrapped_for_safety = True
    return t


def get_tools() -> list:
    """Return all MetaSift tools. Imported by the agent builder."""
    wrapped = [_wrap_for_safety(t) for t in ALL_TOOLS]
    logger.info(f"Loaded {len(wrapped)} local MetaSift tools (errors non-fatal).")
    return wrapped
