# Test Inventory 25a — tests/e_boekhouden (part 1)

**COMPLETE** — Read-only classification of every class-level `def test_*` in the first 29 files of `verenigingen/tests/e_boekhouden` (domain EBKH1). 721 test methods across 29 files; per-file counts cross-checked against `grep -cE 'def test_'`.

Classification key:
- **Happy** = nominal success / expected-valid path
- **Unhappy** = expects error/throw/validation-failure/rejection/failed-import handling
- **Edge** = boundary, empty/null/zero, duplicate, idempotency, malformed data, ordering, Dr/Cr sign, rounding, mutation-number gaps, account-mapping fallbacks
- **Other** = smoke/import-safety/setup-only/tautological, debug-no-assert, mock-into-tautology, live-API-gated (skipped)

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_account_group_fix_coverage.py | 6 | 0 | 2 | 0 | 4 |
| test_account_hierarchy_service_db_coverage.py | 14 | 1 | 5 | 8 | 0 |
| test_account_mapping_api.py | 50 | 19 | 3 | 28 | 0 |
| test_account_organization_service_sweep.py | 10 | 6 | 0 | 4 | 0 |
| test_account_services.py | 26 | 10 | 0 | 16 | 0 |
| test_api_token_expiry.py | 26 | 5 | 8 | 11 | 2 |
| test_bank_transaction_parser.py | 15 | 4 | 0 | 11 | 0 |
| test_cleanup_utils_coverage.py | 7 | 5 | 1 | 1 | 0 |
| test_cleanup_utils.py | 21 | 9 | 4 | 8 | 0 |
| test_cleanup_utils_sweep.py | 5 | 3 | 0 | 2 | 0 |
| test_coa_import.py | 54 | 22 | 1 | 31 | 0 |
| test_coa_import_sweep.py | 8 | 3 | 3 | 2 | 0 |
| test_configurable_account_mapper_unit.py | 30 | 8 | 4 | 13 | 5 |
| test_consolidated_utils.py | 44 | 16 | 9 | 18 | 1 |
| test_cost_center_creation.py | 25 | 8 | 2 | 8 | 7 |
| test_cost_center_fix.py | 16 | 5 | 3 | 8 | 0 |
| test_cost_center_parsing.py | 37 | 10 | 2 | 23 | 2 |
| test_cost_center_ui_integration.py | 12 | 3 | 1 | 0 | 8 |
| test_create_custom_fields_coverage.py | 6 | 3 | 0 | 2 | 1 |
| test_data_integrity.py | 31 | 6 | 2 | 23 | 0 |
| test_data_transformation.py | 54 | 26 | 2 | 26 | 0 |
| test_eboekhouden_api_client.py | 29 | 16 | 4 | 8 | 1 |
| test_eboekhouden_api_sweep.py | 17 | 4 | 7 | 6 | 0 |
| test_eboekhouden_doctype_coverage.py | 66 | 26 | 11 | 24 | 5 |
| test_e_boekhouden_migration_integration.py | 33 | 17 | 2 | 11 | 3 |
| test_enhanced_migration_coverage.py | 7 | 3 | 1 | 3 | 0 |
| test_http_client_mixin.py | 27 | 6 | 10 | 9 | 2 |
| test_import_error_handling.py | 37 | 9 | 3 | 25 | 0 |
| test_import_manager_coverage.py | 8 | 3 | 0 | 5 | 0 |
| **DOMAIN TOTALS** | **721** | **256** | **90** | **334** | **41** |

## Observations

- **Coverage skew toward Edge (334 / 721, 46%).** The domain is dominated by data-transformation, account-mapping, and parsing logic (Dutch bank names, IBAN generation, VAT/BTW codes, UoM, date normalization, account-code ranges). These tests are overwhelmingly boundary/variant/fallback cases — exactly the EDGE bucket. Happy paths (256, 36%) come second; genuine Unhappy/error-path tests are a modest 90 (12%).
- **Strongest files** (real behavioral assertions, real production code under test): `test_coa_import.py` (54), `test_data_transformation.py` (54), `test_consolidated_utils.py` (44), `test_account_mapping_api.py` (50), and `test_eboekhouden_doctype_coverage.py` (66). These carry the bulk of meaningful coverage with clear Happy/Edge/Unhappy separation.
- **Mock-into-tautology flag: `test_cost_center_ui_integration.py`.** 3 of 12 methods (`test_preview_dialog_functionality`, `test_create_cost_centers_dialog_functionality`, `test_error_handling_in_ui_workflow`) `patch()` the exact whitelisted function they then invoke via `frappe.call(...)` and assert on the mock's hard-coded return — pure tautologies proving nothing about production code. Several sibling methods are UI "simulations" (`progress_indication_simulation`, `result_display_formatting`, `form_validation_simulation`, `accessibility_compliance_simulation`) with no production surface. Only its two real end-to-end workflow tests exercise the actual API. Bucketed 8/12 as OTHER.
- **HTTP-boundary mocking is legitimate, not tautological.** `test_api_token_expiry.py`, `test_http_client_mixin.py`, and `test_eboekhouden_api_client.py` mock `requests`/`frappe` at the transport boundary but exercise real token-TTL, retry (429/5xx/401/timeout), pagination, and URL-building logic. These are the domain's densest Unhappy clusters (retry/failure paths) and are honest unit tests. The client files carry an explicit comment justifying the `@patch("requests.post")` boundary mock.
- **Live-REST-API gating is minimal here.** Unlike the broader eBoekhouden sync suite, part-1 files are almost all offline (mocked transport or DB-seeded). `skipTest` guards are for missing custom fields / no seeded company (`test_cleanup_utils*.py`, `test_configurable_account_mapper_unit.py` integration class, `test_eboekhouden_api_client.py::TestFixAccountTypes`, doctype item/suspense mappings), NOT for missing REST credentials. No file is credential-skip-dominated.
- **`test_cost_center_creation.py` OTHER cluster (7/25)** is testing its own `DutchAccountingDataGenerator` scaffolding (`TestDutchAccountingDataGeneration`) plus two performance/memory tests — validating fixtures and timing rather than production behavior. `test_configurable_account_mapper_unit.py` (5 OTHER) ends with three "no_error"/"execute" smoke tests in its real-DB integration class.

## Notes on file set
- All **29** files in scope contained class-level `def test_*` methods; **zero** empty or missing files. Base classes: most DB-touching files use `EnhancedTestCase`; pure-logic files (parsers, mappers, transformers, HTTP-mixin, data-integrity) use plain `unittest.TestCase`, which is appropriate for their no-DB unit scope.
