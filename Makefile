# MetaSift dev commands
# Run `make help` for the full list.

.PHONY: help install dev run stack-up stack-down stack-logs seed clean lint test token \
        api web web-install build-web port-dev

help:
	@echo "MetaSift dev commands"
	@echo "  make install     — create venv and install deps via uv"
	@echo "  make stack-up    — start OpenMetadata docker stack"
	@echo "  make stack-down  — stop and wipe the stack"
	@echo "  make stack-logs  — tail OpenMetadata server logs"
	@echo "  make token       — print instructions for getting a JWT token"
	@echo "  make seed        — populate OpenMetadata with messy demo data"
	@echo "  make run         — launch MetaSift Streamlit app (port 8501)"
	@echo "  make dev         — stack-up + seed + run (one command bootstrap)"
	@echo "  make lint        — ruff check + format"
	@echo "  make test        — pytest"
	@echo "  make clean       — remove venv, caches, duckdb files"
	@echo ""
	@echo "Port targets (port/fastapi-react branch — FastAPI + React UI)"
	@echo "  make api         — launch FastAPI backend (port 8000)"
	@echo "  make web-install — install React/Vite deps (run once)"
	@echo "  make web         — launch Vite dev server (port 5173)"
	@echo "  make build-web   — build React bundle into web/dist"
	@echo "  make port-dev    — run api + web together (parallel)"

install:
	uv venv --python 3.11
	uv pip install -e ".[dev]"
	@echo "✔ Env ready. Run: source .venv/bin/activate"

stack-up:
	docker compose up -d
	@echo ""
	@echo "⏳ OpenMetadata is starting (takes ~2 min on first boot)."
	@echo "   Watch progress: make stack-logs"
	@echo "   When ready:     open http://localhost:8585  (admin / admin)"

stack-down:
	docker compose down -v

stack-logs:
	docker compose logs -f openmetadata-server

token:
	@echo "Get a JWT token:"
	@echo "  1. Open http://localhost:8585 and log in as admin / admin"
	@echo "  2. Settings → Bots → ingestion-bot → Generate new token"
	@echo "  3. Copy token into .env as OPENMETADATA_JWT_TOKEN and AI_SDK_TOKEN"

seed:
	uv run python scripts/seed_messy_catalog.py

run:
	uv run streamlit run app/main.py

dev: stack-up
	@echo "⏳ Waiting for OpenMetadata (up to 3 min)..."
	@until curl -sf http://localhost:8586/healthcheck > /dev/null 2>&1; do sleep 5; done
	@echo "✔ OpenMetadata is up."
	@echo "⚠  Now set OPENMETADATA_JWT_TOKEN in .env (make token) then:"
	@echo "    make seed && make run"

lint:
	uv run ruff check app scripts
	uv run ruff format app scripts

test:
	uv run pytest -v

clean:
	rm -rf .venv .pytest_cache .ruff_cache __pycache__ app/__pycache__ app/*/__pycache__
	rm -f data/*.duckdb data/*.db

# ─── Port targets (FastAPI + React) ────────────────────────────────────────
# These coexist with the Streamlit targets until Phase 8 cutover.

api:
	uv run uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000

web-install:
	cd web && npm install

web:
	@test -d web/node_modules || (echo "→ Installing web deps (one-time)..." && $(MAKE) web-install)
	cd web && npm run dev

build-web:
	@test -d web/node_modules || $(MAKE) web-install
	cd web && npm run build

port-dev:
	$(MAKE) -j 2 api web
