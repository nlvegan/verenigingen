# Test Inventory: tests/api (Domain 29)

> WIP — incremental audit in progress. READ-ONLY classification of every class-level `def test_*` method.
> Categories: HAPPY (nominal success) · UNHAPPY (expects error/throw/denial) · EDGE (boundary/empty/null/dup/idempotency/malformed/guest/ordering) · OTHER (smoke/setup-only/tautological/skip-dominated).

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_anbi_operations.py | 25 | 9 | 10 | 5 | 1 |
| test_chapter_validation.py | 20 | 6 | 7 | 7 | 0 |
| test_check_account_types.py | 21 | 13 | 1 | 6 | 1 |
| test_dashboard_charts.py | 7 | 1 | 0 | 3 | 3 |
| test_document_portal.py | 27 | 6 | 5 | 16 | 0 |
| test_dues_invoice_workflow.py | 14 | 6 | 0 | 6 | 2 |
| test_email_template_manager.py | 17 | 9 | 2 | 6 | 0 |
| test_get_user_chapters.py | 7 | 1 | 0 | 6 | 0 |
| test_manual_invoice_generation.py | 12 | 5 | 4 | 3 | 0 |
| test_membership_email_templates.py | 4 | 2 | 0 | 2 | 0 |
| test_periodic_donation_operations.py | 18 | 9 | 3 | 6 | 0 |
| test_schedule_maintenance.py | 16 | 7 | 1 | 6 | 2 |
| test_security_monitoring_dashboard.py | 16 | 6 | 0 | 3 | 7 |
| test_sepa_health.py | 10 | 0 | 0 | 0 | 10 |
| test_sepa_startup_check.py | 9 | 2 | 3 | 2 | 2 |
| test_team_admin_utilities.py | 9 | 3 | 4 | 1 | 1 |
| test_volunteer_application.py | 23 | 7 | 4 | 12 | 0 |
| test_workspace_health.py | 14 | 5 | 3 | 5 | 1 |
| test_workspace_validator_enhanced.py | 9 | 4 | 3 | 0 | 2 |
| **DOMAIN TOTALS** | **278** | **101** | **50** | **95** | **32** |

## Observations

- **Distribution:** 278 test methods across 19 files. Happy 101 (36%), Edge 95 (34%), Unhappy 50 (18%), Other 32 (12%). Edge + Unhappy together (52%) outweigh pure happy-path coverage — these suites lean hard into negative/boundary behaviour, which is healthy for security- and validation-heavy API endpoints.
- **Classification note on guest/permission tests:** Per the rubric's explicit "guest/unauthenticated edge" carve-out, framework-level Guest `PermissionError` blocks were counted as EDGE, while authorization *denials* returning a `permission_denied` result envelope (IDOR cross-org checks) were counted as UNHAPPY. This split is why `test_document_portal.py` (16 EDGE) and `test_volunteer_application.py` (12 EDGE) dominate the EDGE column — both are guest-facing endpoints with heavy input-validation and injection-neutralization tests (malicious `status`/`user` fields, XSS, mime spoofing).
- **OTHER concentration = shape/smoke suites:** `test_sepa_health.py` is 10/10 OTHER — every method only asserts key-presence and value *types* on `get_sepa_health()` with no seeding, no behaviour, no failure branch. `test_security_monitoring_dashboard.py` (7 OTHER) similarly front-loads envelope-shape and tautological-bounds checks (e.g. `0 <= success_rate <= 100`). These two files hold 17 of the 32 OTHER methods.
- **Weak "returns_operation_result" / branch-guarded pattern spotted (counted OTHER):** `test_prepare_sepa_batch_returns_operation_result` (dues_invoice_workflow) passes on *either* the success or the `NO_ELIGIBLE_INVOICES` failure branch — it can never fail meaningfully. `test_send_consent_requests_targets_unconsented_donors` (anbi) asserts only `sent_count >= 0` (tautological) after admitting it cannot verify the email was sent. `test_fix_all_returns_summary_and_does_not_error` (team_admin) asserts `volunteers_fixed >= 0`.
- **Intentional characterization / dead-code tripwires:** `test_broken_link_detection_is_currently_dead_code` (workspace_health) deliberately pins a KNOWN BUG (`link.type` vs `link_type` comparison) and asserts the broken-link branch is NEVER reached — counted OTHER, and flagged in-code as a tripwire to fail if the bug is fixed. `test_rate_limit_and_auth_sections_have_stable_shape` similarly documents dead process_type filters.
- **Strong suites:** `test_check_account_types.py` (13 HAPPY) and `test_email_template_manager.py` (9 HAPPY, 2 UNHAPPY, 6 EDGE) assert real persisted effects (account_type mutation with DB re-read, template render with exact context substitution, idempotency counts), not just success flags. `test_periodic_donation_operations.py` and `test_manual_invoice_generation.py` verify real Sales Invoice / agreement field values against seeds.

## Coverage notes

- All 19 discovered files contain at least one class-level `def test_*`; **no zero-method or empty files** were found.
- `find verenigingen/tests/api -name "test_*.py"` returned exactly 19 files, all audited. No `@unittest.skip`-dominated files were found (only `test_sepa_startup_check.py` imports `unittest`, and it uses `patch`, not skips).
