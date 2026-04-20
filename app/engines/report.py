"""Executive report — stakeholder-friendly markdown summary of catalog health.

Pulls the composite score, stale descriptions (cleaning engine), tag conflicts,
PII classification gaps, and naming inconsistencies into a single downloadable
document. Designed to be dropped into a Slack / email / PR description as-is.

Reads from DuckDB — call `duck.refresh_all()` before generating if the catalog
may have changed. Sections whose source table hasn't been scanned yet
(cleaning_results, pii_results) are silently skipped rather than empty.
"""

from __future__ import annotations

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
        "a distinct class of quality issue — coverage, accuracy, consistency, and "
        "classification."
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
        pass  # no metadata loaded — silently skip, matches other sections

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
                f"Found **{len(stale)}** descriptions that don't match their actual columns. "
                f"These mislead downstream consumers and warp any search/AI over the catalog."
            )
            lines.append("")
            lines.append("| Table | Confidence | Why stale | Suggested rewrite |")
            lines.append("|---|---|---|---|")
            for _, r in stale.iterrows():
                conf = float(r["stale_confidence"] or 0.0)
                corrected = (r["stale_corrected"] or "").replace("|", "\\|")
                reason = (r["stale_reason"] or "").replace("|", "\\|")
                lines.append(
                    f"| `{r['fqn']}` | {conf:.0%} | {reason} | {corrected or '_(none)_'} |"
                )
            lines.append("")
    except Exception:
        pass  # cleaning_results not yet populated

    # ── Tag conflicts ──────────────────────────────────────────────────────
    try:
        conflicts = analysis.tag_conflicts()
        if not conflicts.empty:
            lines.append("## Classification Conflicts")
            lines.append("")
            lines.append(
                f"**{len(conflicts)}** column name(s) are tagged inconsistently across tables. "
                f"A column like `email` tagged `PII.Sensitive` in one table but untagged in another "
                f"is a compliance blind spot."
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

    # ── PII gaps ───────────────────────────────────────────────────────────
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
                f"**{len(pii)}** column(s) where the heuristic suggests a PII tag that "
                f"differs from (or replaces) the current tag — {sensitive} sensitive, "
                f"{nonsens} non-sensitive person identifiers."
            )
            lines.append("")
            lines.append("| Column | Table | Suggested | Current | Confidence | Reason |")
            lines.append("|---|---|---|---|---|---|")
            for _, r in pii.iterrows():
                current = r["current_tag"] if r["current_tag"] else "_(none)_"
                reason = (r["reason"] or "").replace("|", "\\|")
                lines.append(
                    f"| `{r['column_name']}` | `{r['table_fqn']}` | **{r['suggested_tag']}** | "
                    f"{current} | {float(r['confidence'] or 0):.2f} | {reason} |"
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
                f"**{len(clusters)}** cluster(s) of similar column names — likely naming drift "
                f"that breaks joins and confuses analysts."
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
