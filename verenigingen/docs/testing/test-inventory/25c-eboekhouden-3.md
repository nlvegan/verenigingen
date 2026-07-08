# Test Inventory 25c — eBoekhouden (part 3)

**Status: COMPLETE** — 29/29 files classified. Domain EBKH3 = files 59-87 of
`find verenigingen/tests/e_boekhouden -name "test_*.py" | sort` (29 files).

Classification: HAPPY (nominal success), UNHAPPY (expects error/throw/rejection),
EDGE (boundary/empty/duplicate/idempotency/malformed/ordering/Dr-Cr/rounding/mapping-fallback),
OTHER (smoke/import-safety/setup-only/tautology/mock-into-tautology/live-API-gated/skip-dominated).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_payment_entry_handler.py | 49 | 18 | 3 | 27 | 1 |
| test_payment_mapping_coverage.py | 13 | 9 | 0 | 4 | 0 |
| test_payment_processor_coverage.py | 31 | 8 | 0 | 23 | 0 |
| test_payment_processor_party_resolution.py | 20 | 6 | 2 | 12 | 0 |
| test_payment_processor_sweep.py | 16 | 6 | 1 | 9 | 0 |
| test_processors_base.py | 38 | 18 | 4 | 14 | 2 |
| test_processors_stock.py | 19 | 8 | 0 | 11 | 0 |
| test_progress_utils.py | 53 | 38 | 2 | 12 | 1 |
| test_rest_client_coverage.py | 13 | 5 | 4 | 4 | 0 |
| test_rest_full_migration_dispatch_coverage.py | 8 | 3 | 0 | 5 | 0 |
| test_rest_full_migration_helpers_coverage.py | 22 | 4 | 1 | 16 | 1 |
| test_rest_full_migration_sweep.py | 6 | 1 | 0 | 3 | 2 |
| test_rest_invoice_creation.py | 19 | 8 | 2 | 9 | 0 |
| test_rest_iterator_coverage.py | 20 | 6 | 6 | 8 | 0 |
| test_rest_journal_entry_creation.py | 32 | 10 | 5 | 17 | 0 |
| test_rest_migration_helpers.py | 42 | 13 | 1 | 27 | 1 |
| test_rest_migration_payments.py | 10 | 6 | 0 | 4 | 0 |
| test_rest_orchestration_batch.py | 7 | 1 | 3 | 3 | 0 |
| test_rest_orchestration_dispatch.py | 7 | 1 | 2 | 4 | 0 |
| test_rest_orchestration_start.py | 12 | 2 | 3 | 7 | 0 |
| test_rest_party_dispatch.py | 31 | 10 | 1 | 20 | 0 |
| test_settings.py | 46 | 20 | 7 | 19 | 0 |
| test_stock_account_handler_coverage.py | 13 | 7 | 0 | 3 | 3 |
| test_tegenrekening_mapper_coverage.py | 9 | 3 | 2 | 4 | 0 |
| test_tegenrekening_mapper.py | 13 | 4 | 1 | 8 | 0 |
| test_transaction_type_classification.py | 67 | 36 | 1 | 27 | 3 |
| test_transaction_utils_coverage.py | 9 | 1 | 6 | 2 | 0 |
| test_transaction_utils.py | 14 | 6 | 0 | 8 | 0 |
| test_uom_manager.py | 12 | 6 | 0 | 6 | 0 |
| **DOMAIN TOTALS** | **651** | **264** | **57** | **316** | **14** |

## Observations

- **Edge-dominant domain (316/651 ≈ 49%).** eBoekhouden import is a
  classification/routing engine, so most tests pin branch behavior: Dr/Cr sign
  (positive vs negative amount → row-debited vs main-credited), account-mapping
  fallbacks (unmapped ledger → None / suspense / company-default), skip/idempotency
  paths (already-imported early returns, `get_or_create_*` reuse), and
  malformed-input tolerance (empty/None/non-dict rows, Dutch vs camelCase type
  names). Happy paths (264) are the nominal doctype-creation flows; genuine
  UNHAPPY (57) cluster in the REST-client/settings HTTP-error paths, the
  invoice-validation guards (missing Relatie/customer/supplier ID → structured
  error), and `assertRaises` on unmapped-ledger / unbalanced-JE.
- **External HTTP is stubbed at the transport boundary, not mocked into
  tautology.** `test_rest_client_coverage`, `test_rest_iterator_coverage` and
  `test_settings` replace only `_request_with_retry` / `requests.post`/`get` (or
  use `FakeResponse`), leaving pagination, caching, error-shaping and
  classification logic real. The processor-routing block in
  `test_transaction_type_classification` (`@patch(...base_processor.frappe)`)
  mocks frappe for construction only; `can_process()` still runs for real. No
  live-API-gated skips were found in this slice — the domain is exercised via
  DB-backed fixtures + fake iterators returning synthetic mutations.
- **A few OTHER entries (14) are intentional characterization/regression
  guards**, not filler: `test_progress_utils` /
  `test_rest_full_migration_helpers_coverage` debug-log assertions;
  `test_rest_full_migration_sweep` "does_not_crash_on_settings_company_field" and
  "progresses_past_settings" (guard a fixed `settings.company` AttributeError, the
  second only asserts conditionally); `test_stock_account_handler_coverage`
  "returns_something"/shape checks; `test_transaction_type_classification`
  completeness tests (mapping table has all keys / valid doctype values).
- **Bug-documenting test flagged:** `test_transaction_type_classification.
  test_unknown_numeric_type_raises_error` asserts `AttributeError` on
  `get_erpnext_document_type(99)` and its own docstring says the code *should* be
  fixed to return "Journal Entry" — it characterizes a known defect rather than a
  desired contract. Counted UNHAPPY but worth revisiting.
- **Dead-code tests present:** `test_payment_processor_sweep`'s
  `TestLinkBankTransactionToPayment` class is explicitly commented "dead code — no
  production caller; tested to pin documented behaviour"; the two methods do
  assert real link/reconcile + idempotency, so they were classed HAPPY/EDGE not
  OTHER, but they test an unreachable path.
- **Skippable tests (env/column-gated, not live-API):** a handful `self.skipTest`
  when an optional custom column is absent —
  `test_rest_full_migration_helpers_coverage` (invoice-number `eboekhouden_invoice_number`
  ×2), `test_rest_invoice_creation.test_returns_well_formed_line_when_account_resolvable`
  (mapper default company "Ned Ver Vegan" absent), `test_rest_migration_helpers.
  test_get_mutation_gap_report_closes_a_seeded_gap` (no interior gap on site), and
  `test_tegenrekening_mapper_coverage.test_resolve_by_grootboek_nummer`
  (`eboekhouden_grootboek_nummer` column). These pass or skip cleanly on the test
  sites; none are credential-gated.

## Files with zero methods / missing

None. All 29 listed files exist and contain class-level `def test_*` methods
(counts above). No empty test files encountered in this slice.
