# Makefile for Verenigingen app development

.PHONY: help test test-quick test-all coverage lint format install clean check-imports test-mollie test-mollie-core test-mollie-performance test-mollie-security

# Dynamic paths - works on any server.
# The app is usually at <bench>/apps/verenigingen, but a git worktree lives outside
# the bench tree entirely, so walk up for the bench's own marker file instead of
# assuming a fixed depth. BENCH_DIR is empty when no bench is reachable.
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BENCH_DIR := $(shell d=$(patsubst %/,%,$(MAKEFILE_DIR)); \
	while [ "$$d" != "/" ] && [ -n "$$d" ]; do \
		if [ -f "$$d/sites/common_site_config.json" ]; then echo "$$d"; break; fi; \
		d=$$(dirname "$$d"); \
	done)

# bench runs the app it has installed - the main checkout - not the files in this
# working tree. Running the suite from a linked worktree would therefore report on
# the main checkout's code while appearing to test this branch, so the test targets
# refuse rather than hand back a green that means nothing.
LINKED_WORKTREE := $(shell git rev-parse --git-dir 2>/dev/null | grep -q '/worktrees/' && echo 1)
SITE ?= $(shell cat $(BENCH_DIR)/sites/currentsite.txt 2>/dev/null || echo "veg11.veganisme.org")
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
	@echo "  make lint           - Run code linting"
	@echo "  make format         - Format code with black"
	@echo "  make check-imports  - Runtime import validation (all modules)"
	@echo "  make install        - Install pre-commit hooks"
	@echo "  make clean          - Clean test artifacts"

test:
	@echo "Running comprehensive tests..."
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --app $(APP)

test-quick:
ifeq ($(LINKED_WORKTREE),1)
	@echo "⏭️  Skipping quick tests: this is a linked git worktree, and bench would run"
	@echo "   the main checkout's code rather than this branch's. Run them from"
	@echo "   apps/verenigingen, or let CI run the branch."
else ifeq ($(BENCH_DIR),)
	@echo "⏭️  Skipping quick tests: no bench found above $(MAKEFILE_DIR)"
	@echo "   (looked for sites/common_site_config.json in each parent directory)."
else
	@echo "Running quick validation tests (SEPA naming + Chapter management)..."
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --module verenigingen.tests.sepa.test_sepa_mandate_naming
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --module verenigingen.tests.backend.unit.services.test_chapter_management_service
endif

test-all:
	@echo "Running all tests..."
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --app $(APP)

coverage:
	@echo "Running tests with coverage..."
	@cd $(BENCH_DIR) && bench --site $(SITE) run-tests --app $(APP) --coverage

lint:
	@echo "Running linters..."
	@command -v ruff >/dev/null 2>&1 && ruff check verenigingen || echo "⚠️  ruff not installed, skipping (install with: pip install ruff)"
	@echo "✓ Linting complete"

lint-fix:
	@echo "Running linters with auto-fix..."
	@command -v ruff >/dev/null 2>&1 && ruff check --fix verenigingen || echo "⚠️  ruff not installed"
	@echo "✓ Lint fixes applied"

lint-strict:
	@echo "Running strict linting (ruff + pylint)..."
	@command -v ruff >/dev/null 2>&1 && ruff check verenigingen || echo "⚠️  ruff not installed"
	@command -v pylint >/dev/null 2>&1 && pylint verenigingen --rcfile=.pylintrc --fail-under=8.0 || echo "⚠️  pylint not installed"
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

check-imports:
	@echo "Running runtime import validation..."
	@$(BENCH_DIR)/env/bin/python $(MAKEFILE_DIR)/scripts/validation/check_all_imports.py

# Mollie Test Orchestrator Commands
test-mollie:
	@echo "Running all Mollie test categories..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --all

test-mollie-core:
	@echo "Running core Mollie integration tests..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category core --verbose

test-mollie-performance:
	@echo "Running Mollie performance benchmarks..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category performance --verbose

test-mollie-security:
	@echo "Running Mollie security tests..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category security --verbose

test-mollie-integration:
	@echo "Running Mollie integration tests..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category integration --verbose

test-mollie-specialized:
	@echo "Running specialized Mollie tests..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --category specialized --verbose

mollie-test-status:
	@echo "Mollie test configuration status..."
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --list-categories
	@echo ""
	@cd $(BENCH_DIR) && $(BENCH_DIR)/env/bin/python $(PWD)/$(MOLLIE_ORCHESTRATOR) --validate
