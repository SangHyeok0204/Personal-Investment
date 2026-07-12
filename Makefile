.DEFAULT_GOAL := help
.PHONY: help build up down ps logs migrate test integration clean

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

test:  ## Run api and worker unit tests
	docker compose exec -T api pytest -q
	docker compose exec -T worker pytest -q

integration:  ## Run the end-to-end integration test
	bash scripts/integration-test.sh

clean:  ## DATA-LOSS: stop services and delete data volumes
	@echo "WARNING: this deletes the postgres_data and n8n_data volumes (all jobs and n8n data)."
	docker compose down -v
