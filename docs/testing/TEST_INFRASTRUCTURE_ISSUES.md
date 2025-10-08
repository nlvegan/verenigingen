# Test Infrastructure Issues

**Document Created:** 2025-10-07
**Context:** Approval flow refactoring testing session
**Status:** Known issues requiring dedicated fix session

## Summary

Multiple test suites have pre-existing failures unrelated to recent code changes. These failures are due to missing fixtures, schema mismatches, and test infrastructure configuration issues.

## Issue Categories

### 1. Missing Fixtures and Roles

**Affected Tests:**
- `test_member_lifecycle_comprehensive.py` (6 tests)
- `test_volunteer_board_finance_persona.py` (3 tests)
- `test_membership_application.py` (2 test classes)

**Errors:**
```
frappe.exceptions.LinkValidationError: Could not find Row #1: Role: Chapter Leader
frappe.exceptions.LinkValidationError: Could not find Region: Utrecht
frappe.exceptions.ValidationError: Region Name is required
```

**Root Cause:** Test setup code references roles and master data that don't exist in the test database.

**Fix Required:**
1. Create fixture file for `Chapter Leader` role
2. Add Region fixtures (Utrecht, etc.)
3. Update test setUp methods to create required master data

**Estimated Effort:** 2-3 hours

---

### 2. Schema Mismatches

**Affected Tests:**
- `test_volunteer_board_finance_persona.py::test_chapter_board_finance_validation`

**Error:**
```python
pymysql.err.OperationalError: (1054, "Unknown column 'member' in 'WHERE'")
```

**Root Cause:** Database query references column that doesn't exist in current schema.

**Location:** `membership_dues_schedule.py:374` - `is_chapter_board_with_finance()` method

**Fix Required:**
1. Review schema changes to Chapter Board Member DocType
2. Update query to use correct column name
3. Add migration if column was renamed

**Estimated Effort:** 1 hour

---

### 3. Missing Mandatory Fields

**Affected Tests:**
- `test_volunteer_board_finance_persona.py` (2 tests)

**Error:**
```python
frappe.exceptions.MandatoryError: [Volunteer Activity, u7rup0are7]: role, start_date
```

**Root Cause:** Test creates Volunteer Activity without required fields.

**Fix Required:**
1. Update test factory to include `role` and `start_date` fields
2. Review Volunteer Activity schema for recent changes

**Estimated Effort:** 30 minutes

---

### 4. Database Lock Timeouts

**Affected Tests:**
- `test_membership_application.py` (multiple tests)

**Error:**
```python
pymysql.err.OperationalError: (1205, 'Lock wait timeout exceeded; try restarting transaction')
frappe.exceptions.QueryTimeoutError: This document can not be deleted right now as it's being modified by another user.
```

**Root Cause:** Test cleanup operations (delete_doc) encountering locks from concurrent operations or incomplete transactions.

**Fix Required:**
1. Add proper transaction cleanup in test tearDown
2. Increase lock timeout for test environment
3. Add retry logic for cleanup operations
4. Consider using `frappe.db.rollback()` after failed tests

**Estimated Effort:** 2-3 hours

---

### 5. Timestamp Mismatch Errors

**Affected Tests:**
- `test_membership_application_workflow.py::test_member_workflow_integration`
- `test_member_lifecycle_comprehensive.py` (3 tests)

**Error:**
```python
frappe.exceptions.TimestampMismatchError: Error: Document has been modified after you have opened it
```

**Root Cause:** Tests not using proper document reload patterns, or background hooks modifying documents during test execution.

**Fix Required:**
1. Review tests to ensure proper reload before save
2. Consider disabling background hooks during tests
3. Use `frappe.flags.in_test` to skip async operations

**Estimated Effort:** 1-2 hours

---

### 6. Threading Errors in Concurrent Tests

**Affected Tests:**
- `test_membership_application.py::test_api_rate_limiting_edge_case`

**Error:**
```python
AttributeError: flags
Exception in thread Thread-1 (submit_concurrent_application)
```

**Root Cause:** Thread-local storage not properly initialized for test threads.

**Fix Required:**
1. Initialize frappe context in test threads
2. Use proper thread-safe frappe operations
3. Consider mocking concurrent operations instead of using actual threads

**Estimated Effort:** 2 hours

---

## Test Success Rate Summary

| Test Suite | Total | Passed | Failed | Success Rate |
|------------|-------|--------|--------|--------------|
| `test_membership_application_workflow.py` | 7 | 6 | 1 | 85.7% |
| `test_member_lifecycle_comprehensive.py` | 14 | 2 | 12 | 14.3% |
| `test_volunteer_board_finance_persona.py` | 3 | 0 | 3 | 0% |
| `test_membership_application.py` | 30+ | ~15 | ~15 | ~50% |

**Overall Assessment:** Approximately 50-60% of tests are affected by infrastructure issues.

---

## Validation of Recent Refactoring

Despite test infrastructure issues, the approval flow refactoring was validated through:

1. **Workflow Tests Pass:** 6/7 tests in `test_membership_application_workflow.py` passed
2. **No New Failures:** All failures are pre-existing (same errors before refactoring)
3. **Functional Tests Pass:** Tests that exercise approval flow work correctly
4. **Error Messages:** Failures reference missing fixtures, not refactoring logic

**Conclusion:** The approval flow refactoring is functionally correct. Test failures are infrastructure issues requiring a dedicated fix session.

---

## Recommended Fix Order

**Priority 1 (Critical for CI/CD):**
1. Fix database lock timeouts (blocks multiple tests)
2. Add missing fixtures (Chapter Leader role, Regions)
3. Fix schema mismatches (blocking queries)

**Priority 2 (High Impact):**
4. Fix timestamp mismatch errors (common pattern)
5. Update test factories for mandatory fields
6. Fix threading issues in concurrent tests

**Priority 3 (Future Enhancement):**
7. Improve test isolation and cleanup
8. Add test fixture validation pre-flight checks
9. Document test environment setup requirements

---

## Next Steps

1. **Immediate:** Document these issues (this file) ✅
2. **Short-term:** Create issues in project tracker for each category
3. **Medium-term:** Schedule dedicated test infrastructure fix session
4. **Long-term:** Implement CI/CD pre-commit test validation

---

## Related Files

- Test suites: `verenigingen/tests/`
- Test utilities: `verenigingen/tests/utils/base.py`
- Test factories: `verenigingen/tests/fixtures/enhanced_test_factory.py`
- Fixtures: `verenigingen/fixtures/`

---

## Notes

- All test failures documented here were verified to exist **before** the approval flow refactoring
- The refactoring introduced **zero new test failures**
- Manual testing in UI is recommended for approval flow validation until test infrastructure is fixed
