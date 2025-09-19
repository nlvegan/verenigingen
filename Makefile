# Makefile for Verenigingen app development

.PHONY: help test test-quick test-all coverage lint format install clean test-mollie test-mollie-core test-mollie-performance test-mollie-security

BENCH_DIR=/home/frappe/frappe-bench
SITE=dev.veganisme.net
APP=verenigingen
MOLLIE_ORCHESTRATOR=verenigingen/tests/mollie_test_orchestrator.py

help:
	@echo "Verenigingen Development Commands:"
	@echo "  make test         - Run comprehensive test suite"
	@echo "  make test-quick   - Run quick validation tests"
	@echo "  make test-all     - Run all test categories"
	@echo "  make coverage     - Run tests with coverage report"
	@echo ""
	@echo "Mollie-specific tests:"
	@echo "  make test-mollie         - Run all Mollie test categories"
	@echo "  make test-mollie-core    - Run core consolidated Mollie tests"
	@echo "  make test-mollie-performance - Run Mollie performance benchmarks"
	@echo "  make test-mollie-security    - Run Mollie security tests"
	@echo ""
	@echo "Code quality:"
	@echo "  make lint         - Run code linting"
	@echo "  make format       - Format code with black"
	@echo "  make install      - Install pre-commit hooks"
	@echo "  make clean        - Clean test artifacts"

test:
	@echo "Running comprehensive tests..."
	@cd $(BENCH_DIR) && python $(PWD)/verenigingen/tests/run_all_tests.py --all

test-quick:
	@echo "Running quick tests..."
	@cd $(BENCH_DIR) && python $(PWD)/scripts/testing/runners/enhanced_test_runner.py --suite quick

test-all:
	@echo "Running all tests..."
	@cd $(BENCH_DIR) && python $(PWD)/verenigingen/scripts/testing/runners/enhanced_test_runner.py --suite all --all-reports

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

# Mollie Test Orchestrator Commands
test-mollie:
	@echo "Running all Mollie test categories..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --all

test-mollie-core:
	@echo "Running core Mollie integration tests..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category core --verbose

test-mollie-performance:
	@echo "Running Mollie performance benchmarks..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category performance --verbose

test-mollie-security:
	@echo "Running Mollie security tests..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category security --verbose

test-mollie-integration:
	@echo "Running Mollie integration tests..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category integration --verbose

test-mollie-specialized:
	@echo "Running specialized Mollie tests..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category specialized --verbose

mollie-test-status:
	@echo "Mollie test configuration status..."
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --list-categories
	@echo ""
	@cd $(BENCH_DIR) && python $(PWD)/$(MOLLIE_ORCHESTRATOR) --validate
