# Test Inventory: tests/backend/validation

> Audit complete (19/19 files). READ-ONLY classification of every class-level `def test_*` method.
> Classification key: HAPPY = nominal success / valid input accepted; UNHAPPY = expects error/throw/validation-failure/rejection; EDGE = boundary/empty/null/duplicate/malformed/ordering/type-coercion; OTHER = smoke/import-safety/setup-only/tautological/meta-validator-tautology/skip-dominated.

## Per-file classification

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_api_contracts.py | 8 | 1 | 0 | 1 | 6 |
| test_api_endpoints.py | 9 | 0 | 0 | 0 | 9 |
| test_approval_helpers.py | 23 | 13 | 2 | 7 | 1 |
| test_bsn_rsin_validation_fix_verification.py | 8 | 4 | 3 | 0 | 1 |
| test_comprehensive_validation.py | 1 | 0 | 0 | 0 | 1 |
| test_erpnext_inspired_validations.py | 12 | 3 | 4 | 1 | 4 |
| test_error_recovery_and_rollback.py | 11 | 0 | 9 | 0 | 2 |
| test_event_subscriber_defensive_coding.py | 18 | 3 | 0 | 15 | 0 |
| test_field_sync_service_integration.py | 20 | 8 | 0 | 10 | 2 |
| test_field_sync_service_unit.py | 21 | 7 | 3 | 9 | 2 |
| test_fuzzy_logic_modernization_validation.py | 20 | 6 | 7 | 3 | 4 |
| test_iban_validator.py | 23 | 9 | 3 | 10 | 1 |
| test_import_validation_integration.py | 7 | 0 | 0 | 0 | 7 |
| test_mock_banks.py | 7 | 6 | 0 | 1 | 0 |
| test_n_plus_one_optimization.py | 12 | 7 | 1 | 4 | 0 |
| test_production_scenario_validation.py | 7 | 2 | 0 | 3 | 2 |
| test_special_characters_validation.py | 5 | 2 | 1 | 2 | 0 |
| test_validation_regression.py | 6 | 2 | 2 | 0 | 2 |
| test_validation_utilities.py | 11 | 2 | 1 | 7 | 1 |
| **DOMAIN TOTALS** | **229** | **75** | **36** | **73** | **45** |

## Observations

- **Runtime vs meta-validator split.** The domain is predominantly genuine runtime behavior testing (~184/229 methods exercise product logic). Meta-validators — tests that assert on source greps, file existence, pre-commit config, schema shape, or AST field-references rather than executing product code — are concentrated in a few files: `test_import_validation_integration.py` (7/7, tests dev tooling), `test_comprehensive_validation.py` (1/1, inlines a `RoleProfileSystemValidator` doing method/dataclass existence checks), most of `test_api_contracts.py` (6/8 hasattr / import-exists / constant-defined checks), plus one method each in `test_validation_regression.py` (`test_field_validator_on_test_suite` — genuine source-scan guard) and `test_production_scenario_validation.py` (`test_template_field_completeness` — hasattr). Some meta guards are legitimate (import-safety, field-drift catchers); others are tautological existence assertions.
- **Weak / tautological files to flag.** `test_api_endpoints.py` is entirely dead weight — all 5 classes carry `@unittest.skip("Pseudo-test: references nonexistent API endpoints and self-mocks results")`, so 9/9 methods run nothing (counted OTHER). `test_import_validation_integration.py` has several print-only / pass-either-way methods (`test_import_validator_detects_bad_imports`, `test_no_secure_context_manager_imports`) that never fail. `test_fuzzy_logic_modernization_validation.py`, despite an impressive name, is runtime but soft: 4/20 methods use `try/except: pass` swallowing that makes them near-tautological, and several "negative_case_*" methods actually assert the *positive* path.
- **Strongest files.** `test_approval_helpers.py` (23 focused unit tests on real helper functions, clean happy/edge/unhappy spread), `test_iban_validator.py` (23 tight IBAN/BIC cases with genuine invalid + boundary coverage), `test_validation_utilities.py` (11 age-boundary tests — exemplary EDGE coverage), `test_field_sync_service_unit.py` (21 real unit tests), and `test_event_subscriber_defensive_coding.py` (18 disciplined deleted/missing-entity defensive tests). These are the meaningful core of the domain.
- **Classification skew reflects intent.** UNHAPPY (36) is lower than one might expect for a "validation" domain because much rejection testing is folded into EDGE (73) — invalid IBANs, under-age members, empty/null names, and malformed inputs are boundary/malformed cases first. Pure error-recovery is isolated in `test_error_recovery_and_rollback.py` (9/11 UNHAPPY, rollback-on-failure).
- **Base classes.** Mixed but consistent within the app's conventions: most files use `EnhancedTestCase` (from `tests/fixtures/enhanced_test_factory`) or `VereningingenTestCase` (from `tests/utils/base`); `test_error_recovery_and_rollback.py` uses `TransactionBoundaryTestCase`; `test_field_sync_service_unit.py` uses plain `FrappeTestCase` for pure-unit portions. No non-factory hand-rolled fixture anti-patterns observed.
- **Notable defensive nuance.** The `test_event_subscriber_defensive_coding.py` deleted-member tests use a weak `self.assertTrue(True)` after the call, but the real guard is `self.fail(...)` inside the `except DoesNotExistError` — so they do meaningfully catch regressions (kept as EDGE, not downgraded to OTHER).

## Zero-method / missing files

- None. All 19 files in `tests/backend/validation` contain at least one class-level test method and were audited.
- Note: `test_api_endpoints.py` (9 methods) and `test_comprehensive_validation.py` (1 method) are effectively non-executing — the former is fully `@unittest.skip`-ped, the latter is a single meta-validator — but neither is empty.
- Module-level `def test_*` functions outside test classes (e.g. `test_function` in `test_import_validation_integration.py` at line 61 inside a string literal; `test_special_character_validation` at `test_special_characters_validation.py:109` as a `@frappe.whitelist()` helper) were correctly excluded as non-class-level.
