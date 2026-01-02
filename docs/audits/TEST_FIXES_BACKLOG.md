# Test Fixes Backlog

Identified during e_boekhouden_migration refactoring (2025-01-02).

## Priority: Low

### 1. test_account_classification_service (3 failures)

**File**: `tests/unit/test_account_classification_service.py`

**Failures**:
- `test_vw_expense_fallback` - Expected `"Expense Account"`, got `""`
- `test_vw_income_by_keyword` - Expected confidence `MEDIUM`, got `HIGH`
- `test_vw_income_group_055` - Expected strategy `"profit_loss_group_055"`, got `"profit_loss_income_range"`

**Root cause**: Test expectations don't match current service behavior (likely tests not updated after service changes).

---

### 2. test_e_boekhouden_migration_integration (24 failures)

**File**: `tests/test_e_boekhouden_migration_integration.py`

**Root cause**: Test setup bug in `TestPaymentProcessingIntegration._create_test_account()` - calls `self.test_company` before it's assigned in `_ensure_test_company()`.

**Fix**: Reorder the test setup or pass company as parameter to `_create_test_account()`.

**Affected tests**:
- All tests in `TestPaymentProcessingIntegration` class
- Various security and pipeline integration tests

---

## Notes

These are pre-existing failures, not caused by the refactoring work.
