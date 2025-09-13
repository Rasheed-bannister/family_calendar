.PHONY: help install dev-install test lint format security clean run pre-commit

help:  ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

install:  ## Install production dependencies
	uv venv
	uv pip install -e .

dev-install:  ## Install development dependencies
	uv venv
	uv pip install -e ".[dev]"
	uv pip install pre-commit pip-audit safety bandit[toml] black isort ruff mypy
	pre-commit install

test:  ## Run tests
	uv run pytest -v

test-cov:  ## Run tests with coverage
	uv pip install pytest-cov
	uv run pytest --cov=src --cov-report=html --cov-report=term-missing

lint:  ## Run all linters
	uv run black --check src tests
	uv run isort --check-only --profile black src tests
	uv run ruff check src tests
	uv run mypy src --ignore-missing-imports --no-strict-optional
	uv run bandit -r src -ll --skip B101

format:  ## Format code
	uv run black src tests
	uv run isort --profile black src tests
	uv run ruff check --fix src tests

security:  ## Run security checks
	uv run pip-audit --desc
	uv run safety check
	uv run bandit -r src -ll --skip B101
	detect-secrets scan --baseline .secrets.baseline

security-fix:  ## Try to auto-fix security vulnerabilities
	uv run pip-audit --desc --fix

dead-code:  ## Find dead code and unused imports
	uv run vulture src --min-confidence 80
	uv run autoflake --check-diff --remove-unused-variables --remove-all-unused-imports --recursive src/

complexity:  ## Check code complexity
	uv run flake8 src --max-complexity 10 --select C901
	uv run radon cc src -nc
	uv run radon mi src -nc

quality:  ## Run all code quality checks
	@echo "Running dead code detection..."
	@make dead-code
	@echo "\nRunning complexity analysis..."
	@make complexity
	@echo "\nRunning linters..."
	@make lint

clean-imports:  ## Remove unused imports automatically
	uv run autoflake --in-place --remove-unused-variables --remove-all-unused-imports --recursive src/
	uv run isort --profile black src tests

pre-commit:  ## Run pre-commit hooks on all files
	pre-commit run --all-files

pre-commit-update:  ## Update pre-commit hooks to latest versions
	pre-commit autoupdate

clean:  ## Clean up cache and build files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.db" -delete 2>/dev/null || true
	find . -type f -name "*.log" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	rm -rf build dist *.egg-info
	rm -rf htmlcov .coverage coverage.xml

run:  ## Run the application
	uv run src/main.py

run-debug:  ## Run the application in debug mode
	FLASK_DEBUG=1 uv run src/main.py

deps-check:  ## Check for outdated dependencies
	uv pip list --outdated

deps-update:  ## Update all dependencies to latest versions
	uv pip install --upgrade-package flask
	uv pip install --upgrade-package google-api-python-client
	uv pip install --upgrade-package google-auth-oauthlib
	@echo "Review changes carefully before committing"

git-hooks:  ## Install git hooks
	pre-commit install
	pre-commit install --hook-type commit-msg
	pre-commit install --hook-type pre-push

health-check:  ## Check application health
	@curl -f http://localhost:5000/health || echo "Application not running"