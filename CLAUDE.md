# CLAUDE.md — Project context for Claude Code

## What is MetaSift

MetaSift is an AI-powered metadata analyst and steward for OpenMetadata. Built for the WeMakeDevs x OpenMetadata "Back to the Metadata" hackathon. Solo developer project.

Core thesis: Documentation coverage is a lie. A catalog can be 100% documented and still full of wrong, stale, conflicting metadata. MetaSift introduces a composite score that measures what actually matters.

## Architecture — Four Engines

1. **Analysis engine** (`app/engines/analysis.py`) — Pulls catalog metadata into DuckDB, runs aggregate SQL analytics, generates health dashboards. No LLM needed.

2. **Stewardship engine** (`app/engines/stewardship.py`) — Auto-documents undocumented tables, detects/classifies PII, writes improvements back via REST API PATCH. Uses Llama 3.3 70B via OpenRouter for description generation.

3. **Cleaning engine** (`app/engines/cleaning.py`) — The differentiator. Detects stale descriptions, tag conflicts across schemas, scores description quality 1-5, finds inconsistent naming via fuzzy matching. Mix of DuckDB SQL and LLM calls.

4. **Interface layer** (`app/engines/agent.py`) — LangChain agent wired to MCP tools + custom REST tools. "Stew" is the AI wizard persona. v0.2 ships a React/Vite SPA over a FastAPI port (`app/api/`); v0.1 (preserved at tag `v0.1-streamlit`) was a Streamlit app — both share the engines unchanged.

## Tech Stack

- Python 3.11 on WSL Ubuntu 24.04
- uv for package management
- OpenMetadata 1.9.4 (Docker Compose stack: MySQL + Elasticsearch + server)
- openmetadata-ingestion SDK for REST API
- data-ai-sdk[langchain] for MCP tool integration
- LangChain for agent orchestration
- OpenRouter as the sole LLM provider (free tier) — default model: `meta-llama/llama-3.3-70b-instruct:free`
- DuckDB for in-process analytical SQL on metadata
- v0.2: React 18 + Vite + TanStack Query + Tailwind for the SPA; FastAPI + sse-starlette for the API; SQLite for conversations / review queue / scan-run history; Plotly.js for charts
- v0.1 (preserved): Streamlit + Plotly via `st.plotly_chart()`
- thefuzz for Levenshtein-based naming inconsistency detection

## Key Files

- `app/main.py` — Streamlit entry point (v0.1, preserved at tag `v0.1-streamlit`)
- `app/api/` — FastAPI port (v0.2): routers for chat / scans / review / viz / report / analysis / dq / llm / om, SQLite store, SSE adapters
- `web/` — React 18 + Vite SPA (v0.2): screens/, components/, lib/api.ts
- `app/config.py` — Settings from .env via python-dotenv
- `app/clients/llm.py` — LLM router, picks model per task type (toolcall, description, classification, stale, scoring, reasoning)
- `app/clients/openmetadata.py` — SDK wrapper + REST client + health check
- `app/clients/duck.py` — DuckDB store, paginated REST fetch → DataFrame → SQL tables
- `app/engines/analysis.py` — documentation_coverage(), tag_conflicts(), composite_score()
- `app/engines/stewardship.py` — generate_description(), apply_suggestion() with Suggestion dataclass
- `app/engines/cleaning.py` — detect_stale(), detect_naming_clusters(), score_descriptions_batch(), composite_quality()
- `app/engines/agent.py` — build_agent() with LangChain AgentExecutor
- `scripts/seed_messy_catalog.py` — Populates OpenMetadata with sample catalog data for testing
- `docker-compose.yml` — MySQL + Elasticsearch + migrate + OpenMetadata server
- `Makefile` — make install, stack-up, stack-down, seed, api (v0.2), run (v0.1 Streamlit), reset-all, lint, test

## Composite Score Formula

- Documentation coverage (30%): % tables with descriptions
- Description accuracy (30%): % non-stale descriptions (needs cleaning engine)
- Classification consistency (20%): % columns without tag conflicts
- Description quality mean (20%): 1-5 score normalized to 0-100

## LLM Model Routing

All tasks default to `meta-llama/llama-3.3-70b-instruct:free` via OpenRouter.
Per-task routing configured in .env (swap per task if needed):

- MODEL_TOOLCALL — agent tool-calling
- MODEL_DESCRIPTION — generating table descriptions
- MODEL_CLASSIFICATION — PII detection
- MODEL_STALE_CHECK — stale description comparison
- MODEL_SCORING — description quality 1-5
- MODEL_REASONING — complex analytical reasoning

## Commands

```bash
make install      # create venv + install deps
make stack-up     # start OpenMetadata Docker stack
make stack-down   # stop + wipe volumes
make stack-logs   # tail server logs
make seed         # populate demo catalog
make api          # launch FastAPI (v0.2) on :8000; pair with `cd web && npm run dev` on :5173
make run          # launch Streamlit (v0.1) on :8501 — only meaningful at tag v0.1-streamlit
make reset-all    # wipe + reseed (sqlite + duck + OM volumes)
make lint         # ruff check + format
make test         # pytest
```

## OpenMetadata Credentials

- UI login: admin@openmetadata.org / admin
- JWT token: stored in .env as OPENMETADATA_JWT_TOKEN and AI_SDK_TOKEN
- Bot: ingestion-bot (Settings → Bots → ingestion-bot)

## Important Gotchas

- Import is `ai_sdk` not `data_ai_sdk` despite pip package name `data-ai-sdk`
- openmetadata-ingestion version MUST match server version
- pydantic pinned to <2.12 due to openmetadata-ingestion compatibility
- DuckDB store needs refresh_all() called before any queries work — v0.2 scan endpoints now check this and return typed `no_metadata_loaded` (was a CatalogException crash before audit Part 4 / commit c1bca64)
- v0.2 persists conversations, review queue, and scan_runs in SQLite (`app.api.store`); v0.1 used `st.session_state` (lost on refresh)
- REST API PATCH for descriptions uses JSON Merge Patch format
- Tags `v0.1-streamlit` and `v0.2-rc1` are rollback checkpoints — `git checkout` either to inspect that state
