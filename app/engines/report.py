"""Executive report — stakeholder-friendly markdown summary of catalog health.

Pulls every MetaSift finding into a single downloadable document organized to
tell a coherent story: headline score → breadth → ownership → impact →
accuracy (descriptions + DQ) → consistency → classification → governance
(PII propagation) → data quality (failures/recommendations/risk) → naming.

Reads from DuckDB — call `duck.refresh_all()` before generating if the catalog
may have changed. Sections whose source table hasn't been scanned yet are
silently skipped rather than left empty, so the report reflects exactly the
user's current analysis depth.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.clients import duck
from app.engines import analysis, cleaning


def _format_list(items: list) -> str:
    """Flatten a DuckDB list-typed cell for inline rendering."""
    if items is None:
        return ""
    if hasattr(items, "tolist"):
        items = items.tolist()
    return ", ".join(f"`{x}`" for x in items if x is not None)


def _escape_pipes(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _short_fqn(fqn: str) -> str:
    parts = (fqn or "").split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else (fqn or "")


def generate_markdown_report() -> str:
    """Return a full executive report as a markdown string."""
    lines: list[str] = []

    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines.append("# MetaSift Executive Report")
    lines.append("")
    lines.append(f"_Generated {now}_")
    lines.append("")
    lines.append(
        "AI-powered audit of catalog metadata health. Each section below surfaces "
        "a distinct class of quality, governance, or data-quality issue. Sections "
        "appear only when the relevant scan has been run — an empty DQ section, "
        "for example, means you haven't run the DQ scans yet, not that there's "
        "nothing to report."
    )
    lines.append("")

    # ── Composite score ────────────────────────────────────────────────────
    try:
        score = analysis.composite_score()
        lines.append("## Composite Score")
        lines.append("")
        lines.append(f"### **{score['composite']}% / 100**")
        lines.append("")
        lines.append("| Dimension | Score | Weight |")
        lines.append("|---|---|---|")
        lines.append(f"| Documentation coverage | {score['coverage']}% | 30% |")
        lines.append(f"| Description accuracy | {score['accuracy']}% | 30% |")
        lines.append(f"| Classification consistency | {score['consistency']}% | 20% |")
        lines.append(f"| Description quality | {score['quality']}% | 20% |")
        lines.append("")
    except Exception:
        pass

    # ── Coverage by schema ─────────────────────────────────────────────────
    try:
        cov = analysis.documentation_coverage()
        if not cov.empty:
            lines.append("## Documentation Coverage by Schema")
            lines.append("")
            lines.append(cov.to_markdown(index=False))
            lines.append("")
    except Exception:
        pass

    # ── Stewardship scorecard ──────────────────────────────────────────────
    try:
        teams = analysis.ownership_breakdown()
        if not teams.empty:
            lines.append("## Stewardship Scorecard")
            lines.append("")
            lines.append(
                "Per-team accountability — who owns what, how well it's documented, "
                "and whether they're sitting on PII."
            )
            lines.append("")
            lines.append("| Team | Tables | Coverage | PII tables | Avg quality (1-5) |")
            lines.append("|---|---|---|---|---|")
            for _, r in teams.iterrows():
                q = r.get("quality_avg")
                q_str = f"{float(q):.2f}" if q is not None and str(q) != "<NA>" else "_(no scan)_"
                lines.append(
                    f"| **{r['team']}** | {int(r['tables_owned'])} | "
                    f"{float(r['coverage_pct'])}% | {int(r['pii_tables'])} | {q_str} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── Orphans ────────────────────────────────────────────────────────────
    try:
        orphans = analysis.orphans()
        if not orphans.empty:
            lines.append("## Orphan Tables")
            lines.append("")
            lines.append(
                f"**{len(orphans)}** table(s) have no owner assigned — accountability "
                f"gaps that need a home."
            )
            lines.append("")
            lines.append("| Table | Documented? |")
            lines.append("|---|---|")
            for _, r in orphans.iterrows():
                doc = "yes" if bool(r.get("documented")) else "no"
                lines.append(f"| `{r['fqn']}` | {doc} |")
            lines.append("")
    except Exception:
        pass

    # ── Top blast-radius tables ────────────────────────────────────────────
    try:
        impact = analysis.top_blast_radius(limit=10)
        if not impact.empty:
            lines.append("## Top Impact Tables (Blast Radius)")
            lines.append("")
            lines.append(
                "Tables whose changes ripple furthest — weighted by PII-downstream "
                "count so a small lineage that reaches sensitive data outranks a "
                "large one that doesn't."
            )
            lines.append("")
            lines.append("| Rank | Table | Direct | Transitive | PII downstream | Impact score |")
            lines.append("|---|---|---|---|---|---|")
            for i, (_, r) in enumerate(impact.iterrows(), start=1):
                lines.append(
                    f"| {i} | `{r['fqn']}` | {int(r['direct'])} | "
                    f"{int(r['transitive'])} | {int(r['pii_downstream'])} | "
                    f"**{r['impact_score']}** |"
                )
            lines.append("")
    except Exception:
        pass

    # ── Stale descriptions ─────────────────────────────────────────────────
    try:
        stale = duck.query("""
            SELECT fqn, stale_reason, stale_confidence, stale_corrected
            FROM cleaning_results
            WHERE stale = TRUE
            ORDER BY stale_confidence DESC
        """)
        if not stale.empty:
            lines.append("## Stale Descriptions")
            lines.append("")
            lines.append(
                f"Found **{len(stale)}** descriptions that don't match their actual "
                f"columns. These mislead downstream consumers and warp any search / "
                f"AI over the catalog."
            )
            lines.append("")
            lines.append("| Table | Confidence | Why stale | Suggested rewrite |")
            lines.append("|---|---|---|---|")
            for _, r in stale.iterrows():
                conf = float(r["stale_confidence"] or 0.0)
                lines.append(
                    f"| `{r['fqn']}` | {conf:.0%} | "
                    f"{_escape_pipes(r['stale_reason'])} | "
                    f"{_escape_pipes(r['stale_corrected']) or '_(none)_'} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── Description quality distribution ───────────────────────────────────
    try:
        low_q = duck.query("""
            SELECT fqn, quality_score, quality_rationale
            FROM cleaning_results
            WHERE quality_score IS NOT NULL AND quality_score > 0 AND quality_score <= 2
            ORDER BY quality_score ASC, fqn
        """)
        if not low_q.empty:
            lines.append("## Low-Quality Descriptions (1-2 of 5)")
            lines.append("")
            lines.append(
                f"**{len(low_q)}** description(s) scored at or below 2/5 — vague, "
                f"placeholder, or misleading text that the cleaning engine recommends "
                f"rewriting."
            )
            lines.append("")
            lines.append("| Table | Score | Rationale |")
            lines.append("|---|---|---|")
            for _, r in low_q.iterrows():
                lines.append(
                    f"| `{r['fqn']}` | {int(r['quality_score'])}/5 | "
                    f"{_escape_pipes(r['quality_rationale'])} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── Tag conflicts ──────────────────────────────────────────────────────
    try:
        conflicts = analysis.tag_conflicts()
        if not conflicts.empty:
            lines.append("## Classification Conflicts")
            lines.append("")
            lines.append(
                f"**{len(conflicts)}** column name(s) are tagged inconsistently "
                f"across tables. A column like `email` tagged `PII.Sensitive` in "
                f"one table but untagged in another is a compliance blind spot."
            )
            lines.append("")
            lines.append("| Column | Variants | Affected tables |")
            lines.append("|---|---|---|")
            for _, r in conflicts.iterrows():
                lines.append(
                    f"| `{r['name']}` | {_format_list(r['tag_variants'])} | "
                    f"{_format_list(r['affected_tables'])} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── PII column gaps ────────────────────────────────────────────────────
    try:
        pii = duck.query("""
            SELECT column_name, table_fqn, current_tag, suggested_tag, confidence, reason
            FROM pii_results
            WHERE suggested_tag IS NOT NULL
              AND (current_tag IS NULL OR current_tag != suggested_tag)
            ORDER BY
                CASE WHEN suggested_tag = 'PII.Sensitive' THEN 0 ELSE 1 END,
                confidence DESC
        """)
        if not pii.empty:
            sensitive = int((pii["suggested_tag"] == "PII.Sensitive").sum())
            nonsens = int((pii["suggested_tag"] == "PII.NonSensitive").sum())
            lines.append("## PII Classification Gaps")
            lines.append("")
            lines.append(
                f"**{len(pii)}** column(s) where the heuristic suggests a PII tag "
                f"that differs from (or replaces) the current tag — {sensitive} "
                f"sensitive, {nonsens} non-sensitive person identifiers."
            )
            lines.append("")
            lines.append("| Column | Table | Suggested | Current | Confidence | Reason |")
            lines.append("|---|---|---|---|---|---|")
            for _, r in pii.iterrows():
                current = r["current_tag"] if r["current_tag"] else "_(none)_"
                lines.append(
                    f"| `{r['column_name']}` | `{r['table_fqn']}` | "
                    f"**{r['suggested_tag']}** | {current} | "
                    f"{float(r['confidence'] or 0):.2f} | "
                    f"{_escape_pipes(r['reason'])} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── PII propagation (lineage governance) ───────────────────────────────
    try:
        prop = analysis.pii_propagation()
        if prop["origins"]:
            origin_n = len(prop["origins"])
            tainted_n = len(prop["tainted"])
            clean_n = len(prop["clean"])
            prop_edge_n = len(prop["propagation_edges"])
            lines.append("## PII Propagation (Lineage Governance)")
            lines.append("")
            lines.append(
                f"**{origin_n}** origin table(s) carry PII.Sensitive columns; "
                f"sensitive data propagates via lineage to **{tainted_n}** "
                f"downstream table(s) through **{prop_edge_n}** edge(s). "
                f"{clean_n} table(s) are clean."
            )
            lines.append("")
            lines.append("**Origins (PII present directly):**")
            lines.append("")
            lines.append("| Table | PII columns |")
            lines.append("|---|---|")
            for fqn, cols in sorted(prop["origins"].items()):
                cols_str = ", ".join(f"`{c}`" for c in cols)
                lines.append(f"| `{fqn}` | {cols_str} |")
            lines.append("")
            if prop["tainted"]:
                lines.append(
                    f"**Tainted downstream ({tainted_n}):** "
                    + ", ".join(f"`{_short_fqn(t)}`" for t in prop["tainted"][:20])
                    + (f" _(+{tainted_n - 20} more)_" if tainted_n > 20 else "")
                )
                lines.append("")
    except Exception:
        pass

    # ── DQ failure explanations ────────────────────────────────────────────
    try:
        dq_failures = analysis.dq_failures()
        if not dq_failures.empty:
            # Left-join explanations into the failure list. If the Explain DQ
            # scan hasn't been run, the explanation columns come back NULL and
            # we render em-dashes — the raw failure still shows up.
            have_exp = False
            try:
                duck.query("SELECT 1 FROM dq_explanations LIMIT 1")
                have_exp = True
            except Exception:
                pass
            explanations: dict[str, dict] = {}
            if have_exp:
                try:
                    exp_df = duck.query(
                        "SELECT test_id, summary, likely_cause, next_step, fix_type "
                        "FROM dq_explanations"
                    )
                    for _, r in exp_df.iterrows():
                        explanations[str(r["test_id"])] = {
                            "summary": r.get("summary") or "",
                            "likely_cause": r.get("likely_cause") or "",
                            "next_step": r.get("next_step") or "",
                            "fix_type": r.get("fix_type") or "",
                        }
                except Exception:
                    explanations = {}

            lines.append("## Data Quality — Failing Checks")
            lines.append("")
            lines.append(
                f"**{len(dq_failures)}** failing DQ check(s) across "
                f"{dq_failures['table_fqn'].nunique()} table(s). Each is rendered "
                f"with the raw failure message plus MetaSift's LLM-written "
                f"Summary · Likely cause · Suggested fix (when the Explain DQ "
                f"scan has been run)."
            )
            lines.append("")
            for _, row in dq_failures.iterrows():
                col_part = f".{row['column_name']}" if row.get("column_name") else ""
                lines.append(f"### `{_short_fqn(row['table_fqn'])}{col_part}` — {row['test_name']}")
                lines.append("")
                lines.append(f"**Definition:** `{row['test_definition_name']}`  ")
                lines.append(f"**Message:** {_escape_pipes(row['result_message']) or '_(none)_'}")
                exp = explanations.get(str(row["test_id"]))
                if exp:
                    lines.append("")
                    lines.append(f"- **Summary:** {exp['summary'] or '_(missing)_'}")
                    lines.append(f"- **Likely cause:** {exp['likely_cause'] or '_(missing)_'}")
                    fix_label = (exp.get("fix_type") or "").strip().lower()
                    fix_display = f"_({fix_label.replace('_', ' ')})_" if fix_label else ""
                    lines.append(
                        f"- **Suggested fix:** {exp['next_step'] or '_(missing)_'} "
                        f"{fix_display}".rstrip()
                    )
                lines.append("")
    except Exception:
        pass

    # ── DQ test recommendations ────────────────────────────────────────────
    try:
        recs = duck.query(
            "SELECT table_fqn, column_name, test_definition, parameters, "
            "rationale, severity FROM dq_recommendations "
            "ORDER BY CASE severity WHEN 'critical' THEN 0 "
            "WHEN 'recommended' THEN 1 ELSE 2 END, table_fqn"
        )
        if not recs.empty:
            crit = int((recs["severity"] == "critical").sum())
            rec = int((recs["severity"] == "recommended").sum())
            nice = int((recs["severity"] == "nice-to-have").sum())
            lines.append("## Data Quality — Recommended Tests")
            lines.append("")
            lines.append(
                f"**{len(recs)}** DQ test(s) proposed by MetaSift that don't yet "
                f"exist in the catalog — {crit} critical, {rec} recommended, "
                f"{nice} nice-to-have. Each is constrained to real OpenMetadata "
                f"test definitions so the outputs are paste-ready into an OM "
                f"test suite."
            )
            lines.append("")
            lines.append("| Severity | Table | Column | Test definition | Parameters | Rationale |")
            lines.append("|---|---|---|---|---|---|")
            for _, r in recs.iterrows():
                params = r.get("parameters") or "[]"
                try:
                    parsed = json.loads(params)
                    params_str = (
                        ", ".join(f"{p.get('name')}={p.get('value')}" for p in parsed)
                        if parsed
                        else "_(none)_"
                    )
                except Exception:
                    params_str = "_(malformed)_"
                col = r.get("column_name") or "_(table-level)_"
                lines.append(
                    f"| {r['severity']} | `{_short_fqn(r['table_fqn'])}` | "
                    f"{col if col == '_(table-level)_' else f'`{col}`'} | "
                    f"`{r['test_definition']}` | {params_str} | "
                    f"{_escape_pipes(r['rationale'])} |"
                )
            lines.append("")
    except Exception:
        pass

    # ── DQ × lineage risk ──────────────────────────────────────────────────
    try:
        risk = analysis.dq_risk_ranking(limit=10)
        if not risk.empty:
            lines.append("## Data Quality — Risk Ranking")
            lines.append("")
            lines.append(
                "Tables with at least one failing DQ check, ranked by risk. "
                "Risk = failed_tests × (direct + 0.5·transitive + 2·pii_downstream). "
                "Answers *where should I fix DQ first?* — tables near the top have "
                "broken data AND downstream readers that would feel it."
            )
            lines.append("")
            lines.append("| Rank | Table | Failing | Direct | Transitive | PII downstream | Risk |")
            lines.append("|---|---|---|---|---|---|---|")
            for i, (_, r) in enumerate(risk.iterrows(), start=1):
                lines.append(
                    f"| {i} | `{r['fqn']}` | {int(r['failed_tests'])} | "
                    f"{int(r['direct'])} | {int(r['transitive'])} | "
                    f"{int(r['pii_downstream'])} | **{r['risk_score']}** |"
                )
            lines.append("")
    except Exception:
        pass

    # ── Naming inconsistencies ─────────────────────────────────────────────
    try:
        clusters = cleaning.detect_naming_clusters()
        if clusters:
            lines.append("## Naming Inconsistencies")
            lines.append("")
            lines.append(
                f"**{len(clusters)}** cluster(s) of similar column names — likely "
                f"naming drift that breaks joins and confuses analysts."
            )
            lines.append("")
            for c in clusters:
                variants = ", ".join(f"`{v}`" for v in c["variants"][1:])
                lines.append(f"- **`{c['canonical']}`** ↔ {variants}")
            lines.append("")
    except Exception:
        pass

    lines.append("---")
    lines.append("")
    lines.append(
        "_Generated by MetaSift — AI-powered metadata analyst & steward for OpenMetadata._"
    )
    lines.append("")

    return "\n".join(lines)
