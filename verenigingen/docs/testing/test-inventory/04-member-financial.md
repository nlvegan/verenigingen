# Domain A4 — Member Financial / Fee-Change / Dues / History — Test Inventory

Read-only classification of every `def test_*` method across 13 files under
`verenigingen/tests/services/`. Each method assigned one primary type
(HAPPY / UNHAPPY / EDGE / OTHER) by dominant intent from name, docstring, and
assertion body.

## Per-file breakdown

| File | Total | Happy | Unhappy | Edge | Other |
|------|-------|-------|---------|------|-------|
| test_member_fee_change_history_service.py | 10 | 1 | 0 | 7 | 2 |
| test_member_fee_change_history_service_realdb.py | 10 | 2 | 0 | 8 | 0 |
| test_member_fee_change_service.py | 7 | 2 | 1 | 4 | 0 |
| test_member_financial_services_realdb.py | 27 | 7 | 1 | 18 | 1 |
| test_member_history_update_service_realdb.py | 16 | 8 | 1 | 6 | 1 |
| test_payment_history_service_realdb.py | 11 | 6 | 0 | 5 | 0 |
| test_dues_schedule_lifecycle_service.py | 18 | 7 | 3 | 5 | 3 |
| test_dues_schedule_permission_service.py | 14 | 8 | 4 | 0 | 2 |
| test_progressive_dues_service.py | 18 | 7 | 3 | 6 | 2 |
| test_billing_date_service.py | 18 | 8 | 0 | 8 | 2 |
| test_load_template_for_membership_type.py | 8 | 3 | 3 | 1 | 1 |
| test_member_chapter_display_service.py | 7 | 1 | 1 | 5 | 0 |
| test_member_donor_integration_service.py | 9 | 4 | 1 | 3 | 1 |
| **DOMAIN TOTALS** | **173** | **64** | **18** | **76** | **15** |

## Per-file classification notes

### test_member_fee_change_history_service.py (mock-based, FrappeTestCase)
- HAPPY: validate_billing_frequency_valid_values.
- EDGE: invalid_value, none, empty_string, add_uses_validation_helper (invalid→Custom normalization), dedup (duplicate schedule updates), 50_entry_limit (boundary), update_calls_add_if_not_found (fallback branch).
- OTHER: valid_billing_frequencies_constant + class_constant_immutable — both assert the class constant equals a literal / is a 6-item list; tautological, no behavior exercised.

### test_member_fee_change_history_service_realdb.py (EnhancedTestCase)
- HAPPY: add_appends_new_entry, update_found_persists_via_secure_operation.
- EDGE: updates_existing_for_same_schedule, invalid_billing_normalized, matches_by_amendment_request, update_when_history_empty, update_not_found_adds, update_found_default_reason_when_missing, add_truncates_to_50, add_default_reason_from_schedule_name (all dedup/default/boundary branches).

### test_member_fee_change_service.py (mock-based)
- HAPPY: change_detection_creates_pending_change, record_fee_change_uses_history_manager (delegation).
- UNHAPPY: exception_handling_notifies_user (exception → msgprint).
- EDGE: csv_import_skips, system_update_skips, new_document_skips, no_change_when_values_equal (guard/no-op branches).

### test_member_financial_services_realdb.py (EnhancedTestCase, 5 classes)
- HAPPY (7): record_creates_entry, no_skip_for_clean_member, custom_override_takes_precedence, display_fee_current_when_no_amendment, get_or_create_membership_item, default_item_group_resolves, validate_amount_accepts_positive.
- UNHAPPY (1): validate_amount_rejects_negative (ValidationError).
- OTHER (1): dedup_window_constant (asserts constant == 60).
- EDGE (18): the record() skip/merge/dup filters, all should_skip_processing flag guards, process_pending false-without-attr, handle_after_save skip, no_membership none-source, item idempotent, ignores_zero, reason skip/early, permissions skip system/unchanged.

### test_member_history_update_service_realdb.py (EnhancedTestCase, 2 classes)
- HAPPY (8): prefetch_collects_reconciled, update_invoice_adds_row, update_dues_adds_unreconciled, incremental_update_returns_ok, row_needs_update_detects_diff, resolve_payment_entry_picks_most_recent, build_dues_payment_row, refresh_builds_entry.
- UNHAPPY (1): refresh_unknown_member_returns_fail (OperationResult fail, HIST_006).
- EDGE (6): prefetch_no_customer, update_invoice_no_customer_zero, incremental_no_invoices, resolve_empty_refs, remove_stale_history_rows, refresh_no_schedules.
- OTHER (1): service_singleton_and_name (asserts service_name string).

### test_payment_history_service_realdb.py (EnhancedTestCase, 2 classes)
- HAPPY (6): load_unpaid_builds_row, load_paid_builds_reconciled, membership_invoice_transaction_type, unreconciled_payment_standalone_row, refresh_financial_history_returns_stats, build_payment_history_entry.
- EDGE (5): load_no_customer_skips, load_no_invoices_zero, refresh_cleans_broken_invoice_row, coverage_falls_back_to_invoice_cache, coverage_returns_none_when_nothing.

### test_dues_schedule_lifecycle_service.py (EnhancedTestCase, mock schedules)
- HAPPY (7): pause_active, pause_test, resume_paused, resume_with_new_date, validate_allowed_transition, cancel_active, cancel_paused.
- UNHAPPY (3): pause_invalid_status, resume_invalid_status, validate_disallowed_transition (all InvalidStatusTransitionError).
- EDGE (5): pause_without_reason, validate_new_document, validate_no_previous_state, validate_same_status, cancel_already_cancelled (idempotent).
- OTHER (3): service_initialization, get_lifecycle_service_returns_instance, allowed_transitions_defined (config-dict tautology).

### test_dues_schedule_permission_service.py (EnhancedTestCase, real users/roles)
- HAPPY (8): result_allowed, sysmgr_has_access, admin_has_access, sysmgr_document_access, template_visible_to_authenticated, member_can_access_own_schedule, new_schedule_allowed, allowed_field_changes.
- UNHAPPY (4): result_denied (denial representation), template_edit_requires_admin (staff denied), other_user_cannot_access, disallowed_field_changes.
- OTHER (2): service_initialization, get_permission_service_returns_instance.
- No EDGE tests in this file.

### test_progressive_dues_service.py (EnhancedTestCase, mock schedules)
- HAPPY (7): calculate_at_reference, midpoint, custom_base_dues, rounding, description below_average / around_average / above_average.
- UNHAPPY (3): validate_requires_reference_income, validate_requires_lower_threshold, validate_threshold_less_than_reference (ValidationError).
- EDGE (6): at_lower_threshold (0% boundary), below_lower_threshold (floored), above_reference (>100% boundary), invalid_configuration (ref<=threshold fallback), validate_skips_non_progressive, description_below_threshold.
- OTHER (2): service_initialization, get_service_returns_instance.

### test_billing_date_service.py (EnhancedTestCase, mostly mock schedules)
- HAPPY (8): next_date monthly/quarterly/annual, with_from_date, set_billing_day_from_member_since, update_with_actual_date, updates_member_next_invoice_date, daily_uses_coverage_end.
- EDGE (8): uses_today_when_no_date, defaults_1_without_member_since, defaults_1_for_templates, preserves_existing_value, replaces_zero, without_actual_date (fallback), no_recursive_cycle (regression guard, save-count==1), skips_terminated_member.
- OTHER (2): service_initialization, get_service_returns_instance.

### test_load_template_for_membership_type.py (EnhancedTestCase)
- HAPPY (3): returns_template_from_doc, returns_template_from_string, required_false_still_returns_when_present.
- UNHAPPY (3): required_true_throws_when_no_template, required_true_throws_from_string, nonexistent_membership_type_throws (DoesNotExistError).
- EDGE (1): required_false_returns_none_when_no_template.
- OTHER (1): template_has_expected_fields — asserts `hasattr(doc, field)` for defined Frappe fields (always True); weak/tautological.

### test_member_chapter_display_service.py (mock-based, XSS focus)
- HAPPY (1): safe_content_rendered_correctly.
- UNHAPPY (1): error_handling (exception → graceful error message).
- EDGE (5): xss_protection in chapter_name / region / join_date, no_chapters_display (empty state), multiple_chapters_mixed_content (all malicious/empty/mixed data).

### test_member_donor_integration_service.py (EnhancedTestCase, real docs)
- HAPPY (4): create_donor_happy_path, dutch_landline_formatting, links_customer, copies_address.
- UNHAPPY (1): missing_member_returns_error (DoesNotExist caught → error dict).
- EDGE (3): no_phone_leaves_empty, already_prefixed_keeps_country_code (no double-prefix), duplicate_returns_existing (success=False rejection).
- OTHER (1): factory_returns_service.

## Observations

- **Edge-heavy domain (76/173 = 44%).** Coverage strongly favors branch/guard/boundary
  paths: skip-processing flags, dedup/merge filters, empty-history, boundary incomes,
  and date defaults dominate. This is largely healthy for financial mutation code.
- **Unhappy path is thin (18/173 = 10%) and unevenly distributed.** It clusters in
  validation-style files (permission service 4, progressive validation 3, lifecycle
  transitions 3, load_template 3). Several core money-path files have **zero UNHAPPY
  tests**: fee_change_history (both mock + realdb), payment_history_service_realdb,
  billing_date_service. Error/rollback behavior of the real-DB record/refresh paths is
  under-tested for failure (only refresh_unknown_member covers a fail result).
- **Real-DB vs mock split is deliberate and documented.** `*_realdb.py` files use
  `EnhancedTestCase` and assert persisted child-table state (fee_change_history,
  payment_history) against real Sales Invoices/Payment Entries; the non-realdb siblings
  (`test_member_fee_change_history_service.py`, `test_member_fee_change_service.py`,
  `test_member_chapter_display_service.py`) are mock-based `FrappeTestCase` unit tests.
  The realdb files explicitly state they exist to cover the load/persist path the mock
  suites skip.
- **15 OTHER tests are mostly low-value scaffolding.** Recurring pattern: per-service
  `test_service_initialization` + `test_get_*_returns_instance` (init/singleton smoke)
  appear in lifecycle, permission, progressive, billing_date files. Also tautological
  constant asserts (`VALID_BILLING_FREQUENCIES`, `class_constant_immutable`,
  `dedup_window_constant`, `allowed_transitions_defined`) and a `hasattr`-only field
  check (`template_has_expected_fields`) that passes trivially on any Frappe doc.
- **Base classes:** 10/13 files use `verenigingen ... EnhancedTestCase` (factory-based,
  real DB). 3 files (`test_member_fee_change_history_service.py`,
  `test_member_fee_change_service.py`, `test_member_chapter_display_service.py`) use
  `frappe.tests.utils.FrappeTestCase` with unittest.mock — pure-unit by design. Note
  `test_load_template_for_membership_type.py` imports both FrappeTestCase and
  EnhancedTestCase but the test class inherits EnhancedTestCase (the FrappeTestCase
  import is unused/dead).
- **Gap — no concurrency/idempotency tests on the real record() dedup window.**
  Dedup is asserted via sequential calls + `frappe.db.commit()`, but the documented
  60-second window and merge-persist regression are only checked single-threaded; no
  test exercises concurrent writes or the FOR-UPDATE/lock semantics referenced in the
  service layer.

No files were missing; all 13 assigned files exist and were classified.
