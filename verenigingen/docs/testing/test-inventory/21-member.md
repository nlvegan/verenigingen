# Test Inventory — Domain 21: tests/member

**COMPLETE** — read-only classification of every class-level `def test_*` method across all 54 files in `verenigingen/tests/member`.

Classification key:
- **Happy** = nominal success / expected-valid path
- **Unhappy** = expects error/throw/validation-failure/permission-denial/rejection
- **Edge** = boundary, empty/null/zero, duplicate, concurrency, idempotency, malformed data, ordering, date-fallbacks
- **Other** = smoke/import-safety/setup-only/tautological, debug-no-assert, mock-into-tautology, skip-dominated

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_account_creation_api_coverage.py | 5 | 2 | 0 | 3 | 0 |
| test_account_creation_api.py | 28 | 9 | 12 | 7 | 0 |
| test_account_creation_api_sweep.py | 12 | 4 | 2 | 6 | 0 |
| test_account_creation_dutch_rules.py | 5 | 3 | 0 | 2 | 0 |
| test_account_creation_manager_sweep.py | 22 | 14 | 2 | 6 | 0 |
| test_account_creation_pipeline.py | 43 | 22 | 10 | 8 | 3 |
| test_account_creation_request_invoice.py | 5 | 1 | 0 | 4 | 0 |
| test_account_creation_security.py | 5 | 0 | 5 | 0 | 0 |
| test_account_creation_request.py | 32 | 14 | 10 | 8 | 0 |
| test_bulk_account_creation.py | 15 | 7 | 4 | 2 | 2 |
| test_csv_data_transformers.py | 27 | 17 | 5 | 5 | 0 |
| test_csv_data_validator.py | 26 | 6 | 11 | 9 | 0 |
| test_csv_import_integration.py | 15 | 10 | 0 | 5 | 0 |
| test_csv_import_user_linking.py | 5 | 1 | 0 | 4 | 0 |
| test_customer_creation_duplicate_name.py | 3 | 0 | 1 | 2 | 0 |
| test_customer_member_link_integration.py | 3 | 3 | 0 | 0 | 0 |
| test_donor_auto_creation_management.py | 26 | 15 | 1 | 10 | 0 |
| test_donor.py | 32 | 18 | 7 | 7 | 0 |
| test_dutch_business_logic_integration.py | 40 | 16 | 1 | 9 | 14 |
| test_member_address_service.py | 17 | 9 | 3 | 5 | 0 |
| test_member_approval_permissions.py | 2 | 2 | 0 | 0 | 0 |
| test_member_permissions.py | 7 | 4 | 0 | 2 | 1 |
| test_member_doctype_coverage.py | 40 | 32 | 6 | 2 | 0 |
| test_member_doctype_integration_fixed.py | 14 | 10 | 0 | 1 | 3 |
| test_member_doctype_integration.py | 12 | 7 | 0 | 1 | 4 |
| test_member_duplicate_detection.py | 21 | 7 | 3 | 11 | 0 |
| test_member_lifecycle_comprehensive.py | 14 | 8 | 0 | 5 | 1 |
| test_member_lifecycle_workflows.py | 8 | 6 | 0 | 0 | 2 |
| test_member_merge.py | 5 | 3 | 1 | 1 | 0 |
| test_member_performance_optimization.py | 6 | 0 | 1 | 5 | 0 |
| test_member_renewal_edge_cases.py | 18 | 0 | 0 | 16 | 2 |
| test_member_role_service_extended.py | 10 | 5 | 1 | 3 | 1 |
| test_member_scheduler_coverage.py | 3 | 2 | 0 | 1 | 0 |
| test_member_scheduler.py | 15 | 9 | 2 | 2 | 2 |
| test_member_service_coverage.py | 83 | 35 | 11 | 29 | 8 |
| test_membership_application_integration.py | 8 | 2 | 0 | 0 | 6 |
| test_membership_application_workflow.py | 8 | 1 | 0 | 1 | 6 |
| test_membership_commitment_period.py | 8 | 2 | 1 | 5 | 0 |
| test_membership_type_change.py | 8 | 5 | 3 | 0 | 0 |
| test_membership_termination_analytics.py | 30 | 21 | 0 | 9 | 0 |
| test_membership_termination_request.py | 44 | 23 | 16 | 5 | 0 |
| test_member_status_transitions_enhanced.py | 16 | 3 | 2 | 3 | 8 |
| test_member_user_account_service_extended.py | 25 | 7 | 7 | 10 | 1 |
| test_member_user_account_service_sweep.py | 17 | 5 | 4 | 8 | 0 |
| test_member_user_email_sync.py | 8 | 1 | 1 | 6 | 0 |
| test_user_member_image_sync.py | 6 | 2 | 0 | 2 | 2 |
| test_member_utils_coverage.py | 18 | 10 | 2 | 6 | 0 |
| test_member_utils_endpoints.py | 43 | 21 | 4 | 17 | 1 |
| test_member_utils.py | 68 | 30 | 4 | 34 | 0 |
| test_mijnrood_member_reconciliation.py | 18 | 7 | 0 | 11 | 0 |
| test_procurios_csv_import.py | 40 | 19 | 5 | 14 | 2 |
| test_secure_csv_parser_unit.py | 26 | 11 | 4 | 11 | 0 |
| test_secure_member_list_performance.py | 4 | 0 | 1 | 3 | 0 |
| test_termination_service_coverage.py | 21 | 10 | 6 | 5 | 0 |
| **DOMAIN TOTALS (54 files)** | **1040** | **481** | **159** | **331** | **69** |

Distribution: Happy 46.3% · Unhappy 15.3% · Edge 31.8% · Other 6.6%.

## Observations

- **Strong Happy/Edge balance overall (78% combined), but Unhappy is thin (15%).** Negative-path coverage is concentrated in a handful of validation/permission-heavy files (`test_membership_termination_request.py` 16 unhappy, `test_membership_type_change.py` 3/8, `test_account_creation_api.py` 12/28, `test_csv_data_validator.py` 11/26, `test_account_creation_security.py` 5/5). Many "coverage sweep" files lean Edge-heavy because they enumerate empty/null/not-found/filter branches of getter utilities (`test_member_utils.py` 34 edge/68, `test_member_utils_endpoints.py` 17 edge/43).
- **Two files dominate the `Other` (weak/tautological) bucket and are the clearest quality liabilities:** `test_dutch_business_logic_integration.py` (14 Other/40 — `if hasattr(...)`-guarded no-ops for `sorting_name`/`anonymize_personal_data`/consent fields, print-based permission tests that pass whether or not access is denied, and 5 "error message" tests whose `try/except: print(...)` branch passes silently when validation never fires) and `test_member_status_transitions_enhanced.py` (8 Other/16 — including `test_invalid_status_transitions`, `test_status_with_missing_required_fields`, `test_status_with_invalid_dates` whose bodies are literally just `pass`, plus over-broad `assertIn(status, [4 options])` cascade checks).
- **Wrong-target / self-testing helpers flagged in `test_member_lifecycle_workflows.py`:** `test_iban_validation_comprehensive_dutch_banks` and `test_chapter_assignment_by_postal_code_dutch_geography` assert against test-local helper methods (`validate_dutch_iban` does `startswith("NL") and len==18`; `assign_member_to_chapter_by_postal_code` reimplements range matching) rather than production code — green but non-load-bearing.
- **Mock usage is mostly legitimate.** `@patch('frappe.session')` (test_member_utils), `@patch('frappe.sendmail')` (external SMTP), and `patch.object(report, "_fetch_*")` (mijnrood reconciliation seam) all leave the business logic real. The `@patch(...data_transformers.frappe)` block in `test_csv_data_transformers.py` mocks only `frappe.get_single`/`db.exists` while exercising the real `determine_membership_type`/`get_dues_schedule_template` functions — not tautological, though the `*_throws` variants that set `mock_frappe.throw.side_effect` then assertRaises are close to circular.
- **Strongest, most meaningful files:** `test_membership_termination_analytics.py` (30 real computed assertions on trend/risk/prediction math, 0 Other), `test_membership_termination_request.py` (44, thorough happy+unhappy workflow + guard coverage), `test_member_duplicate_detection.py` (21, real confidence-score + injection-safety), `test_donor.py` (32, real BSN/RSIN eleven-proof + encryption-at-rest + permlevel denial), and the account-creation cluster (`test_account_creation_request.py`, `_pipeline.py`, `_manager_sweep.py`) which pair happy pipelines with real permission/rollback assertions.
- **Base classes:** most files use the factory-backed `EnhancedTestCase` or `VereningingenTestCase` (real DB, no business-logic mocking, `assertNoErrorLog`/`assertQueryCount` helpers). A minority of pure-unit files use bare `frappe.tests.utils.FrappeTestCase` (`test_csv_data_transformers.py`, `test_csv_data_validator.py`, `test_member_merge.py`, `test_secure_csv_parser_unit.py`) — appropriate since they test pure functions.

## Coverage / file notes

- All 54 discovered `test_*.py` files were audited; none were empty or zero-method.
- One method is skipped-by-default and counted as **Other**: `test_bulk_account_creation.py::test_03_large_scale` (`@unittest.skipIf(skip_large_tests, default True)`). Another skip-dominated method counted Other: `test_membership_application_workflow.py::test_member_creation_imports_integration` (`@unittest.skip`, deleted module). `test_member_renewal_edge_cases.py::test_renewal_volunteer_record_integrity` is `@unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)` (Other).
- Borderline calls that could shift ±a few between Edge/Unhappy: validator-returns-`False`-on-bad-input tests were classified **Unhappy** when the intent is rejection and **Edge** when the value is graceful None/empty; duplicate-that-raises → Unhappy, duplicate-that-short-circuits-ok → Edge; performance `assertQueryCount` baselines → Edge.
