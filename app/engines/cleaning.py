"""Cleaning engine — the differentiator.

Detects stale descriptions, tag conflicts, inconsistent naming, and low-quality docs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
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
        for b in cols[i + 1:]:
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
        f"{i + 1}. {d['fqn']}: \"{d['description']}\" (columns: {', '.join(d.get('columns', [])[:5])})"
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
            out.append({
                "fqn": descriptions[idx]["fqn"],
                "score": item.get("score", 0),
                "rationale": item.get("rationale", ""),
            })
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
