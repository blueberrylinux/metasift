# MetaSift dev commands
# Run `make help` for the full list.
#
# v0.2 (current): React 18 + FastAPI. Default `make` targets point here.
# v0.1 (preserved): Streamlit. Tagged at `v0.1-streamlit` — to run the
# original demo: `git checkout v0.1-streamlit && uv run streamlit run app/main.py`.

.PHONY: help install dev run stack-up stack-down stack-logs seed clean lint test token \
        api web web-install build-web reset-metasift reset-all sandbox-stack-up sandbox-config

help:
	@echo "MetaSift dev commands (v0.2 — React + FastAPI)"
	@echo "  make install     — create venv and install deps via uv"
	@echo "  make stack-up    — start OpenMetadata docker stack"
	@echo "  make stack-down  — stop and wipe the stack"
	@echo "  make stack-logs  — tail OpenMetadata server logs"
	@echo "  make token       — print instructions for getting a JWT token"
	@echo "  make seed        — populate OpenMetadata with messy demo data"
	@echo "  make run         — launch the React app + FastAPI backend (api on :8000, web on :5173)"
	@echo "  make dev         — stack-up + wait + print bootstrap steps"
	@echo "  make lint        — ruff check + format"
	@echo "  make test        — pytest"
	@echo "  make clean       — remove venv, caches, duckdb files"
	@echo ""
	@echo "Component targets (start one piece at a time)"
	@echo "  make api         — launch FastAPI backend only (port 8000)"
	@echo "  make web         — launch Vite dev server only (port 5173)"
	@echo "  make web-install — install React/Vite deps (run once)"
	@echo "  make build-web   — build React bundle into web/dist"
	@echo ""
	@echo "Reset"
	@echo "  make reset-metasift — wipe MetaSift sqlite (keep OM as-is)"
	@echo "  make reset-all      — wipe OM volumes + MetaSift sqlite (full demo reset)"
	@echo ""
	@echo "Sandbox VPS deployment helpers (mostly for verifying configs locally — see"
	@echo "deploy/sandbox/README.md for the actual VPS runbook)"
	@echo "  make sandbox-config    — render the merged sandbox compose to verify port bindings"
	@echo "  make sandbox-stack-up  — boot OM stack with the sandbox override (OM bound to 127.0.0.1)"
	@echo ""
	@echo "v0.1 Streamlit (preserved)"
	@echo "  git checkout v0.1-streamlit && uv run streamlit run app/main.py"

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
	@echo "  4. (Or, in v0.2 only:) paste the token in Settings → OpenMetadata"
	@echo "     to rotate live without restarting the API."

seed:
	uv run python scripts/seed_messy_catalog.py

# Default `make run` launches the v0.2 stack: FastAPI on :8000 + Vite on :5173,
# both with hot-reload, in parallel via `-j 2`. Open http://localhost:5173.
# To run them individually (e.g. for separate-terminal log tailing), use
# `make api` and `make web` directly.
run:
	$(MAKE) -j 2 api web

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

# ─── Component targets ─────────────────────────────────────────────────────
# Start one piece of the v0.2 stack at a time. `make run` ties them together
# in parallel; these are for when you want separate terminals or to run
# only the API while pointing the React app at a different host.

api:
	uv run uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000 \
		--timeout-keep-alive 5 \
		--limit-concurrency 128

web-install:
	cd web && npm install

web:
	@test -d web/node_modules || (echo "→ Installing web deps (one-time)..." && $(MAKE) web-install)
	cd web && npm run dev -- --open

build-web:
	@test -d web/node_modules || $(MAKE) web-install
	cd web && npm run build

# ─── Reset targets ─────────────────────────────────────────────────────────
# `reset-metasift` clears MetaSift's local SQLite (conversations, scan_runs,
# suggestions, dq_explanations, dq_recommendations) so the next API boot
# starts blank. OM is left running and untouched. Stop the API first — `rm`
# succeeds against open files but the running process keeps the old inode.
#
# `reset-all` additionally wipes OM's docker volumes via `stack-down`. The
# JWT for ingestion-bot is regenerated on next stack-up, so seeding before
# rotating the token in .env will fail with 401s — the printed steps walk
# through the rotation in order.

reset-metasift:
	@echo "⚠  Wiping MetaSift local state (sqlite + WAL + SHM)."
	@echo "   OM data is untouched. Stop the API first if it's running."
	@echo ""
	rm -f metasift.sqlite metasift.sqlite-shm metasift.sqlite-wal
	@echo "✔ Cleared. Restart the API and click Refresh metadata in the UI."

reset-all: stack-down
	rm -f metasift.sqlite metasift.sqlite-shm metasift.sqlite-wal
	@echo ""
	@echo "✔ OM volumes + MetaSift state wiped."
	@echo ""
	@echo "Next steps (in order):"
	@echo "  1. make stack-up           — boot OM (~2 min)"
	@echo "  2. make token              — print JWT rotation instructions"
	@echo "  3. update OPENMETADATA_JWT_TOKEN + AI_SDK_TOKEN in .env"
	@echo "  4. make seed && make run   — repopulate + start the React app"

# ─── Sandbox compose helpers ───────────────────────────────────────────────
# These layer deploy/sandbox/docker-compose.sandbox.yml on top of the dev
# compose so OM binds to 127.0.0.1 only — what the VPS actually runs.
# Useful locally to confirm the override merges correctly before pushing.

sandbox-config:
	@docker compose \
		-f docker-compose.yml \
		-f deploy/sandbox/docker-compose.sandbox.yml \
		config

sandbox-stack-up:
	docker compose \
		-f docker-compose.yml \
		-f deploy/sandbox/docker-compose.sandbox.yml \
		up -d
	@echo ""
	@echo "⚠  OM is bound to 127.0.0.1 only — http://localhost:8585 still works"
	@echo "   from this machine, but external connections are refused. This"
	@echo "   mirrors the VPS posture; revert with 'make stack-down && make stack-up'."
