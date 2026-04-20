# CLAUDE.md — Project context for Claude Code

## What is MetaSift

MetaSift is an AI-powered metadata analyst and steward for OpenMetadata. Built for the WeMakeDevs x OpenMetadata "Back to the Metadata" hackathon. Solo developer project.

Core thesis: Documentation coverage is a lie. A catalog can be 100% documented and still full of wrong, stale, conflicting metadata. MetaSift introduces a composite score that measures what actually matters.

## Architecture — Four Engines

1. **Analysis engine** (`app/engines/analysis.py`) — Pulls catalog metadata into DuckDB, runs aggregate SQL analytics, generates health dashboards. No LLM needed.

2. **Stewardship engine** (`app/engines/stewardship.py`) — Auto-documents undocumented tables, detects/classifies PII, writes improvements back via REST API PATCH. Uses Llama 3.3 70B via OpenRouter for description generation.

3. **Cleaning engine** (`app/engines/cleaning.py`) — The differentiator. Detects stale descriptions, tag conflicts across schemas, scores description quality 1-5, finds inconsistent naming via fuzzy matching. Mix of DuckDB SQL and LLM calls.

4. **Interface layer** (`app/engines/agent.py`) — LangChain agent wired to MCP tools + custom REST tools. "Stew" is the AI wizard persona. Users interact via natural language chat in Streamlit.

## Tech Stack

- Python 3.11 on WSL Ubuntu 24.04
- uv for package management
- OpenMetadata 1.9.4 (Docker Compose stack: MySQL + Elasticsearch + server)
- openmetadata-ingestion SDK for REST API
- data-ai-sdk[langchain] for MCP tool integration
- LangChain for agent orchestration
- OpenRouter as the sole LLM provider (free tier) — default model: `meta-llama/llama-3.3-70b-instruct:free`
- DuckDB for in-process analytical SQL on metadata
- Streamlit for UI (dashboard left, chat right)
- Plotly for charts via st.plotly_chart()
- thefuzz for Levenshtein-based naming inconsistency detection

## Key Files

- `app/main.py` — Streamlit entry point, dashboard + chat layout
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
- `Makefile` — make install, stack-up, stack-down, seed, run, lint, test

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
make run          # launch Streamlit app
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
- DuckDB store needs refresh_all() called before any queries work
- Streamlit uses st.session_state for conversation history and review queues
- REST API PATCH for descriptions uses JSON Merge Patch format
