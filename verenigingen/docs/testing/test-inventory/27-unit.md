# Test Inventory 27 — tests/unit (excluding services/)

> **COMPLETE** — READ-ONLY classification of every class-level `def test_*` method. 23/23 files audited.
> Domain: `verenigingen/tests/unit` excluding `*/services/*` (audited separately).
> Categories: HAPPY (nominal success) · UNHAPPY (expects error/throw/denial/rejection) · EDGE (boundary/empty/null/dup/idempotency/malformed/ordering/date-fallback) · OTHER (smoke/import-only/setup/tautology/config-const/perf-smoke/no-assert/skip-dominated).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_account_classification_service.py | 58 | 41 | 5 | 12 | 0 |
| test_base_history_manager.py | 14 | 3 | 5 | 2 | 4 |
| test_chapter_cost_center_resolution.py | 11 | 3 | 0 | 8 | 0 |
| test_donation_history_manager_regression.py | 17 | 2 | 0 | 0 | 15 |
| test_eboekhouden_mock_elimination.py | 7 | 2 | 0 | 3 | 2 |
| test_invoice_generation_orchestrator.py | 9 | 2 | 1 | 6 | 0 |
| test_invoice_helpers_account_lookup.py | 4 | 1 | 1 | 2 | 0 |
| test_member_lifecycle_mock_elimination_fixed.py | 5 | 4 | 0 | 0 | 1 |
| test_member_lifecycle_mock_elimination.py | 8 | 2 | 0 | 3 | 3 |
| test_member_lifecycle_production_issues_discovered.py | 7 | 0 | 0 | 0 | 7 |
| test_member_lifecycle_unit.py | 15 | 1 | 0 | 2 | 12 |
| test_member_payment_matcher.py | 15 | 7 | 0 | 8 | 0 |
| test_mollie_bulk_transaction_core_functionality.py | 17 | 6 | 1 | 8 | 2 |
| test_mollie_donation_webhook_regression.py | 19 | 3 | 1 | 3 | 12 |
| test_mollie_iban_validation_and_extraction.py | 14 | 5 | 1 | 4 | 4 |
| test_mollie_payment_service_wrapper.py | 16 | 7 | 7 | 2 | 0 |
| test_payment_direction.py | 12 | 0 | 0 | 0 | 12 |
| test_payment_processor.py | 30 | 14 | 9 | 7 | 0 |
| test_security_wrappers_unit.py | 14 | 7 | 2 | 3 | 2 |
| test_sepa_business_logic_unit.py | 13 | 0 | 0 | 1 | 12 |
| test_volunteer_statistics.py | 7 | 1 | 0 | 6 | 0 |
| utils/test_billing_period_calculator.py | 34 | 25 | 0 | 9 | 0 |
| utils/test_security_utilities.py | 84 | 29 | 21 | 17 | 17 |
| **DOMAIN TOTALS** | **430** | **165** | **54** | **106** | **105** |

Distribution: HAPPY 38.4% · UNHAPPY 12.6% · EDGE 24.7% · OTHER 24.4%.

## Observations

- **~24% of methods are OTHER, and a large slice of those are tautological** — they define the "business logic" (or copy the production formula) *inline in the test body* and assert against it, exercising no production code. Whole files are affected: `test_payment_direction.py` (12/12 re-implement the `is_incoming` expression inline), `test_member_lifecycle_unit.py` (12/15 test inline `def normalize_postal_code`/`is_valid_email`/`calculate_membership_fee`/… helpers), and `test_sepa_business_logic_unit.py` (12/13 inline `validate_payment_amount`/`determine_sequence_type`/… — only the one IBAN test calls a real validator). These pass green but would never catch a regression in the real code.
- **Two "mock-elimination"/"production-issues" files carry little to no assertion value.** `test_member_lifecycle_production_issues_discovered.py` is 7/7 pure `print()` documentation (no asserts at all), and the `*_mock_elimination.py` pair leans on try/except-swallow-then-print for the "invalid" branches, so failure paths are never actually asserted (counted HAPPY/EDGE only where a real assertion survives). Effectively regression-inert.
- **The strongest files are the newer, narrowly-scoped ones** that call real functions: `utils/test_security_utilities.py` (84 tests, real masking/redaction/authz + genuine `assertRaises` denial coverage), `utils/test_billing_period_calculator.py` (34 tests, real date math with clear boundary cases), `test_payment_processor.py` (30, real branch/guard/error coverage), and `test_mollie_payment_service_wrapper.py` (balanced 7 HAPPY / 7 UNHAPPY). These account for most of the domain's real UNHAPPY coverage.
- **UNHAPPY is heavily concentrated** — of 54 unhappy methods, ~30 live in just three files (`utils/test_security_utilities.py` 21, `test_payment_processor.py` 9, `test_mollie_payment_service_wrapper.py` 7). Twelve of the 23 files have zero UNHAPPY methods, several of those being pure happy/tautological suites.
- **EDGE coverage is genuinely strong (~25%)** and mostly high-quality: IBAN spacing/case/length boundaries, null/empty/nonexistent lookups, fallback-to-default date logic, idempotency/duplicate detection, and reversal/sign edge cases (Mollie + payment processor). This is the domain's most valuable real coverage after the security suite.
- **Regression/structural suites over-index on introspection.** `test_donation_history_manager_regression.py` (15/17 OTHER) and `test_mollie_donation_webhook_regression.py` (12/19 OTHER) verify behavior via `inspect.getsource(...)` string-greps, `issubclass`, `hasattr`, schema `meta.get_field`, and signature checks rather than executing the fixed code path — brittle to refactors and blind to logic errors that keep the same source text.

## Notes on zero-method / missing / removed

- No zero-method files: all 23 files contain at least 4 class-level test methods.
- No missing files: the `find` list (23) was audited in full; `find` returns 23 (not "~23").
- `*/services/*` subdirectory intentionally excluded per scope (audited separately).
- `test_member_lifecycle_unit.py` and `test_volunteer_statistics.py` contain commented-out/removed tests (e.g. `test_status_mapping_comprehensive`, `test_map_erpnext_status_to_volunteer_status`) tied to archived DocTypes — these are not counted (no live `def test_`).
