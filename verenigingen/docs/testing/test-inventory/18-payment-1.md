# Test Inventory — Domain PAY1 (tests/payment, part 1)

> **COMPLETE** — Read-only classification of the first 85 `test_*.py` files under
> `verenigingen/tests/payment` (sorted). Each class-level `def test_*` classified as
> HAPPY (nominal success), UNHAPPY (expects error/throw/validation-fail/permission-denial/
> reject), EDGE (boundary/empty/null/duplicate/idempotency/concurrency/malformed/retry/
> proration/rounding), or OTHER (smoke/import/setup-only/tautological/mock-tautology/skip).
> Classification is primarily name-based with spot body-reads for ambiguous cases.
> Rows appended as each file is completed.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_advanced_prorating.py | 4 | 0 | 0 | 4 | 0 |
| test_amendment_fee_change_fix.py | 4 | 2 | 0 | 2 | 0 |
| test_audit_trail_integrity.py | 4 | 1 | 1 | 2 | 0 |
| test_balances_client.py | 12 | 6 | 1 | 5 | 0 |
| test_balance_transaction_processing.py | 32 | 5 | 18 | 9 | 0 |
| test_balance_transaction_processor_coverage.py | 18 | 6 | 2 | 10 | 0 |
| test_bank_integration.py | 34 | 12 | 9 | 11 | 2 |
| test_bank_reconciliation_matching.py | 27 | 9 | 1 | 15 | 2 |
| test_bank_transaction_reconciliation.py | 70 | 21 | 5 | 41 | 3 |
| test_billing_constants.py | 10 | 3 | 0 | 1 | 6 |
| test_billing_service_coverage.py | 102 | 33 | 15 | 48 | 6 |
| test_billing_transitions_proper.py | 7 | 5 | 0 | 0 | 2 |
| test_billing_transitions.py | 7 | 2 | 0 | 5 | 0 |
| test_bulk_payment_checker.py | 33 | 8 | 5 | 20 | 0 |
| test_bulk_transaction_importer_branches.py | 26 | 4 | 6 | 16 | 0 |
| test_bulk_transaction_importer.py | 18 | 4 | 0 | 11 | 3 |
| test_bulk_transaction_importer_sweep.py | 25 | 16 | 0 | 9 | 0 |
| test_chapter_dues_domain_model.py | 32 | 9 | 2 | 21 | 0 |
| test_chargebacks_client.py | 12 | 11 | 0 | 1 | 0 |
| test_comprehensive_prorating.py | 6 | 0 | 0 | 6 | 0 |
| test_contribution_amendment_integration.py | 7 | 5 | 0 | 0 | 2 |
| test_contribution_system.py | 2 | 2 | 0 | 0 | 0 |
| test_custom_billing_frequency.py | 6 | 5 | 1 | 0 | 0 |
| test_dd_batch_api_integration.py | 5 | 3 | 0 | 0 | 2 |
| test_dd_batch_scheduler_orchestration.py | 14 | 4 | 0 | 10 | 0 |
| test_dd_batch_workflow_controller.py | 28 | 9 | 6 | 13 | 0 |
| test_dues_schedule_date_validation.py | 6 | 5 | 1 | 0 | 0 |
| test_dues_schedule_health_manager_branches.py | 13 | 8 | 2 | 3 | 0 |
| test_dues_schedule_health_manager.py | 14 | 9 | 1 | 3 | 1 |
| test_dues_schedule_sync.py | 5 | 4 | 0 | 1 | 0 |
| test_dues_schedule_system.py | 2 | 0 | 0 | 0 | 2 |
| test_dues_validation.py | 26 | 15 | 0 | 11 | 0 |
| test_enhanced_contribution_amendment_system.py | 11 | 7 | 0 | 3 | 1 |
| test_event_driven_payment_history.py | 7 | 5 | 0 | 2 | 0 |
| test_fee_override_migration.py | 8 | 5 | 2 | 1 | 0 |
| test_financial_calculation_utils.py | 51 | 12 | 2 | 37 | 0 |
| test_financial_error_handler.py | 34 | 14 | 8 | 10 | 2 |
| test_ing_doctype_coverage.py | 39 | 18 | 10 | 9 | 2 |
| test_invoice_edge_cases.py | 24 | 1 | 0 | 22 | 1 |
| test_invoice_eligibility_validation.py | 6 | 3 | 2 | 1 | 0 |
| test_invoice_generation_and_payment_history_sync.py | 8 | 6 | 1 | 1 | 0 |
| test_invoices_client.py | 11 | 8 | 0 | 3 | 0 |
| test_invoice_validation_safeguards.py | 10 | 3 | 2 | 3 | 2 |
| test_mollie_amendment_events.py | 11 | 5 | 2 | 4 | 0 |
| test_mollie_amendment_subscription_sync.py | 18 | 10 | 2 | 6 | 0 |
| test_mollie_api_data_factory.py | 0 | 0 | 0 | 0 | 0 |
| test_mollie_bulk_run_api.py | 15 | 6 | 6 | 3 | 0 |
| test_mollie_bulk_run_fetch.py | 7 | 1 | 0 | 6 | 0 |
| test_mollie_bulk_run.py | 15 | 2 | 1 | 12 | 0 |
| test_mollie_configuration_migration.py | 7 | 6 | 0 | 1 | 0 |
| test_mollie_core_client.py | 39 | 20 | 12 | 4 | 3 |
| test_mollie_cost_center_coverage_b2.py | 6 | 2 | 0 | 4 | 0 |
| test_mollie_data_validator.py | 15 | 3 | 6 | 5 | 1 |
| test_mollie_debug_service_admin.py | 69 | 14 | 48 | 7 | 0 |
| test_mollie_debug_service_bulk.py | 31 | 11 | 3 | 17 | 0 |
| test_mollie_debug_service_read.py | 65 | 23 | 20 | 22 | 0 |
| test_mollie_deprecated_payment_entry_factory.py | 4 | 1 | 0 | 0 | 3 |
| test_mollie_dues_payment_processor.py | 15 | 3 | 2 | 10 | 0 |
| test_mollie_dues_processor_coverage_b3.py | 11 | 2 | 5 | 4 | 0 |
| test_mollie_edge_cases_integration.py | 14 | 1 | 1 | 10 | 2 |
| test_mollie_financial_validator_coverage_b1.py | 45 | 10 | 28 | 7 | 0 |
| test_mollie_gap_donation_financial_chain.py | 3 | 2 | 0 | 1 | 0 |
| test_mollie_gap_unified_webhook_handlers.py | 14 | 4 | 4 | 6 | 0 |
| test_mollie_logging.py | 40 | 14 | 4 | 22 | 0 |
| test_mollie_orchestrator_coverage_b2.py | 21 | 7 | 0 | 14 | 0 |
| test_mollie_payment_classification.py | 28 | 10 | 0 | 18 | 0 |
| test_mollie_payment_entry_factory_coverage_b1.py | 9 | 2 | 0 | 7 | 0 |
| test_mollie_payment_service.py | 18 | 9 | 4 | 5 | 0 |
| test_mollie_payment_webhook_helpers.py | 30 | 17 | 2 | 11 | 0 |
| test_mollie_performance_benchmarks.py | 5 | 0 | 0 | 1 | 4 |
| test_mollie_rate_limiter_coverage_b1.py | 29 | 8 | 0 | 20 | 1 |
| test_mollie_refund_handler.py | 14 | 3 | 2 | 9 | 0 |
| test_mollie_retry_policy_coverage_b3.py | 30 | 4 | 6 | 20 | 0 |
| test_mollie_security_manager_coverage_b1.py | 18 | 5 | 5 | 8 | 0 |
| test_mollie_security_utils.py | 52 | 18 | 8 | 26 | 0 |
| test_mollie_shared_payment_entry_factory.py | 25 | 8 | 0 | 17 | 0 |
| test_mollie_subscription_consolidation.py | 48 | 16 | 10 | 22 | 0 |
| test_mollie_subscription_service_coverage.py | 35 | 10 | 11 | 14 | 0 |
| test_mollie_sync_api.py | 26 | 7 | 5 | 14 | 0 |
| test_mollie_unified_payment_api.py | 23 | 6 | 16 | 1 | 0 |
| test_mollie_utils_payment_checker.py | 7 | 3 | 2 | 2 | 0 |
| test_mollie_validators.py | 93 | 27 | 0 | 66 | 0 |
| test_mollie_webhook_auth_helpers.py | 9 | 4 | 4 | 1 | 0 |
| test_mollie_webhook_parser.py | 21 | 10 | 0 | 10 | 1 |
| test_mollie_webhook_signature_optional.py | 4 | 1 | 1 | 2 | 0 |
| **DOMAIN TOTALS** | **1809** | **623** | **323** | **809** | **54** |

## Observations

- **Coverage skew toward EDGE (809, ~45%) and HAPPY (623, ~34%), with UNHAPPY at 323 (~18%) and OTHER only 54 (~3%).**
  This is a healthy, defensively-tested domain: the volume of EDGE cases (boundary amounts, empty/null,
  idempotency/duplicate-skip, malformed IBAN/date/JSON, retry/backoff, proration/rounding) reflects genuine
  attention to payment-processing failure modes rather than happy-path-only coverage.
- **Strongest files** are the Mollie coverage sweeps and validator suites: `test_mollie_validators.py` (93 methods,
  IBAN/amount/currency/email/postal/eligibility with an explicit shared-implementation *parity* block),
  `test_billing_service_coverage.py` (102), `test_mollie_debug_service_admin.py` (69, almost entirely
  input-validation/require/reject UNHAPPY paths), `test_mollie_debug_service_read.py` (65), and
  `test_financial_calculation_utils.py` (51, dense proration/coverage-gap/decimal-precision EDGE work). These read
  as real behavioral assertions, not coverage-padding.
- **Heaviest UNHAPPY concentration:** `test_mollie_debug_service_admin.py` (48 U — parameter validation for
  mandate/subscription/webhook/payment admin ops), `test_mollie_financial_validator_coverage_b1.py` (28 U),
  `test_mollie_unified_payment_api.py` (16 U, `@whitelist` endpoints mapping validation to `frappe.throw`), and
  `test_mollie_subscription_consolidation.py` (10 U). Webhook-signature/permission rejection is well covered
  (`test_mollie_security_utils.py`, `test_mollie_security_manager_coverage_b1.py`, `test_mollie_webhook_auth_helpers.py`).
- **OTHER / potential dead-or-thin files:** `test_dues_schedule_system.py` (2 module-level funcs, **0 asserts**,
  print-based debug script meant for `bench execute` — pure OTHER); `test_mollie_api_data_factory.py` (**0 test
  methods** — it is a data-factory helper module, not a test); `test_mollie_deprecated_payment_entry_factory.py`
  (3/4 are deprecation-shim smoke: subclass/inheritance/delegation-warn); `test_mollie_performance_benchmarks.py`
  (4/5 are timing/throughput/memory benchmarks) and `test_billing_constants.py` (6/10 are enum/`__all__`/regex-perf
  constant smoke). These are the main candidates for "assertion-light" review.
- **Mock-tautology flags (low):** `test_billing_transitions_proper.py` has `test_mock_bank_iban_integration` and
  `test_no_duplicate_billing_conceptual_validation` (named "conceptual" — likely asserts a constructed expectation
  rather than real dedup) — flagged OTHER. The many Mollie `*_uses_config_service` /`*_delegates`/`*_wraps_sdk_*`
  tests are delegation/characterization tests; classified HAPPY since they assert real call-through, but a reviewer
  should confirm they aren't just asserting a mock was called.
- **Base classes vary by file vintage:** older behavioral files use `VereningingenTestCase`/`EnhancedTestCase`
  factory bases (e.g. billing-transitions, invoice, dues-schedule, event-driven history), while the newer
  `*_coverage_b1/b2/b3` and client/validator sweeps are lighter `unittest.TestCase`/pytest-style pure-unit tests
  with stubbed SDK clients — appropriate for the utility surface they cover.

## Notes on zero-method / anomalous files

- `test_mollie_api_data_factory.py` — **0 class-level test methods** (data-factory helper module providing Mollie
  API fixtures for other tests; counted as Total 0).
- `test_dues_schedule_system.py` — 2 **module-level** functions (`test_complete_workflow`, `test_template_operations`),
  both print-based `bench execute` debug scripts with **no assertions**; classified OTHER.
- `test_mollie_payment_service.py` — `grep` counts 19 `def test_`, but line 170 `def test_mode` is a **nested helper**
  inside another test (12-space indent); real class-level count is **18** (used in the table).
- No `@unittest.skip`-dominated files were observed in this domain.
