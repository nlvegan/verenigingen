# Verenigingen Test Modules Reference

This document lists all test modules that can be run with `bench run-tests --module`.

## Test Summary (Verified Nov 28, 2025)

| Category | Files | Tests | Pass Rate |
|----------|-------|-------|-----------|
| Services | 16/17 | 221 | 94% |
| Mollie Integration | 22/22 | 169 | 100% |
| Backend Components | 29/30 | 310 | 97% |
| **TOTAL** | **67/69** | **700** | **97%** |

## Quick Commands

```bash
# Smoke tests (quick validation)
bench --site dev.veganisme.net run-tests --module verenigingen.tests.services.test_operation_result_migration
bench --site dev.veganisme.net run-tests --module verenigingen.tests.services.test_termination_operations
bench --site dev.veganisme.net run-tests --module verenigingen.integrations.mollie.tests.test_core_integration

# Run all tests in a directory
python scripts/testing/run_test_files.py --dir=verenigingen/tests/services
python scripts/testing/run_test_files.py --dir=verenigingen/integrations/mollie/tests
python scripts/testing/run_test_files.py --dir=verenigingen/tests/backend/components

# Quick smoke test
python scripts/testing/run_test_files.py --smoke
```

## Verified Working Test Modules

### Services (221 tests, ~6 min)
| Module | Tests | Status |
|--------|-------|--------|
| `verenigingen.tests.services.test_operation_result_migration` | 13 | PASS |
| `verenigingen.tests.services.test_termination_operations` | 22 | PASS |
| `verenigingen.tests.services.test_termination_approval_service` | 26 | PASS |
| `verenigingen.tests.services.test_termination_execution_service` | 13 | PASS |
| `verenigingen.tests.services.test_sepa_mandate_manager` | 28 | PASS |
| `verenigingen.tests.services.test_payment_entry_creation_service` | 15 | PASS |
| `verenigingen.tests.services.test_volunteer_activity_service` | 19 | PASS |
| `verenigingen.tests.services.test_volunteer_assignment_service` | 19 | PASS |
| `verenigingen.tests.services.test_volunteer_assignment_service_simple` | 13 | PASS |
| `verenigingen.tests.services.test_volunteer_expense_approver_service` | 10 | PASS |
| `verenigingen.tests.services.test_member_cleanup_service` | 9 | PASS |
| `verenigingen.tests.services.test_member_fee_change_service` | 7 | PASS |
| `verenigingen.tests.services.test_member_fee_change_history_service` | 10 | PASS |
| `verenigingen.tests.services.test_member_chapter_display_service` | 7 | PASS |
| `verenigingen.tests.services.test_field_sync_integration` | 10 | PASS |
| `verenigingen.tests.services.test_chapter_permission_service_integration` | - | SLOW (>3min) |

### Mollie Integration (169 tests, ~3 min)
| Module | Tests | Status |
|--------|-------|--------|
| `verenigingen.integrations.mollie.tests.test_core_integration` | 11 | PASS |
| `verenigingen.integrations.mollie.tests.test_common_helpers` | 48 | PASS |
| `verenigingen.integrations.mollie.tests.test_payment_processors` | 18 | PASS |
| `verenigingen.integrations.mollie.tests.test_integration_boundaries` | 15 | PASS |
| `verenigingen.integrations.mollie.tests.test_payment_context_resolver` | 14 | PASS |
| `verenigingen.integrations.mollie.tests.test_mollie_core_integration` | 11 | PASS |
| `verenigingen.integrations.mollie.tests.test_mollie_webhook_security` | 8 | PASS |
| `verenigingen.integrations.mollie.tests.test_webhook_integration_comprehensive` | 8 | PASS |
| `verenigingen.integrations.mollie.tests.test_webhook_security` | 8 | PASS |
| `verenigingen.integrations.mollie.tests.test_failed_payment_processing` | 7 | PASS |
| `verenigingen.integrations.mollie.tests.test_refund_chargeback` | 7 | PASS |
| `verenigingen.integrations.mollie.tests.test_refund_chargeback_integration` | 7 | PASS |
| `verenigingen.integrations.mollie.tests.test_mollie_refund_chargeback_integration` | 7 | PASS |

## Running Tests

### Single Module
```bash
bench --site dev.veganisme.net run-tests --module verenigingen.tests.services.test_termination_operations
```

### Directory (using script)
```bash
python scripts/testing/run_test_files.py --dir=verenigingen/tests/services
```

### Smoke Tests (quick validation)
```bash
python scripts/testing/run_test_files.py --smoke
```

## Known Issues

1. **`bench run-tests --app` fails**: DocType fixture ordering issues with Donor/Contact integration
2. **`test_chapter_permission_service_integration`**: Very slow (>3 min), may timeout
3. **Many modules show "0 tests"**: Tests are in subdirectories, use file-level runner

## Test Infrastructure Files

- `scripts/testing/run_test_modules.py` - Module-level test runner
- `scripts/testing/run_test_files.py` - File-level test runner
- `scripts/testing/setup_test_fixtures.py` - Creates required test fixtures (_Test Role, etc.)
