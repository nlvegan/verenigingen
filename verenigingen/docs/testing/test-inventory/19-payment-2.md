# Test Inventory — Domain PAY2 (tests/payment, part 2)

> **WIP** — Incremental audit in progress. Read-only classification of every
> class-level `def test_*` into HAPPY / UNHAPPY / EDGE / OTHER.
> Files 86-170 of `find verenigingen/tests/payment -name "test_*.py" | sort` (85 files).

Classification key:
- **HAPPY** = nominal success / expected-valid path
- **UNHAPPY** = expects error/throw/validation-failure/permission-denial/rejection/signature-reject
- **EDGE** = boundary, empty/null/zero, duplicate/replay, concurrency, idempotency, malformed data, retry/backoff, proration/rounding
- **OTHER** = smoke/import-safety/setup-only/tautological/debug-no-assert/mock-tautology/skip-dominated

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_mollie_webhook_wrapper_coverage_b2.py | 5 | 0 | 1 | 4 | 0 |
| test_mt940_import_coverage.py | 26 | 13 | 0 | 13 | 0 |
| test_mt940_import_integration.py | 16 | 9 | 2 | 5 | 0 |
| test_mt940_parsing.py | 24 | 9 | 0 | 15 | 0 |
| test_organizations_client.py | 12 | 7 | 3 | 2 | 0 |
| test_payment_alert_service.py | 15 | 6 | 7 | 1 | 1 |
| test_payment_api_mutations.py | 7 | 5 | 0 | 1 | 1 |
| test_payment_baseline_comparison.py | 1 | 0 | 0 | 0 | 1 |
| test_payment_data_extractor_examples.py | 27 | 20 | 5 | 2 | 0 |
| test_payment_data_extractor.py | 47 | 21 | 10 | 15 | 1 |
| test_payment_doctype_coverage.py | 63 | 29 | 24 | 10 | 0 |
| test_payment_entry_cleanup.py | 22 | 11 | 2 | 8 | 1 |
| test_payment_entry_handler.py | 9 | 5 | 2 | 1 | 1 |
| test_payment_failure_email_templates.py | 9 | 4 | 1 | 2 | 2 |
| test_payment_gateways_coverage.py | 29 | 12 | 7 | 10 | 0 |
| test_payment_gateways_endpoints.py | 13 | 3 | 7 | 2 | 1 |
| test_payment_gateways_live.py | 4 | 2 | 1 | 1 | 0 |
| test_payment_gateways.py | 17 | 10 | 4 | 2 | 1 |
| test_payment_gateways_sepa_ponto_coverage.py | 16 | 8 | 1 | 5 | 2 |
| test_payment_gateways_subscription_sweep.py | 19 | 3 | 7 | 9 | 0 |
| test_payment_gateways_sweep2_coverage.py | 33 | 15 | 11 | 7 | 0 |
| test_payment_gateways_unit.py | 19 | 9 | 3 | 7 | 0 |
| test_payment_history_race_condition.py | 11 | 3 | 0 | 6 | 2 |
| test_payment_history_scalability.py | 9 | 0 | 0 | 1 | 8 |
| test_payment_history_validator.py | 10 | 2 | 1 | 5 | 2 |
| test_payment_hook.py | 19 | 11 | 5 | 0 | 3 |
| test_payment_integration.py | 22 | 13 | 2 | 6 | 1 |
| test_payment_integration_workflows.py | 8 | 0 | 0 | 0 | 8 |
| test_payment_logger_adoption.py | 3 | 3 | 0 | 0 | 0 |
| test_payment_logger_exception_safety.py | 6 | 0 | 0 | 6 | 0 |
| test_payment_plan_system_proper.py | 3 | 2 | 1 | 0 | 0 |
| test_payment_plan_system.py | 0 | 0 | 0 | 0 | 0 |
| test_payment_processing_recovery.py | 30 | 6 | 2 | 19 | 3 |
| test_payment_retry.py | 32 | 9 | 2 | 20 | 1 |
| test_payments_utils_gateways_endpoints_coverage.py | 6 | 1 | 4 | 1 | 0 |
| test_payments_utils_mt940_recon_coverage.py | 11 | 2 | 0 | 7 | 2 |
| test_payment_system_functionality.py | 11 | 7 | 1 | 1 | 2 |
| test_payment_utils_coverage.py | 22 | 18 | 0 | 4 | 0 |
| test_payment_utils.py | 15 | 10 | 0 | 4 | 1 |
| test_ponto_configuration_service.py | 30 | 19 | 3 | 7 | 1 |
| test_ponto_doctype_coverage_extra.py | 29 | 11 | 1 | 17 | 0 |
| test_ponto_doctype_coverage.py | 48 | 21 | 18 | 8 | 1 |
| test_ponto_doctype_unit.py | 17 | 8 | 6 | 3 | 0 |
| test_ponto_models.py | 30 | 20 | 0 | 10 | 0 |
| test_ponto_oauth2_callback.py | 8 | 1 | 4 | 3 | 0 |
| test_ponto_secure_cert_manager.py | 13 | 7 | 2 | 4 | 0 |
| test_ponto_settings_methods_unit.py | 21 | 8 | 7 | 5 | 1 |
| test_ponto_token_manager_unit.py | 17 | 7 | 5 | 4 | 1 |
| test_procurios_mandate_import.py | 24 | 4 | 3 | 14 | 3 |
| test_procurios_mandate_validator.py | 14 | 5 | 3 | 6 | 0 |
| test_r6_parity.py | 14 | 5 | 5 | 4 | 0 |
| test_real_world_dues_amendment_scenarios.py | 9 | 5 | 2 | 1 | 1 |
| test_refund_utility.py | 26 | 8 | 16 | 2 | 0 |
| test_regression_invoice_due_date_calculation.py | 5 | 1 | 0 | 4 | 0 |
| test_regression_payment_history_draft_status.py | 3 | 2 | 0 | 1 | 0 |
| test_regression_payment_history_dynamic_links.py | 9 | 7 | 0 | 2 | 0 |
| test_self_service_fee_adjustment.py | 10 | 5 | 4 | 0 | 1 |
| test_sepa_batch_notifications.py | 14 | 6 | 5 | 3 | 0 |
| test_sepa_batch_ui.py | 31 | 11 | 16 | 4 | 0 |
| test_sepa_batch_ui_secure.py | 34 | 11 | 20 | 2 | 1 |
| test_sepa_config_manager.py | 47 | 26 | 4 | 14 | 3 |
| test_sepa_conflict_detector.py | 46 | 13 | 0 | 33 | 0 |
| test_sepa_error_handler.py | 49 | 14 | 2 | 31 | 2 |
| test_sepa_input_validation.py | 112 | 26 | 33 | 51 | 2 |
| test_sepa_mandate_management.py | 14 | 5 | 4 | 5 | 0 |
| test_sepa_mandate_service.py | 20 | 10 | 0 | 8 | 2 |
| test_sepa_notifications_coverage.py | 23 | 9 | 0 | 14 | 0 |
| test_sepa_parser.py | 64 | 23 | 0 | 41 | 0 |
| test_sepa_race_condition_manager.py | 22 | 7 | 3 | 12 | 0 |
| test_sepa_reconciliation.py | 47 | 16 | 10 | 19 | 2 |
| test_sepa_retry_manager_parity.py | 10 | 3 | 0 | 6 | 1 |
| test_sepa_return_parser.py | 37 | 25 | 3 | 9 | 0 |
| test_sepa_rollback_manager.py | 34 | 17 | 3 | 10 | 4 |
| test_sepa_rulebook_validator.py | 83 | 34 | 18 | 27 | 4 |
| test_sepa_utilities.py | 68 | 25 | 13 | 30 | 0 |
| test_sepa_xml_enhanced_generator.py | 46 | 12 | 24 | 10 | 0 |
| test_settlement_processing.py | 13 | 2 | 4 | 7 | 0 |
| test_settlements_client.py | 14 | 13 | 0 | 1 | 0 |
| test_timezone_utils.py | 36 | 22 | 3 | 11 | 0 |
| test_unified_idempotency_manager.py | 17 | 5 | 2 | 9 | 1 |
| test_unified_webhook_error_scenarios.py | 2 | 0 | 1 | 1 | 0 |
| test_unified_webhook_wrapper_service.py | 24 | 10 | 7 | 7 | 0 |
| test_webhook_error_handler.py | 20 | 8 | 10 | 2 | 0 |
| test_webhook_rate_limiter.py | 15 | 4 | 3 | 7 | 1 |
| test_webhook_security.py | 16 | 3 | 7 | 6 | 0 |
| **DOMAIN TOTALS** | **1936** | **792** | **390** | **677** | **77** |

*Share: Happy 40.9% · Unhappy 20.1% · Edge 35.0% · Other 4.0%*

## Observations

- **Edge-heavy, failure-conscious suite.** Combined Unhappy+Edge = 55% of all
  methods; the payment domain is dominated by validators, parsers and
  webhook/retry machinery, so boundary/empty/null/malformed/duplicate cases
  (Edge) and explicit rejection/throw cases (Unhappy) outweigh nominal Happy
  paths. Strongest concentration of Unhappy is in the input-validation and
  DocType-validation files.

- **Standout rigorous files** (deep, real-assert coverage of both accept and
  every reject/boundary branch): `test_sepa_input_validation.py` (112 methods,
  every validator's accept + reject + adversarial/boundary path),
  `test_sepa_rulebook_validator.py` (83), `test_sepa_utilities.py` (68),
  `test_sepa_parser.py` (64, exhaustive normalization/sentinel edges),
  `test_sepa_conflict_detector.py` (46, all-Edge conflict matrix),
  `test_payment_doctype_coverage.py` (63) and `test_refund_utility.py` (26,
  16 distinct rejection error-codes). These are the load-bearing tests.

- **Dead / skip-heavy / debug files (the Other bucket, 77 methods):**
  - `test_payment_integration_workflows.py` — **all 8 methods `@unittest.skip`
    (STUB_WORKFLOW_PLACEHOLDER)**; pure stubs, zero live coverage.
  - `test_payment_plan_system.py` — **0 class-level methods**; module-level
    `def test_*()` debug script with `print()`/try-except and no assertions
    (see zero-method note).
  - `test_payment_baseline_comparison.py` — single method `@unittest.skip`;
    a perf baseline comparator, not a behavior test.
  - `test_payment_history_scalability.py` — 8/9 methods are scale/perf smoke
    (100–5000 members, skipTest-gated) + 1 `@unittest.skip` concurrency test.
  - `test_payment_gateways_live.py` — whole file is live-Mollie-key gated
    (setUp `skipTest`); intent-classified but normally skipped in CI.

- **Parity / characterization files (meaningful but not domain happy/unhappy):**
  `test_r6_parity.py`, `test_sepa_retry_manager_parity.py`, and the parity
  classes inside `test_sepa_error_handler.py` / `test_sepa_return_parser.py` /
  `test_sepa_rulebook_validator.py` re-implement the pre-refactor behavior
  inline and assert byte/shape equality. Not tautological (they pin real
  output), but they inflate the "characterization" surface rather than testing
  new business rules.

- **Mock usage is largely disciplined and self-justified.** Files that patch
  (`test_payment_logger_exception_safety.py`, `test_payment_gateways_*`,
  `test_unified_webhook_*`, `test_webhook_security.py`) carry inline
  "Mock justified:" comments scoping the patch to the crypto/HTTP/SDK boundary
  only; no wholesale business-logic mocking observed. Exception-safety files
  (logger/notifications "swallows_*") are genuine fault-injection Edge tests,
  not mock-tautologies.

- **Base classes:** the DB-backed files overwhelmingly use Frappe's
  `FrappeTestCase` (or the app's Enhanced/Verenigingen base via factory helpers
  like `create_test_member`); the pure-logic parser/validator/util/model files
  (`test_sepa_parser`, `test_sepa_input_validation`, `test_ponto_models`,
  `test_payment_data_extractor`, `test_timezone_utils`) subclass
  `unittest.TestCase` and need no DB — an appropriate split.

## Notes on zero-method / anomalous files

- `test_payment_plan_system.py` — **0 class-level `def test_*`**. Contains only
  module-level `test_*()` functions (a runnable debug script with prints and
  no asserts). Counted as 0 per the class-level rule; effectively OTHER/dead.
- `test_payment_system_functionality.py` — table Total is **11** class-level
  methods; a raw `grep` shows 13 because `test_api_security_decorators_basic_functionality`
  defines two nested helper functions (`test_utility_function`,
  `test_standard_function`) that are ignored per the nested-helper rule.
- No other missing or empty test files in the 86–170 slice; all 85 present.
