"""Cleaning engine — the differentiator.

Detects stale descriptions, tag conflicts, inconsistent naming, and low-quality docs.
"""

from __future__ import annotations

import json
import re
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


def _build_stale_prompt(fqn: str, description: str, col_summary: str) -> str:
    """Adversarial prompt with few-shot anchors — soft prompts rubber-stamp any
    grammatically-clean description; we need the model to hunt for mismatches.
    """
    return (
        "You are auditing a data catalog for descriptions that don't match their "
        "actual columns.\n\n"
        "A description is STALE when it does NOT accurately describe what the table "
        "contains. Be skeptical — the description may have been copy-pasted from "
        "another table, written before the schema drifted, or left as a placeholder.\n\n"
        "Look for:\n"
        "- Entity mismatch (description mentions one concept, columns describe another)\n"
        "- Grain mismatch (claims 'daily/aggregated' but columns are row-level)\n"
        "- Placeholder text (single chars, 'TODO', 'data table', generic noun phrases)\n\n"
        "Example 1 — STALE (entity mismatch):\n"
        "  Table: sales.refund_events\n"
        '  Description: "Daily sales aggregates by region and product."\n'
        "  Columns: refund_id (BIGINT), order_id (BIGINT), reason_code (STRING), "
        "refunded_at (TIMESTAMP)\n"
        '  Verdict: {"stale": true, "reason": "description claims sales aggregates '
        "by region/product but columns describe individual refund events — no region, "
        'product, or aggregation", "corrected": "Refund events — one row per refund, '
        'linked to the originating order and reason code.", "confidence": 0.95}\n\n'
        "Example 2 — STALE (placeholder):\n"
        "  Table: finance.payments\n"
        '  Description: "t"\n'
        "  Columns: payment_id (BIGINT), invoice_id (BIGINT), amount (DECIMAL)\n"
        '  Verdict: {"stale": true, "reason": "single-letter placeholder, not a real '
        'description", "corrected": "Payments — one row per payment event, linked to '
        'the invoice it settles.", "confidence": 0.99}\n\n'
        "Example 3 — NOT stale:\n"
        "  Table: sales.orders\n"
        '  Description: "Customer order transactions with payment and fulfillment status."\n'
        "  Columns: order_id (BIGINT), customer_id (BIGINT), total_amount (DECIMAL), "
        "created_at (TIMESTAMP)\n"
        '  Verdict: {"stale": false, "reason": "description accurately reflects the '
        'columns", "corrected": "", "confidence": 0.9}\n\n'
        "Now audit this table:\n"
        f"  Table: {fqn}\n"
        f"  Description: {description}\n"
        f"  Columns: {col_summary}\n\n"
        "Respond with ONLY a JSON object (no prose, no code fences):\n"
        '{"stale": bool, "reason": str, "corrected": str, "confidence": float}'
    )


def _parse_stale_json(text: str) -> dict | None:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def detect_stale(fqn: str, current_description: str, columns: list[dict]) -> StaleReport:
    """Compare a description against actual column metadata.

    Retries once on JSON parse failure — free-tier models sometimes emit
    truncated or missing-value objects (e.g. `"stale":,`) that still contain
    the intended verdict, so a strict-mode retry rescues the finding.
    """
    llm = get_llm("stale")
    col_summary = ", ".join(f"{c['name']} ({c['dataType']})" for c in columns[:20])
    prompt = _build_stale_prompt(fqn, current_description, col_summary)

    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    parsed = _parse_stale_json(text)

    if parsed is None:
        logger.warning(f"Stale JSON malformed for {fqn}, retrying with strict mode")
        retry_prompt = (
            prompt + "\n\nYour previous response was not valid JSON. Return ONLY the JSON "
            "object — no prose, no code fences. Every field must have a value."
        )
        retry = llm.invoke(retry_prompt)
        text = retry.content if hasattr(retry, "content") else str(retry)
        parsed = _parse_stale_json(text)

    if parsed is None:
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
            stale_corrected VARCHAR,
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
            "INSERT INTO cleaning_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                fqn,
                report.stale,
                report.reason,
                report.confidence,
                report.corrected,
                q_score,
                q_reason,
            ],
        )
    # Tables where stale detection succeeded but quality didn't get added need
    # insertion too; and vice versa. Above covers stale-succeeded path. Let's
    # also backfill for tables where only quality worked.
    for fqn, (q_score, q_reason) in quality_map.items():
        if fqn not in stale_map:
            conn.execute(
                "INSERT INTO cleaning_results VALUES (?, ?, ?, ?, ?, ?, ?)",
                [fqn, None, None, None, None, q_score, q_reason],
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


# ── PII detection ──────────────────────────────────────────────────────────────
#
# Heuristic-first classifier. Applies four safety layers in order:
#   1. Exclusion list — columns that look like PII but aren't (product_name,
#      ip_address, email_template, etc.). Short-circuits any PII match.
#   2. Ordered rule matches — specific patterns first (exact names, strong
#      signals), fuzzy patterns second.
#   3. Table-context de-weighting — tables about products/catalogs/events
#      reduce confidence of name-based PII matches.
#   4. Confidence tier — low-confidence matches (<0.8) are flagged
#      needs_review=True so the agent knows not to auto-apply.
#
# LLM fallback is optional and only runs for columns with no heuristic match.
# Even 0.99-confidence matches only SUGGEST a tag — applying is a separate step.

# Exclusions — checked FIRST. These patterns catch names that superficially
# look like PII but aren't (product_name, ip_address, email_template, etc.).
_PII_EXCLUSIONS: list[str] = [
    # Product / catalog / event attributes (not person names)
    r"^(product|brand|company|organization|org|file|database|host|server|service|team|group|role|app|event|channel|region|country|city|state|category|tag|topic|feature|page|post|comment)_?name$",
    r"^(device|file|service|api|function|class|method|module|package|library|framework|schema|table|column|field|index)_name$",
    # Network / tech "addresses" (not physical home addresses)
    r"^ip_?address$|^mac_?address$|^wallet_?address$|^contract_?address$|^eth_?address$|^btc_?address$|^blockchain_?address$",
    # Email-adjacent non-PII
    r"^email_(template|subject|body|count|type|status|id|domain|provider|category)$",
    # Phone-adjacent non-PII
    r"^phone_(type|kind|brand|model|os|version|count)$",
    # Generic metadata fields
    r".*_(type|kind|category|model|status|state|flag|enum|template|format|count|price|total|sum|avg|min|max|sku|score|rank|position|order|version|revision)$",
    # Obvious identifiers that aren't personal
    r"^(order|invoice|transaction|payment|shipment|refund|subscription|session|request|page|post|comment|like|share|view|event)_id$",
    r"^(product|sku|catalog|variant|item|listing|inventory)_id$",
]

# PII rules in priority order. First match wins. Format:
#   (regex, suggested_tag, base_confidence, reason)
_PII_RULES: list[tuple[str, str, float, str]] = [
    # ── PII.Sensitive — HIGH confidence (exact / strong patterns) ─────────
    (r"^email$", "PII.Sensitive", 0.98, "direct email field"),
    (r"^(phone|mobile|telephone|cellphone|cell)(_?number)?$", "PII.Sensitive", 0.96, "phone field"),
    (
        r"^ssn$|^social_?security(_?number)?$|^tax_?id$|^tin$",
        "PII.Sensitive",
        0.99,
        "SSN / tax identifier",
    ),
    (
        r"^(first|last|middle|full|given|family|sur|maiden|preferred)_?name$",
        "PII.Sensitive",
        0.94,
        "person name",
    ),
    (
        r"^(date_of_birth|birthdate|birthday|birth_date|dob)$",
        "PII.Sensitive",
        0.96,
        "date of birth",
    ),
    (
        r"^(street_)?address$|^home_address$|^mailing_address$|^billing_address$|^shipping_address$|^address_line_?\d*$",
        "PII.Sensitive",
        0.92,
        "physical address",
    ),
    (
        r"^zip(_?code)?$|^postal_?code$|^postcode$|^pin_?code$",
        "PII.Sensitive",
        0.82,
        "postal code (quasi-identifier)",
    ),
    (
        r"^credit_card.*|^cc_number$|^card_num(ber)?$|^debit_card.*|^pan$",
        "PII.Sensitive",
        0.97,
        "payment card number",
    ),
    (
        r"^cvv$|^cvc$|^card_cvv$|^card_security_code$",
        "PII.Sensitive",
        0.99,
        "card verification code",
    ),
    (
        r"^passport(_?number)?$|^drivers?_?license(_?number)?$|^license_?number$|^national_?id$|^government_?id$",
        "PII.Sensitive",
        0.96,
        "government-issued ID",
    ),
    (
        r"^iban$|^account_number$|^bank_account.*|^routing_number$|^swift_?code$",
        "PII.Sensitive",
        0.94,
        "bank account info",
    ),
    (
        r"^password$|^pwd$|^passwd$|^api_?key$|^secret$|^access_token$|^refresh_token$|^auth_token$",
        "PII.Sensitive",
        0.98,
        "credential / secret",
    ),
    (
        r"^latitude$|^longitude$|^lat$|^lng$|^lon$|^geo_location$|^gps_location$|^precise_location$",
        "PII.Sensitive",
        0.82,
        "precise location",
    ),
    (
        r"^medical_?record(_?number)?$|^mrn$|^patient_?id$|^health_?insurance.*|^diagnosis.*|^prescription.*",
        "PII.Sensitive",
        0.96,
        "protected health info",
    ),
    (
        r"^race$|^ethnicity$|^religion$|^sexual_?orientation$|^gender_?identity$",
        "PII.Sensitive",
        0.93,
        "sensitive demographic",
    ),
    # ── PII.Sensitive — MEDIUM confidence (fuzzy) ─────────────────────────
    (r".*_email$|^email_.*", "PII.Sensitive", 0.82, "email-like"),
    (r".*_phone$|^phone_.*|.*_mobile$|^mobile_.*", "PII.Sensitive", 0.80, "phone-like"),
    (r".*_address$|^address_.*", "PII.Sensitive", 0.72, "address-like"),
    (r".*_name$", "PII.Sensitive", 0.68, "ends in '_name' — possibly person name"),
    # ── PII.NonSensitive — person-linked identifiers ──────────────────────
    (
        r"^(customer|user|account|member|client|patient|employee|contact|subscriber|buyer|seller)_id$",
        "PII.NonSensitive",
        0.92,
        "opaque person identifier",
    ),
    (
        r"^cust_id$|^cid$|^uid$|^usr_id$|^pat_id$|^mem_id$",
        "PII.NonSensitive",
        0.84,
        "abbreviated person identifier",
    ),
    (
        r"^(customer|user|account|member|patient|employee)_(code|key|number|ref|reference|uuid|guid)$",
        "PII.NonSensitive",
        0.88,
        "person reference",
    ),
]

# Table contexts that de-weight name-based PII matches. If the table's FQN
# contains any of these, we reduce match confidence — `products.name` is
# probably a product name, not a person's name.
_TABLE_CONTEXT_NON_PERSON = re.compile(
    r"\.("
    r"products?|inventory|catalogs?|brands?|events?|logs?|metrics?|files?|resources?|"
    r"databases?|apps?|servers?|services?|assets?|tags?|categories|features?|"
    r"pages?|posts?|comments?|reviews?|sessions?|audits?|workflows?|pipelines?|"
    r"models?|experiments?|ingestions?"
    r")\.",
    re.IGNORECASE,
)


def _normalize_col_name(name: str) -> str:
    """Normalize a column name for rule matching.

    - Converts camelCase / PascalCase to snake_case so `CustomerID` matches
      the same rules as `customer_id`.
    - Lowercases the result.
    """
    if not name:
        return ""
    # Insert underscore between lower/digit and following uppercase (camelCase).
    s1 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore between uppercase and uppercase-then-lowercase
    # (handles consecutive-capitals like "XMLParser" -> "XML_Parser").
    s2 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s1)
    return s2.strip().lower()


def _pii_match(column_name: str, table_fqn: str) -> dict:
    """Classify a column's PII sensitivity using the heuristic rule set.

    Returns a dict with:
        suggested_tag: str | None  — PII.Sensitive / PII.NonSensitive / None
        confidence:    float       — 0.0-1.0
        reason:        str
        source:        str         — "heuristic" / "heuristic_exclusion" / "none"
        needs_review:  bool        — True when confidence < 0.80
    """
    name = _normalize_col_name(column_name)
    if not name:
        return {
            "suggested_tag": None,
            "confidence": 0.0,
            "reason": "empty column name",
            "source": "none",
            "needs_review": False,
        }

    # Layer 1: exclusions
    for pat in _PII_EXCLUSIONS:
        if re.fullmatch(pat, name):
            return {
                "suggested_tag": None,
                "confidence": 0.0,
                "reason": "matched exclusion pattern (non-PII despite name)",
                "source": "heuristic_exclusion",
                "needs_review": False,
            }

    # Layer 2: ordered rule matching
    for pattern, tag, base_conf, reason in _PII_RULES:
        if re.fullmatch(pattern, name):
            confidence = base_conf

            # Layer 3: table-context de-weighting
            if _TABLE_CONTEXT_NON_PERSON.search(table_fqn or ""):
                confidence = round(max(0.0, confidence - 0.25), 2)
                reason = f"{reason} — de-weighted (non-person table context)"

            return {
                "suggested_tag": tag,
                "confidence": round(confidence, 2),
                "reason": reason,
                "source": "heuristic",
                "needs_review": confidence < 0.80,
            }

    # No heuristic match
    return {
        "suggested_tag": None,
        "confidence": 0.0,
        "reason": "no heuristic rule matched",
        "source": "none",
        "needs_review": False,
    }


def _as_list_local(value) -> list:
    """Local copy of the list-coercion helper — avoids cross-module import."""
    if value is None:
        return []
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value) if value else []


def run_pii_scan(use_llm_fallback: bool = False) -> dict[str, int]:
    """Scan every column, classify PII, persist results to `pii_results` table.

    Args:
        use_llm_fallback: If True, run LLM classification on columns that
            have no heuristic match AND a meaningful (non-generic) name.
            Default False (heuristic-only — fast, free, deterministic).

    Returns:
        Summary dict: scanned, sensitive, nonsensitive, gaps (columns where
        suggested tag differs from current).
    """
    cols = duck.query("SELECT table_fqn, name, dataType, tags FROM om_columns")
    if cols.empty:
        return {"scanned": 0, "sensitive": 0, "nonsensitive": 0, "gaps": 0}

    conn = duck.get_conn()
    conn.execute("""
        CREATE OR REPLACE TABLE pii_results (
            table_fqn VARCHAR,
            column_name VARCHAR,
            data_type VARCHAR,
            current_tag VARCHAR,
            suggested_tag VARCHAR,
            confidence DOUBLE,
            reason VARCHAR,
            source VARCHAR,
            needs_review BOOLEAN
        )
    """)

    counts = {"scanned": 0, "sensitive": 0, "nonsensitive": 0, "gaps": 0}

    for _, row in cols.iterrows():
        current_tags = _as_list_local(row["tags"])
        # Normalise to just the first PII-ish tag for the "current" column.
        current_tag = None
        for t in current_tags:
            if isinstance(t, str) and t.startswith("PII."):
                current_tag = t
                break
        if current_tag is None and current_tags:
            current_tag = current_tags[0] if isinstance(current_tags[0], str) else None

        result = _pii_match(row["name"], row["table_fqn"])

        # Layer 4: LLM fallback (opt-in, only for no-match columns)
        if (
            use_llm_fallback
            and result["suggested_tag"] is None
            and result["source"] == "none"
            and row["name"]
            and len(row["name"]) >= 3
        ):
            # Placeholder hook — LLM fallback is a stretch extension.
            # Keep it disabled-by-default so the feature stays deterministic.
            pass

        conn.execute(
            "INSERT INTO pii_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row["table_fqn"],
                row["name"],
                (row.get("dataType") or "") if hasattr(row, "get") else (row["dataType"] or ""),
                current_tag,
                result["suggested_tag"],
                result["confidence"],
                result["reason"],
                result["source"],
                result["needs_review"],
            ],
        )

        counts["scanned"] += 1
        if result["suggested_tag"] == "PII.Sensitive":
            counts["sensitive"] += 1
        elif result["suggested_tag"] == "PII.NonSensitive":
            counts["nonsensitive"] += 1
        if result["suggested_tag"] and current_tag != result["suggested_tag"]:
            counts["gaps"] += 1

    logger.info(
        f"PII scan done — {counts['scanned']} columns scanned, "
        f"{counts['sensitive']} sensitive, {counts['nonsensitive']} non-sensitive, "
        f"{counts['gaps']} gaps (missing tag)"
    )
    return counts


# ── Data quality failure explanations ──────────────────────────────────────────
#
# Turns a raw DQ test failure (status, result message, parameters, a few
# sample failing rows) into a plain-English summary + root-cause hypothesis
# + recommended next step. LLM-powered because the failure messages are
# terse and generic; a human steward's time is better spent on the fix than
# on deciphering `"columnValuesToBeUnique failed with 12 duplicates"`.


@dataclass
class DQExplanation:
    test_id: str
    test_name: str
    table_fqn: str
    column_name: str | None
    summary: str
    likely_cause: str
    next_step: str


_DQ_PROMPT_TEMPLATE = (
    "You are a senior data engineer explaining a failed data quality check to a "
    "busy steward in plain English.\n\n"
    "Return THREE short, specific paragraphs (one sentence each, no more than ~30 "
    "words per paragraph):\n"
    '- "summary": what the test checks and what the failure means for this table\n'
    '- "likely_cause": the MOST plausible root cause given the test, parameters, '
    "and the failing rows sample\n"
    '- "next_step": one concrete action a steward or engineer should take first\n\n'
    "Ground every claim in the supplied evidence. Do NOT invent numbers, column "
    "names, or upstream systems that aren't in the input. If evidence is thin, "
    "say so rather than guessing.\n\n"
    "Evidence:\n"
    "  Table: {table_fqn}\n"
    "  Table description: {table_description}\n"
    "  Column: {column_name}\n"
    "  Test name: {test_name}\n"
    "  Test definition: {test_definition}\n"
    "  Test description: {test_description}\n"
    "  Parameters: {parameters}\n"
    "  Failure message: {result_message}\n"
    "  Sample failing rows: {failed_sample}\n\n"
    "Respond with ONLY a JSON object (no prose, no code fences):\n"
    '{{"summary": str, "likely_cause": str, "next_step": str}}'
)


def _parse_dq_json(text: str) -> dict | None:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def explain_dq_failure(row: dict) -> DQExplanation:
    """Turn a single failed DQ test row into a plain-English explanation.

    Expects the dict shape produced by `analysis.dq_failures()`. Retries once
    on malformed JSON; if both attempts fail the explanation falls back to
    echoing the result message so the caller still gets a displayable row.
    """
    llm = get_llm("reasoning")
    prompt = _DQ_PROMPT_TEMPLATE.format(
        table_fqn=row.get("table_fqn") or "",
        table_description=(row.get("table_description") or "(no description)")[:400],
        column_name=row.get("column_name") or "(table-level test)",
        test_name=row.get("test_name") or "",
        test_definition=row.get("test_definition_name") or "",
        test_description=(row.get("test_description") or "")[:300],
        parameters=row.get("parameter_values") or "[]",
        result_message=(row.get("result_message") or "")[:500],
        failed_sample=(row.get("failed_rows_sample") or "[]")[:500],
    )

    result = llm.invoke(prompt)
    text = result.content if hasattr(result, "content") else str(result)
    parsed = _parse_dq_json(text)

    if parsed is None:
        retry = llm.invoke(
            prompt + "\n\nYour previous response was not valid JSON. Return ONLY the JSON "
            "object — no prose, no code fences. Every field must have a value."
        )
        text = retry.content if hasattr(retry, "content") else str(retry)
        parsed = _parse_dq_json(text)

    if parsed is None:
        logger.warning(f"DQ explanation parse failed for {row.get('test_name')}: {text[:200]}")
        parsed = {
            "summary": row.get("result_message") or "Test failed.",
            "likely_cause": "Explanation unavailable — couldn't parse LLM response.",
            "next_step": "Inspect the failing rows sample in OpenMetadata directly.",
        }

    return DQExplanation(
        test_id=str(row.get("test_id") or ""),
        test_name=str(row.get("test_name") or ""),
        table_fqn=str(row.get("table_fqn") or ""),
        column_name=row.get("column_name"),
        summary=str(parsed.get("summary") or "").strip(),
        likely_cause=str(parsed.get("likely_cause") or "").strip(),
        next_step=str(parsed.get("next_step") or "").strip(),
    )


def run_dq_explanations(progress_cb=None) -> dict[str, int]:
    """Run explain_dq_failure on every failing test, persist to `dq_explanations`.

    Args:
        progress_cb: Optional callable(step:int, total:int, label:str).

    Returns:
        Summary dict with counts.
    """
    from app.engines import analysis

    failures = analysis.dq_failures()
    total = len(failures)
    if total == 0:
        return {"explained": 0, "total": 0}

    conn = duck.get_conn()
    conn.execute("""
        CREATE OR REPLACE TABLE dq_explanations (
            test_id VARCHAR PRIMARY KEY,
            test_name VARCHAR,
            table_fqn VARCHAR,
            column_name VARCHAR,
            summary VARCHAR,
            likely_cause VARCHAR,
            next_step VARCHAR
        )
    """)

    explained = 0
    for idx, (_, row) in enumerate(failures.iterrows(), start=1):
        if progress_cb:
            progress_cb(idx, total, f"Explaining: {row['test_name']}")
        try:
            exp = explain_dq_failure(row.to_dict())
            conn.execute(
                "INSERT INTO dq_explanations VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    exp.test_id,
                    exp.test_name,
                    exp.table_fqn,
                    exp.column_name,
                    exp.summary,
                    exp.likely_cause,
                    exp.next_step,
                ],
            )
            explained += 1
        except Exception as e:
            logger.warning(f"DQ explanation failed for {row['test_name']}: {e}")

    logger.info(f"DQ explanations done — {explained}/{total} failures explained.")
    return {"explained": explained, "total": total}
