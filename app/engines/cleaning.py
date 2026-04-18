"""Cleaning engine — the differentiator.

Detects stale descriptions, tag conflicts, inconsistent naming, and low-quality docs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger
from thefuzz import fuzz

from app.clients import duck
from app.clients.llm import get_llm

# ── Stale description detection ────────────────────────────────────────────────


@dataclass
class StaleReport:
    fqn: str
    old: str
    corrected: str
    stale: bool
    reason: str
    confidence: float


def detect_stale(fqn: str, current_description: str, columns: list[dict]) -> StaleReport:
    """Compare a description against actual column metadata."""
    llm = get_llm("stale")
    col_summary = ", ".join(f"{c['name']} ({c['dataType']})" for c in columns[:20])
    prompt = (
        "Compare this table description against its actual columns. Is the description "
        "accurate, or is it stale/wrong?\n\n"
        f"Table: {fqn}\nCurrent description: {current_description}\nColumns: {col_summary}\n\n"
        "Respond ONLY with JSON:\n"
        '{"stale": bool, "reason": str, "corrected": str, "confidence": float 0-1}'
    )
    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    try:
        # Strip markdown code fences if present
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse stale response for {fqn}: {text[:200]}")
        parsed = {"stale": False, "reason": "parse_error", "corrected": "", "confidence": 0.0}
    return StaleReport(
        fqn=fqn,
        old=current_description,
        corrected=parsed.get("corrected", ""),
        stale=bool(parsed.get("stale", False)),
        reason=parsed.get("reason", ""),
        confidence=float(parsed.get("confidence", 0.0)),
    )


# ── Inconsistent naming detection ──────────────────────────────────────────────


def detect_naming_clusters(similarity_threshold: int = 75) -> list[dict]:
    """Cluster similar column names across the catalog using fuzzy matching."""
    cols = duck.query("SELECT DISTINCT name FROM om_columns WHERE name IS NOT NULL").name.tolist()
    clusters: list[list[str]] = []
    assigned: set[str] = set()

    for i, a in enumerate(cols):
        if a in assigned:
            continue
        cluster = [a]
        for b in cols[i + 1 :]:
            if b in assigned:
                continue
            if fuzz.ratio(a, b) >= similarity_threshold and a.lower() != b.lower():
                cluster.append(b)
                assigned.add(b)
        if len(cluster) > 1:
            clusters.append(cluster)
            assigned.add(a)

    return [{"canonical": c[0], "variants": c} for c in clusters]


# ── Description quality scoring ────────────────────────────────────────────────


def score_descriptions_batch(descriptions: list[dict]) -> list[dict]:
    """Score a batch of descriptions 1-5 on specificity/accuracy/completeness.

    Input: [{fqn, description, columns}, ...]
    Output: [{fqn, score, rationale}, ...]
    """
    if not descriptions:
        return []
    llm = get_llm("scoring")
    items = "\n".join(
        f'{i + 1}. {d["fqn"]}: "{d["description"]}" (columns: {", ".join(d.get("columns", [])[:5])})'
        for i, d in enumerate(descriptions)
    )
    prompt = (
        "Score each description 1-5 on specificity, accuracy, and completeness. "
        "1 = useless (e.g. 'data table'), 5 = excellent (specific, complete, accurate).\n\n"
        f"{items}\n\n"
        "Respond ONLY with a JSON array:\n"
        '[{"index": int, "score": int, "rationale": str}, ...]'
    )
    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    try:
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse scoring response: {text[:200]}")
        return []
    out = []
    for item in parsed:
        idx = item.get("index", 0) - 1
        if 0 <= idx < len(descriptions):
            out.append(
                {
                    "fqn": descriptions[idx]["fqn"],
                    "score": item.get("score", 0),
                    "rationale": item.get("rationale", ""),
                }
            )
    return out


# ── Composite metadata quality score ──────────────────────────────────────────


def composite_quality(
    coverage_pct: float,
    accuracy_pct: float,
    consistency_pct: float,
    avg_quality_score: float,
) -> float:
    """Weighted composite per plan: 30/30/20/20."""
    quality_normalized = (avg_quality_score / 5.0) * 100 if avg_quality_score else 0.0
    return round(
        coverage_pct * 0.30
        + accuracy_pct * 0.30
        + consistency_pct * 0.20
        + quality_normalized * 0.20,
        1,
    )


# ── Deep scan: populates the cleaning_results cache ────────────────────────────


def _as_list(value) -> list:
    """Coerce a DuckDB/pandas cell to a plain list (handles numpy arrays)."""
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value) if value else []


def run_deep_scan(progress_cb=None) -> dict[str, float | int]:
    """Run stale detection + quality scoring on every documented table and
    persist results to a DuckDB `cleaning_results` table.

    Args:
        progress_cb: Optional callable(step:int, total:int, label:str) invoked
            after each stale check — lets the caller render a progress bar.

    Returns:
        Summary dict with counts + computed accuracy_pct / quality_avg_1_5.
    """
    tables = duck.query("""
        SELECT fullyQualifiedName AS fqn, description, columns
        FROM om_tables
        WHERE description IS NOT NULL AND length(description) > 0
    """)
    total = len(tables)
    if total == 0:
        return {"analyzed": 0, "accuracy_pct": 0.0, "quality_avg_1_5": 0.0}

    conn = duck.get_conn()
    conn.execute("""
        CREATE OR REPLACE TABLE cleaning_results (
            fqn VARCHAR PRIMARY KEY,
            stale BOOLEAN,
            stale_reason VARCHAR,
            stale_confidence DOUBLE,
            quality_score INTEGER,
            quality_rationale VARCHAR
        )
    """)

    # Stage 1: stale detection, one LLM call per table (sequential for demo).
    stale_map: dict[str, StaleReport] = {}
    for idx, (_, row) in enumerate(tables.iterrows(), start=1):
        fqn = row["fqn"]
        if progress_cb:
            progress_cb(idx, total, f"Checking staleness: {fqn}")
        try:
            report = detect_stale(fqn, row["description"], _as_list(row["columns"]))
            stale_map[fqn] = report
        except Exception as e:
            logger.warning(f"detect_stale failed for {fqn}: {e}")

    # Stage 2: quality scoring, one batched LLM call for everything documented.
    if progress_cb:
        progress_cb(total, total, "Scoring description quality…")
    items = [
        {
            "fqn": row["fqn"],
            "description": row["description"],
            "columns": [c.get("name") for c in _as_list(row["columns"])],
        }
        for _, row in tables.iterrows()
    ]
    quality_results = score_descriptions_batch(items)
    quality_map = {r["fqn"]: (r["score"], r.get("rationale", "")) for r in quality_results}

    # Persist merged results.
    for fqn, report in stale_map.items():
        q_score, q_reason = quality_map.get(fqn, (0, ""))
        conn.execute(
            "INSERT INTO cleaning_results VALUES (?, ?, ?, ?, ?, ?)",
            [fqn, report.stale, report.reason, report.confidence, q_score, q_reason],
        )
    # Tables where stale detection succeeded but quality didn't get added need
    # insertion too; and vice versa. Above covers stale-succeeded path. Let's
    # also backfill for tables where only quality worked.
    for fqn, (q_score, q_reason) in quality_map.items():
        if fqn not in stale_map:
            conn.execute(
                "INSERT INTO cleaning_results VALUES (?, ?, ?, ?, ?, ?)",
                [fqn, None, None, None, q_score, q_reason],
            )

    analyzed = len(stale_map)
    non_stale = sum(1 for r in stale_map.values() if not r.stale)
    accuracy = round(100.0 * non_stale / analyzed, 1) if analyzed else 0.0
    scores = [s for s, _ in quality_map.values() if s and s > 0]
    quality_avg = round(sum(scores) / len(scores), 2) if scores else 0.0

    logger.info(
        f"Deep scan done — {analyzed}/{total} tables analyzed, "
        f"accuracy={accuracy}%, quality={quality_avg}/5"
    )
    return {
        "analyzed": analyzed,
        "accuracy_pct": accuracy,
        "quality_avg_1_5": quality_avg,
    }
