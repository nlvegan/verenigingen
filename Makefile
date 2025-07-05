# Makefile for Verenigingen app development

.PHONY: help test test-quick test-all coverage lint format install clean

BENCH_DIR=/home/frappe/frappe-bench
SITE=dev.veganisme.net
APP=verenigingen

help:
	@echo "Verenigingen Development Commands:"
	@echo "  make test         - Run comprehensive test suite"
	@echo "  make test-quick   - Run quick validation tests"
	@echo "  make test-all     - Run all test categories"
	@echo "  make coverage     - Run tests with coverage report"
	@echo "  make lint         - Run code linting"
	@echo "  make format       - Format code with black"
	@echo "  make install      - Install pre-commit hooks"
	@echo "  make clean        - Clean test artifacts"

test:
	@echo "Running comprehensive tests..."
	@cd $(BENCH_DIR) && bench --site $(SITE) execute $(APP).tests.test_runner_simple.run_comprehensive_tests

test-quick:
	@echo "Running quick tests..."
	@cd $(BENCH_DIR) && bench --site $(SITE) execute $(APP).tests.test_runner_simple.run_quick_tests

test-all:
	@echo "Running all tests..."
	@cd $(BENCH_DIR) && bench --site $(SITE) execute $(APP).tests.test_runner_simple.run_all_tests

coverage:
	@echo "Running tests with coverage..."
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --app $(APP) --coverage

lint:
	@echo "Running linters..."
	@flake8 verenigingen --max-line-length=110 --extend-ignore=E203,E501,W503
	@pylint verenigingen --rcfile=.pylintrc --fail-under=7.0 || true
	@echo "✓ Linting complete"

lint-strict:
	@echo "Running strict linting..."
	@flake8 verenigingen --max-line-length=110 --extend-ignore=E203,E501,W503
	@pylint verenigingen --rcfile=.pylintrc --fail-under=8.0
	@echo "✓ Strict linting complete"

format:
	@echo "Formatting code..."
	@black verenigingen --line-length=110
	@isort verenigingen --profile black --line-length 110
	@echo "✓ Formatting complete"

install:
	@echo "Installing development tools..."
	@pip install pre-commit black flake8 isort
	@pre-commit install
	@echo "✓ Development tools installed"

clean:
	@echo "Cleaning test artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@rm -rf .coverage htmlcov
	@rm -rf $(BENCH_DIR)/sites/$(SITE)/test-results/*.json
	@echo "✓ Cleanup complete"
