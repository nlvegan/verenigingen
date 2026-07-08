# Domain P3 — Payments App Core / Shared-Utils / SEPA-XML / Doctypes

Test-method inventory for 26 files (all present, none missing). Every `def test_*`
method classified by dominant intent: HAPPY (nominal success), UNHAPPY (expects
error/throw/validation-failure/rejection), EDGE (boundary/empty/duplicate/malformed/
retry/rounding/XML-schema edge), OTHER (smoke/placeholder/tautological/config-shape).

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| api/test_dd_batch_api.py | 24 | 13 | 5 | 6 | 0 |
| api/test_dd_batch_optimizer.py | 31 | 12 | 4 | 14 | 1 |
| core/test_error_handler.py | 23 | 4 | 10 | 7 | 2 |
| core/test_response_cache.py | 37 | 13 | 0 | 20 | 4 |
| core/test_response_parsing.py | 33 | 8 | 11 | 13 | 1 |
| services/test_mollie_configuration_service.py | 42 | 17 | 12 | 6 | 7 |
| tests/test_api_regression.py | 15 | 0 | 1 | 0 | 14 |
| tests/test_direct_debit_batch_refactoring.py | 12 | 7 | 0 | 3 | 2 |
| tests/test_model_field_mapping.py | 8 | 6 | 0 | 2 | 0 |
| tests/test_sepa_xml_adapter_coverage.py | 16 | 6 | 1 | 9 | 0 |
| tests/test_sepa_xml_adapter.py | 20 | 8 | 0 | 10 | 2 |
| tests/test_sepa_xml_compliance.py | 17 | 3 | 0 | 14 | 0 |
| tests/test_service_layer_validation.py | 17 | 9 | 2 | 5 | 1 |
| tests/utils_shared/test_backoff.py | 8 | 5 | 0 | 3 | 0 |
| tests/utils_shared/test_db_helpers.py | 7 | 3 | 3 | 1 | 0 |
| tests/utils_shared/test_money.py | 22 | 8 | 0 | 14 | 0 |
| tests/utils_shared/test_recipient_resolver.py | 6 | 2 | 0 | 4 | 0 |
| tests/utils_shared/test_responses.py | 28 | 16 | 0 | 8 | 4 |
| tests/utils_shared/test_sliding_window.py | 17 | 2 | 0 | 14 | 1 |
| tests/utils_shared/test_xml_helpers.py | 22 | 9 | 0 | 13 | 0 |
| utils/test_bank_transaction_reconciliation_coverage.py | 25 | 10 | 1 | 14 | 0 |
| doctype/mollie_settings/test_mollie_settings_coverage.py | 33 | 20 | 8 | 4 | 1 |
| doctype/mollie_settings/test_mollie_settings.py | 5 | 3 | 0 | 1 | 1 |
| doctype/sepa_audit_log/test_sepa_audit_log.py | 1 | 0 | 0 | 0 | 1 |
| doctype/sepa_mandate/test_sepa_mandate_comprehensive.py | 20 | 11 | 3 | 1 | 5 |
| doctype/sepa_mandate/test_sepa_mandate.py | 13 | 8 | 4 | 1 | 0 |
| **DOMAIN TOTALS** | **502** | **203** | **65** | **187** | **47** |

Distribution: Happy 40.4%, Unhappy 12.9%, Edge 37.3%, Other 9.4%.

## Observations

- **SEPA-XML compliance rigor is high and pain.008-schema-specific.** `test_sepa_xml_compliance.py`
  is 14/17 EDGE: it parses generated XML against the pain.008.001.08 namespace and asserts
  SvcLvl=SEPA, LclInstrm/Cd=CORE, SeqTp membership, Dutch IBAN/BIC/incassant-ID formats,
  NbOfTxs/CtrlSum accuracy, and — a recurring regression guard across three files — that
  DtOfSgntr is NOT the old hardcoded `2023-01-01`. The `TestBuildPostalAddressParity` class
  proves byte-identical XML output vs. the inlined block it replaced (real structural parity,
  not tautology). `test_sepa_xml_adapter.py::test_one_invalid_debtor_iban_skips_only_that_row`
  is a genuine per-transaction skip regression test. Caveat: most compliance tests wrap the
  body in `try/except → frappe.logger().warning(...)`, so they silently pass ("skip") when
  XML generation raises on incomplete config — meaningful only when config is fully seeded.

- **utils_shared pure-unit suite is the highest-quality cluster** — legitimate, fast,
  dependency-free, and adversarial. backoff/money/sliding_window/xml_helpers/responses test
  real boundaries: exact window-edge keep-vs-prune semantics, currency-symbol regex stripping,
  HMAC known-vectors, exponential-cap clamping, Ctry-first element ordering. `test_money.py`
  and `test_sliding_window.py` are ~64% and ~82% EDGE respectively. db_helpers and
  recipient_resolver are real DB-integration (temp table create/drop, enabled-vs-disabled user
  filtering) with readback assertions — no mock-into-tautology here.

- **`test_api_regression.py` is coverage-padding (14/15 OTHER) and should be flagged.** Nearly
  every method wraps the call in `try/except` accepting `(str, None)` OR any of several
  exception types, then only asserts `isinstance`. `test_api_security_decorators_preserved` /
  `test_critical_api_decorators` assert `hasattr(func, "__wrapped__") or hasattr(func,
  "__name__")` — the second disjunct is true for every Python function, so these are
  tautological. It cannot catch a regression. Similar (milder) padding: mollie_configuration
  `test_is_*_returns_bool` and `_returns_string_or_none` are type-only assertions (7 OTHER),
  and several `validate_*_with_configuration` tests are `if configured: ... else: ...`
  conditionals that assert nothing when the branch condition is false on a bare CI site.

- **Doctype coverage is uneven.** `test_sepa_mandate.py` (13 tests) and
  `test_mollie_settings_coverage.py` (33 tests, 8 real UNHAPPY rejections incl. SSRF/traversal/
  overlong-URL webhook-security guards) are substantive real-integration suites. But
  `test_sepa_audit_log.py` is a single `assertTrue(True)` placeholder, `test_mollie_settings.py`
  has one, and `test_sepa_mandate_comprehensive.py` carries 5 OTHER placeholder tests
  (`test_mandate_audit_logging`, `_data_retention_compliance`, `_cleanup_on_member_deletion`,
  `_data_protection_compliance`, `_mollie_integration...`) whose bodies save a doc then assert
  nothing about the feature named, ending in bare `pass` or "implementation depends" comments.

- **The dd_batch and bank-reconciliation suites carry the real bug-regression value.** These
  are dense with EDGE branch coverage tied to documented product-bug fixes: `_create_mollie_
  payment_entry` paid_from/paid_to swap, missing-`company`/`cost_center` on fee Journal Entries,
  the `get_eligible_invoices` Member↔Customer join fix, and conflict-resolution reload-before-
  save persistence. `test_bank_transaction_reconciliation_coverage.py` uses a single narrow
  `_StubSettlementsClient` at the HTTP boundary and runs all downstream PE/JE booking for real
  — a clean boundary, not business-logic mocking. `test_mixed_payments_classify_each_outcome`
  exercises 6 distinct outcome classes (error/duplicate/success/not-found/mismatch/no-match)
  in one test.

- **Base classes are consistent with project convention.** DB-touching suites use
  `EnhancedTestCase`/`SEPATestDataFactory` (or the domain-specific `BTRBase`); pure-unit
  utils_shared and model-mapping suites correctly use plain `unittest.TestCase`. A few
  Mollie/error-handler suites use `FrappeTestCase` with `unittest.mock.patch` on
  `frappe.log_error`/`msgprint` — appropriate here since they test the error-handler wiring
  itself, not business logic. `test_sepa_mandate_comprehensive.py` guards its imports with
  try/except `HAS_ENHANCED_FACTORY` fallbacks, which is defensive but means some assertions
  become `skipTest` no-ops if utils are unavailable.
