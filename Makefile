.DEFAULT_GOAL := help
.PHONY: help build up down ps logs migrate test test-docker lint typecheck check integration clean

help:  ## List available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

build:  ## Build all service images
	docker compose build

up:  ## Start all services in the background
	docker compose up -d

down:  ## Stop and remove containers (keeps data volumes)
	docker compose down

ps:  ## Show service status
	docker compose ps

logs:  ## Follow logs for all services
	docker compose logs -f

migrate:  ## Apply database migrations (run after 'up')
	docker compose exec api alembic upgrade head

test:  ## Run api then worker unit tests on the host (sequential, never parallel)
	cd apps/api && ../../.venv/bin/python -m pytest -q
	cd apps/worker && ../../.venv/bin/python -m pytest -q

test-docker:  ## Run api and worker unit tests inside the docker containers
	docker compose exec -T api pytest -q
	docker compose exec -T worker pytest -q

lint:  ## Ruff bug-class subset (E9,F63,F7,F82) on api and worker
	.venv/bin/ruff check --select E9,F63,F7,F82 apps/api apps/worker

typecheck:  ## TypeScript type check for apps/web (tsc --noEmit)
	cd apps/web && npm run typecheck

check:  ## lint -> test -> typecheck, stopping at the first failure
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) typecheck

integration:  ## Run the end-to-end integration test
	bash scripts/integration-test.sh

clean:  ## DATA-LOSS: stop services and delete data volumes
	@echo "WARNING: this deletes the postgres_data and n8n_data volumes (all jobs and n8n data)."
	docker compose down -v
