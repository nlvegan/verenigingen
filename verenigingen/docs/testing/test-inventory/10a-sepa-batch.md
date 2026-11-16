# Domain A10a — SEPA batch / validation / reconciliation core

Read-only test-method inventory across the 11 assigned files under
`verenigingen/tests/sepa/`. Every `def test_*` method classified by dominant
intent: HAPPY (nominal success), UNHAPPY (expects error/throw/validation
failure), EDGE (boundary/empty/duplicate/idempotency/malformed/R-transaction
return/missing-record), OTHER (smoke/shape/identity/tautology/script).

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|---|---|---|---|---|---|
| test_batch_processing_service_happy_path.py | 2 | 2 | 0 | 0 | 0 |
| test_batch_validation_service_coverage.py | 26 | 6 | 6 | 11 | 3 |
| test_dd_batch_pipeline_coverage.py | 31 | 13 | 5 | 9 | 4 |
| test_dd_batch_scheduler.py | 23 | 12 | 2 | 6 | 3 |
| test_enhanced_sepa_integration.py | 1* | 0 | 0 | 0 | 1 |
| test_iban_validator.py (removed in #1939) | 0 | 0 | 0 | 0 | 0 |
| test_sepa_bank_reconciliation_coverage.py | 20 | 9 | 0 | 11 | 0 |
| test_sepa_batch_processor_logic.py | 27 | 17 | 0 | 8 | 2 |
| test_sepa_batch_processor_returns_coverage.py | 9 | 3 | 1 | 5 | 0 |
| test_sepa_input_validation.py | 25 | 11 | 7 | 6 | 1 |
| test_sepa_invoice_validation.py | 22 | 17 | 0 | 5 | 0 |
| **DOMAIN TOTALS** | **186** | **90** | **21** | **61** | **14** |

\* `test_enhanced_sepa_integration.py` defines NO `unittest.TestCase` and NO
test *methods* — it is a legacy print-driven script of module-level `test_*`
helper functions plus a `main()`. Counted as 1 OTHER (the top-level driver
`test_enhanced_sepa_integration`); the ~15 other `test_*` module functions are
its called helpers, not independently collectible test methods.

## Observations

- **Edge-heavy domain (61/186 = 33%).** SEPA batch/reconciliation logic is
  dominated by boundary work: idempotency (create/link by reference),
  R-transaction returns (pain.002 RJCT), missing/nonexistent invoice & mandate
  lookups, empty batches, collection-date notice windows (too-early/far-future/
  weekend), and duplicate detection. The reconciliation-coverage file is 11/20
  edge with zero unhappy — it targets branch coverage of hit/miss/cancelled/
  fall-through paths rather than throws.
- **Two files carry effectively no live coverage.** `test_iban_validator.py` (removed in #1939) was
  a pure `import *` bridge to `tests/backend/validation/test_iban_validator.py`
  (outside this domain) — 0 local methods. `test_enhanced_sepa_integration.py`
  is a non-unittest print script that swallows every failure in broad
  `try/except: return` blocks and asserts nothing — it inflates the appearance
  of coverage without gating regressions.
- **UNHAPPY concentrates in the two input-validation files.** `test_sepa_input_
  validation.py` (7) and `test_batch_validation_service_coverage.py` (6) hold
  most of the genuine rejection tests; the processor/pipeline/reconciliation
  files lean on guard-throw EDGE cases (`assertRaises` on empty batch / missing
  SEPA file / submit-state guards) which were classified by their boundary
  trigger rather than as pure UNHAPPY.
- **`test_sepa_invoice_validation.py` is HAPPY-skewed and partly tautological.**
  Several methods assert values the factory just set (e.g. mandate.status,
  invoice.currency, grand_total after a manual rate set) rather than exercising
  batch validation logic; `test_sepa_invoice_creditor_identifier_compliance`
  guards on `hasattr` (no-op if absent) and `test_sepa_invoice_collection_date_
  compliance` computes a weekday but ends without a final assertion.
- `test_bank_integration_boundaries.py` was deleted (#2531): it never ran in CI, 9 of its 12
  methods failed when enabled, and the IBAN/corrupted-file checks moved into
  `tests/payment/test_sepa_utilities.py` and `tests/payment/test_bank_integration.py`.
- **Strong real-DB discipline in the coverage files.** The `_dd_batch_pipeline`,
  `_returns_coverage`, `_bank_reconciliation_coverage`, and
  `batch_processing_service_happy_path` files use committed-doc tracking +
  force-delete tearDowns and `expectErrorLog("Fiscal Year Auto-Creation Error")`
  acknowledgement — mock-free, shard-safe integration style.
- **OTHER (14) is mostly singleton/shape/construction smoke**, e.g.
  `test_singleton_is_the_service_instance`, `test_processor_constructs_with_
  dependencies`, `test_..._returns_valid_shape`, `test_to_dict_round_trips_
  state` — low regression value but cheap coverage of accessors/serialization.

## Missing files

None. All 11 assigned files were present and read.
