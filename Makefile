.DEFAULT_GOAL := help
.PHONY: help install dev test test-cov lint format typecheck clean all frontend serve run lock deploy-dev deploy-prod bundle-validate

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install package
	pip install -e .

dev: ## Install with all dev dependencies
	pip install -e ".[all]"

test: ## Run all tests (no coverage; faster)
	pytest tests/ --no-cov

test-cov: ## Run tests with coverage report (term + html)
	pytest tests/ --cov-report=html

lint: ## Lint with ruff
	ruff check src/ tests/ server/

format: ## Format code with ruff
	ruff format src/ tests/ server/

typecheck: ## Type check with mypy
	mypy src/a2d/
	mypy server/

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info htmlcov/ .pytest_cache/ .mypy_cache/ .ruff_cache/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

all: lint typecheck test ## Lint + typecheck + test

frontend: ## Build React frontend
	cd frontend && npm install && BUILD_SHA=$$(git rev-parse --short HEAD) BUILD_DATE=$$(date -u +%Y-%m-%dT%H:%M:%SZ) npm run build

serve: ## Start FastAPI dev server
	PYTHONPATH=src:. uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload

run: dev frontend serve ## Full setup and run

lock: ## Generate requirements.lock
	pip-compile --strip-extras -o requirements.lock pyproject.toml

# Resolve a Databricks CLI ≥ 0.100.0 — a pyenv shim may resolve to legacy CLI
# v0.18.0, which breaks the Terraform provider used internally by `bundle deploy`
# ("legacy databricks CLI detected; upgrade to >= 0.100.0").
DATABRICKS_CLI := $(shell test -x /opt/homebrew/bin/databricks && echo /opt/homebrew/bin/databricks || command -v databricks)
DBX := DATABRICKS_CLI_PATH=$(DATABRICKS_CLI) $(DATABRICKS_CLI)

# Deployment-specific env (Lakebase host, FMAPI endpoint) is NOT committed —
# app.yaml ships with those empty so the repo stays portable and AI stays opt-in.
# To supply real values, create the untracked file `.local/app.env.yaml` holding
# just the `env:` entries you want appended, e.g.
#
#   - name: "A2D_DB_BACKEND"
#     value: "lakebase"
#   - name: "A2D_FMAPI_ENDPOINT"
#     value: "https://<workspace>/serving-endpoints/<model>/invocations"
#
# `make deploy-*` splices it into app.yaml for the upload and restores the clean
# file afterwards, so a deploy never leaves workspace identifiers in your tree.
LOCAL_APP_ENV := .local/app.env.yaml

# Databricks profile for deploys. Without this, `bundle deploy` falls back to
# default credentials and fails with "cannot configure default credentials" on any
# machine that authenticates per-profile. Pass PROFILE=<name> or export
# DATABRICKS_PROFILE.
PROFILE ?= $(DATABRICKS_PROFILE)
PROFILE_FLAG := $(if $(PROFILE),-p $(PROFILE),)

# NOTE: deliberately NOT dependent on `frontend`. Rebuilding regenerates Vite
# content hashes, so deploying and then committing left the repo and the deployed
# app pointing at different entry chunks (and dirtied frontend/dist every deploy).
# Deploy the committed build; run `make frontend` first if you have source changes.
deploy-dev: ## Deploy to Databricks Apps (dev) — uploads files AND triggers app restart
	@$(MAKE) --no-print-directory _deploy TARGET=dev

deploy-prod: ## Deploy to Databricks Apps (prod) — uploads files AND triggers app restart
	@$(MAKE) --no-print-directory _deploy TARGET=prod

_deploy:
	@if [ -f "$(LOCAL_APP_ENV)" ]; then \
		echo "Splicing $(LOCAL_APP_ENV) into app.yaml for this deploy"; \
		cp app.yaml .app.yaml.bak; \
		cat "$(LOCAL_APP_ENV)" >> app.yaml; \
	else \
		echo "No $(LOCAL_APP_ENV) — deploying with defaults (history off, AI off)"; \
	fi
	@$(DBX) bundle deploy -t $(TARGET) $(PROFILE_FLAG); status=$$?; \
		if [ -f .app.yaml.bak ]; then mv .app.yaml.bak app.yaml; fi; \
		exit $$status
	$(DBX) bundle run -t $(TARGET) a2d_app $(PROFILE_FLAG)

bundle-validate: ## Validate DAB configuration
	$(DBX) bundle validate
