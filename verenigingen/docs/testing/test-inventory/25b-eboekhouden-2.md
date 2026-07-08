# Test Inventory 25b — tests/e_boekhouden (part 2 / EBKH2)

> COMPLETE — all 29 files classified. Read-only classification of class-level `def test_*` methods.
> Classification: HAPPY (nominal success) / UNHAPPY (expects error/rejection) / EDGE (boundary, null, dup, idempotency, malformed, Dr/Cr sign, rounding, mapping fallback) / OTHER (smoke/import-only/tautology/mock-into-tautology/live-API-gated/skipped).

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_invoice_classifier.py | 18 | 3 | 3 | 9 | 3 |
| test_invoice_helpers_construction_coverage.py | 38 | 13 | 3 | 22 | 0 |
| test_invoice_helpers_coverage.py | 19 | 6 | 1 | 12 | 0 |
| test_invoice_helpers.py | 44 | 18 | 4 | 22 | 0 |
| test_item_naming.py | 42 | 24 | 0 | 18 | 0 |
| test_ledger_mapping_coverage.py | 13 | 4 | 0 | 8 | 1 |
| test_migration_audit_trail.py | 14 | 5 | 3 | 6 | 0 |
| test_migration_config_coverage.py | 15 | 6 | 0 | 8 | 1 |
| test_migration_controller_accounts_coverage.py | 12 | 4 | 1 | 7 | 0 |
| test_migration_controller_config_coverage.py | 12 | 4 | 3 | 5 | 0 |
| test_migration_controller_endpoints.py | 19 | 5 | 11 | 3 | 0 |
| test_migration_controller_guards_coverage.py | 9 | 1 | 5 | 3 | 0 |
| test_migration_controller_helpers_coverage.py | 8 | 4 | 0 | 1 | 3 |
| test_migration_controller_sweep.py | 9 | 2 | 5 | 2 | 0 |
| test_migration_date_chunking.py | 15 | 8 | 2 | 5 | 0 |
| test_migration_dry_run.py | 12 | 8 | 1 | 3 | 0 |
| test_migration_error_recovery.py | 15 | 5 | 2 | 7 | 1 |
| test_migration_performance.py | 14 | 6 | 3 | 5 | 0 |
| test_migration_phase_failure.py | 12 | 2 | 6 | 4 | 0 |
| test_migration_pre_validation.py | 21 | 3 | 13 | 3 | 2 |
| test_migration_pure_helpers.py | 45 | 1 | 0 | 43 | 1 |
| test_migration_transaction.py | 16 | 8 | 4 | 3 | 1 |
| test_migration_transaction_safety.py | 11 | 5 | 0 | 1 | 5 |
| test_mutation_savepoint.py | 3 | 1 | 1 | 1 | 0 |
| test_opening_balance_import.py | 35 | 7 | 1 | 27 | 0 |
| test_party_extractor.py | 17 | 8 | 1 | 8 | 0 |
| test_party_resolver_coverage.py | 30 | 7 | 2 | 19 | 2 |
| test_party_resolver.py | 35 | 9 | 3 | 14 | 9 |
| test_payment_entry_handler_allocation.py | 19 | 2 | 2 | 14 | 1 |
| **DOMAIN TOTALS (29 files)** | **572** | **179** | **80** | **283** | **30** |

## Observations

- **Edge-heavy domain (283/572 ≈ 49%).** eBoekhouden sync is fundamentally about mapping messy external accounting data into ERPNext, so the bulk of tests probe boundaries: Dr/Cr sign resolution, zero/negative amounts, credit-note detection, duplicate/idempotent imports, empty payloads, malformed lines, account-mapping fallbacks, and truncation caps. `test_migration_pure_helpers.py` (43/45 EDGE) and `test_opening_balance_import.py` (27/35 EDGE) are the strongest concentrations — opening-balance Dr/Cr placement and credit-note sign flipping dominate.
- **Live REST API is deliberately NOT exercised.** Every file carrying a live seam documents that it tests paths *before* `api.make_request()` / `requests.get`. There are no skipped/credential-gated tests in this set — instead the suites stop at the HTTP boundary (guards, config-absent branches, provisional-party creation on real DB). `test_migration_controller_guards_coverage.py`, `test_party_resolver_coverage.py`, and `test_opening_balance_import.py` (api_fetch_* tests inject payloads rather than hit the network). This is a design choice noted in-file, not a coverage gap masked by skips.
- **Real-DB integration is the norm; heavy mocking is isolated to one file.** Most suites subclass `EnhancedTestCase` and write real records. The exception is `test_party_resolver.py`, which `@patch`es `frappe` wholesale — 9 of its 35 methods are OTHER: config-shape tautologies (`*_config_has_required_keys/fields`) and delegation-verification tests (`*_delegates`, `*_calls_resolve_party`, convenience-function wrappers) that only assert a mock forwarded a call (mock-into-tautology). The parallel `test_party_resolver_coverage.py` is the real-DB counterpart of the same module and is far more meaningful.
- **Strong UNHAPPY presence in the controller/validation cluster.** `test_migration_pre_validation.py` (13/21 UNHAPPY), `test_migration_controller_endpoints.py` (11/19), `test_migration_phase_failure.py` (6/12) and `test_migration_controller_guards_coverage.py` (5/9) drive most of the 80 UNHAPPY methods — non-draft rejection, missing/invalid params, unbalanced journal entries, missing accounts, enqueue/exception failure paths, and permission-denied throws. These are genuine error-path assertions, not smoke.
- **OTHER (30) is mostly benign scaffolding.** Beyond the `test_party_resolver.py` tautologies, OTHER items are singleton/cache identity checks (`get_*_is_cached`), "contract"-shape assertions in `test_migration_transaction_safety.py` (5 — verify return keys without asserting correctness), message-interpolation/formatting checks (`*_message_is_formatted`, `record_identifier_uses_fstring`, `log_*_summary_formats_counts`), and `debug_info_populated` smoke. The transaction-safety "contract" tests are the weakest (characterization without correctness).
- **Pure-helper files are the cleanest and most numerous.** `test_invoice_helpers*.py`, `test_item_naming.py`, `test_ledger_mapping_coverage.py`, `test_migration_pure_helpers.py` are stateless unit tests with zero OTHER (except deliberate debug smoke) and no live dependency — high signal, fast, and the natural home for the Dr/Cr / rounding / mapping-fallback EDGE cases.

## Notes on files
- All 29 assigned files (indices 30–58 of the sorted list) exist and contain class-level `def test_*` methods; none were empty or missing.
- No `@unittest.skip` / `skipIf` / `skipUnless` decorators found in any of the 29 files — the "live-API-gated skip" pattern common elsewhere in eBoekhouden is absent here; these suites instead structure tests to stop short of the network seam.
