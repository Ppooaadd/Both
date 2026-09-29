# PianoForge developer commands. `make help` lists them.

COMPOSE := docker compose -f infra/docker-compose.yml --env-file infra/.env
COMPOSE_GPU := docker compose -f infra/docker-compose.yml -f infra/docker-compose.gpu.yml --env-file infra/.env

.DEFAULT_GOAL := help
.PHONY: help env build up up-gpu doctor down clean logs ps migrate test test-backend test-web e2e

help: ## Show this help
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

env: ## Create infra/.env with random secrets (never overwrites)
	@sh infra/scripts/init-env.sh

build: env ## Build all images
	$(COMPOSE) build

up: env ## Build and start the stack in the background (http://localhost:3000)
	$(COMPOSE) build
	@timeout 420 $(COMPOSE) up -d || { echo "\nStartup did not finish in time or failed."; sh infra/scripts/diagnose.sh; exit 1; }
	@echo ""
	@echo "  PianoForge is running: $$(grep ^WEB_ORIGIN infra/.env | cut -d= -f2)"
	@echo ""

up-gpu: env ## Same as up, with the NVIDIA GPU overlay for the ML worker
	$(COMPOSE_GPU) build
	@timeout 420 $(COMPOSE_GPU) up -d || { echo "\nStartup did not finish in time or failed."; sh infra/scripts/diagnose.sh; exit 1; }
	@echo ""
	@echo "  PianoForge is running: $$(grep ^WEB_ORIGIN infra/.env | cut -d= -f2)"
	@echo ""

doctor: env ## Print diagnostics (service status, logs, network checks)
	@sh infra/scripts/diagnose.sh

down: env ## Stop the stack (keeps data volumes)
	$(COMPOSE) down

clean: env ## Stop the stack and delete all data volumes
	$(COMPOSE) down -v

logs: env ## Follow logs of every service
	$(COMPOSE) logs -f --tail=100

ps: env ## Service status
	$(COMPOSE) ps

migrate: env ## Apply database migrations
	$(COMPOSE) run --rm migrate

test: test-backend test-web ## Backend and web unit tests (no stack needed)

test-backend: ## Backend lint, types and unit tests
	cd backend && ruff check src tests alembic && mypy src && pytest tests/unit -q

test-web: ## Web typecheck, lint and unit tests
	cd apps/web && npm run typecheck && npm run lint && npm test

e2e: ## Playwright full-flow test against the running stack
	cd apps/web && E2E_BASE_URL=$$(grep ^WEB_ORIGIN ../infra/.env | cut -d= -f2) npx playwright test
