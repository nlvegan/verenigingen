# Domain A6 — Billing services + customer/invoice: Test Inventory

Read-only classification of every `def test_*` method across the 21 co-located
billing suites (`verenigingen/services/billing/test_*.py`) plus 5 targeted
`verenigingen/tests/services/` suites. Each method assigned ONE primary type by
dominant intent (HAPPY / UNHAPPY / EDGE / OTHER).

**Scope: 26 files, 527 test methods.**

Classification notes:
- Cutoff/period/coverage calculators: exact-value nominal calc = HAPPY; leap-year,
  month-end/year rollover, invalid-day/unknown-frequency fallbacks = EDGE.
- Eligibility "blocked" results (can_generate=False with a rejection reason) counted
  UNHAPPY; the suspended-still-billable exception and nonexistent-member/orphan cases
  counted EDGE.
- Dry-run / idempotency / no-mutation / guard-skip / fallback branches counted EDGE.
- Dataclass default/custom-value smoke, singleton/factory smoke, key-only "shape"
  asserts, deprecated no-ops, `@unittest.skip`/`skipTest` bodies, and `assertTrue(True)`
  / `pass` placeholders counted OTHER.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| services/billing/test_billing_date_service.py | 18 | 8 | 0 | 9 | 1 |
| services/billing/test_billing_period_calculator.py | 48 | 27 | 3 | 18 | 0 |
| services/billing/test_bulk_invoice_generation_service.py | 43 | 16 | 9 | 15 | 3 |
| services/billing/test_coverage_calculator.py | 32 | 23 | 0 | 8 | 1 |
| services/billing/test_coverage_overlap_detector.py | 17 | 9 | 0 | 8 | 0 |
| services/billing/test_dues_schedule_auto_creator.py | 35 | 18 | 3 | 7 | 7 |
| services/billing/test_dues_schedule_creation_service.py | 17 | 8 | 6 | 3 | 0 |
| services/billing/test_dues_schedule_health_manager.py | 18 | 11 | 3 | 4 | 0 |
| services/billing/test_dues_schedule_lifecycle_service.py | 12 | 4 | 4 | 3 | 1 |
| services/billing/test_dues_schedule_permission_service.py | 30 | 18 | 7 | 4 | 1 |
| services/billing/test_dues_schedule_validation_service.py | 31 | 5 | 11 | 14 | 1 |
| services/billing/test_eligibility_checker.py | 17 | 6 | 8 | 3 | 0 |
| services/billing/test_fee_change_tracking_service.py | 5 | 4 | 0 | 0 | 1 |
| services/billing/test_invoice_error_handler_service.py | 18 | 12 | 0 | 5 | 1 |
| services/billing/test_invoice_generation_orchestrator.py | 4 | 2 | 1 | 1 | 0 |
| services/billing/test_invoice_matcher.py | 15 | 6 | 1 | 8 | 0 |
| services/billing/test_invoice_management.py | 28 | 8 | 0 | 17 | 3 |
| services/billing/test_progressive_dues_service.py | 21 | 7 | 3 | 11 | 0 |
| services/billing/test_sales_invoice_account_handler.py | 10 | 4 | 0 | 6 | 0 |
| services/billing/test_sales_invoice_hooks.py | 5 | 3 | 0 | 2 | 0 |
| services/billing/test_template_services.py | 21 | 7 | 7 | 6 | 1 |
| tests/services/test_bulk_invoice_generation_service.py | 34 | 12 | 1 | 8 | 13 |
| tests/services/test_customer_group_resolver.py | 4 | 1 | 1 | 2 | 0 |
| tests/services/test_customer_handling_service_coverage.py | 14 | 3 | 3 | 8 | 0 |
| tests/services/test_customer_handling_service_integration.py | 15 | 7 | 2 | 4 | 2 |
| tests/services/test_payment_entry_creation_service.py | 15 | 3 | 4 | 1 | 7 |
| **DOMAIN TOTALS** | **527** | **232** | **77** | **175** | **43** |

Distribution: Happy 44.0% · Unhappy 14.6% · Edge 33.2% · Other 8.2%.

## Observations

- **Edge-heavy, as expected for billing.** A third of all methods (175) are EDGE —
  the date/coverage math suites are dominated by leap-year, month-end, year-rollover,
  and unknown-frequency/invalid-config fallback assertions. `test_billing_period_calculator.py`
  alone contributes 48 methods (18 edge) of pure exact-date boundary checking.
- **The co-located billing suites are strong, real-integration tests.** They create
  real Member/Membership/Dues-Schedule/Sales-Invoice docs, drive through actual hooks,
  and force-clean committed fixtures in tearDown. Several are genuine red-green
  regression guards (documented product bugs): the "Banned"/duplicate-"Quit" eligibility
  filter fix, the invoice-NAME-vs-doc-object payment-history silent-drop, and the
  `get_parallel_status` list-vs-dict AttributeError — all in
  `services/billing/test_bulk_invoice_generation_service.py`.
- **The `tests/services/` duplicate of `test_bulk_invoice_generation_service.py` is the
  weakest suite audited** — 13 of 34 (38%) are OTHER: dataclass default/custom-value
  smoke, mock-based lock tests, key-only shape asserts, and two outright tautologies
  (`test_sequential_processing_for_small_batch` is just `pass`;
  `test_parallel_processing_threshold` is `assertTrue(True)`). Its cutoff-calc coverage
  is entirely superseded by the richer co-located suite.
- **`test_payment_entry_creation_service.py` is half-dead:** 7 of 15 methods are
  `@unittest.skip` / integration stubs, and the file docstring itself lists most tests
  as failing on ERPNext account setup. Only ~3 happy + 4 unhappy methods actually run
  meaningful assertions. It also uses `unittest.mock` (patch/MagicMock) — the only
  MagicMock-heavy suite in the domain besides the duplicate bulk-gen file.
- **Unhappy concentration reflects validation-service design.**
  `test_dues_schedule_validation_service.py` (11 unhappy), `test_eligibility_checker.py`
  (8), `test_dues_schedule_permission_service.py` (7), and `test_template_services.py`
  (7) carry most of the 77 rejection/throw tests — these are the guard-rail services
  (rate boundaries, permission denials, status transitions, template rejections).
- **Permission and lifecycle services test denials thoroughly.**
  `test_dues_schedule_permission_service.py` and `test_dues_schedule_lifecycle_service.py`
  pair each allow-path with an explicit denial/invalid-transition throw, giving balanced
  HAPPY/UNHAPPY coverage rather than happy-only.
- **A few classification-sensitive calls:** cutoff calculators that bundle leap +
  rollover assertions were treated EDGE; predicate-style `should_advance`/`is_deadlock`
  classifiers returning False for non-matching input were treated HAPPY (nominal
  classification output, not rejection); `_calculate_*_cutoff` for fiscal-year configs
  were HAPPY (valid config variation).

## Co-located billing test files found (21)

Under `verenigingen/services/billing/`:
1. test_billing_date_service.py
2. test_billing_period_calculator.py
3. test_bulk_invoice_generation_service.py
4. test_coverage_calculator.py
5. test_coverage_overlap_detector.py
6. test_dues_schedule_auto_creator.py
7. test_dues_schedule_creation_service.py
8. test_dues_schedule_health_manager.py
9. test_dues_schedule_lifecycle_service.py
10. test_dues_schedule_permission_service.py
11. test_dues_schedule_validation_service.py
12. test_eligibility_checker.py
13. test_fee_change_tracking_service.py
14. test_invoice_error_handler_service.py
15. test_invoice_generation_orchestrator.py
16. test_invoice_matcher.py
17. test_invoice_management.py
18. test_progressive_dues_service.py
19. test_sales_invoice_account_handler.py
20. test_sales_invoice_hooks.py
21. test_template_services.py
