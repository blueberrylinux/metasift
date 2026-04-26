"""Stress-test every MetaSift agent tool by calling each one directly.

Hits the same wrapped-for-safety LangChain tools the agent uses, with
representative arguments for each. Reports pass/fail with first 200 chars
of output. Exits non-zero on any failure (returned text starting with
"Tool '...' failed").

Run: uv run python scripts/stress_tools.py
"""

from __future__ import annotations

import sys
import time
import traceback
from typing import Any

from app.clients.duck import refresh_all
from app.engines.tools import get_tools

# Representative argument sets for each tool. Picks a real demo FQN where
# possible; falls back to a known-good schema otherwise.
DEMO_FQN = "metasift_demo_db.analytics.users.customer_profiles"
DEMO_SCHEMA = "metasift_demo_db.analytics.users"

ARGS_BY_TOOL: dict[str, list[tuple[tuple[Any, ...], dict[str, Any]]]] = {
    "list_services": [((), {})],
    "list_schemas": [((), {})],
    "list_tables": [((), {}), ((), {"schema_name": "users"})],
    "documentation_coverage": [((), {})],
    "find_tag_conflicts": [((), {})],
    "composite_score": [((), {})],
    "find_naming_inconsistencies": [((), {}), ((), {"similarity_threshold": 60})],
    "check_description_staleness": [
        ((), {"fqn": DEMO_FQN}),
        ((), {"fqn": "nonsense.bad.fqn.table"}),
    ],
    "score_descriptions": [((), {}), ((), {"limit": 3})],
    "about_metasift": [
        ((), {}),
        ((), {"topic": "composite_score"}),
        ((), {"topic": "capabilities"}),
        ((), {"topic": "differentiators"}),
        ((), {"topic": "setup"}),
        ((), {"topic": "doesnotexist"}),
    ],
    "ownership_report": [((), {})],
    "impact_check": [
        ((), {"fqn": DEMO_FQN}),
        ((), {"fqn": "nonsense.bad.fqn.table"}),
    ],
    "impact_catalog": [((), {}), ((), {"limit": 3}), ((), {"limit": 100})],
    "pii_propagation": [((), {})],
    "dq_impact": [
        ((), {"fqn": DEMO_FQN}),
        ((), {"fqn": "nonsense.bad.fqn.table"}),
    ],
    "dq_risk_catalog": [((), {}), ((), {"limit": 3})],
    "dq_failures_summary": [((), {}), ((), {"schema_name": "users"})],
    "dq_explain": [
        ((), {"fqn": DEMO_FQN}),
        ((), {"fqn": "nonsense.bad.fqn.table"}),
    ],
    "recommend_dq_tests": [
        ((), {"fqn": DEMO_FQN}),
        ((), {"fqn": "nonsense.bad.fqn.table"}),
    ],
    "find_dq_gaps": [((), {}), ((), {"severity": "critical"}), ((), {"severity": "junk"})],
    # generate_description_for hits the LLM — single shot only.
    "generate_description_for": [((), {"fqn": DEMO_FQN})],
    # auto_document_schema also LLM-heavy. Pass a known schema name.
    "auto_document_schema": [((), {"schema_name": "users"})],
    # Write tools — DRY-RUN style: bad FQN so the SDK call returns a clean
    # error rather than mutating the catalog. Exercises the error path.
    "apply_description": [
        ((), {"fqn": "nonsense.bad.fqn.table", "description": "test"}),
    ],
    "scan_pii": [((), {})],
    "find_pii_gaps": [((), {}), ((), {"min_confidence": 0.5})],
    "apply_pii_tag": [
        (
            (),
            {
                "table_fqn": "nonsense.bad.fqn.table",
                "column_name": "x",
                "tag_fqn": "PII.Sensitive",
            },
        )
    ],
    "run_sql": [
        ((), {"query": "SELECT 1 AS one"}),
        ((), {"query": "SELECT COUNT(*) FROM om_tables"}),
        ((), {"query": "DROP TABLE om_tables"}),  # write — should be rejected
        ((), {"query": "this is not sql"}),
    ],
}


def _truncate(s: str, n: int = 200) -> str:
    s = s.replace("\n", " ⏎ ")
    return s if len(s) <= n else s[:n] + " …"


def main() -> int:
    print("Refreshing DuckDB cache before stress test …")
    refresh_all()
    print()

    tools = {t.name: t for t in get_tools()}
    print(f"Loaded {len(tools)} local tools.\n")

    missing = sorted(set(tools) - set(ARGS_BY_TOOL))
    extra = sorted(set(ARGS_BY_TOOL) - set(tools))
    if missing:
        print(f"⚠ Tools not in stress matrix: {missing}")
    if extra:
        print(f"⚠ Stress matrix has unknown tools: {extra}")

    failures: list[str] = []
    suspicious: list[str] = []

    for name in sorted(tools):
        if name not in ARGS_BY_TOOL:
            continue
        runs = ARGS_BY_TOOL[name]
        for _args, kwargs in runs:
            label = f"{name}({', '.join(f'{k}={v!r}' for k, v in kwargs.items())})"
            t0 = time.perf_counter()
            try:
                # The @tool decorator returns a langchain BaseTool. Use .invoke()
                # with the kwargs dict, which is what the agent calls.
                result = tools[name].invoke(kwargs or {})
                elapsed = (time.perf_counter() - t0) * 1000
                text = result if isinstance(result, str) else str(result)
                # _wrap_for_safety converts exceptions into "Tool '...' failed"
                # strings — flag those even though the call returned successfully.
                if text.startswith(f"Tool '{name}' failed"):
                    failures.append(label)
                    print(f"❌ {label}  [{elapsed:.0f}ms]")
                    print(f"   {_truncate(text, 300)}")
                else:
                    looks_iffy = (
                        "traceback" in text.lower() or "internal server error" in text.lower()
                    )
                    tag = "⚠" if looks_iffy else "✓"
                    if looks_iffy:
                        suspicious.append(label)
                    print(f"{tag} {label}  [{elapsed:.0f}ms]")
                    print(f"   {_truncate(text)}")
            except Exception as e:
                failures.append(label)
                elapsed = (time.perf_counter() - t0) * 1000
                print(f"💥 {label}  [{elapsed:.0f}ms]  RAISED {type(e).__name__}: {e}")
                traceback.print_exc()

    print()
    print("=" * 72)
    print(f"Summary: {len(failures)} hard fails, {len(suspicious)} suspicious")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
    if suspicious:
        print("Suspicious (look like server-error spillage):")
        for s in suspicious:
            print(f"  - {s}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
