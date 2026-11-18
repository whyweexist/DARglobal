.PHONY: up down logs status build doctor migrate ingest scrape-darglobal scrape-wasalt refresh index eval test test-e2e lint typecheck smoke-test backup restore prod-up
COMPOSE=docker compose
API=$(COMPOSE) run --rm --no-deps api
init-env:
	@test -f .env || (cp .env.example .env && echo 'Created .env; configure OPENROUTER_API_KEY before LLM chat.')
up: init-env
	$(COMPOSE) up -d --build --wait
	@echo 'Application: open the forwarded port 3000 in Codespaces.'
down:
	$(COMPOSE) down
logs:
	$(COMPOSE) logs -f --tail=150
status:
	$(COMPOSE) ps
build: init-env
	$(COMPOSE) build
migrate: init-env
	$(COMPOSE) run --rm init sh -c 'alembic upgrade head'
ingest: init-env
	$(API) python -m app.cli ingest
scrape-darglobal: init-env
	$(API) python /app/scripts/scrape_darglobal.py
scrape-wasalt: init-env
	$(API) python /app/scripts/scrape_wasalt.py
refresh: init-env
	$(API) python -m app.cli ingest --force
index: init-env
	$(API) python -m app.cli index
doctor: init-env
	$(API) python -m app.cli doctor
smoke-test:
	python3 scripts/smoke_test.py
test: init-env
	cd backend && uv run --extra dev pytest -q tests
test-e2e:
	cd frontend && pnpm exec playwright test
lint:
	cd backend && uv run --extra dev ruff check app tests
	cd frontend && pnpm lint
typecheck:
	cd backend && uv run --extra dev mypy app --ignore-missing-imports
	cd frontend && pnpm lint
eval: init-env
	$(COMPOSE) run --rm --no-deps --volume "$(CURDIR)/evaluations:/app/evaluations:ro" api python /app/scripts/evaluate_rag.py
backup: init-env
	$(API) python -m app.cli backup
restore:
	@echo 'See docs/operations.md. Restoring requires stopping writers first.'
prod-up:
	docker compose --env-file .env.production -f compose.prod.yaml up -d --build --wait

# Native workflows (no Docker daemon required)
.PHONY: local local-api local-setup local-ingest local-index local-scrape-darglobal local-scrape-wasalt chat models stats search export local-doctor
local-setup:
	bash scripts/local.sh setup
local:
	bash scripts/local.sh up
local-api:
	bash scripts/local.sh api
local-ingest:
	bash scripts/local.sh cli ingest --force
local-index:
	bash scripts/local.sh cli index
local-scrape-darglobal:
	bash scripts/local.sh scrape-darglobal $(ARGS)
local-scrape-wasalt:
	bash scripts/local.sh scrape-wasalt $(ARGS)
local-doctor:
	bash scripts/local.sh cli doctor
chat:
	bash scripts/local.sh cli chat $(ARGS)
models:
	bash scripts/local.sh cli models
stats:
	bash scripts/local.sh cli stats
search:
	bash scripts/local.sh cli search --question "$(Q)" $(ARGS)
export:
	bash scripts/local.sh cli export --output "$(CURDIR)/data/exports"

.PHONY: check-ai local-check-ai
check-ai: init-env
	$(API) python -m app.cli check-ai $(ARGS)
local-check-ai:
	bash scripts/local.sh cli check-ai $(ARGS)
