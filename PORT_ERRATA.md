# PORT_ERRATA

Reference sheet for the `port/fastapi-react` branch. Lists every spot where
the scaffold docs in `metasift+/` disagree with the real engines in this
repo, and the corrected name/signature the port code must use.

**Read this before copy-pasting from the scaffolding docs.** The scaffold was
written against an idealized API that was never built; the real engines use
module-level functions and slightly different names.

Format: `scaffold says` → `reality` → `fix in port code`.

## Clients

| Scaffold | Reality | Fix |
| --- | --- | --- |
| `DuckStore.from_settings(settings)` class constructor | Module-level `app.clients.duck.get_conn()` with `@lru_cache`, plus `refresh_all()` and `query()` functions | Don't instantiate a class. In FastAPI routes, call `duck.query(...)` / `duck.refresh_all()` directly. No `app.state.duck`. |
| `OMClient.from_settings(settings)` class constructor | Module-level `app.clients.openmetadata.get_http()`, `health_check()`, `patch_table_description()`, `patch_column_tag()` | Same — call module functions. No `app.state.om`. |
| `LLMClient.from_settings(settings)` class constructor | Module-level `app.clients.llm.get_llm(task)` with `@lru_cache`, plus `set_override()`, `set_model()`, `set_task_model()`, `get_override()`, `clear_override()`, `clear_per_task_models()` | Call module functions. The override singleton is process-wide. |
| `app.state.duck.ensure_hydrated()` auto-refresh on startup | No such method. `duck.refresh_all()` is sync and takes minutes. | **Do not** hydrate in `lifespan`. DuckDB starts empty; first user-initiated `/analysis/refresh` populates it. |
| `duck.new_conversation()`, `append_message()`, `review_queue()`, `review_item()`, `close_review_item()`, `dq_failures()`, `dq_fix_type_counts()`, `welcome_state()`, `dismiss_welcome()`, `events.subscribe/unsubscribe()` | **None exist.** Invented `DuckStore` facade in scaffold | Routes call engine modules directly. Persistence for conversations / review actions / scan runs lives in `app.api.store` (SQLite), not in `DuckStore`. |

## Agent

| Scaffold | Reality | Fix |
| --- | --- | --- |
| `build_agent(llm=..., duck=..., om=...)` | `build_agent()` — zero args, reads module-level singletons | Call `build_agent()` in lifespan; store as `app.state.agent`. |
| `agent.astream_events(question, convo_id)` → already shaped event stream | Actual: LangGraph `CompiledStateGraph.stream({"messages": [HumanMessage(...)]}, stream_mode="updates")`, returns node-update dicts | Write an adapter: iterate `agent.stream(...)`, pull `AIMessage.tool_calls` + `ToolMessage` by `tool_call_id`, emit `{type: 'token'\|'tool_call'\|'tool_result'\|'final'}` SSE frames. Reference: `app/main.py::1431-1488` already does this in sync. |
| `agent.reload()` | No such method | On LLM config change: call `llm.set_override(...)` (clears `get_llm.cache`) THEN rebuild `app.state.agent = build_agent()`. |
| `agent.list_tools()` | No such method | Return `[t.name for t in app.engines.tools.ALL_TOOLS]` + MCP tool names from `_load_mcp_tools()`. |
| `agent.last_trace()` | No such method | Build traces client-side by demuxing stream events (see adapter above). |

## Analysis engine names

| Scaffold | Reality | Fix |
| --- | --- | --- |
| `analysis.coverage_by_schema()` | `analysis.documentation_coverage()` | — |
| `analysis.team_scorecard()` | `analysis.ownership_breakdown()` | — |
| `analysis.blast_radius_topn()` | `analysis.top_blast_radius(limit=10)` | — |
| `cleaning.pii_propagation_dag(duck)` | `viz.governance_lineage_dag()` (in viz, not cleaning — returns a plotly Figure) | — |
| `cleaning.dq_risk_catalog(duck, limit=...)` | `analysis.dq_risk_ranking(limit=20)` | — |
| `cleaning.dq_impact(duck, fqn)` | `analysis.dq_impact(fqn, max_depth=10)` | — |
| `cleaning.explain_one_failure(duck, test_case_id)` | `cleaning.explain_dq_failure(row)` — takes a dict row from `analysis.dq_failures()`, not a test_case_id | — |
| `cleaning.set_fix_type(...)`, `cleaning.classify_fix_type(...)`, `cleaning.fix_action(...)` | **None exist.** `fix_type` is computed inside `explain_dq_failure`; there's no manual override API | If manual classification is needed, add a column to `dq_explanations` and write a new function. Skip for Phase 1-5. |

## Stewardship dispatch

| Scaffold | Reality | Fix |
| --- | --- | --- |
| `stewardship.apply(item, om=om)` — single dispatcher | Two separate functions: `apply_suggestion(Suggestion)` for descriptions, `apply_pii_tag(table_fqn, column_name, tag_fqn)` for tags | Route-level dispatcher: look at `item.kind`, build a `Suggestion` dataclass or pull FQN/column/tag, call the right one. |
| `stewardship.render_dq_payload(duck, table_fqn, rec_id)` | No such function | Construct the OM test-case JSON client-side or add a new helper. |

## Engines (scan) — sync vs async

All run functions in the engines are **sync** with `progress_cb(step, total, label)`:

- `cleaning.run_deep_scan(progress_cb=None)` → `dict`
- `cleaning.run_pii_scan(use_llm_fallback=False)` → `dict` *(no progress_cb)*
- `cleaning.run_dq_explanations(progress_cb=None)` → `dict`
- `stewardship.run_dq_recommendations(progress_cb=None)` → `dict`
- `stewardship.bulk_document_schema(schema_name, max_tables=20, progress_cb=None)` → `dict`
- `duck.refresh_all()` → `dict` *(no progress_cb)*

Scaffold treats these as async generators (`async for ev in cleaning.run_dq_explanations(duck)`). They're not.

**Fix pattern** (write once, reuse):

```python
# app/api/scans.py
import asyncio
from functools import partial

async def stream_engine_scan(run_fn, **kwargs):
    queue: asyncio.Queue = asyncio.Queue()

    def progress_cb(step, total, label):
        queue.put_nowait({"type": "progress", "step": step, "total": total, "label": label})

    async def runner():
        try:
            summary = await asyncio.to_thread(partial(run_fn, progress_cb=progress_cb, **kwargs))
            queue.put_nowait({"type": "done", **summary})
        except Exception as e:
            queue.put_nowait({"type": "error", "message": str(e)})
        queue.put_nowait(None)  # sentinel

    asyncio.create_task(runner())
    while True:
        ev = await queue.get()
        if ev is None:
            return
        yield ev
```

Use from an SSE route:

```python
@router.post("/scans/dq-explain")
async def scan_dq_explain():
    async def events():
        async for ev in stream_engine_scan(cleaning.run_dq_explanations):
            yield {"event": ev["type"], "data": json.dumps(ev)}
    return EventSourceResponse(events())
```

## Config

| Scaffold | Reality | Fix |
| --- | --- | --- |
| `settings.cors_origins`, `settings.serve_static` | Not defined on `app.config.Settings` | Defined in `app.api.config.api_settings` instead. **Do not** edit `app/config.py`. |
| `settings.load_llm_config()`, `settings.save_llm_config()` | No such methods | Persist overrides through `app.clients.llm.set_override()` + SQLite if persistence needed. |
| `settings.load_per_task_models()`, `settings.save_per_task_models()` | Same | Use `llm.get_task_model(task)` / `llm.set_task_model(task, model)`. |

## Pydantic / OpenAPI gotchas

- **`pydantic<2.12` is pinned** (via `openmetadata-ingestion`). `pydantic-settings>=2.4` is compatible. Don't bump pydantic.
- **`openmetadata-ingestion==1.12.4`** — scaffold's starter says `1.9.4`. Don't change it. The version must match the OM server image in `docker-compose.yml` (1.9.4 for MetaSift's trimmed stack) but the Python client lib can run ahead — already validated.
- Docs claim ingestion SDK "pinned to server version for write compatibility" — that's correct behavior but the repo currently runs 1.12.4 client + 1.9.4 server and writes work. Don't downgrade to chase the doc.

## Tool count

**Resolved (2026-04-24):** `list_services` added, so `ALL_TOOLS` is now **26 local + 3 MCP = 29**. Scaffold docs, WelcomeModal, StewHome, and Settings strings all align.

## MCP allowlist

Hardcoded in `app/engines/agent.py::_MCP_TOOL_ALLOWLIST`:

```python
{"search_metadata", "get_entity_details", "get_entity_lineage"}
```

Write-capable MCP tools (`patch_entity`, `create_glossary*`) are **explicitly excluded** — all writes must go through MetaSift's review queue. Do not widen the allowlist in the port.

## Docker compose

| Scaffold mentions | Reality |
| --- | --- |
| `ingestion` service (OM's Airflow) | **Not in docker-compose.yml.** Deliberately trimmed — see compose header comment. |
| `api` + `web` service blocks | Not yet present; Phase 8 cutover decision. |

## Additional notes

- **LangGraph event-stream shape is the highest Phase-2 risk.** Test the adapter against the current LangGraph version (`langchain==0.3.x` / `langgraph` bundled) before building UI around it. Pin exact versions once it works.
- **OpenRouter catalog endpoint** — `GET /api/v1/models` is public and cacheable. Mock in tests.
- **Every tool in `app/engines/tools.py` is wrapped by `_wrap_for_safety()`** — exceptions become text messages the agent can retry. Don't bypass the wrapper when the port calls tools directly.
- **Streamlit's `_build_review_queue()` (in `app/main.py`)** already contains the exact SQL joins for the review queue across `cleaning_results`, `pii_results`, `doc_suggestions`. Lift that SQL verbatim into the FastAPI route instead of re-deriving.
