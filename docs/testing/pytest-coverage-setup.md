# Pytest Coverage Pre-commit Integration

This document describes the pytest-coverage integration added to the Verenigingen codebase for automated test coverage enforcement during commits.

## Overview

The pytest-coverage integration adds automated test coverage checks to the pre-commit workflow, ensuring that critical tests pass and maintain adequate coverage before code can be committed.

## Components

### 1. Pytest Configuration (`pytest.ini`)
- **Location**: `/home/frappe/frappe-bench/apps/verenigingen/pytest.ini`
- **Purpose**: Configures pytest test discovery, markers, and coverage settings
- **Key Features**:
  - Test discovery paths set to `verenigingen/tests`
  - Coverage branch analysis enabled
  - Multiple test markers for selective execution (slow, integration, unit, critical, etc.)
  - Coverage omit patterns for test files and migrations

### 2. Pytest Frappe Runner
- **Location**: `/home/frappe/frappe-bench/apps/verenigingen/scripts/testing/pytest_frappe_runner.py`
- **Purpose**: Full pytest runner with Frappe context initialization
- **Features**:
  - Initializes Frappe database connection
  - Sets up test environment flags
  - Supports coverage arguments
  - Can run selective tests for pre-commit

### 3. Pre-commit Runner
- **Location**: `/home/frappe/frappe-bench/apps/verenigingen/scripts/testing/pytest_precommit_runner.py`
- **Purpose**: Lightweight runner specifically for pre-commit hooks
- **Features**:
  - Runs critical tests only (validation regression and business logic)
  - Uses existing bench test infrastructure
  - 60-second timeout to prevent blocking commits
  - Graceful failure handling

### 4. Pre-commit Hook Configuration
- **Location**: `.pre-commit-config.yaml`
- **Hook ID**: `pytest-coverage-critical`
- **Features**:
  - Runs on Python file changes
  - Excludes test files, migrations, and debug scripts
  - Verbose output for debugging
  - Serial execution (no parallel runs)

## How It Works

1. **On Commit**: When you commit Python files, the pre-commit hook triggers
2. **Test Execution**: The runner executes critical tests using `bench run-tests`
3. **Coverage Check**: Coverage is measured (currently informational, not enforced)
4. **Pass/Fail**: Commit proceeds if tests pass, blocked if they fail

## Current Configuration

- **Tests Run**:
  - `test_validation_regression.py` - Field validation and API compliance
  - `test_critical_business_logic.py` - Core business logic validation
- **Coverage Threshold**: Currently informational only (no hard threshold)
- **Timeout**: 60 seconds maximum execution time
- **Failure Mode**: Non-blocking for infrastructure issues

## Usage

### Running Tests Manually

```bash
# Run all tests with coverage
cd /home/frappe/frappe-bench/apps/verenigingen
python scripts/testing/pytest_frappe_runner.py

# Run pre-commit tests only
python scripts/testing/pytest_precommit_runner.py

# Run with specific pytest arguments
python scripts/testing/pytest_frappe_runner.py -v --cov-fail-under=75
```

### Customizing Test Selection

To modify which tests run during pre-commit, edit the `critical_tests` list in `pytest_precommit_runner.py`:

```python
critical_tests = [
    app_path / "verenigingen/tests/test_validation_regression.py",
    app_path / "verenigingen/tests/test_critical_business_logic.py",
    # Add more critical test files here
]
```

### Adjusting Coverage Thresholds

To enforce coverage thresholds, modify the pytest runner to use `--cov-fail-under`:

```python
# In pytest_frappe_runner.py
pytest_args.extend([
    "--cov=verenigingen",
    "--cov-branch",
    "--cov-fail-under=75",  # Enforce 75% minimum coverage
])
```

## Troubleshooting

### Tests Not Running
- Ensure pytest and pytest-cov are installed: `bench pip install pytest pytest-cov`
- Check that test files exist in the expected locations
- Verify Frappe site is accessible: `bench --site dev.veganisme.net console`

### Coverage Not Showing
- The current setup uses `bench run-tests` which may not display detailed coverage
- For full coverage reports, use the main pytest runner directly

### Pre-commit Timeout
- Default timeout is 60 seconds
- For longer test suites, increase timeout in `pytest_precommit_runner.py`

## Future Enhancements

1. **Enforce Coverage Thresholds**: Currently coverage is measured but not enforced
2. **Expand Test Scope**: Add more critical test modules as they stabilize
3. **Parallel Execution**: Run tests in parallel for faster feedback
4. **HTML Coverage Reports**: Generate detailed coverage reports
5. **Integration with CI/CD**: Use same pytest infrastructure in CI pipelines

## Benefits

- **Immediate Feedback**: Developers know immediately if their changes break critical tests
- **Coverage Awareness**: Visibility into test coverage during development
- **Quality Gates**: Prevents committing code that breaks core functionality
- **Consistent Testing**: Same test infrastructure used locally and in CI
- **Gradual Adoption**: Conservative start with ability to expand over time
