# Domain A8 — backend/unit/services (part 2) — Test Inventory

Read-only classification of every `def test_*` method across 18 files under
`verenigingen/tests/backend/unit/services/`. Each method assigned ONE primary
type (HAPPY / UNHAPPY / EDGE / OTHER). Dominant intent wins.

This tree mixes two styles: (a) **mock-heavy pure unit tests** that patch
`frappe` and drive the service directly (event_emission, onload,
status_notification, validation), and (b) **integration-flavored "unit" tests**
that hit real DocTypes via `EnhancedTestCase`/`VereningingenTestCase` factories
(the `_api` and `_coverage` files). Where mocking defeats the assertion, it is
flagged OTHER.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_member_event_emission_service.py | 11 | 5 | 1 | 5 | 0 |
| test_member_history_update_helpers.py | 9 | 4 | 0 | 5 | 0 |
| test_member_history_update_service.py | 27 | 15 | 1 | 11 | 0 |
| test_member_id_service.py | 13 | 4 | 8 | 1 | 0 |
| test_member_merge_api.py | 8 | 4 | 4 | 0 | 0 |
| test_member_onload_service.py | 16 | 8 | 6 | 2 | 0 |
| test_membership_application_service_coverage.py | 21 | 10 | 5 | 6 | 0 |
| test_membership_creation_service_coverage.py | 17 | 3 | 9 | 4 | 1 |
| test_member_status_notification_service.py | 15 | 10 | 0 | 5 | 0 |
| test_member_test_utilities_api.py | 9 | 7 | 1 | 1 | 0 |
| test_member_user_account_service.py | 11 | 8 | 3 | 0 | 0 |
| test_member_validation_service.py | 13 | 7 | 0 | 6 | 0 |
| test_payment_history_service.py | 17 | 5 | 0 | 8 | 4 |
| test_payment_validation_api.py | 10 | 5 | 3 | 2 | 0 |
| test_payment_validation_service.py | 45 | 14 | 19 | 11 | 1 |
| test_sepa_mandate_api.py | 7 | 4 | 3 | 0 | 0 |
| test_service_import_safety_unit.py | 4 | 0 | 0 | 0 | 4 |
| test_service_integration_api.py | 6 | 5 | 0 | 1 | 0 |
| **DOMAIN TOTALS** | **259** | **118** | **63** | **68** | **10** |

## Observations

- **Tautological / no-op tests flagged OTHER (real quality issues):**
  `test_payment_history_service.py::test_determine_payment_status_draft` and
  `::test_determine_payment_status_paid` set attributes on a `MagicMock` and
  then assert those same attributes — the production `_determine_payment_status`
  is never invoked (the real logic is instead covered in
  test_member_history_update_service.py). `test_payment_validation_service.py::
  test_bic_required_but_missing` has **zero assertions** (only a comment about
  what "should" happen) — it can never fail.

- **`test_service_import_safety_unit.py` is entirely import-smoke (all 4 OTHER)**
  as predicted: verifies no DB calls / lazy singletons / import time / clean
  import. Uses instrumented *detection* mocks (explicitly exempted via
  `test-quality-enforcer: exempt-detection-mocks`), not replacement mocks — a
  legitimate use, but asserts infrastructure hygiene, not business behavior.

- **Weak "returns_operation_result" + conditional-assertion pattern is pervasive
  in the `_api` files** (merge_api, test_utilities_api, payment_validation_api,
  sepa_mandate_api, service_integration_api). Many "happy" tests only assert
  `"success" in result` or guard real checks behind `if result["success"]:`, so
  on failure they still pass. Counted HAPPY by intent, but their regression-catch
  power is thin. The `*_never_throw_exceptions` sweeps loop invalid inputs and
  are counted UNHAPPY (they expect graceful failure), though several also only
  assert non-None.

- **Mock-heavy pure-unit files are genuinely meaningful** despite patching
  `frappe`: event_emission, onload, status_notification, and validation services
  drive the real service method and assert on emitted events, isolated error
  handling, notification-config selection, and skip/clear branch logic. These
  are the strongest tests in the domain (skip-flags, error isolation, and
  status-config branches dominate their EDGE/UNHAPPY counts).

- **Best pure-logic coverage** lives in test_member_history_update_helpers.py
  and the `TestInvoiceHistoryHelpers` / `TestBuildContributionSettings` classes:
  static helpers exercised on plain `frappe._dict` stubs with real assertions on
  field mapping, fallbacks, stale-row scoping, dedup, and payment-status mapping.
  Rich EDGE coverage (falsy fallbacks, most-recent ordering, missing data,
  malformed multipliers).

- **UNHAPPY concentration** is in the validation services: payment_validation_service
  (19 UNHAPPY of 45 — invalid IBAN/BIC/amount/method paths) and
  membership_creation_service_coverage (9 UNHAPPY of 17 — defense-in-depth
  `frappe.ValidationError` raises for bad doctype/unsaved/negative/absurd/
  non-numeric/non-dict inputs). member_id_service is also rejection-heavy
  (8 UNHAPPY: empty/nonexistent/already-has-id).

- **Amount/BIC boundary tests** in payment_validation_service straddle
  UNHAPPY vs EDGE: clearly-invalid inputs (negative, None, non-numeric type,
  nonexistent/disabled method) counted UNHAPPY; true boundaries
  (zero, below-min, above-max, custom min/max, excessive decimals,
  case-insensitivity, precision) counted EDGE.

## Missing files

None. All 18 assigned files were present and classified.
