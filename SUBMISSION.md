# MetaSift — Hackathon Submission

**Track:** WeMakeDevs × OpenMetadata — *"Back to the Metadata"*

**Repo:** <https://github.com/blueberrylinux/metasift>

**One-line pitch:** An AI-powered metadata analyst and steward that sifts through your OpenMetadata catalog to analyze health, clean dirty metadata, and automate stewardship — with plain-English DQ explanations, lineage-aware governance, and a composite score that measures what documentation coverage alone can't.

---

## Why this project exists

Data catalogs accumulate metadata debt the way codebases accumulate tech debt. Teams spend weeks documenting tables, classifying PII, and assigning ownership — but nobody fact-checks what's already there. Descriptions go stale as tables get repurposed. The same column gets tagged differently across schemas. Naming conventions drift. Data-quality tests fail in silence. The result: a catalog that looks healthy on paper (65% documented!) but is full of inaccurate, inconsistent, and misleading metadata.

Existing tools generate new metadata (auto-documentation) or keep metadata fresh (active syncing). **Nobody audits the quality of existing metadata.** MetaSift does — and extends that same cleaning lens over lineage, PII propagation, and DQ test failures.

## Hackathon issues addressed

MetaSift directly addresses **six issues** from the hackathon board:

| Issue | Title | How MetaSift covers it | Where to look |
| --- | --- | --- | --- |
| [#26608](https://github.com/open-metadata/OpenMetadata/issues/26608) | Conversational Data Catalog Chat App | **Stew** — full chat experience with 27 local tools + 3 allowlisted MCP tools (30 total), streamed responses over Server-Sent Events, "Show your work" tool-trace expander per reply, natural-language routing to every MetaSift capability | `app/engines/agent.py`, `app/engines/tools.py` |
| [#26659](https://github.com/open-metadata/OpenMetadata/issues/26659) | Human-Readable Explanations for Failed DQ Checks | Ingest DQ test cases, LLM writes three fields per failure: **Summary** · **Likely cause** · **Suggested fix**. Cached in `dq_explanations`. Synthetic 7-row fixture provides a demo path when OM has no configured tests. | `app/engines/cleaning.py::explain_dq_failure`, `app/clients/duck.py::_fetch_test_cases`, `scripts/dq_fixtures.json` |
| [#26660](https://github.com/open-metadata/OpenMetadata/issues/26660) | AI-Powered Data Quality Recommendations | `recommend_dq_tests(fqn)` — grounds the LLM in columns + tags + existing tests, proposes severity-ranked DQ tests that should exist but don't. Constrained to a 12-definition OM-test allowlist so outputs are always valid. Filters duplicates. Catalog-wide `run_dq_recommendations`. | `app/engines/stewardship.py::recommend_dq_tests`, `_DQ_TEST_CATALOG` |
| [#26658](https://github.com/open-metadata/OpenMetadata/issues/26658) | Data Quality Checks Impact | `dq_impact(fqn)` — multiplicative risk score combining failing tests × downstream blast radius × PII amplifier. Zero when either side is zero (contained). `dq_risk_catalog` ranks the catalog. 🎯 DQ risk viz tab renders bars with a PII-amplified color ramp. | `app/engines/analysis.py::dq_impact`, `dq_risk_ranking` |
| [#26661](https://github.com/open-metadata/OpenMetadata/issues/26661) | Propose Automated Fixes for Failed DQ Checks | Every DQ explanation includes a **fix_type** classifier (schema_change / etl_investigation / data_correction / upstream_fix / other) + the prose next-step IS the proposed fix. Rendered as colored chips alongside "Suggested fix" labels in both the viz and the agent markdown output. | `app/engines/cleaning.py::DQExplanation.fix_type`, `tools.py::_FIX_TYPE_CHIPS` |
| [#25146](https://github.com/open-metadata/OpenMetadata/issues/25146) | Lineage Governance Layer | **🛡️ Governance** viz tab — same DAG layout as the standard lineage view, recolored by PII status (🔴 origin · 🟠 tainted · ⚪ clean). Propagation edges drawn red, non-propagation faded gray. Single recursive CTE seeded at every origin computes the transitive taint. | `app/engines/analysis.py::pii_propagation`, `viz.py::governance_lineage_dag` |

Beyond those six: MetaSift also ships the chat app and a full cleaning-engine suite that predates the DQ track (stale detection, quality scoring, tag-conflict finder, naming-drift clusters, PII heuristics, composite score, blast radius, stewardship leaderboard, orphan detection, review queue, executive report).

## v0.1 → v0.2 — porting from Streamlit to FastAPI + React

MetaSift shipped twice during the hackathon. **v0.1** (April 21, tagged
[`v0.1-streamlit`](https://github.com/blueberrylinux/metasift/releases/tag/v0.1-streamlit))
was a Streamlit app: dashboard left, Stew chat right, all four engines wired
end-to-end. It worked, but Streamlit's whole-page rerun model was a poor fit
for streaming chat, multi-step scans, and the kind of dense viz tabs the
project had grown into.

**v0.2** (April 26 — this submission) is a full port to FastAPI + React 19 +
TanStack Query, completed in 5 calendar days across 70+ commits on
`port/fastapi-react` (April 21 v0.1 → April 26 v0.2).

The point worth flagging: **the engines didn't change.** All four — Analysis,
Stewardship, Cleaning, Interface — and the LangChain agent with its 27 local
tools + 3 MCP tools moved across untouched. What got rewritten was the UI
surface: the Streamlit dashboard became React components driven by a
typed FastAPI port (`app/api/`), Server-Sent Events replaced Streamlit
session state for chat streaming, a SQLite store replaced `st.session_state`
for conversation history + review-queue durability, and the chat router got
a watchdog timeout, an abortable worker thread, and a sanitized error path
that doesn't leak server internals to the client.

Two things this proves:

1. **Engine decoupling held.** The same `app.engines.*` modules served two
   completely different presentation layers. Anyone wanting to bolt MetaSift
   onto Slack, an MCP client, or a notebook can do it without touching
   the analytical core.
2. **Iteration matters more than first-shot polish.** The Streamlit version
   was already "shipped" by hackathon-submission standards; rebuilding
   anyway — on day 5 of 7 — was the right call because the demo this
   project deserves needed a UI that didn't blink the whole page on every
   message.

To audit the journey: `git checkout v0.1-streamlit` runs the Streamlit
version (`make stack-up && make seed && make run`), `main`/`port/fastapi-react`
runs the React app (`make api && cd web && npm run dev`).

## What's shipped (feature inventory)

### Analysis engine

- **Composite Score** — weighted: 30% coverage + 30% accuracy + 20% consistency + 20% quality
- **Documentation coverage** per schema
- **Blast-radius / impact analysis** — direct + transitive downstream, PII-amplified `impact_score`
- **Top-N impact ranking** across the whole catalog
- **Tag conflicts** — columns named X tagged differently across tables
- **Ownership breakdown** — per-team scorecard (coverage %, PII footprint, avg quality)
- **Orphan detection** — tables with no owner
- **PII propagation** — origin / tainted / clean classification + propagation edge set (governance)
- **DQ failures** — the failing-tests list joined with table context
- **DQ impact** — `failed_tests × (direct + 0.5·transitive + 2·pii_downstream)`
- **DQ risk ranking** — catalog-wide sort by the above

### Cleaning engine

- **Stale description detection** — adversarial few-shot prompt with retry-on-malformed-JSON
- **Description quality scoring** — 1-5 with partial-JSON salvage (so a truncated LLM response still populates the metric)
- **Naming inconsistency detection** — Levenshtein clusters, `customer_id` ↔ `cust_id` ↔ `cid`
- **Heuristic PII classifier** — 5 layers: exclusions → ordered rules → table-context → confidence → review-needed flag
- **DQ failure explanations** — LLM writes summary / likely_cause / next_step, classified by fix_type

### Stewardship engine

- **Auto-documentation** — one table or a whole schema at once (NL-triggered: *"auto-document the sales schema"*)
- **Review queue** — Accept / Edit / Reject per suggestion before anything hits OM
- **PII tag application** via `JSON-Patch` on column paths
- **DQ test recommendations** — severity-ranked proposals, allowlisted, duplicate-filtered

### Interface (Stew)

- **26 local tools** over the three engines + **3 MCP tools** (search, entity details, lineage)
- **Show-your-work** trace expander per reply
- **Review queue** as the only write surface (agent cannot write directly)
- **Streaming responses** via LangChain's `create_agent` / LangGraph
- **10-tab visualization panel** — Score gauge · Lineage · **Governance** · Blast radius · Stewardship · Catalog map · Tag conflicts · Quality · **DQ failures** · **DQ gaps** · **DQ risk**

### Bring-your-own LLM

- **LLM setup modal** — paste any OpenAI-compatible key, session-scoped, never persisted
- **6 provider presets** — OpenRouter · OpenAI · Gemini · Groq · Ollama · Custom
- **💫 MetaSift defaults button** — one-click setup matching the developer's tested `.env`
- **Chat-area model picker** — dropdown with the full OpenRouter catalog fetched dynamically (~343 models, type-to-filter via Streamlit's built-in selectbox search)
- **Per-task routing** — Advanced expander lets power users route each of the 6 task types (toolcall / reasoning / description / stale / scoring / classification) to its own model. Ships with the hybrid default: Llama 3.3 70B for 5 tasks + GPT-4o-mini for tool-calling.
- **Welcome modal + 📖 Guide button** — first-launch overlay with the 3-step quick-start, reachable any time from the sidebar

## Architecture highlights

- **DuckDB in-memory** as the analytics substrate. Populated from OM's REST API in one pass per refresh. Recursive CTEs for lineage + DQ impact. Seven DuckDB tables: `om_tables`, `om_columns`, `om_lineage`, `om_test_cases`, `cleaning_results`, `dq_explanations`, `dq_recommendations`.
- **Three OM channels**: REST for bulk reads + writes, MCP for read-only agent discovery (with a hard allowlist so writes stay gated), SDK pinned at 1.9.4 for compatibility.
- **Review queue is the only write surface.** Neither the agent nor the cleaning engine writes directly to OM. Every change ships through `Accept / Edit / Reject` cards.
- **Two-hop LLM layer:** every task (toolcall / reasoning / description / stale / scoring / classification) routes through `app/clients/llm.py`, which merges the UI override with `.env` defaults per field, per task. `@lru_cache` is invalidated on every credential change.

## Engineering decisions worth flagging

1. **Synthetic DQ fixture as a deliberate fallback.** Wiring real DQ test cases through OM's API is complex (executable suites, test definitions, entity links). Instead, `scripts/dq_fixtures.json` provides 7 real-shape rows that hydrate `om_test_cases` when the OM endpoint returns empty — so the DQ track demos end-to-end without requiring extra OM configuration. The API-fetch path supersedes the fixture automatically when real tests exist.

2. **Partial-JSON salvage on LLM truncation.** Free-tier models routinely hit `max_tokens` mid-rationale during bulk scoring. The scoring code now runs a char-level scan to extract every complete `{...}` object before the truncation point, so partial coverage beats zero coverage. Caught a real bug (Quality metric stuck at 0.0/5) during testing.

3. **Per-task model routing as the default config.** Llama 3.3 70B loops on tool-calling introspection — observed during the DQ scan runs. Shipping a hybrid default (cheap Llama for 5 tasks, reliable GPT-4o-mini for toolcall) avoids that failure mode while keeping session cost minimal.

4. **Multiplicative DQ risk score.** `failed_tests × weighted_blast_radius`. Additive would score a leaf table with 5 failing tests equal to a high-fanout healthy table — multiplying makes risk compound and requires both broken data AND downstream readers to matter.

5. **Dynamic OpenRouter catalog over a hardcoded shortlist.** The public `openrouter.ai/api/v1/models` endpoint returns ~343 models with no auth required. Caching for 1 hour via `@st.cache_data` gives users a current list without bloat. Hardcoded fallback for offline scenarios.

6. **agentred-reviewed commits.** Every feature commit in the DQ track + governance + BYO-LLM work was fact-checked by an independent code-review subagent before push. Multiple real bugs caught pre-push (dialog collision, CTE scope error, infinite rerun loop on empty model-picker input) that a human reviewer would have missed.

## Demo flow (for the video)

1. Open app → Welcome modal shows → dismiss. Click **🔑 LLM setup** → paste OpenRouter key → click **💫 Use MetaSift defaults** → modal closes.
2. Click **🔄 Refresh metadata** → sidebar populates (Composite 56-70%, Coverage 77%, etc.)
3. Click **🔬 Deep scan** (progress bar steps through 7 tables)
4. Click **🔐 PII scan** (instant, heuristic)
5. Click **🧪 Explain DQ failures** (6 failures from the fixture get plain-English explanations)
6. Click **💡 Recommend DQ tests** (catalog-wide scan proposes ~30 tests)
7. Open **Visualizations** → walk through Score gauge → Governance (point at PII propagation chain) → DQ failures → DQ risk → DQ gaps
8. Ask Stew: *"what's my composite score?"*, *"where does PII propagate?"*, *"why is the email_not_null test failing?"*, *"what DQ tests should I add to orders?"* — each reply shows the tool-call trace
9. Open **Review queue** (9 pending) — accept a description, reject a PII tag
10. Click **📄 Export report** — download the markdown summary

## Tech stack

- Python 3.11 on WSL Ubuntu 24.04
- OpenMetadata 1.9.4 (Docker Compose: MySQL + Elasticsearch + server)
- `openmetadata-ingestion` SDK (version-pinned)
- `data-ai-sdk[langchain]` for MCP tool integration
- LangChain 1.x with `create_agent` / LangGraph
- OpenRouter by default (any OpenAI-compatible endpoint works)
- DuckDB for in-process analytical SQL
- **v0.2:** FastAPI + Server-Sent Events for the API; React 19 + Vite + TanStack Query + Tailwind for the SPA; SQLite for conversations / review queue / scan-run history; Plotly.js for charts
- **v0.1 (tagged `v0.1-streamlit`):** Streamlit + Plotly for the UI
- `thefuzz` for fuzzy naming clusters
- `httpx` for REST + the dynamic OpenRouter catalog fetch

## AI tool disclosure

MetaSift was built with assistance from **Claude Code (Anthropic)** — used for ~all of the Python engineering, prompt design, and agent orchestration. Declared per hackathon rules.

## License

MIT. See [`LICENSE`](./LICENSE).

## Links

- **Repo:** <https://github.com/blueberrylinux/metasift>
- **README:** see [`README.md`](./README.md) for full architecture + setup
- **Port specs** for a FastAPI + React rebuild: [`../metasift+/`](../metasift+/) (six feature docs, zero-refactor to the engines)
