# Test Runners

This directory contains specialized test runner scripts for the Verenigingen association management system.

## Available Runners

### 1. Cypress Controller Tests (`run_controller_tests.sh`)
Comprehensive Cypress test runner for 25+ DocType JavaScript controller tests.

**Features:**
- Complete test suite execution with categorized reporting
- Health checks and prerequisite validation
- Parallel and sequential test execution modes
- Detailed logging and error reporting
- Coverage analysis and performance metrics
- CI/CD integration support

**Usage:**
```bash
# Run all controller tests
./run_controller_tests.sh --all --headless

# Run by business priority
./run_controller_tests.sh --high-priority     # Financial operations (6 DocTypes)
./run_controller_tests.sh --medium-priority   # Admin & reporting (7 DocTypes)
./run_controller_tests.sh --lower-priority    # Extended features (12+ DocTypes)

# Interactive mode for debugging
./run_controller_tests.sh --interactive

# Validate environment without running tests
./run_controller_tests.sh --validate-only

# Performance and coverage analysis
./run_controller_tests.sh --all --parallel --coverage --performance
```

### 2. Core Component Tests (`run_core_tests.py`)
Tests essential Mollie Backend Integration components that are fully working.

**Features:**
- Validates essential components
- Quick validation suite
- Mock-based testing for external dependencies

**Usage:**
```bash
python scripts/testing/runners/run_core_tests.py
```

### 3. Standalone Test Suite (`run_tests.py`)
Full test suite that can run without full Frappe environment.

**Features:**
- Standalone operation without Frappe dependencies
- Comprehensive test coverage
- Colored terminal output
- Performance benchmarking

**Usage:**
```bash
python scripts/testing/runners/run_tests.py
```

## Integration

These test runners are integrated into:
- **CI/CD Pipeline**: `.github/workflows/deploy-to-press.yml`
- **Documentation**: `cypress/README-JAVASCRIPT-TESTING.md`
- **Implementation Reports**: `docs/implementation/IMPLEMENTATION_REPORT.md`

## Prerequisites

- **Cypress Tests**: Requires Cypress installation and proper test environment
- **Core Tests**: Requires Python 3.x and mock libraries
- **Standalone Tests**: Minimal dependencies, designed for standalone operation

## Troubleshooting

If tests fail:
1. Verify environment setup with `./run_controller_tests.sh --validate-only`
2. Check prerequisite installations
3. Review error logs for specific issues
4. Consult the main testing documentation in `docs/testing/`