.PHONY: setup install install-aws dev dev-backend dev-frontend build lint format lint-fix check serve help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## First-time setup: dependencies, model, .env and frontend build
	./setup.sh

install: ## Install all dependencies
	uv sync
	cd client && npm install

install-aws: ## Install with AWS dependencies
	uv sync --group aws
	cd client && npm install

dev: ## Run backend and frontend together
	@trap 'kill 0' EXIT; \
	uv run fastapi dev main.py & \
	cd client && npm run dev & \
	wait

dev-backend: ## Run backend only
	uv run fastapi dev main.py

dev-frontend: ## Run frontend dev server
	cd client && npm run dev

build: ## Build frontend to static/
	cd client && npm run build

lint: ## Run linter
	uv run ruff check .

format: ## Format code
	uv run ruff format .

lint-fix: ## Fix lint errors
	uv run ruff check --fix .

check: ## Run lint and format check
	uv run ruff check .
	uv run ruff format --check .

serve: ## Run production server
	uv run fastapi run main.py --port 8000
