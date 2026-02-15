# Cyclomatic Complexity Audit — Python Controllers >1600 LOC

**Date:** 2026-02-13 (updated 2026-02-15)
**Tool:** radon 6.0.1 (`radon cc -s`)
**Scope:** All non-test Python files >1600 LOC in `verenigingen/`
**Files analyzed:** 18
**Total LOC:** ~43,628

---

## Summary

18 Python files exceed 1600 lines. Of those, **7 contain F-grade functions** (CC 26+, considered unmaintainable) and **5 more contain E-grade functions** (CC 21-25, very high risk).

| Severity | Count (original) | Count (post-refactor) | Description |
|----------|-----------------:|----------------------:|-------------|
| F-grade functions (CC 26+) | 7 in target file | **0 in target file** | Unmaintainable — should be decomposed |
| E-grade functions (CC 21-25) | 4 in target file | **2 in target file** | Very high risk — strong candidates for refactoring |
| D-grade functions (CC 16-20) | 1 in target file | **3 in target file** | Moderate risk — consider simplifying |
| C-grade functions (CC 11-15) | 10 in target file | **12 in target file** | Slightly complex — acceptable for controllers |

**App-wide totals (excluding tests):** 14 F-grade, 45 E-grade, 163 D-grade functions.

---

## Refactoring Completed: `eboekhouden_rest_full_migration.py`

**PR:** [#20](https://github.com/nlvegan/verenigingen/pull/20) — merged to `develop` 2026-02-14
**Branch:** `refactor/decompose-migration-file` (3 commits)

### Before → After

| Metric | Before | After | Change |
|--------|-------:|------:|--------|
| LOC | 4,879 | 4,549 | -330 (-7%) |
| Functions | 55 | 75 | +20 (smaller helpers) |
| F-grade (CC 26+) | **7** | **0** | All eliminated |
| E-grade (CC 21-25) | 4 | 2 | -2 |
| D-grade (CC 16-20) | 1 | 3 | +2 (from decomposed F-grade) |
| Worst function CC | 80 | 39 | -51% |
| Average CC | D (17.2 est.) | B (8.4) | -51% |
| Test coverage | 0 tests | 45 tests | New test file |

### What was done

1. **Removed dead code** (~150 LOC): deprecated wrappers (`get_default_cost_center`, `get_party_account`), unused old batch importer (`_import_rest_mutations_batch`)
2. **Decomposed `_create_sales_invoice`** (CC 35→13): Extracted `_resolve_receivable_account`, `_process_invoice_line_items`
3. **Decomposed `_create_purchase_invoice`** (CC 32→12): Extracted `_resolve_payable_account`, `_process_purchase_invoice_line_items`
4. **Decomposed `_create_journal_entry`** (CC 62→30): Extracted `_process_journal_entry_rows`, `_validate_journal_balance`, `_get_memorial_booking_amounts`, `_should_debit_increase`, `_build_memorial_balancing_entry`, `_assign_party_to_entry`
5. **Decomposed `_import_opening_balances`** (CC 52→39) and `_import_opening_balances_from_data` (CC 36→20): Extracted `_classify_opening_balance_account`, `_calculate_opening_balance_debit_credit`, shared helpers
6. **Decomposed `_import_rest_mutations_batch_enhanced`** (CC 80→22): Extracted `_process_mutation_with_coordinator`, `_categorize_batch_errors`, `_log_batch_summary`, `_get_bank_transaction_stats`, `_retry_transient_failures`
7. **Fixed PaymentProcessor duplication**: `_create_money_transfer_payment_entry` (170 LOC) → 20-line delegation to `PaymentProcessor._process_money_transfer()`
8. **Unified DRY violation**: `_resolve_receivable_account` and `_resolve_payable_account` share `_resolve_party_account`
9. **Added 45 unit tests** for 5 pure helper functions

### Remaining E-grade functions in migration file

| CC | Function | Notes |
|---:|----------|-------|
| 39 | `_import_opening_balances` | Complex account classification + party assignment loop; further decomposition possible but diminishing returns |
| 33 | `start_full_rest_import` | Orchestrator with many sequential steps; CC driven by branching on import options |

---

## Full Results Table (updated)

| File | LOC | Funcs | F | E | D | C | Max CC | Tests | Worst function |
|------|----:|------:|--:|--:|--:|--:|-------:|------:|----------------|
| `e_boekhouden/utils/eboekhouden_rest_full_migration.py` | **4549** | **75** | **0** | **2** | **3** | **12** | **39** | **45** | `_import_opening_balances` |
| `api/chapter_dashboard_api.py` | **921** | **15** | 0 | 0 | 0 | 1 | 18 | 0 | `reprocess_mt940_import` (production only; debug in `chapter_dashboard_debug.py`) |
| `services/mollie_debug_service.py` | 3071 | 32 | 0 | 0 | 0 | **19** | ~~33~~ **20** | 0 | ~~`bulk_retrieve_all_member_payments`~~ `create_subscription` (was CC 33) |
| `verenigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` | **1980** | **56** | 0 | 0 | **1** | **8** | **23** | 1 | ~~`_update_member_fields`~~ `_finalize_import_results` |
| `setup/__init__.py` | 2903 | 69 | 0 | 0 | 0 | 3 | 17 | 0 | `update_workspace_links` |
| `utils/member_import_cleanup.py` | 2569 | 12 | 1 | 2 | 2 | 3 | **110** | 0 | `nuclear_cleanup_all_members` |
| `utils/account_creation_manager.py` | **2358** | **34** | **0** | **0** | **1** | **9** | **14** | 5 | `create_user_account` (was CC 45) |
| `e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py` | 2171 | 52 | 1 | 0 | 1 | 6 | 43 | 1 | `import_single_mutation` |
| `vereinigingen_payments/utils/payment_gateways.py` | 2167 | 57 | 0 | 1 | 0 | 4 | ~~34~~ 6 | 0 | `mollie_subscription_webhook` (was CC 34) |
| `api/member_management.py` | 2066 | 31 | 0 | 0 | ~~4~~ 0 | 6 | ~~30~~ 13 | 2 | `extract_transaction_data_improved` (was CC 30) |
| `permissions.py` | 2005 | 34 | 0 | 0 | ~~1~~ 0 | 14 | ~~22~~ 20 | 16 | `has_volunteer_permission` (was CC 22) |
| `mijnrood_sync/services/event_application_service.py` | 1987 | 46 | 0 | 0 | **0** | **8** | ~~21~~ **16** | 1 | ~~`_process_member_roles`~~ `_sync_division_to_chapter` (was CC 21) |
| `api/membership_application.py` | 1822 | 51 | 0 | 0 | ~~4~~ 0 | 1 | ~~29~~ 13 | 8 | `submit_application` (was CC 29) |
| `templates/pages/donate.py` | 1793 | 26 | 0 | 0 | 0 | 4 | 17 | 16 | `get_context` |
| `vereinigingen_payments/mollie/services/webhook_wrapper_service_unified.py` | 1754 | 22 | 0 | 0 | 1 | 8 | 26 | 0 | `_process_pending_refunds` |
| `utils/security/api_security_framework.py` | 1736 | 49 | 0 | 0 | 0 | 5 | 19 | 0 | `analyze_api_security_status` |
| `verenigingen/page/membership_analytics/membership_analytics.py` | 1733 | 35 | 0 | 0 | 0 | 1 | 12 | 0 | `get_current_year_revenue` |
| `e_boekhouden/utils/payment_processing/payment_entry_handler.py` | **1699** | **29** | **0** | **1** | **0** | **10** | **22** | 4 | `_extract_invoice_references_from_rows` (was `_process_payment_mutation_internal` CC 47) |

**Grade scale:** F=26+ (unmaintainable), E=21-25 (very high risk), D=16-20 (moderate risk), C=11-15 (slightly complex), B=6-10 (low risk), A=1-5 (simple)
**Tests column:** Number of test files found matching the source file name pattern.

---

## All Functions with CC >= 21 (E/F Grade) — Updated

| CC | Grade | Function | Status | File |
|---:|:-----:|----------|--------|------|
| 110 | F | `nuclear_cleanup_all_members` | Cleanup tooling, low priority | `utils/member_import_cleanup.py` |
| 53 | F | `validate_csv_members` | Template page | `templates/pages/mollie_bulk_payment_creation.py` |
| ~~50~~ 11 | ~~F~~ C | `approve_membership_application` | **Refactored** (was 50) | `api/membership_application_review.py` |
| 49 | F | `get_smart_account_type` | eBoekhouden util | `e_boekhouden/utils/eboekhouden_smart_account_typing.py` |
| 48 | F | `_classify_by_code_pattern` | eBoekhouden service | `e_boekhouden/services/account_classification_service.py` |
| 48 | F | `get_or_create_item_improved` | eBoekhouden util | `e_boekhouden/utils/eboekhouden_improved_item_naming.py` |
| ~~47~~ 9 | ~~F~~ A | `_process_payment_mutation_internal` | **Refactored** (was 47) | `e_boekhouden/utils/payment_processing/payment_entry_handler.py` |
| ~~47~~ | ~~F~~ | ~~`create_unreconciled_payment_entry`~~ | **Deleted** (zero callers) | ~~`utils/create_unreconciled_payment.py`~~ |
| ~~45~~ 14 | ~~F~~ C | `create_user_account` | **Refactored** (was 45) | `utils/account_creation_manager.py` |
| 44 | F | `auto_create_ledger_mapping` | eBoekhouden util | `e_boekhouden/utils/invoice_helpers.py` |
| 43 | F | `import_single_mutation` | eBoekhouden migration | `e_boekhouden/doctype/e_boekhouden_migration/e_boekhouden_migration.py` |
| 43 | F | `get_data` (members_without_chapter) | Report | `vereinigingen/report/members_without_chapter/` |
| ~~42~~ 14 | ~~F~~ C | `process_payment` (MolliePaymentOrchestrator) | **Refactored** (was 42) | `vereinigingen_payments/services/mollie_payment_orchestrator.py` |
| 42 | F | `parse_and_validate_csv` | Template page | `templates/pages/mollie_subscription_recreation.py` |
| 40 | E | `create_account` (AccountMigrationService) | eBoekhouden service | `e_boekhouden/services/account_migration_service.py` |
| ~~40~~ 15 | ~~E~~ C | `check_payments_for_customer` | **Refactored** (was 40) | `vereinigingen_payments/mollie/services/bulk_payment_checker.py` |
| 39 | E | `_import_opening_balances` | **Refactored** (was 52) | `e_boekhouden/utils/eboekhouden_rest_full_migration.py` |
| ~~39~~ | ~~E~~ | ~~`_update_member_fields`~~ | **Deleted** (dead code) | `vereinigingen/doctype/mijnrood_csv_import/` |
| 39 | E | `nuclear_truncate_member_tables` | Cleanup tooling | `utils/member_import_cleanup.py` |
| 39 | E | `get_data` (new_members) | Report | `vereinigingen/report/new_members/` |
| 39 | E | `check_transaction_status` | Balance transactions API | `vereinigingen_payments/api/balance_transaction_processing.py` |
| ~~39~~ 16 | ~~E~~ D | `_check_via_balance_transactions` | **Refactored** (was 39) | `vereinigingen_payments/mollie/services/bulk_payment_checker.py` |
| 38 | E | `cleanup_all_test_data` | Cleanup tooling | `utils/member_import_cleanup.py` |
| 38 | E | `robust_cleanup_all_imported_data` | Cleanup tooling | `utils/robust_cleanup_all_data.py` |
| 38 | E | `load_payment_history_batch_optimized` | Background jobs | `utils/background_jobs.py` |
| 38 | E | `get_data` (overdue_member_payments) | Report | `vereinigingen/report/overdue_member_payments/` |
| 37 | E | `_process_money_transfer` | Payment processor | `e_boekhouden/utils/processors/payment_processor.py` |
| 37 | E | `cleanup_orphaned_child_tables` | Cleanup util | `utils/orphaned_child_table_cleanup.py` |
| 37 | E | `get_erpnext_expense_data` | Report | `vereinigingen/report/chapter_expense_report/` |
| 36 | E | `_retrieve_global_payments_with_orphans` | Template page | `templates/pages/mollie_payment_processing.py` |
| 36 | E | `auto_calculate_derived_colors` | Brand settings | `vereinigingen/doctype/brand_settings/` |
| 36 | E | `cleanup_child_table_broken_links` | History util | `utils/history_manager_utils.py` |
| ~~35~~ 15 | ~~E~~ C | `incremental_update_history_tables` | **Refactored** (was 35) | `services/member/history/member_history_update_service.py` |
| 35 | E | `_create_bank_transaction_for_journal_entry` | Payment processor | `e_boekhouden/utils/processors/payment_processor.py` |
| 35 | E | `process_dues_payment` | **Payment processing** | `vereinigingen_payments/mollie/services/dues_payment_processor.py` |
| 35 | E | `find_party_by_iban_or_name` | MT940 util | `utils/mt940_import.py` |
| 35 | E | `get_data` (overdue, payments report) | Report | `vereinigingen_payments/report/overdue_member_payments/` |
| ~~34~~ 10 | ~~E~~ B | `_update_invoice_payment_history` | **Refactored** (was 34) | `services/member/history/member_history_update_service.py` |
| ~~34~~ 6 | ~~E~~ B | `mollie_subscription_webhook` | **Refactored** (was 34) | `vereinigingen_payments/utils/payment_gateways.py` |
| 34 | E | `get_pending_applications` | API | `api/membership_application_review.py` |
| 34 | E | `validate_row` (CSVDataValidator) | CSV util | `utils/csv/csv_data_validator.py` |
| 33 | E | `start_full_rest_import` | **Refactored** (was 33, unchanged) | `e_boekhouden/utils/eboekhouden_rest_full_migration.py` |
| ~~33~~ 13 | ~~E~~ C | `bulk_retrieve_all_member_payments` | **Refactored** (was 33) | `services/mollie_debug_service.py` |
| 33 | E | `get_data` (members_without_payment_info) | Report | `vereinigingen/report/members_without_payment_info/` |
| 33 | E | `get_summary` (chapter_expense) | Report | `vereinigingen/report/chapter_expense_report/` |
| 33 | E | `get_payment_processing_status` | Recovery util | `utils/payment_processing_recovery.py` |
| 32 | E | `admin_tools:execute_admin_tool` | Admin template | `templates/pages/admin_tools.py` |
| 32 | E | `extract_sepa_data_enhanced` | MT940 util | `utils/mt940_import.py` |
| 32 | E | `create_enhanced_bank_transaction_from_mt940` | MT940 util | `utils/mt940_import.py` |
| 32 | E | `complete_partial_payments` | Recovery util | `utils/payment_processing_recovery.py` |
| ~~31~~ 14 | ~~E~~ C | `create_scheduled_subscription` | **Refactored** (was 31) | `services/mollie_debug_service.py` |
| 31 | E | `upload_expense_receipt` | Volunteer template | `templates/pages/volunteer/expenses.py` |
| 31 | E | `get_processing_status` (Orchestrator) | Payment service | `vereinigingen_payments/services/mollie_payment_orchestrator.py` |
| 31 | E | `_process_single_transaction` | Balance processor | `vereinigingen_payments/services/balance_transaction_processor.py` |
| 31 | E | `execute` (v2_0 patch) | Migration patch | `patches/v2_0/migrate_membership_type_billing_to_dues_schedule.py` |
| 31 | E | `validate_role_profile_data_integrity` | Util | `utils/user_role_profile_calculator.py` |
| 31 | E | `bulk_delete_payment_entries` | Cleanup util | `utils/payment_entry_cleanup.py` |

---

## Prioritized Refactoring Candidates (Updated)

### Tier 1 — Critical (F-grade production code, untested, high LOC)

#### ~~1. `e_boekhouden/utils/eboekhouden_rest_full_migration.py` (4879 LOC)~~ COMPLETED

**Status:** Refactored in PR #20 (merged 2026-02-14). 7 F-grade → 0 F-grade, 45 unit tests added. See "Refactoring Completed" section above.

#### ~~2. `e_boekhouden/utils/payment_processing/payment_entry_handler.py` (1652 LOC)~~ COMPLETED

**Status:** Refactored in commit `d6bc0f2b` (2026-02-14). `_process_payment_mutation_internal` decomposed from CC 47 → 9. Also `create_unreconciled_payment.py` (CC 47, zero callers) deleted in `240962e3`. F-grade → 0, worst now E-grade (CC 22).

#### ~~3. `utils/account_creation_manager.py` (2370 LOC)~~ COMPLETED

**Status:** Decomposed `create_user_account` from CC 45 → 14 in commit `b7dd379e` (2026-02-15). Extracted 5 helpers: `_parse_name_components`, `_prepare_user_data`, `_bulk_import_flags`, `_insert_user_with_deadlock_retry`, `_handle_username_conflict`. Also fixed latent bug where deadlock retries during username conflict lost the username override. 36 existing tests pass unchanged.

#### ~~4. `api/membership_application_review.py`~~ COMPLETED (extraction + CC decomposition)

**Status:** Debug/admin/notification endpoints extracted in `54c5ae9c` (2026-02-15). Approval orchestration unified in `ad5582ad`. CC decomposition of `approve_membership_application` completed (2026-02-15): CC 50 → 11 (F → C). Extracted 7 helpers: `_handle_idempotent_approval`, `_prepare_approval_fields`, `_calculate_billing_amount`, `_activate_volunteer_if_requested`, `_create_user_account_safe`, `_send_approval_email_safe`, `_build_approval_response`. All helpers are A/B-grade. Pure code moves, no logic changes.

### Tier 2 — High Priority (production code, E/D-grade, mixed concerns)

#### ~~5. `vereinigingen_payments/utils/payment_gateways.py`~~ COMPLETED

**Status:** Decomposed `mollie_subscription_webhook` from CC 34 → 6 in commit `30386ce5` (2026-02-15). Extracted 3 helpers: `_authenticate_and_parse_subscription_payload` (C), `_find_member_for_subscription` (A), `_update_subscription_status` (A). Reuses existing `MollieWebhookParser` for event routing instead of duplicating its logic inline. Public API unchanged.

#### ~~6. `vereinigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` (2995 LOC)~~ COMPLETED

**Status:** Removed 19 dead methods (~1015 LOC) in commit `22c20825` (2026-02-15). Methods were superseded by extracted services (MemberImportService, AddressImportService, MollieSyncService, MembershipImportService). 2995 → 1980 LOC. 1 E-grade (`_update_member_fields` CC 39) + 2 D-grade eliminated. Remaining: `_finalize_import_results` (CC 23, D-grade). 23 tests pass.

#### ~~7. `vereinigingen_payments/services/mollie_payment_orchestrator.py`~~ COMPLETED

**Status:** Decomposed `process_payment` from CC 42 → 14 in commit `2f33e337` (2026-02-15). Extracted 5 helpers: `_validate_payment_preconditions` (B), `_determine_final_status` (B), `_determine_failed_step` (A), `_resolve_invoice` (A), `_resolve_invoice_fresh` (A). Also fixed `test_factory.py` using wrong `custom_` prefix for Member fields. Public API unchanged.

#### 8. `api/member_management.py` (2066 LOC)

| Metric | Value |
|--------|-------|
| D-grade functions | ~~4~~ **0** |
| Worst function | `extract_transaction_data_improved` — ~~CC 30~~ **CC 13**, 136 lines |
| Test files | **2** |

**Key issue: mixed concerns.** Debug functions mixed with production API endpoints.

**Status:** Decomposed 3 D-grade functions (2026-02-15). Extracted 6 helpers: `_parse_mt940_amount` (B/8), `_build_transaction_description` (B/10), `_sanitize_member_filters` (B/7), `_enrich_members_with_chapters` (B/7), `_resolve_mt940_bank_account` (B/9), `_process_mt940_statements` (B/10). Results: `extract_transaction_data_improved` CC 30→13, `get_members_with_chapter_info` CC 23→11, `import_mt940_improved` CC 23→7. No D-grade functions remain. Public API unchanged.

#### ~~9. `api/membership_application.py`~~ COMPLETED

**Status:** Decomposed remaining D/C-grade functions (2026-02-15). Quick Win #1 (commit `80cfdbd6`) already removed 2 test functions (CC 29, 25). This pass extracted `_create_pending_chapter_membership_safe` from `submit_application` (CC 16→13) and `_determine_chapter_for_member` from `fix_specific_member` (CC 13→B). No D-grade functions remain. Only `_match_chapter_region_heuristic` (CC 12, 21 lines) left as C-grade — too small to decompose.

### Tier 3 — Moderate Priority

| File | Max CC | Tests | Notes |
|------|-------:|------:|-------|
| ~~`permissions.py`~~ | ~~22~~ 20 | 16 | **DONE** — D-grade `has_volunteer_permission` (CC 22→20) already refactored |
| ~~`services/mollie_debug_service.py`~~ | ~~33~~ 20 | 0 | **DONE** — 5 E/D-grade functions decomposed (CC 33→13, 31→14, 27→11, 25→below C, 23→below C), 12 helpers extracted |
| ~~`mijnrood_sync/services/event_application_service.py`~~ | ~~21~~ C | 1 | **DONE** — `_process_member_roles` (CC 21→below C), extracted `_handle_admin_role_change` + `_handle_division_contact_change` |
| ~~`services/member/history/member_history_update_service.py`~~ | ~~35~~ 15 | 1 | **DONE** — 3 D/E-grade functions decomposed, 7 helpers extracted |
| ~~`vereinigingen_payments/mollie/services/bulk_payment_checker.py`~~ | ~~40~~ 16 | 0 | **DONE** — 2 E-grade functions decomposed, 7 helpers extracted |

### Tier 4 — Low Priority / Acceptable

| File | LOC | Max CC | Tests | Notes |
|------|----:|-------:|------:|-------|
| `setup/__init__.py` | 2903 | 17 | 0 | Setup code, runs once per deploy |
| `utils/member_import_cleanup.py` | 2569 | 110 | 0 | Cleanup tooling, not production |
| `templates/pages/donate.py` | 1793 | 17 | 16 | Well-tested, reasonable CC |
| `utils/security/api_security_framework.py` | 1736 | 19 | 0 | Infrastructure, stable |
| `verenigingen/page/membership_analytics/membership_analytics.py` | 1733 | 12 | 0 | Mostly SQL query builders |
| ~~`api/chapter_dashboard_api.py`~~ | ~~3174~~ **921** | 18 | 0 | **DONE** — Debug/admin functions extracted to `chapter_dashboard_debug.py` (2310 LOC) |

---

## Quick Wins (< 1 hour each)

1. ~~**Delete test functions from `api/membership_application.py`**~~ **DONE** (commit `80cfdbd6`, 2026-02-14) — Removed `test_status_field_integration` and `test_chapter_membership_workflow`. Saved 355 LOC.

2. ~~**Move debug functions from `api/member_management.py`**~~ **DONE** (commits `c46c096c` + `53198d51`, 2026-02-14) — Extracted 5 `debug_*` functions to `api/member_management_debug.py`.

3. ~~**Move debug functions from `api/chapter_dashboard_api.py`**~~ **DONE** (2026-02-15) — Removed 37 debug/admin/setup functions (already copied to `chapter_dashboard_debug.py`). 3174 → 921 LOC, 15 production endpoints remain.

---

## Previously Completed Refactorings

| Target | What was done | PR/Commit | Date |
|--------|--------------|-----------|------|
| `e_boekhouden/utils/eboekhouden_rest_full_migration.py` | Decomposed 7 F-grade functions, added 45 tests | [#20](https://github.com/nlvegan/verenigingen/pull/20) | 2026-02-14 |
| `templates/pages/donation_dashboard.py` | Extracted to `services/donation/dashboard_service.py` | `2bff88b1` | 2026-02-13 |
| `www/e_boekhouden_dashboard.py` | Extracted to `e_boekhouden/services/dashboard_service.py` | `2ed46a24` | 2026-02-13 |
| `templates/pages/membership_application.py` | Extracted to `services/member/application/membership_application_service.py` | `2ed46a24` | 2026-02-13 |
| `api/membership_application.py` | Quick Win #1: Removed 2 test functions (355 LOC) | `80cfdbd6` | 2026-02-14 |
| `api/member_management.py` | Quick Win #2: Extracted debug functions to `member_management_debug.py` | `c46c096c`, `53198d51` | 2026-02-14 |
| `api/chapter_dashboard_api.py` | Quick Win #3: Removed 37 debug/admin functions (3174→921 LOC); already in `chapter_dashboard_debug.py` | `2332b536` | 2026-02-15 |
| `e_boekhouden/utils/payment_processing/payment_entry_handler.py` | Tier 1 #2: Decomposed `_process_payment_mutation_internal` (CC 47→9) | `d6bc0f2b` | 2026-02-14 |
| `utils/create_unreconciled_payment.py` | Deleted dead code (CC 47, zero callers) | `240962e3` | 2026-02-14 |
| `api/membership_application_review.py` | Tier 1 #4: Extracted debug/admin/notification endpoints + unified approval orchestration | `54c5ae9c`, `ad5582ad` | 2026-02-15 |
| `utils/account_creation_manager.py` | Tier 1 #3: Decomposed `create_user_account` (CC 45→14), deduplicated deadlock retry, fixed username bug | `b7dd379e` | 2026-02-15 |
| `vereinigingen_payments/services/mollie_payment_orchestrator.py` | Tier 2 #7: Decomposed `process_payment` (CC 42→14), extracted 5 helpers, fixed test_factory.py field names | `2f33e337` | 2026-02-15 |
| `vereinigingen_payments/utils/payment_gateways.py` | Tier 2 #5: Decomposed `mollie_subscription_webhook` (CC 34→6), extracted 3 helpers, reused MollieWebhookParser | `30386ce5` | 2026-02-15 |
| `vereinigingen/doctype/mijnrood_csv_import/mijnrood_csv_import.py` | Tier 2 #6: Removed 19 dead methods (1015 LOC), eliminated E-grade `_update_member_fields` (CC 39) + 2 D-grade | `22c20825` | 2026-02-15 |
| `api/member_management.py` | Tier 2 #8: Decomposed 3 D-grade functions (CC 30→13, CC 23→11, CC 23→7), extracted 6 helpers | — | 2026-02-15 |
| `api/membership_application.py` | Tier 2 #9: Decomposed `submit_application` (CC 16→13) + `fix_specific_member` (CC 13→B), extracted 2 helpers | — | 2026-02-15 |
| `api/membership_application_review.py` | Tier 1 #4 CC decomposition: `approve_membership_application` (CC 50→11), extracted 7 helpers, all A/B-grade | — | 2026-02-15 |
| `permissions.py` | Tier 3: D-grade `has_volunteer_permission` (CC 22→20) already refactored in earlier pass | — | 2026-02-15 |
| `services/member/history/member_history_update_service.py` | Tier 3: Decomposed 3 E-grade functions (`refresh_fee_change_history` CC 29→15, `_update_dues_payment_history` CC 23→B, `_update_invoice_payment_history` CC 34→B). Extracted 7 helpers: 3 shared (`_remove_stale_history_rows`, `_row_needs_update`, `_update_or_add_history_row`), 1 dues-specific (`_build_dues_payment_row`), 1 invoice-specific (`_process_single_invoice`), 2 fee-specific (`_process_fee_amendments`, `_process_fee_schedule`) | — | 2026-02-15 |
| `vereinigingen_payments/mollie/services/bulk_payment_checker.py` | Tier 3: Decomposed 2 E-grade functions (`check_payments_for_customer` CC 40→15, `_check_via_balance_transactions` CC 39→16). Extracted 7 helpers: `_fetch_customer_with_rate_limit_retry`, `_check_for_matching_invoice`, `_build_payment_info`, `_filter_payment_by_date`, `_extract_payment_ids_from_transactions`, `_batch_check_already_processed`, `_classify_orphaned_payment` | — | 2026-02-15 |
| `services/mollie_debug_service.py` | Tier 3: Decomposed 5 E/D-grade functions. `bulk_retrieve_all_member_payments` CC 33→13, `create_scheduled_subscription` CC 31→14, `bulk_process_member_payments` CC 27→11, `sync_membership_end_dates_from_mollie` CC 25→below C, `create_mandate` CC 23→below C. Extracted 12 helpers. | — | 2026-02-15 |
| `mijnrood_sync/services/event_application_service.py` | Tier 3: `_process_member_roles` CC 21→below C. Extracted `_handle_admin_role_change` + `_handle_division_contact_change`. | — | 2026-02-15 |

---

## Methodology

- **Tool:** [radon](https://radon.readthedocs.io/) v6.0.1
- **Complexity:** `radon cc <file> -n C -s` (show functions with CC >= 11)
- **Function LOC:** `radon cc <file> -j` (JSON output includes `lineno` and `endline`)
- **Caller counts:** `grep -rn --include=*.py "<func_name>(" <base_dir>` excluding definitions and comments
- **Test coverage:** `find <base_dir> -path "*test*<pattern>*" -name "*.py"` matching source file names
- **Scope:** All `*.py` files in `vereinigingen/` excluding `tests/`, `__pycache__/`, `node_modules/`
- **Threshold:** Files with >1600 LOC
- **CC Grade Scale:** A(1-5) B(6-10) C(11-15) D(16-20) E(21-25) F(26+)

To reproduce:
```bash
# Install radon
/home/frappeuser/frappe-bench/env/bin/pip install radon

# Run on a specific file (show grade C and worse)
radon cc verenigingen/<path>.py -n C -s

# JSON output for scripting (includes line numbers and endlines)
radon cc verenigingen/<path>.py -j

# Average complexity per file
radon cc verenigingen/<path>.py -a -s

# Find all files over N lines
find verenigingen -name "*.py" -not -path "*/__pycache__/*" -not -path "*/tests/*" \
  -exec sh -c 'lines=$(wc -l < "$1"); [ "$lines" -gt 1600 ] && echo "$lines $1"' _ {} \; | sort -rn
```
