# Test Inventory — Domain BINTEG (tests/backend/integration)

READ-ONLY classification of every class-level `def test_*` method. Audit complete: 17 files, 219 methods.

Classification key: HAPPY = nominal success path; UNHAPPY = expects error/throw/validation-failure/permission-denial; EDGE = boundary/empty/null/duplicate/concurrency/idempotency/malformed/ordering/cross-module edges; OTHER = smoke/import-safety/setup-only/tautological/no-assert/HTTP-status-set-only/skip-dominated.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_b6_b9_backends.py | 6 | 2 | 2 | 2 | 0 |
| test_chapter_cost_center_seeding.py | 2 | 0 | 0 | 1 | 1 |
| test_concurrency_safety.py | 5 | 0 | 1 | 4 | 0 |
| test_eboekhouden_integration.py | 12 | 0 | 0 | 0 | 12 |
| test_erpnext_expense_integration.py | 29 | 4 | 4 | 0 | 21 |
| test_erpnext_expense_integration_real.py | 17 | 9 | 2 | 4 | 2 |
| test_erpnext_integration_complete.py | 9 | 6 | 0 | 0 | 3 |
| test_javascript_api_integration.py | 7 | 1 | 0 | 1 | 5 |
| test_member_contact_request_integration.py | 10 | 8 | 1 | 1 | 0 |
| test_notification_configuration_integration.py | 12 | 5 | 4 | 3 | 0 |
| test_payment_report_integration.py | 7 | 5 | 1 | 0 | 1 |
| test_sepa_duplicate_prevention_core.py | 34 | 5 | 9 | 18 | 2 |
| test_sepa_duplicate_prevention_coverage.py | 24 | 8 | 2 | 12 | 2 |
| test_sepa_security_feedback.py | 19 | 3 | 3 | 10 | 3 |
| test_suspension_integration.py | 11 | 5 | 3 | 3 | 0 |
| test_suspension_integration_real.py | 7 | 5 | 1 | 1 | 0 |
| test_volunteer_portal_integration.py | 8 | 5 | 1 | 0 | 2 |
| **DOMAIN TOTALS** | **219** | **71** | **34** | **60** | **54** |

## Observations

- **Real integration, not HTTP smoke.** Unlike some other domains, this cluster contains *no* "HTTP-status-set-only + print" tests. Everything calls Python service/API functions directly against a real DB (EnhancedTestCase / VereningingenTestCase). The closest to smoke is `test_payment_report_integration.py`, which executes real report/API business logic but guards most business assertions behind `if data:` and falls back to `print()` — the guaranteed assertions are only structural (`isinstance list/dict`). It is print-heavy but not status-code theater.
- **Skip debt dominates the OTHER bucket (54 total).** The single largest OTHER contributor is `test_eboekhouden_integration.py` — the *entire class* is `@unittest.skip` ("outdated/incorrect schema"), so all 12 methods are dead. `test_erpnext_expense_integration.py` carries 13 `@unittest.skip(VOLUNTEER_EXPENSE_ARCHIVED)` methods plus 8 tautological/setup-only ones (asserts on dict literals or fixture existence). Other unconditional skips: 3 in `test_erpnext_integration_complete.py` (multi-currency / expense-claim / tax "requires complex setup"), 2 in `test_volunteer_portal_integration.py` (unimplemented DocType/function), 1 SEPA mandate-sequence concurrency test.
- **SEPA files are the strongest and most EDGE-heavy.** `test_sepa_duplicate_prevention_core.py` (34), `_coverage.py` (24) and `test_sepa_security_feedback.py` (19) account for 40 of the 60 EDGE tests — tight, well-documented coverage of lock semantics, TTL expiry, idempotency-key determinism, tolerance boundaries, duplicate-prevention throws, and XML-security attacks (XXE / billion-laughs / size-limit). These read as deliberate, high-value integration tests, not coverage padding.
- **Best-shaped conventional files:** `test_member_contact_request_integration.py` (10 methods, 8 happy / 1 edge / 1 permission-denial, all real DB, zero skips) and the two suspension files (`test_suspension_integration.py` 11, `_real.py` 7) — clean happy/unhappy/edge splits exercising real member-status + user-account + team side effects.
- **Weak spots beyond skips:** `test_javascript_api_integration.py` is mostly static source-code linting (5 of 7 methods `grep` .py/.js files for `int()`/`@whitelist` patterns rather than executing anything) — misfiled as "integration." `test_payment_report_integration.py::test_permission_integration_workflow_real_permission_system` has *no assertions at all* (only `print()` of accessible-chapter lists across three user roles). Several `get_organization_cost_center` tests in `test_erpnext_expense_integration.py` assert only `isinstance(result, (str, type(None)))` ("doesn't crash").
- **Base classes:** overwhelmingly `EnhancedTestCase` (15 files); `test_b6_b9_backends.py` and `test_member_contact_request_integration.py` use `VereningingenTestCase`. `test_notification_configuration_integration.py` mixes in `FlagBackupMixin`; SEPA-security/coverage use a local `_RedisEnabledTestCase` subclass. Email/SMTP is consistently mocked (`patch("frappe.sendmail")`) as an external-service boundary; business logic is not mocked.

## Files with zero methods / missing

None. All 17 files were found and every file contained class-level `def test_*` methods. Note two files are effectively inert at runtime: `test_eboekhouden_integration.py` (whole class skipped, 12/12 OTHER) and the heavily-skipped `test_erpnext_expense_integration.py` (13/29 skipped).
