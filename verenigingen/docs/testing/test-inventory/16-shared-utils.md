# Test Inventory — Domain I2: Shared Utils / Helpers

READ-ONLY audit. Every `def test_*` method classified as HAPPY (nominal success) /
UNHAPPY (expects error/throw/validation-fail/rejection) / EDGE (boundary, empty/null,
duplicate, concurrency, idempotency, malformed data, date-parse fallbacks, ordering) /
OTHER (smoke/import-safety/setup-only/tautological).

Scope: 23 target files across `verenigingen/tests/utils/` (+`csv/`) and
`verenigingen/tests/backend/unit/utils/`. Three of the named files
(`test_utils.py`, `test_helpers.py`, `test_setup.py`) contain **no** `def test_*`
methods — they are helper/infrastructure modules, not test suites (counted as 0).

## Summary

- **473** classified test methods across **20** files that actually contain tests.
- Skew is heavily toward **HAPPY (206, 44%)** and **EDGE (198, 42%)**; UNHAPPY is
  thin (47, 10%) and concentrated in a handful of API-guard / validation files.
- **OTHER (22, 5%)** flags real weak spots: `test_email_mocking.py` (self-tests the
  mock harness) and `test_notification_helpers.py` (6 mock-into-tautology tests that
  re-implement production logic inside the test) are the worst offenders.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| tests/utils/test_utils.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/test_utils_init.py | 35 | 19 | 0 | 15 | 1 |
| tests/utils/test_helpers.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/test_history_manager_utils.py | 48 | 17 | 6 | 25 | 0 |
| tests/utils/test_member_history_integrity.py | 23 | 6 | 0 | 17 | 0 |
| tests/utils/test_member_portal_utils.py | 24 | 10 | 1 | 13 | 0 |
| tests/utils/test_orphaned_child_table_cleanup.py | 22 | 13 | 1 | 8 | 0 |
| tests/utils/test_mandate_sync_utility.py | 11 | 4 | 1 | 5 | 1 |
| tests/utils/test_department_hierarchy.py | 26 | 15 | 1 | 10 | 0 |
| tests/utils/test_email_mocking.py | 5 | 0 | 0 | 0 | 5 |
| tests/utils/test_improved_error_handling.py | 9 | 0 | 8 | 0 | 1 |
| tests/utils/test_validation_utilities_coverage.py | 61 | 25 | 12 | 23 | 1 |
| tests/utils/test_sepa_sandbox.py | 18 | 11 | 0 | 5 | 2 |
| tests/utils/test_setup.py | 0 | 0 | 0 | 0 | 0 |
| tests/utils/csv/test_base_csv_import.py | 17 | 5 | 6 | 6 | 0 |
| backend/unit/utils/test_application_helpers_coverage.py | 33 | 19 | 4 | 10 | 0 |
| backend/unit/utils/test_application_helpers_reapplication.py | 21 | 10 | 0 | 11 | 0 |
| backend/unit/utils/test_application_payments_coverage.py | 11 | 5 | 2 | 4 | 0 |
| backend/unit/utils/test_date_extraction.py | 50 | 23 | 0 | 27 | 0 |
| backend/unit/utils/test_fee_query_consolidation.py | 9 | 4 | 0 | 0 | 5 |
| backend/unit/utils/test_folder_category_detector.py | 16 | 10 | 0 | 6 | 0 |
| backend/unit/utils/test_import_helpers.py | 11 | 3 | 0 | 8 | 0 |
| backend/unit/utils/test_notification_helpers.py | 23 | 7 | 5 | 5 | 6 |
| **DOMAIN TOTALS** | **473** | **206** | **47** | **198** | **22** |

## Observations

- **Strong base class is the norm, and it correlates with quality.** The high-value
  files (`test_history_manager_utils`, `test_member_history_integrity`,
  `test_department_hierarchy`, `test_validation_utilities_coverage`,
  `test_orphaned_child_table_cleanup`, `test_member_portal_utils`) all extend
  `EnhancedTestCase` and hit the **real DB / real branches** — they earn their large
  EDGE counts legitimately (broken links, grace-period date-type regressions, idx
  resequencing, dynamic-link orphans, SQL-injection table-name rejection, concurrency
  locks). These are the meaningful tests in the domain. `VereningingenTestCase`
  (`tests/utils/base`) is used by the application-helpers files.

- **EDGE-heavy by design, and that's appropriate.** Two pure-string modules
  (`test_date_extraction` 27 EDGE, `test_folder_category_detector` 6 EDGE) plus the
  date/validation utilities drive the EDGE total. These pure functions have no DB
  and are exhaustively table-tested (invalid month/day, Feb-30, case-insensitivity,
  priority/ordering, None/empty). Genuinely good coverage, low value-per-test but
  cheap and correct — not padding.

- **UNHAPPY is concentrated, not absent.** 40 of 47 UNHAPPY tests live in just four
  files: `test_validation_utilities_coverage` (12, date-range/throw + not-found),
  `test_improved_error_handling` (8, API guard PermissionError/ValidationError),
  `test_history_manager_utils` (6, failure-result contracts), and
  `csv/test_base_csv_import` (6, only_for rejection + before_submit guard). The many
  pure-function files have near-zero UNHAPPY because their "failure" is a graceful
  None/False (classified EDGE), which is correct.

- **Weakest file: `test_notification_helpers.py`.** 6 of 23 tests are OTHER and are
  **mock-into-tautology / coverage-padding**: `test_sends_email_with_correct_context`,
  `test_truncates_long_subject`, `test_truncates_long_message`,
  `test_limits_recipients_to_max` all *re-implement the production logic inside the
  test* and assert on locally-built values — they never call the function under test.
  `test_uses_default_roles_when_not_specified` computes `call_args` but has **no
  assertion**. `test_emergency_fallback_to_system_manager` is `assertTrue(True)`. The
  whole file is `frappe.get_doc`/`get_single`-mocked, so even the "real" tests only
  exercise wiring. This is the file to rewrite as real integration tests.

- **`test_email_mocking.py` (5/5 OTHER) tests the test harness, not product code.**
  It verifies that `frappe.sendmail` is patched and captured by the mock queue —
  valuable as a harness guard, but it exercises no production logic and uses `print()`
  for output. Correctly OTHER, not a product-behavior test.

- **`test_fee_query_consolidation.py` is mostly import-safety smoke** (5/9 OTHER:
  four `getattr(module, ...)` importable checks + one conditional-assertion test that
  skips its asserts when `success` is falsy). It overlaps `test_application_helpers_
  coverage.py::TestFeeInfoTrio`, which tests the same functions with real data and
  real shape assertions — the consolidation file adds little. `test_sepa_sandbox.py`
  has 2 OTHER (dataclass-construction + isinstance smoke) but is otherwise a clean,
  focused unit suite on `FrappeTestCase`.

## Missing / not-a-suite files

All 23 named files exist. Three contain **no test methods** and are helper modules,
not test suites — counted as Total 0:

- `tests/utils/test_utils.py` — email-mock queue, `TestDataFactory`, cleanup
  helpers (imported by other suites).
- `tests/utils/test_helpers.py` — `run_member_tests()` programmatic runner only.
- `tests/utils/test_setup.py` — `setup_test_environment()` / company/account/
  warehouse bootstrap functions only.

(Non-test top-level runners also present but excluded from method counts:
`run_error_handling_tests()` in `test_improved_error_handling.py`.)
