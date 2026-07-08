# Test Inventory 24 — Integration (tests/integration, excluding services/)

> **WIP** — incremental audit in progress. READ-ONLY classification of each class-level `def test_*`.
> Types: HAPPY (nominal success) · UNHAPPY (expects error/throw/denial) · EDGE (boundary/empty/dup/concurrency/idempotency/malformed/ordering/cross-module) · OTHER (smoke/setup-only/tautological/no-assert/skip-dominated).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_account_creation_real.py | 10 | 5 | 3 | 2 | 0 |
| test_account_creation_service_orchestration.py | 12 | 6 | 2 | 4 | 0 |
| test_api_authentication_decorators_integration.py | 12 | 2 | 8 | 1 | 1 |
| test_api_security_phase3.py | 2 | 0 | 1 | 0 | 1 |
| test_application_payments_invoice_paths.py | 7 | 4 | 1 | 2 | 0 |
| test_authentication_flows.py | 19 | 7 | 7 | 4 | 1 |
| test_bank_transaction_security.py | 12 | 5 | 2 | 4 | 1 |
| test_canonical_approval_chapter_activation.py | 1 | 1 | 0 | 0 | 0 |
| test_chapter_membership_approval_integration.py | 17 | 8 | 0 | 9 | 0 |
| test_contribution_mode_template_integration.py | 21 | 10 | 0 | 11 | 0 |
| test_document_reclassify_service.py | 9 | 2 | 2 | 5 | 0 |
| test_dutch_business_rules_phase3.py | 7 | 6 | 0 | 1 | 0 |
| test_employee_user_link_security.py | 7 | 2 | 2 | 1 | 2 |
| test_invoice_generator_integration.py | 1 | 1 | 0 | 0 | 0 |
| test_member_doctype_phase3_security.py | 8 | 4 | 1 | 0 | 3 |
| test_member_lifecycle_complete_real.py | 7 | 7 | 0 | 0 | 0 |
| test_membership_approval.py | 8 | 5 | 1 | 1 | 1 |
| test_membership_type_change_integration.py | 17 | 11 | 2 | 4 | 0 |
| test_mollie_bulk_transaction_consumer_data_qa.py | 27 | 13 | 1 | 10 | 3 |
| test_monitoring_system.py | 0 | 0 | 0 | 0 | 0 |
| test_organization_document_applies_on.py | 5 | 2 | 0 | 3 | 0 |
| test_payment_api_integration_simple.py | 2 | 1 | 1 | 0 | 0 |
| test_payment_processing_api_integration.py | 10 | 6 | 3 | 0 | 1 |
| test_payment_processing_http_integration.py | 4 | 0 | 1 | 0 | 3 |
| test_performance_with_real_data.py | 8 | 2 | 0 | 0 | 6 |
| test_permission_bypass_elimination_validation.py | 8 | 0 | 0 | 0 | 8 |
| test_portal_authentication_security.py | 15 | 5 | 4 | 5 | 1 |
| test_public_api_guest_access.py | 10 | 5 | 1 | 0 | 4 |
| test_query_optimization_suite.py | 10 | 1 | 1 | 1 | 7 |
| test_security_framework_integration.py | 12 | 3 | 0 | 6 | 3 |
| test_sepa_mandate_authentication_security.py | 12 | 1 | 8 | 2 | 1 |
| test_sepa_mandate_real.py | 9 | 6 | 3 | 0 | 0 |
| test_sepa_payment_workflow.py | 5 | 4 | 0 | 1 | 0 |
| test_source_folder_backfill.py | 4 | 1 | 0 | 3 | 0 |
| test_suspension_api_http_integration.py | 11 | 1 | 0 | 0 | 10 |
| test_suspension_api_simple_http.py | 3 | 0 | 0 | 0 | 3 |
| test_team_background_jobs.py | 5 | 4 | 0 | 0 | 1 |
| test_team_member_lifecycle.py | 4 | 3 | 0 | 1 | 0 |
| **DOMAIN TOTALS** | **341** | **144** | **55** | **81** | **61** |

> Audit complete — all 38 files classified.

## Observations

- **Security/permission tests dominate the UNHAPPY column.** Nearly all 55 UNHAPPY methods are permission-denial or validation-rejection assertions (`assertRaises(PermissionError | ValidationError | DoesNotExistError)`). The API-decorator / SEPA-auth / auth-flow files (`test_api_authentication_decorators_integration`, `test_sepa_mandate_authentication_security`, `test_authentication_flows`) are role-matrix suites that pair one positive path with several negative denials per method; these were classified UNHAPPY because the distinctive, load-bearing assertions are the denials. Where a method's primary axis was a data/state boundary rather than a throw (e.g. concurrency, case-insensitive matching, active_only filtering) it was placed in EDGE.
- **A large OTHER bucket (61, ~18%) is concentrated in a few files and is mostly weak-by-design.** Two whole files are pure source-inspection meta-tests (`test_permission_bypass_elimination_validation` 8/8, plus the `no_permission_bypasses`/`security_validation` meta-tests in `employee_user_link_security` and `member_doctype_phase3_security`). The HTTP-integration files (`test_suspension_api_http_integration`, `test_suspension_api_simple_http`, `test_payment_processing_http_integration`) are the biggest source of tautological OTHERs: they accept `status_code in [200, 401, 403]` and only `print()` — they cannot fail on business behavior (and mostly `skipTest` when no live web server is reachable). Performance/timing tests (`test_performance_with_real_data`, `test_query_optimization_suite`, plus scattered `*_performance*` methods) round out OTHER.
- **EDGE (81, ~24%) is genuinely rich**, driven by three clusters: (1) the contribution-mode/fee-template files exhaustively exercise absent/zero/`None` suggested-amount fallbacks; (2) chapter-membership approval/termination covers idempotency, multiple-chapter fan-out, pending-vs-active state, and orphaned-row partial-failure; (3) document-reclassify / source-folder-backfill / organization-document cover skip/no-op/dry-run/precision-snapping boundaries.
- **Several methods assert their stated purpose only tautologically** and were marked OTHER despite living among real tests — e.g. `test_authentication_flows::test_sepa_mandate_cross_member_prevention` (never asserts the cross-member block it names), `test_membership_approval::test_approval_workflow_validation_errors` (`if approved… else…` accepts either outcome), `test_public_api_guest_access::test_cor_rules_exist_for_public_endpoints` (prints a WARNING, never fails), and the `audit_trail`/`permission_validation_works` methods that assert `len(...) >= 0`.
- **Genuinely mock-free happy-path integration coverage is strongest** in `test_member_lifecycle_complete_real` (7/7 HAPPY), `test_sepa_mandate_real`, `test_contribution_mode_template_integration`, `test_payment_processing_api_integration`, and `test_membership_type_change_integration` — these drive real DocType saves/submits and assert concrete downstream field/state values.
- **Concurrency is a recurring EDGE pattern** implemented consistently (`test_api_concurrent_access_safety`, `test_concurrent_authentication_safety`, `test_portal_concurrent_session_safety`, `test_sepa_mandate_concurrent_access_safety`) — each spins its own per-thread `frappe.init()/connect()` and commits setUp data first so worker connections can see roles.

## Notes on zero-method / missing / special files

- `test_monitoring_system.py` — **0 class-level `def test_*`**. It defines a plain `MonitoringSystemTestRunner` class (not a `unittest.TestCase`) with a `run_all_tests()` method plus a module-level `run_comprehensive_tests()`; nothing is discoverable by the test runner. Counted as 0.
- `test_api_security_phase3.py` — 2 methods, but 1 (`test_csrf_protection_validation`) is `@unittest.skip` (no HTTP request context under `bench run-tests`) → counted OTHER.
- `test_public_api_guest_access.py::test_guest_can_access_membership_types` — `@unittest.skip` (imports a since-removed module) → counted OTHER.
- File count: prompt estimated ~29; actual is **38** `test_*.py` files under `tests/integration` excluding `services/`. All 38 audited.
- Nested helper functions defined inside test bodies (e.g. `def test_public_endpoint()` inside `test_api_authentication_decorators_integration`) were excluded; only class-level methods were counted.
