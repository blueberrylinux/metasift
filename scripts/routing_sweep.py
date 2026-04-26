"""Agent routing sweep — for each tool, send its natural-language prompt
through the live FastAPI /chat/stream and verify the FIRST tool_call frame
invokes the expected tool name.

Complements scripts/stress_tools.py (which verifies each tool's direct
invocation works) and scripts/port_parity.py (which verifies the React
and Streamlit paths agree). This script asks the question the user would
ask and confirms the agent routes correctly.

Run: uv run python scripts/routing_sweep.py [--host http://127.0.0.1:8000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

# Each row: (expected_first_tool, natural_question)
# A few tools allow multiple acceptable first tools — comma-separated alternates.
SWEEP: list[tuple[str, str]] = [
    # Discovery
    ("list_services", "what data sources do I have?"),
    ("list_schemas", "list my schemas"),
    ("list_tables", "what tables are in the users schema?"),
    ("about_metasift", "what is MetaSift?"),
    ("run_sql", "run sql: select count(*) from om_tables"),
    # Analysis
    ("composite_score", "what's my composite score?"),
    ("documentation_coverage", "what's my documentation coverage?"),
    ("ownership_report", "who owns what?"),
    ("impact_check", "blast radius of metasift_demo_db.analytics.users.customer_profiles"),
    ("impact_catalog", "blast-radius top 10"),
    ("pii_propagation", "where does PII propagate?"),
    # Cleaning
    (
        "check_description_staleness",
        "is the description of metasift_demo_db.analytics.sales.refund_events still accurate?",
    ),
    ("find_tag_conflicts", "find tag conflicts in my catalog"),
    ("score_descriptions", "score my table descriptions"),
    ("find_naming_inconsistencies", "find naming inconsistencies"),
    # Stewardship
    (
        "generate_description_for",
        "draft a description for metasift_demo_db.analytics.sales.cart_abandonments",
    ),
    ("auto_document_schema", "auto-document the sales schema"),
    ("scan_pii", "run a PII scan on my catalog"),
    ("find_pii_gaps", "show me PII gaps"),
    # DQ
    ("dq_failures_summary", "summarize DQ failures"),
    (
        "dq_explain",
        "explain DQ failures on metasift_demo_db.analytics.users.customer_profiles",
    ),
    (
        "recommend_dq_tests",
        "recommend DQ tests for metasift_demo_db.analytics.sales.orders",
    ),
    ("find_dq_gaps", "show me DQ gaps across the catalog"),
    (
        "dq_impact",
        "DQ blast radius for metasift_demo_db.analytics.users.customer_profiles",
    ),
    ("dq_risk_catalog", "rank the catalog by DQ risk"),
    # MCP
    ("search_metadata", "search OpenMetadata for tables containing customer"),
    (
        "get_entity_details",
        "show full OpenMetadata record for metasift_demo_db.analytics.users.customer_profiles",
    ),
    (
        "get_entity_lineage",
        "show upstream and downstream lineage of metasift_demo_db.analytics.users.customer_profiles",
    ),
    # Write tools — tested via stress_tools.py path with bad-FQN; routing
    # here would require a confirm-flow that's hard to trigger in one shot.
    # Skipped: apply_description, apply_pii_tag.
]


def first_tool_call(host: str, question: str, timeout_s: float = 60.0) -> str | None:
    """POST /chat/stream and pull the FIRST `tool_call` event's name. Returns
    None if no tool was invoked (agent answered from cache / refused)."""
    url = f"{host.rstrip('/')}/api/v1/chat/stream"
    body = {"question": question, "history": []}
    try:
        with httpx.stream(
            "POST",
            url,
            json=body,
            headers={"Accept": "text/event-stream"},
            timeout=timeout_s,
        ) as r:
            r.raise_for_status()
            event = None
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("event: "):
                    event = line[7:].strip()
                elif line.startswith("data: "):
                    if event == "tool_call":
                        try:
                            payload = json.loads(line[6:])
                            return payload.get("name")
                        except json.JSONDecodeError:
                            continue
                    elif event in ("final", "error"):
                        return None
        return None
    except Exception as e:
        print(f"  EXC: {e}")
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("--filter", default="", help="Substring filter on tool name")
    args = parser.parse_args()

    rows = [(t, q) for t, q in SWEEP if args.filter in t]
    print(f"Testing {len(rows)} tools at {args.host}\n")

    pass_count = 0
    fail_rows = []

    for expected, question in rows:
        t0 = time.perf_counter()
        actual = first_tool_call(args.host, question)
        elapsed = (time.perf_counter() - t0) * 1000
        ok = actual == expected
        sym = "✓" if ok else "✗"
        print(f"{sym} {expected:32} got={str(actual):28} [{elapsed:5.0f}ms]  q={question[:60]}")
        if ok:
            pass_count += 1
        else:
            fail_rows.append((expected, actual, question))

    print()
    print("=" * 80)
    print(f"Pass: {pass_count}/{len(rows)}")
    if fail_rows:
        print("\nFailures:")
        for exp, got, q in fail_rows:
            print(f"  expected={exp!r}, got={got!r}, q={q!r}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
