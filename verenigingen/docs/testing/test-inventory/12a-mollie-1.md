# Test Inventory 12a — Mollie payments app, part 1

Read-only classification of every `def test_*` method across 23 files under
`verenigingen/verenigingen_payments/mollie/tests/`. Each method assigned ONE
primary type by dominant intent (HAPPY / UNHAPPY / EDGE / OTHER).

**Domain shape:** 368 test methods. Coverage skews heavily toward EDGE (145,
40%) and HAPPY (133, 36%), with a strong UNHAPPY block (81, 22%) concentrated in
the base-client HTTP-error sweep and the bulk-payment admin-page guards. Only 9
OTHER (2%). Two files carry zero `test_*` methods (a factory and an API harness).

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| fixtures/test_factory.py | 0 | 0 | 0 | 0 | 0 |
| integration/test_real_api.py | 7 | 5 | 1 | 1 | 0 |
| integration/test_subscription_integration.py | 4 | 2 | 0 | 0 | 2 |
| test_amount_helpers_unit.py | 26 | 14 | 0 | 12 | 0 |
| test_api_integration.py | 0 | 0 | 0 | 0 | 0 |
| test_bulk_payment_checker_flow_unit.py | 19 | 3 | 3 | 13 | 0 |
| test_bulk_payment_checker_unit.py | 24 | 4 | 0 | 20 | 0 |
| test_common_helpers.py | 49 | 29 | 8 | 12 | 0 |
| test_complete_payment_service_integration.py | 28 | 8 | 14 | 6 | 0 |
| test_core_integration.py | 10 | 3 | 1 | 1 | 5 |
| test_cost_center_resolver.py | 7 | 3 | 0 | 4 | 0 |
| test_customer_creation_concurrency.py | 5 | 0 | 0 | 3 | 2 |
| test_donation_lookup_integration.py | 22 | 13 | 0 | 9 | 0 |
| test_dues_payment_processor_coverage_sweep.py | 11 | 4 | 0 | 7 | 0 |
| test_dues_payment_processor_creation_unit.py | 10 | 4 | 1 | 5 | 0 |
| test_dues_payment_processor_integration.py | 5 | 3 | 0 | 2 | 0 |
| test_dues_payment_processor_unit.py | 22 | 6 | 5 | 11 | 0 |
| test_failed_payment_processing.py | 7 | 4 | 1 | 2 | 0 |
| test_integration_boundaries.py | 15 | 6 | 4 | 5 | 0 |
| test_mollie_audit_unit.py | 16 | 6 | 3 | 7 | 0 |
| test_mollie_base_client_sweep.py | 42 | 7 | 18 | 17 | 0 |
| test_mollie_bulk_payment_creation.py | 39 | 9 | 22 | 8 | 0 |
| **DOMAIN TOTALS** | **368** | **133** | **81** | **145** | **9** |

## Observations

- **Live/skip-gated files (skip cleanly without Mollie credentials):**
  `integration/test_real_api.py` (setUpClass raises SkipTest when no test key /
  API unreachable — all 7 methods gated); `integration/test_subscription_integration.py`
  (`@unittest.skipUnless(_has_live_mollie_credentials())` — all 4 gated);
  `test_core_integration.py::TestMollieCoreIntegration` (skips per-method when no
  `test_` API key). CI without a key runs none of these. Base class throughout the
  domain is `EnhancedTestCase` (from `enhanced_test_factory`); the pure-unit
  base-client/bulk-checker-unit/cost-center files use plain `unittest.TestCase`
  or `FrappeTestCase`.

- **`test_integration_boundaries.py` is almost entirely dead:** 3 of 4 classes are
  `@unittest.skip`ed wholesale (subscription lifecycle, webhook processing,
  chargeback handling) plus 2 more skipped methods — all documented as
  "unimplemented feature" / "non-existent contract". Only 1 of 15 methods
  (`test_invalid_webhook_payload_handling`) actually runs. Classified by intent
  but effectively non-executing coverage.

- **Mock-tautology flags (OTHER):** `test_subscription_integration.py::test_phase4d_dutch_business_rules_validation`
  defines its OWN regex patterns + VAT arithmetic inside the test and asserts
  `re.match`/`round()` against them — exercises no production code (tautological);
  its `test_phase4d_performance_monitoring_baseline` is pure `assertQueryCount`
  timing/print with no behavioral assertions. In `test_core_integration.py` the 4
  `TestMollieClientContractValidation` methods are `hasattr`/`Mock(spec=...)`
  contract smoke tests, and `test_performance_baselines_validation` only prints
  timings — all OTHER.

- **Disabled/placeholder tests (not counted):** `test_failed_payment_processing.py`
  carries 6 `_disabled_*` methods (WebhookWrapperService archived) that are not
  `test_*` and don't run. `test_customer_creation_concurrency.py` has 2 real
  placeholder bodies (`test_lock_contention_logging`, `test_full_service_concurrent_creation`)
  that are pure `pass`/`skipTest` — counted as OTHER (setup-only/tautological).

- **UNHAPPY concentration is genuine, not tautological:** the two big UNHAPPY
  blocks — `test_mollie_base_client_sweep.py` (18: real HTTP status→exception
  mapping 401/403/404/422/429/5xx, IBAN/currency/amount validation, strict
  financial-field raises incl. a documented regression guard for the
  `ResponseValidationError` kwarg bug) and `test_mollie_bulk_payment_creation.py`
  (22: CSV/interval/amount/row-count/permission guards on a financially sensitive
  admin page) — assert real error paths against real code, with only the HTTP
  transport / Mollie SDK boundary faked.

- **EDGE-heavy pure-unit files carry the boundary logic:** the bulk-payment-checker
  unit + flow files (24+19) and amount-helpers (26) are dominated by
  null/empty/currency/date-filter/idempotency/dedup/fallback branch tests — real
  pure-function coverage with SimpleNamespace SDK stubs, no `unittest.mock.patch`.

## Missing / zero-method files

- **fixtures/test_factory.py** — factory helper (`MollieTestDataFactory` +
  `MollieTestCase` base + convenience `mollie_factory` instance). Verified: NO
  `def test_*` methods; the `if __name__ == "__main__"` block is a manual demo, not
  a test. Correctly a fixtures module.
- **test_api_integration.py** — contains only `run_mollie_integration_test()`, a
  `@frappe.whitelist()` / `@development_only_api` API-callable harness (prints a
  results list). NO `test_*` methods; not a unittest module despite the filename.
