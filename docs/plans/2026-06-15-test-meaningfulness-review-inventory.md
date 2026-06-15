# Test-Meaningfulness Review Inventory

**Date:** 2026-06-15
**Purpose:** Enumerate every test file added or expanded by the 2026-06-14/15 coverage-sweep
wave, so each can be audited for *meaningfulness* (real behavioral assertions vs. coverage
padding). The sweeps were gated by `test-quality-enforcer` (blocks mock-abuse /
`ignore_permissions` in test bodies) and skeptical-reviewed **for the product fixes they
surfaced** — but the *test bodies themselves* were never audited for assertion quality.

## Scope

- **Range:** `4716acae..HEAD` (everything after the CI-infra commits; first sweep commit is `b5a7fa53`).
- **Totals:** **145 test files** — **124 new** (3,647 test fns) + **21 expanded** (481 test fns) = **~4,128 test functions**.

## What "meaningfulness audit" should flag, per file

- Tests with **no assertion** (only "didn't raise").
- **Tautological** assertions (`assertEqual(x, x)`, asserting on the test's own setup constants).
- Asserting on **mock/stub return values** rather than product behavior.
- Tests that exercise a line for coverage but assert nothing about the **outcome that matters**.
- Over-broad `assertRaises(Exception)` that would pass on the wrong error.

## Review chunks (grouped by originating sweep session)

Prior-review column: **fixes** = the bug fixes were skeptically reviewed; **none** = no session
review at all. **No chunk had its test assertions audited** — that is the gap this inventory feeds.

### A. eBoekhouden sweep — `6f6ecfe6` / `d9c0d129` (NEWEST, prior review: **none**)
Highest priority — never went through any review session.
```
tests/e_boekhouden/test_account_mapping_api.py           26
tests/e_boekhouden/test_account_services.py              35
tests/e_boekhouden/test_cleanup_utils.py                 13
tests/e_boekhouden/test_coa_import.py                    44
tests/e_boekhouden/test_cost_center_fix.py               16
tests/e_boekhouden/test_invoice_classifier.py            18
tests/e_boekhouden/test_invoice_helpers.py               30
tests/e_boekhouden/test_item_naming.py                   42
tests/e_boekhouden/test_migration_enhancements.py        38
tests/e_boekhouden/test_payment_entry_handler.py         47
tests/e_boekhouden/test_processors_base.py               38
tests/e_boekhouden/test_processors_stock.py              16
tests/e_boekhouden/test_rest_migration_helpers.py        40
tests/e_boekhouden/test_settings.py                      36
tests/e_boekhouden/test_tegenrekening_mapper.py          13
tests/e_boekhouden/test_transaction_utils.py             14
tests/e_boekhouden/test_uom_manager.py                   13
```

### B. Payments api/+utils coverage — `23a1581f..bf6a89fe`, `bae35c03..b0f5efa2`, `2e872485`, `bc407df5`, `0cfb059e`, `8ada25f2` (prior review: **fixes**, 2 skeptical reviewers on the money-path fixes)
Largest cluster; money-moving paths. Test assertions unaudited.
```
tests/payment/test_sepa_input_validation.py             104
tests/payment/test_sepa_rulebook_validator.py            74
tests/payment/test_sepa_utilities.py                     68
tests/payment/test_sepa_parser.py                        64
tests/payment/test_sepa_config_manager.py                47
tests/payment/test_sepa_reconciliation.py                47
tests/payment/test_sepa_conflict_detector.py             46
tests/payment/test_sepa_error_handler.py                 43
tests/payment/test_financial_calculation_utils.py        51
tests/payment/test_financial_error_handler.py            34
tests/payment/test_sepa_return_parser.py                 29
tests/payment/test_sepa_rollback_manager.py              34
tests/payment/test_payment_entry_cleanup.py              22
tests/payment/test_payment_retry.py                      31
tests/payment/test_payment_processing_recovery.py        30
tests/payment/test_bank_transaction_reconciliation.py    70
tests/payment/test_balance_transaction_processing.py     32
tests/payment/test_bank_reconciliation_matching.py       26
tests/payment/test_bulk_transaction_importer.py          18
tests/payment/test_sepa_batch_ui.py                      31
tests/payment/test_sepa_batch_ui_secure.py               34
tests/payment/test_sepa_batch_notifications.py           14
tests/payment/test_sepa_mandate_management.py            14
tests/payment/test_dd_batch_workflow_controller.py       28
tests/payment/test_dd_batch_scheduler_orchestration.py   14
tests/payment/test_settlement_processing.py              13
verenigingen_payments/api/test_dd_batch_api.py           24
verenigingen_payments/api/test_dd_batch_optimizer.py     30
tests/sepa/test_dd_batch_scheduler.py                    23
tests/sepa/test_sepa_batch_processor_logic.py            26
tests/backend/components/test_sepa_reconciliation.py      9  (EXPAND)
tests/backend/components/test_enhanced_sepa_processing.py 17 (EXPAND)
tests/backend/comprehensive/test_sepa_mandate_edge_cases.py 16 (EXPAND)
tests/sepa/test_sepa_mandate_member_integration_service.py 30 (EXPAND)
tests/sepa/test_sepa_option_ac_workflow.py               10 (EXPAND)
tests/sepa/test_sepa_security_comprehensive.py           33 (EXPAND)
tests/sepa/test_sepa_sequence_type_validation.py          9 (EXPAND)
verenigingen_payments/tests/test_api_regression.py       15 (EXPAND)
verenigingen_payments/tests/test_direct_debit_batch_refactoring.py 15 (EXPAND)
verenigingen_payments/tests/test_sepa_xml_adapter.py     19 (EXPAND)
verenigingen_payments/tests/test_sepa_xml_compliance.py   9 (EXPAND)
```

### C. Ponto sweep — `bc6d6255..5bb1875c` (prior review: **fixes**, 3 skeptical reviews)
HTTP boundary stubbed (no live creds) — high padding risk.
```
tests/payment/test_ponto_configuration_service.py        30
tests/payment/test_ponto_doctype_coverage_extra.py       29
tests/payment/test_ponto_doctype_unit.py                 17
tests/payment/test_ponto_models.py                       30
tests/payment/test_ponto_oauth2_callback.py               8
tests/payment/test_ponto_secure_cert_manager.py          13
tests/payment/test_ponto_token_manager_unit.py           17
tests/sepa/test_ponto_bank_account_creator.py            12
tests/sepa/test_ponto_betaalverzoek_client_unit.py       26
tests/sepa/test_ponto_callbacks.py                       17
tests/sepa/test_ponto_payment_client_unit.py             16
tests/sepa/test_ponto_payment_initiation_service.py      13
tests/sepa/test_ponto_sync_client_unit.py                17
tests/sepa/test_ponto_transaction_pipeline_unit.py       28
tests/sepa/test_ponto_webhook_entrypoint.py              19
tests/sepa/test_ponto_webhook_security_unit.py           30
```

### D. Mollie orchestrator — `c6a1a8bb` (prior review: **fixes**)
```
verenigingen_payments/mollie/tests/test_bulk_payment_checker_unit.py                24
verenigingen_payments/mollie/tests/test_dues_payment_processor_integration.py        5
verenigingen_payments/mollie/tests/test_dues_payment_processor_unit.py              22
verenigingen_payments/mollie/tests/test_mollie_payment_db_integration.py             7
verenigingen_payments/mollie/tests/test_mollie_payment_orchestrator_flow_unit.py    27
verenigingen_payments/mollie/tests/test_mollie_payment_orchestrator_unit.py         19
verenigingen_payments/mollie/tests/test_mollie_payments_debug_unit.py               21
verenigingen_payments/mollie/tests/test_mollie_subscription_recreation_unit.py      37
verenigingen_payments/mollie/tests/test_payment_webhook_helpers_unit.py             40
verenigingen_payments/mollie/tests/test_settlement_bank_transaction_processor_unit.py 19
verenigingen_payments/mollie/tests/test_settlement_processor_db_integration.py       3
verenigingen_payments/mollie/tests/test_webhook_wrapper_unified_unit.py             19
```

### E. Member coverage sweep — `ed5b134a..2d27b3bf` (prior review: **fixes**, 16 skeptical reviews)
```
tests/chapter/test_board_manager.py                      52
tests/chapter/test_chapter_controller.py                 51
tests/chapter/test_communication_manager.py              37
tests/chapter/test_member_manager.py                     40
tests/member/test_account_creation_api.py                28
tests/member/test_account_creation_request.py            32
tests/member/test_account_creation_request_invoice.py     5
tests/member/test_donor.py                               32
tests/member/test_donor_auto_creation_management.py      16
tests/member/test_member_scheduler.py                    15
tests/member/test_member_utils_endpoints.py              43
tests/member/test_membership_termination_analytics.py    30
tests/member/test_membership_termination_request.py      41
tests/membership/test_contribution_amendment_request.py  24
tests/membership/test_membership_dues_integration.py     21
tests/membership/test_membership_dues_schedule.py        35
tests/membership/test_membership_endpoints.py            33
tests/membership/test_membership_scheduler.py            14
tests/services/test_base_role_profile_manager.py         53
tests/services/test_donor_service.py                     24
tests/services/test_user_role_profile_calculator.py      40
tests/backend/unit/api/test_chapter_api.py               17 (EXPAND)
tests/backend/unit/api/test_member_management_api_coverage.py 36
```

### F. coverage-bugfixes session — `2d41629a..ed5b134a` (prior review: **fixes**, 5 review agents)
```
tests/security/test_permissions_coverage.py              44
tests/payment/test_mt940_import_integration.py           16
tests/payment/test_mt940_parsing.py                      23
tests/payment/test_payment_gateways.py                   17
tests/payment/test_payment_gateways_unit.py              19
tests/payment/test_payment_gateways_endpoints.py         13
tests/payment/test_payment_gateways_live.py               4
tests/payment/test_payment_doctype_coverage.py           63 (EXPAND)
tests/payment/test_payment_integration.py                22 (EXPAND)
```

### G. Core services / billing / CSV / utils-portal sweeps (prior review: **fixes**)
```
services/termination/test_termination_integration.py     48
services/billing/test_bulk_invoice_generation_service.py 24
services/billing/test_dues_schedule_auto_creator.py      32
services/billing/test_invoice_management.py              17
services/document/test_document_portal_service.py        47
verenigingen/doctype/brand_settings/test_brand_settings.py 27
tests/backend/unit/api/test_member_management_api_coverage.py (listed in E)
tests/backend/components/test_chapter_dashboard_page.py  27
tests/backend/components/test_donate_page.py             34
tests/backend/components/test_setup_init.py              30
tests/utils/test_api_classifier.py                       51
tests/utils/test_file_storage.py                         50
tests/utils/test_utils_init.py                           35
tests/utils/test_orphaned_child_table_cleanup.py         22
tests/utils/test_analytics_engine.py                      9   (Area B observability, review: fixes)
events/subscribers/test_chapter_subscribers.py           38
e_boekhouden/services/tests/test_account_migration_service.py 34
mijnrood_sync/services/test_document_import_service.py   37
mijnrood_sync/test_client_unit.py                        33
mijnrood_sync/doctype/mijnrood_sync_settings/test_mijnrood_sync_settings.py 26 (EXPAND)
verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py 49 (EXPAND)
verenigingen/doctype/vip_import/test_vip_import.py       46 (EXPAND)
verenigingen/doctype/verenigingen_settings/test_verenigingen_settings.py 6 (EXPAND)
tests/report/test_membership_dues_coverage_analysis.py   33
tests/report/test_members_without_dues_schedule.py       16
tests/services/test_polling_service.py                   59 (EXPAND)
tests/workflows/test_financial_workflows.py               5 (EXPAND)
tests/workflows/test_sepa_processing_pipeline.py          6 (EXPAND)
```

## Suggested review order (by risk × prior-review gap)

1. **Chunk A (eBoekhouden, newest)** — zero prior review, 477 tests across 17 files.
2. **Chunk B (payments utils/api)** — largest, money paths; fixes reviewed but tests not.
3. **Chunk C (Ponto)** — fully stubbed boundary → highest padding risk.
4. **Chunks D–G** — already had fix-level skeptical review; lower (but nonzero) risk.

## Fast mechanical pass — results (2026-06-15)

AST analyzer (`/tmp/audit_tests.py`) run over all 145 files / 4,130 test functions.
It resolves assertion-bearing helper methods (e.g. `self._ok(...)`) transitively, so a test
that delegates its assertions to a helper is **not** flagged. (First pass without this gave
106 NO_ASSERTION incl. ~19 false positives in `test_sepa_input_validation.py` that delegate
to `_ok`/`_bad`; corrected total below.)

### Flag counts
| Flag | Count | Meaning |
|---|---|---|
| **NO_ASSERTION** | **82** | test body has zero assertions — pure "didn't raise" |
| BROAD_RAISES | 13 | `assertRaises(Exception)` / `pytest.raises(Exception)` — too broad |
| MOCK_ONLY | 5 | only assertion is mock introspection (`assert_called*`), no product-state check |
| TAUTOLOGY | 3 | `assertEqual(a,a)` / `assertTrue(const)` etc. |
| PARSE_ERROR | 0 | — |

**Spot-checked and confirmed real** (not helper false-positives): every NO_ASSERTION sample
is an explicit "must not raise" test that verifies nothing about the *outcome* (e.g.
`test_uom_manager.py::test_setup_conversions_does_not_raise` — comment admits it creates ZERO
conversion factors but only asserts no-raise; a meaningful version would assert the count).

### NO_ASSERTION by file (82 total) — one cluster dominates
```
33  events/subscribers/test_chapter_subscribers.py        <-- 40% of all findings; chunk G
 5  mijnrood_sync/.../test_mijnrood_sync_settings.py
 3  tests/sepa/test_sepa_mandate_member_integration_service.py
 3  tests/payment/test_ponto_doctype_coverage_extra.py
 3  tests/member/test_account_creation_request.py
 3  tests/backend/comprehensive/test_sepa_mandate_edge_cases.py
 2  verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py
 2  tests/sepa/test_sepa_security_comprehensive.py
 2  tests/payment/test_sepa_utilities.py
 2  tests/payment/test_ponto_doctype_unit.py
 2  tests/payment/test_payment_doctype_coverage.py
 2  tests/e_boekhouden/test_payment_entry_handler.py
 2  tests/chapter/test_board_manager.py
 2  tests/backend/unit/api/test_chapter_api.py
 2  mijnrood_sync/test_client_unit.py
 1  x14 other files (one each)
```

### Full BROAD_RAISES / MOCK_ONLY / TAUTOLOGY list (21 sites — eyeball each)
Note: several BROAD_RAISES are *probably acceptable* (parser tests like `test_malformed_xml_raises`
where the product legitimately raises a generic error); flagged for confirmation, not as defects.
```
BROAD_RAISES  tests/backend/components/test_sepa_reconciliation.py            test_duplicate_transaction_handling:402
BROAD_RAISES  tests/backend/unit/api/test_chapter_api.py                      test_error_handling:430
BROAD_RAISES  tests/backend/unit/api/test_member_management_api_coverage.py   test_assign_denied_for_plain_member:164
BROAD_RAISES  tests/payment/test_sepa_error_handler.py                        test_decorator_defaults_operation_name_to_func_name:365
BROAD_RAISES  tests/payment/test_sepa_error_handler.py                        test_decorator_does_not_crash_when_circuit_open:373
BROAD_RAISES  tests/payment/test_sepa_error_handler.py                        test_decorator_raises_on_non_circuit_failure:356
BROAD_RAISES  tests/payment/test_sepa_reconciliation.py                       test_parse_xml_invalid_raises:632
BROAD_RAISES  tests/payment/test_sepa_return_parser.py                        test_malformed_xml_raises:177
BROAD_RAISES  tests/payment/test_sepa_utilities.py                            test_missing_file_raises:605
BROAD_RAISES  tests/sepa/test_sepa_mandate_member_integration_service.py      test_validate_mandate_link_fields_meta_exception:328
BROAD_RAISES  tests/sepa/test_sepa_security_comprehensive.py                  test_authorization_validation:161
BROAD_RAISES  verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py  test_field_length_limits:308
BROAD_RAISES  verenigingen/doctype/mijnrood_csv_import/test_mijnrood_csv_import.py  test_file_extension_validation:291
MOCK_ONLY     tests/payment/test_ponto_doctype_unit.py                        test_cancel_ponto_payment_calls_delete:209
MOCK_ONLY     tests/payment/test_ponto_doctype_unit.py                        test_cancel_ponto_request_calls_delete:120
MOCK_ONLY     tests/sepa/test_ponto_transaction_pipeline_unit.py             test_no_counter_increment_when_nothing_imported:427
MOCK_ONLY     tests/sepa/test_sepa_mandate_member_integration_service.py      test_validate_sepa_mandate_permissions_audit_logging:262
MOCK_ONLY     tests/sepa/test_sepa_mandate_member_integration_service.py      test_validate_sepa_mandate_permissions_with_resolver:208
TAUTOLOGY     tests/backend/comprehensive/test_sepa_mandate_edge_cases.py     test_valid_iban_formats:66
TAUTOLOGY     tests/e_boekhouden/test_invoice_classifier.py                   test_singleton_identity:186
TAUTOLOGY     tests/payment/test_sepa_utilities.py                            test_identical_logical_content_same_hash:428
```

### Verdict of the fast pass
- **~100 of 4,130 tests (2.4%)** carry a mechanical smell — the suite is **mostly meaningful**, not coverage-padding wholesale.
- **One real hotspot:** `events/subscribers/test_chapter_subscribers.py` — 33 no-assertion no-op tests (a true deep-review target).
- The remaining NO_ASSERTION are scattered 1–5 per file; many are deliberate "must not raise" smoke tests that *have a sibling assertion test* — low value individually but not wrong.
- BROAD_RAISES/MOCK_ONLY/TAUTOLOGY (21) are low-volume; a human/agent eyeball each is cheap.
- This mechanical pass cannot judge whether an *existing* assertion checks the *right* thing — that needs the deep per-file pass, best targeted at the hotspot + chunk A (eBoekhouden, never reviewed).

## Deep per-file review — results (2026-06-15)

6 read-only review agents: 1 on `chapter_subscribers`, 5 covering the 17 eBoekhouden files.
Each read the test bodies AND the product code, classifying every test MEANINGFUL / WEAK /
WRONG-VACUOUS. The deep pass found three things the fast pass cannot see, in rising order of
severity:

### Finding 1 — `chapter_subscribers.py` is a genuine weak hotspot (6/38 meaningful)
Root cause: **every `handle_*` wraps its body in a bare `try/except` + `frappe.log_error`**, so
the 32 "must not raise" tests are *structurally incapable of failing on a happy-path bug* — if
role-profile sync, the notification send, or volunteer sync throws, the handler swallows it and
the test still passes. The most important "does the work actually happen" paths (role-profile
sync, welcome/farewell emails, volunteer sync) are exactly the ones with zero assertions.
- **Cheap universal hardening:** assert `frappe.db.count("Error Log")` (or a title-filtered
  count) is unchanged across the call — converts a swallowed exception from green to red without
  per-test spies.
- 8 highest-value fixes named with file:line (top: `test_board_role_assignment_syncs_role_profile:160`,
  `test_volunteer_sync_runs_for_board_action:224`, the two bulk-import vacuous tests `:114`/`:123`).

### Finding 2 — 4 "characterization-of-bug" tests that actively DEFEND real bugs ⚠️
These pass *because the product is broken* and will turn **red when the bug is fixed** — i.e. a
green test that blocks its own fix and gives false "endpoint works" confidence. The opposite of
meaningful. (Named `test_PRODUCT_BUG_*`, so written knowingly — but they assert `assertRaises`,
not `@expectedFailure`, so CI treats them as passing.)
- `test_account_mapping_api.py::test_PRODUCT_BUG_config_status_queries_missing_columns:139`
- `test_account_mapping_api.py::test_PRODUCT_BUG_preview_migration_impact_missing_column:180`
- `test_coa_import.py::test_PRODUCT_BUG_ing_substring_false_positive:112`
- `test_coa_import.py::test_PRODUCT_BUG_rekening_triggers_ing_misclassification:219`

### Finding 3 — real PRODUCT BUGS surfaced by the review (agent-reported, schema-verified)
1. **eBoekhouden mapping endpoints query non-existent columns.** `get_migration_config_status`
   and `preview_migration_impact` (`e_boekhouden_account_mapping/api.py:31-42, 277-291`) SELECT
   `category`/`confidence`/`target_document_type`, which are not in the doctype JSON (it has
   `transaction_category`, `document_type`). → MySQL 1054 `ValidationError` on **every real call**
   of both whitelisted endpoints. **Needs confirmation via a live call before fixing.**
2. **Bank-name misclassification.** `identify_bank_name_enhanced` / `extract_bank_info_from_account_name`
   (`utils/eboekhouden_coa_import.py:341-342, 241`) match `"ing"` as a *substring* of `"rekening"`,
   so any account named `...betaalrekening`/`...rekening` (Knab, Rabobank, …) is imported as
   **ING Bank**. Corrupts bank-account import.
3. **UOM conversions silently never created.** `uom_manager._create_conversion` (`utils/uom_manager.py:266-283`)
   never sets the mandatory `category` field on `UOM Conversion Factor` → every insert raises
   MandatoryError, swallowed by a bare `except` → `setup_conversions()`/`setup_dutch_uoms()`
   create **zero** conversions while returning `status:"success"`. (Confirmed `category` is `reqd`.)
4. **Dead cleanup code (low blast-radius).** `smart_tegenrekening_mapper._generate_item_name`
   uses literal `"{self.company}"`/`"{account_code} - "` in `.replace()` (not f-strings) → the
   intended stripping never runs. Module is DEPRECATED/out of the prod invoice path, so low
   priority; `test_generate_item_name_passthrough:38` is vacuous and masks it.
   Plus two **dead-stub** tests asserting hardcoded constants: `is_enhanced_processing_enabled`
   (`return True`) and `get_progress_info` (fixed dict) — delete the tests (and likely the stubs).

### Other weak/mislabelled tests (no false confidence, just low value)
- `test_migration_enhancements.py::TestDetermineAccountTypeFallback` (`:228/234/240`) — name says
  "fallback" but actually exercises smart-typing (the import succeeds); the real `except ImportError`
  fallback has **zero** coverage. Rename + add a forced-ImportError test.
- Scattered WEAK shape-only/idempotency tests that don't assert the contract: `test_processors_stock.py::test_get_or_create_stock_item_idempotent:186` (never checks `is_stock_item=1`),
  `test_processors_base.py::test_default_cost_center_resolved:60` (`hasattr` always true) and
  `:test_validate_prerequisites_runs_for_real_company:297`, `test_rest_migration_helpers.py`
  gap/failure-report tests that hit empty-DB early returns, several `test_coa_import` /
  `test_account_services` constant-mirroring asserts. ~15 in total, each with a concrete fix noted.

### Coverage GAP (not a weak test — missing tests)
The eBoekhouden payment/stock suites deliberately stop at decision/parse/route logic. The
**money-moving core has zero behavioral assertions**: `_create_payment_entry` (amounts, paid_from/
paid_to, references; `payment_entry_handler.py:721`, allocation `:808-1020`) and
`_create_stock_reconciliation` (qty/valuation/GL; `stock_processor.py:171`). A follow-up
integration test is the highest-value *addition* (distinct from fixing the weak tests above).

### Scorecard
| Area | Tests | Meaningful | Weak | Vacuous/Wrong | Real bugs found |
|---|---|---|---|---|---|
| chapter_subscribers | 38 | 6 | ~20 | ~6 | 0 (but swallow-all masks any) |
| eBoekhouden (17 files) | ~477 | majority | ~15 | ~6 | 3 live + 1 dead-code |

**Verdict:** the eBoekhouden tests are mostly genuinely meaningful (strong DB-side-effect
assertions, real MOD-97 math, real routing) — the sweep did *not* mass-produce padding. But it
left (a) 4 bug-defending tests, (b) 3 real production bugs documented-but-unfixed, and (c) one
genuinely weak file (chapter_subscribers). Findings 2 and 3 are the actionable ones.

## Remediation completed (2026-06-15)

All four scopes the deep review identified were addressed. Product changes are minimal; the bulk
is test hardening. Every touched module verified green individually on veg11; ruff clean.

### Production bugs fixed (+ their bug-defending tests flipped to real assertions)
- **A1 — mapping API phantom columns.** `api.py`: `get_migration_config_status` /
  `preview_migration_impact` now select real columns (`transaction_category`/`document_type`, not
  `category`/`confidence`/`target_document_type`). Live call confirmed the endpoint threw before and
  returns correctly after. The 2 `test_PRODUCT_BUG_*` tests now assert the real success payload.
- **A2 — bank-name "ing" substring misclassification.** `eboekhouden_coa_import.py`: added
  `_matches_bank_keyword` (word-boundary-prefix match) and routed all four matching loops through it,
  so "ing" no longer matches inside "rekening" while "rabo"→"rabobank" still matches. The 2
  `test_PRODUCT_BUG_*` tests now assert the correct bank (Knab / Rabobank).
- **A3 — UOM conversions.** Decision (Foppe): **delete the broken setup.** The conversion table was
  inverted vs ERPNext's `1 from = value × to` convention (and never inserted due to the missing
  mandatory `category`). `setup_conversions` is now a documented no-op; `_create_conversion` removed.
  Tests assert no conversion factors are fabricated and that `setup_dutch_uoms` still seeds base UOMs.

### Test hardening
- **chapter_subscribers (B):** 38/38 green. Added an Error-Log-count guard (verified it catches a
  swallowed exception via failure injection) + email-service mock assertions; rebuilt the 2 vacuous
  bulk-import tests against real records. No product change.
- **Scattered eBoekhouden weak tests (C):** 8 modules. Deleted 2 vacuous stub-asserting tests,
  fixed the mislabelled smart-typing-vs-fallback class (+ a real forced-ImportError fallback test),
  strengthened shape-only/idempotency/tautology tests with real DB-state assertions, made the
  deprecated-module tegenrekening passthrough test honestly document the f-string dead code.
- **Money-core integration tests (D):** 5 new tests. Payment Entry create path (customer receipt,
  supplier payment, receipt allocated to a real Sales Invoice) asserting payment_type/party/
  paid_from/paid_to/amounts/references/outstanding; Stock Reconciliation create path asserting
  item/warehouse/qty/valuation + a real Stock Ledger Entry. No product bug found in the create paths.

### Notes / residual
- `_generate_item_name` f-string dead code left unfixed (deprecated module, out of prod path) — now
  honestly documented by its test rather than masked.
- Stock Reconciliation lacks an `eboekhouden_mutation_nr` custom field, so its idempotency branch
  can't be exercised here (documented in the new test class).
- Dead method `is_enhanced_processing_enabled` (`return True`) — its vacuous test was deleted; the
  method itself was left (product untouched) for a future cleanup.

## Method note
Per-file `def test_` counts were taken from the current working tree; NEW vs EXPAND is relative
to `4716acae`. File list: `/tmp/changed_tests.txt` regenerable via
`git diff --name-only 4716acae..HEAD -- '*.py' | grep -E '(^|/)test_[^/]*\.py$'`.
