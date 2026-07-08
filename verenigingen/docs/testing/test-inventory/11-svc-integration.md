# DOMAIN A11 — Service Integration + Remaining Service Tests

Read-only test-method inventory. Every `def test_*` in the 20 assigned files classified by dominant intent:
HAPPY (nominal success) · UNHAPPY (expects error/throw/rejection/block) · EDGE (boundary/null/empty/duplicate/concurrency/idempotency/malformed/ordering) · OTHER (smoke/dataclass/factory/tautological).

All 20 assigned files were present. 368 test methods total.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| integration/services/test_chapter_cost_center_auto_creation.py | 13 | 7 | 0 | 4 | 2 |
| integration/services/test_chapter_cost_center_integration.py | 11 | 5 | 0 | 6 | 0 |
| integration/services/test_coverage_calculator_module.py | 24 | 12 | 0 | 11 | 1 |
| integration/services/test_coverage_calculator.py | 22 | 13 | 0 | 9 | 0 |
| integration/services/test_cutoff_date_calculations.py | 16 | 11 | 1 | 4 | 0 |
| integration/services/test_duplicate_invoice_detector.py | 14 | 1 | 3 | 7 | 3 |
| integration/services/test_eligibility_checker.py | 21 | 3 | 13 | 2 | 3 |
| integration/services/test_invoice_generator_branches.py | 31 | 4 | 16 | 11 | 0 |
| integration/services/test_invoice_generator.py | 14 | 6 | 5 | 3 | 0 |
| unit/services/test_chapter_finance_service.py | 21 | 7 | 5 | 9 | 0 |
| unit/services/test_customer_handling_service.py | 5 | 4 | 1 | 0 | 0 |
| unit/services/test_member_membership_service.py | 4 | 2 | 1 | 1 | 0 |
| services/payment/test_pain002_ingestion.py | 24 | 13 | 0 | 9 | 2 |
| services/payment/test_sepa_upload_guard.py | 37 | 12 | 10 | 11 | 4 |
| services/payment/test_reconciliation_alerts.py | 13 | 5 | 0 | 5 | 3 |
| services/payment/test_sepa_upload_integration.py | 5 | 3 | 1 | 1 | 0 |
| services/payment/test_mollie_webhook_service.py | 13 | 6 | 6 | 0 | 1 |
| services/test_mollie_sync_service.py | 6 | 3 | 0 | 3 | 0 |
| services/test_mollie_sync_service_integration.py | 15 | 5 | 6 | 4 | 0 |
| services/test_polling_service.py | 59 | 29 | 2 | 28 | 0 |
| **DOMAIN TOTALS** | **368** | **151** | **70** | **128** | **19** |

## Observations

- **Strong balance overall (41% happy / 19% unhappy / 35% edge / 5% other).** The billing/coverage suites lean edge-heavy because they systematically walk frequency/cutoff/fallback branches; the guard/validator suites (eligibility_checker, invoice_generator_branches, sepa_upload_guard) carry nearly all the unhappy weight, which is appropriate for rejection-focused services.

- **`test_eligibility_checker.py` and `test_invoice_generator_branches.py` are the unhappy-path workhorses** (13 and 16 UNHAPPY). They exhaustively assert rejections: blocked member statuses, rate limits, SEPA-mandate validation failures (mismatch/expired/no-IBAN/malformed/future sign-date), and coverage-date/account-config errors. Well-targeted negative coverage.

- **`test_polling_service.py` is by far the largest (59 methods)** and is edge-dominant (28): pure-function tag/summary/diff logic tested across null-vs-empty, int-vs-str, dedup, tag priority ORDERING, truncation, and unknown-table fallbacks. Only 2 unhappy (fetch-exception→0, row-savepoint catch) — its failure model is graceful degradation, not throwing, so low UNHAPPY is expected.

- **Classification friction: "blocked/prevented" outcomes.** Many billing tests return a structured result object (`can_generate=False`, `success=False`) rather than raising. I scored rule-driven rejections (duplicate prevented, too-early, member-status blocked, sandbox block) as UNHAPPY, but reserved EDGE for tests whose focus is the boundary/absence of data (no-member, zero-invoices, gap-reset, exactly-at-cutoff). This is the main judgment call affecting the U/E split.

- **`OTHER` (19) is almost entirely legitimate infrastructure tests**: dataclass `to_dict`/`repr`/default-value checks (duplicate_invoice_detector, eligibility_checker, reconciliation_alerts, sepa_upload_guard), factory `get_*_service()` instance smoke tests, and two "does-not-query-nonexistent-field" regression guards in chapter_cost_center_auto_creation. No tautological business-logic tests spotted.

- **Mock discipline varies by tier as expected.** The three `unit/services/` files (chapter_finance, customer_handling, member_membership) are pure `unittest.mock`-based branch tests; everything under `integration/services/` and `services/payment/` uses real DB via EnhancedTestCase/FrappeTestCase with only the true external boundary faked (Mollie SDK seam in mollie_webhook/sync, stubbed MijnRood DB client in polling). Consistent with project conventions.

- **Several tests are internally mixed** (e.g. sepa_upload_integration `guard_check_before_register` exercises allow→register→block in one method; webhook `counts_success_and_error` asserts both success and error tallies). Scored by dominant intent; the totals slightly understate incidental unhappy/edge assertions embedded in happy-path tests.

## Missing files
None — all 20 assigned files exist and were audited.
