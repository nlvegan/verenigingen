# Test Infrastructure System

## Overview

The Test Infrastructure System provides testing capabilities for the Verenigingen association management platform. The test suite was significantly reorganized in Phase 3 (March 2026) to move ~207 top-level files into domain subdirectories.

## Directory Structure

### Domain Subdirectories

| Directory | Focus |
|-----------|-------|
| `tests/payment/` | Payment, Mollie, invoice tests |
| `tests/member/` | Member lifecycle, membership tests |
| `tests/sepa/` | SEPA mandate, batch, processing tests |
| `tests/chapter/` | Chapter management, assignment tests |
| `tests/security/` | Security framework, access control tests |
| `tests/donor/` | Donor management, donation tests |
| `tests/financial/` | Financial operations, expense tests |
| `tests/email/` | Email system tests |
| `tests/volunteer/` | Volunteer management tests |
| `tests/e_boekhouden/` | eBoekhouden integration tests |
| `tests/workflows/` | Cross-cutting workflow tests |

### Backend Test Structure (`tests/backend/`)

| Directory | Focus |
|-----------|-------|
| `backend/unit/api/` | API endpoint unit tests |
| `backend/unit/controllers/` | DocType controller tests |
| `backend/unit/services/` | Service layer tests |
| `backend/components/` | Component-level integration tests |
| `backend/integration/` | Cross-component integration tests |
| `backend/features/` | Feature-level tests |
| `backend/business_logic/` | Business rule tests |
| `backend/comprehensive/` | Comprehensive suite demos |
| `backend/performance/` | Performance tests |
| `backend/optimization/` | UI optimization tests |
| `backend/portal/` | Portal function tests |
| `backend/security/` | Security tests |
| `backend/validation/` | Validation tests |
| `backend/workflows/` | Workflow tests |

### Other Test Directories

| Directory | Purpose |
|-----------|---------|
| `tests/api/` | API-level tests |
| `tests/config/` | Test configuration |
| `tests/contracts/` | API contract tests (SEPA, Mollie JSON) |
| `tests/docs/` | Test documentation |
| `tests/e2e/` | End-to-end tests |
| `tests/fixtures/` | Test data factories and helpers |
| `tests/frontend/` | Frontend/JS controller tests |
| `tests/integration/` | Integration tests |
| `tests/performance/` | Performance tests |
| `tests/reports/` | Report tests |
| `tests/repositories/` | Repository pattern tests |
| `tests/resilience/` | Resilience tests |
| `tests/safety/` | Safety tests |
| `tests/scalability/` | Scalability tests |
| `tests/services/` | Service layer tests |
| `tests/setup/` | Test setup utilities |
| `tests/support/` | Test support modules |
| `tests/test_records/` | Test record data |
| `tests/unit/` | Unit tests |
| `tests/utils/` | Test utility modules |

## Test Factory Framework

### Base Test Cases

**`VereningingenTestCase`** (`tests/utils/base.py`):
- General-purpose base class
- Re-exported from `tests/base_test_case.py` as `BaseTestCase`

**`EnhancedTestCase`** (`tests/fixtures/enhanced_test_factory.py`):
- Business logic validation framework
- Field Validator: Validates DocType field existence at test time
- Deterministic data generation with seeded randomness
- Real database testing without inappropriate mocks

### Test Data Factories (`tests/fixtures/`)

| Factory | Purpose |
|---------|---------|
| `test_data_factory.py` | Core test data factory |
| `test_data_factory_extended.py` | Extended factory |
| `enhanced_test_factory.py` | EnhancedTestCase with field validation |
| `test_secure_factory.py` | Security-aware test data |
| `sepa_test_factory.py` | SEPA-specific test data |
| `sepa_mandate_test_factory.py` | SEPA mandate test data |
| `ponto_test_data_factory.py` | Ponto (banking) test data |
| `field_validator.py` | Field existence validation |
| `dutch_validation_helpers.py` | Dutch business logic helpers |
| `anbi_test_personas.py` | ANBI donation personas |
| `billing_transition_personas.py` | Billing transition scenarios |
| `test_personas.py` | General test personas |

### Test Utilities (`tests/utils/`)

- `base.py` -- VereningingenTestCase base class
- `factories.py` -- Factory utility functions
- `assertions.py` -- Custom assertion helpers
- `setup_helpers.py`, `test_helpers.py`, `test_setup.py`
- `test_config.py`, `test_utils.py`, `test_email_mocking.py`
- `fixture_validator.py`, `coverage_reporter.py`, `quick_validation.py`
- `hybrid_report_tester.py`, `contribution_amendment_test_utilities.py`

## JavaScript Testing

### Cypress E2E Tests

Configuration: `cypress.config.js`
Test runner: `./run_controller_tests.sh`
Frontend test files: `tests/frontend/doctypes/`

### Jest Unit Tests

Configuration: `jest.config.js`
Note: Pre-push Jest hook has 3 pre-existing failures (`SKIP=jest-testing`).

## Quality Assurance

### Pre-commit Hooks (`.pre-commit-config.yaml`)

**Pre-commit stage:** ruff, black (line-length 110), eslint, field validators, test quality enforcer, import path validator

**Pre-push stage:** pylint (threshold 7.0), security validators (bandit, whitelist-type-safety, API security, insecure-api-detector)

### Contract Testing

- `tests/contracts/sepa-contracts.json`
- `tests/contracts/mollie-contracts.json`

### Mollie Integration Tests

Runner: `./run_mollie_e2e_tests.sh`
Tests: `vereinigingen_payments/mollie/tests/`

## DocType-Level Tests

Each DocType directory contains its own `test_<doctype_name>.py` file following Frappe conventions. These tests run with:

```bash
bench --site veg11.veganisme.org run-tests --app verenigingen --doctype "DocType Name"
```

### e-Boekhouden Tests (`tests/e_boekhouden/`)

- `test_bank_transaction_parser.py` -- Bank transaction parsing
- `test_party_extractor.py` -- Party data extraction
- `test_configurable_account_mapper.py` -- Account mapping configuration

### Mollie Tests (`vereinigingen_payments/mollie/tests/`)

Separate from the main test suite, with its own fixtures:

- `fixtures/test_factory.py` -- Mollie-specific test data factory
- `mollie_test_helper.py` -- Helper for Mollie test setup
- `integration/test_real_api.py` -- Real API integration tests
- `integration/test_subscription_integration.py` -- Subscription integration

### Test Quality Enforcement

The pre-commit hook `test-quality-enforcer` blocks mock abuse and enforces real integration testing. The `block-inappropriate-mocks` hook prevents mocking of business logic.

## Running Tests

```bash
# All tests
bench --site veg11.veganisme.org run-tests --app verenigingen

# Specific DocType
bench --site veg11.veganisme.org run-tests --app verenigingen --doctype "Member"

# Parallel
bench --site veg11.veganisme.org run-parallel-tests --app verenigingen

# Cypress
./run_controller_tests.sh --all --headless

# Mollie E2E
./run_mollie_e2e_tests.sh
```

## Key File Locations

- **Test root**: `tests/` (34 subdirectories)
- **Base test case**: `tests/utils/base.py`
- **Enhanced factory**: `tests/fixtures/enhanced_test_factory.py`
- **Core factory**: `tests/fixtures/test_data_factory.py`
- **Cypress config**: `cypress.config.js`
- **Jest config**: `jest.config.js`
- **Test runners**: `run_controller_tests.sh`, `run_mollie_e2e_tests.sh`
- **API contracts**: `tests/contracts/`
- **Mollie tests**: `vereinigingen_payments/mollie/tests/`
