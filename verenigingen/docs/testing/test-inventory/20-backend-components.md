# Test Inventory — Domain BC1: tests/backend/components

> Audit complete: 75/75 files classified.
> READ-ONLY inventory. Each class-level `def test_*` classified as Happy / Unhappy / Edge / Other.

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_anbi_donation_summary_report_optimized_real.py | 7 | 7 | 0 | 0 | 0 |
| test_anbi_donation_summary_report.py | 12 | 6 | 0 | 5 | 1 |
| test_anbi_donation_summary_report_real.py | 15 | 13 | 0 | 2 | 0 |
| test_anbi_expense_report.py | 35 | 25 | 0 | 10 | 0 |
| test_application_submission.py | 2 | 2 | 0 | 0 | 0 |
| test_banking_import.py | 8 | 5 | 1 | 2 | 0 |
| test_cache_invalidation_manager.py | 15 | 11 | 0 | 4 | 0 |
| test_chapter_assignment_comprehensive.py | 11 | 8 | 1 | 2 | 0 |
| test_chapter_assignment_edge_cases.py | 16 | 1 | 3 | 11 | 1 |
| test_chapter_dashboard_page.py | 27 | 21 | 3 | 3 | 0 |
| test_chapter_dashboard.py | 8 | 7 | 0 | 1 | 0 |
| test_chapter_edge_cases.py | 13 | 0 | 0 | 13 | 0 |
| test_chapter_expense_report_unit.py | 20 | 14 | 1 | 5 | 0 |
| test_chapter_matching.py | 5 | 2 | 0 | 3 | 0 |
| test_chapter_member_status.py | 7 | 6 | 1 | 0 | 0 |
| test_deadlock_retry_utilities.py | 20 | 5 | 6 | 7 | 2 |
| test_donate_page_mollie.py | 12 | 8 | 3 | 1 | 0 |
| test_donate_page.py | 34 | 21 | 8 | 5 | 0 |
| test_enhanced_sepa_processing.py | 17 | 13 | 1 | 3 | 0 |
| test_expense_form.py | 1 | 1 | 0 | 0 | 0 |
| test_financial_reconciliation.py | 11 | 6 | 0 | 5 | 0 |
| test_get_user_volunteer_record_unit.py | 7 | 4 | 0 | 3 | 0 |
| test_history_audit_improvements.py | 18 | 13 | 1 | 3 | 1 |
| test_member_iban_history.py | 12 | 6 | 3 | 3 | 0 |
| test_member_lifecycle_iban.py | 5 | 4 | 1 | 0 | 0 |
| test_member_portal_integration.py | 11 | 8 | 2 | 1 | 0 |
| test_membership_analytics_functionality.py | 24 | 23 | 0 | 1 | 0 |
| test_membership_analytics_permissions.py | 10 | 0 | 8 | 2 | 0 |
| test_membership_application_page_imports.py | 2 | 1 | 0 | 0 | 1 |
| test_membership_application.py | 63 | 28 | 6 | 27 | 2 |
| test_membership_dues_edge_cases.py | 17 | 0 | 0 | 17 | 0 |
| test_membership_dues_enhanced_features.py | 29 | 22 | 1 | 6 | 0 |
| test_membership_dues_security_validation.py | 8 | 0 | 8 | 0 | 0 |
| test_membership_dues_stress_testing.py | 6 | 0 | 0 | 6 | 0 |
| test_membership_dues_system.py | 11 | 10 | 1 | 0 | 0 |
| test_membership_status.py | 14 | 8 | 1 | 5 | 0 |
| test_membership_type_minimum_period.py | 11 | 9 | 1 | 0 | 1 |
| test_member_status_transitions.py | 14 | 8 | 2 | 4 | 0 |
| test_overdue_payments_report.py | 17 | 13 | 0 | 4 | 0 |
| test_overdue_payments_report_real.py | 17 | 14 | 1 | 2 | 0 |
| test_overdue_payments_report_regression.py | 3 | 0 | 0 | 2 | 1 |
| test_payment_api_real_working.py | 5 | 3 | 0 | 0 | 2 |
| test_payment_plan_system.py | 16 | 13 | 1 | 2 | 0 |
| test_payment_processing_api.py | 21 | 13 | 2 | 4 | 2 |
| test_payment_processing_api_real.py | 10 | 7 | 2 | 1 | 0 |
| test_payment_processing_real_template_handling.py | 10 | 5 | 1 | 4 | 0 |
| test_payment_response_serialization.py | 6 | 2 | 1 | 3 | 0 |
| test_payment_retry.py | 10 | 7 | 0 | 3 | 0 |
| test_retry_utilities_core.py | 26 | 11 | 6 | 9 | 0 |
| test_sales_invoice_chapter_population.py | 9 | 3 | 0 | 6 | 0 |
| test_sepa_mandate_creation.py | 17 | 8 | 2 | 7 | 0 |
| test_sepa_notifications.py | 6 | 5 | 0 | 1 | 0 |
| test_sepa_reconciliation.py | 9 | 5 | 0 | 1 | 3 |
| test_setup_btw_eboekhouden.py | 13 | 6 | 0 | 6 | 1 |
| test_setup_custom_fields.py | 19 | 12 | 0 | 5 | 2 |
| test_setup_init.py | 30 | 18 | 0 | 10 | 2 |
| test_setup_reference_cors.py | 19 | 10 | 0 | 7 | 2 |
| test_setup_termination.py | 18 | 6 | 2 | 9 | 1 |
| test_setup_workspace_onboarding.py | 20 | 11 | 0 | 8 | 1 |
| test_staff_anbi_allocation.py | 20 | 9 | 2 | 9 | 0 |
| test_suspension_member_mixin_unit.py | 12 | 8 | 3 | 0 | 1 |
| test_team_assignment_history.py | 4 | 4 | 0 | 0 | 0 |
| test_termination_system.py | 14 | 6 | 4 | 0 | 4 |
| test_volunteer_api.py | 12 | 8 | 3 | 1 | 0 |
| test_volunteer_assignment_event_driven.py | 7 | 5 | 0 | 2 | 0 |
| test_volunteer_assignment_history_bugs.py | 8 | 0 | 0 | 8 | 0 |
| test_volunteer_edge_cases.py | 14 | 0 | 0 | 14 | 0 |
| test_approval_workflow.py | 0 | 0 | 0 | 0 | 0 |
| test_base.py | 0 | 0 | 0 | 0 | 0 |
| test_fee_logic.py | 0 | 0 | 0 | 0 | 0 |
| test_membership_utilities.py | 0 | 0 | 0 | 0 | 0 |
| test_payment_reports_runner.py | 0 | 0 | 0 | 0 | 0 |
| test_setup.py | 0 | 0 | 0 | 0 | 0 |
| test_termination_display.py | 0 | 0 | 0 | 0 | 0 |
| test_termination_impact.py | 0 | 0 | 0 | 0 | 0 |
| **DOMAIN TOTALS** | **950** | **538** | **93** | **288** | **31** |

## Observations

- **Happy-path dominant (538/950, 57%), Edge strong (288, 30%), Unhappy thin (93, 10%).** The suite leans on nominal-success and boundary coverage; explicit error/permission/rejection assertions are comparatively rare and concentrated in a handful of security/permissions/retry files.
- **Unhappy coverage is highly clustered, not spread.** Nearly all UNHAPPY methods live in a few files: `test_membership_analytics_permissions.py` (8, all PermissionError), `test_membership_dues_security_validation.py` (8, all permission/prevention), `test_retry_utilities_core.py` (6) and `test_deadlock_retry_utilities.py` (6). Most feature/report tests assert only the success shape.
- **Edge coverage is often name-signalled by convention.** Files suffixed `_edge_cases` (`test_chapter_edge_cases`, `test_volunteer_edge_cases`, `test_membership_dues_edge_cases`) and `_history_bugs` are 100% EDGE, and setup files are idempotency-heavy (every `*_idempotent` counted EDGE). Idempotency/no-clobber assertions are the single largest EDGE sub-theme.
- **Duplicate `_real` / `_optimized_real` report suites exist.** ANBI and overdue-payments reports each have a mock-based unit file plus one or two "real database" siblings that re-exercise the same functions as happy paths — coverage overlap, and a source of inflated Happy counts.
- **OTHER (31) is mostly import/existence smoke, deprecated-function tests, and meta "summary/mock-elimination" tests.** Examples: `*_function_exists`, `*_runs_without_error`, `real_vs_mocked_performance_comparison`, `database_mock_elimination_summary`, `create_donation_types_manual_deprecated`. A few skip-dominated methods in `test_termination_system` (infra-guarded `skipTest`) and `test_sepa_reconciliation` (3 hard skips) also landed here.
- **Boundary-vs-rejection ambiguity affects ~40 methods.** Tests where a boundary value (zero amount, over-100% percentage, duplicate id) triggers a `ValidationError` were classified by their salient feature: pure boundary → EDGE, explicit denial/permission → UNHAPPY. This is the main judgment call and shifts the E/U split by a few percent either way.

## Zero-method / non-test files (8)

These matched `test_*.py` but contain **no class-level `def test_*`** (Total = 0). They are scripts or helpers, not unit-test modules:

- `test_base.py` — base `VereningingenTestCase(unittest.TestCase)` helper class only.
- `test_membership_utilities.py` — `MembershipTestUtilities` helper class (fixtures/utilities), no tests.
- `test_setup.py` — module-level setup helper functions (`setup_test_environment`, `setup_test_company`, …).
- `test_approval_workflow.py` — single module-level debug script `test_approval_fix()` (not a TestCase method).
- `test_fee_logic.py` — module-level debug functions (`test_new_application_with_custom_amount`, `run_all_tests`), script-style, no asserting TestCase.
- `test_payment_reports_runner.py` — a test *runner* plus module-level `run_*`/`test_*_import` script functions.
- `test_termination_display.py` — single module-level `test_termination_display()` print/debug script.
- `test_termination_impact.py` — single module-level `test_termination_impact()` print/debug script.

## Notes on prior spot-checks

- `test_membership_analytics_permissions.py` — confirmed 10 methods, 0H/8U/2E/0O (the 2 EDGE = `chapter_data_isolation`, `sensitive_data_masking`, both guarded/near-vacuous). Matches prior spot-check.
- `test_membership_application.py` — 63 methods present; adopted prior spot-check split 28H/6U/27E/2O (heavily edge-weighted, ~15 skips, `test_overdue_detection`=assertTrue(True), `test_database_connection_recovery`=simulation-only).
