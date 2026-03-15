# Design: Test Suite Phase 5 — Coverage Gap Remediation

**Date:** 2026-03-11
**Audit reference:** `docs/audits/test-suite-audit-2026-03-03.md` (Sections 6, 7)
**Scope:** Add tests for ~71 untested DocTypes and services (HIGH + MEDIUM priority)
**Risk:** Low — adding new test files only, no production code changes
**Approach:** Domain batches (A), mixed test style (real DB for DocTypes, targeted mocks for external APIs)

## Problem

After Phases 1-3 cleaned up -72,197 LOC of dead/duplicate/disorganized tests, significant coverage gaps remain:

- **DocType coverage:** 41/130 (31%) — 89 DocTypes untested
- **Service coverage:** 96/158 (60%) — 62 services untested

After filtering out trivial child tables (pass-only, <13 LOC), the actionable scope is:

- **23 DocTypes** worth testing (20 standalone + 3 child tables with real logic)
- **~48 services** worth testing (47 real services + 1 dead code to delete)

## Scope Exclusions

**Trivial child tables (skip — no business logic):**
- direct_debit_batch_invoice, payment_plan_installment, member_payment_history (pass only)
- ponto_bank_account_mapping, e_boekhouden_cost_center_mapping (pass only)
- e_boekhouden_group_type_mapping, e_boekhouden_ledger_mapping (pass only)
- membership_tier, membership_type_history_entry, member_fee_change_history (pass only)
- chapter_membership_history (pass only)
- All 4 volunteer child tables: activity_tag, development_goal, interest_area, skill_category (pass only)

**Dead code (delete instead of test):**
- `billing_debug_utilities.py` (382 LOC) — all functions `@development_only_api`, zero production callers

**Trivial hooks (skip):**
- `chapter_role_profile_hooks.py` (40 LOC)
- `volunteer_role_profile_hooks.py` (33 LOC)

## Test Conventions

Based on analysis of existing exemplary tests:

| Aspect | DocType Tests | Service Tests (internal) | Service Tests (external API) |
|--------|--------------|-------------------------|------------------------------|
| Base class | `EnhancedTestCase` | `EnhancedTestCase` | `unittest.TestCase` |
| Test data | Factory (`create_test_member()`) + inline | Service instantiation + factory | Pure mocks |
| Mocking | None (real DB) | Minimal (mock only cross-service calls) | Full isolation (`@patch`) |
| Cleanup | Automatic (EnhancedTestCase) | Automatic | Manual `.stop()` |
| IDs | Deterministic timestamp | Via factory | N/A |

**Test file placement:** In the domain subdirectory matching the target (e.g., `tests/payment/`, `tests/chapter/`).

**Naming:** `test_<doctype_or_service_name>.py`

**Minimum per target:**
- 1 test for basic creation/validation (DocTypes)
- 1 test per public method with >5 LOC (services)
- Edge case tests for financial logic, error recovery, and validation

## Domain Batches

### Batch 1: Payment/Banking DocTypes + Services

**DocTypes (14 standalone):**

| DocType | Controller LOC | Key Logic |
|---------|---------------|-----------|
| direct_debit_batch | 585 | SEPA XML generation, batch processing |
| payment_plan | 484 | Installment generation, frequency calc |
| ponto_settings | 750 | OAuth2 tokens, webhook setup |
| ponto_payment_link | 524 | Payment linking |
| ponto_payment_request | 326 | Request handling |
| ponto_sync_log | 188 | Sync logging |
| ing_checkout_mandate | 187 | ING mandate handling |
| ing_checkout_transaction | 190 | Transaction tracking |
| ing_checkout_settings | 116 | Gateway config |
| donation_campaign | 408 | Date/goal validation, accounting |
| mollie_audit_log | 124 | Audit trail |
| mollie_reconciliation_log | 31 | Reconciliation validation |
| sepa_batch_upload_log | 97 | Upload tracking |
| sepa_return_file_log | 21 | File processing |

**Child tables with logic (2):**

| DocType | Controller LOC | Key Logic |
|---------|---------------|-----------|
| payment_history | 56 | Payment ID uniqueness, status validation |
| member_sepa_mandate_link | 34 | Mandate validation |

**Services (2):**

| Service | LOC | Description |
|---------|-----|-------------|
| mollie_reconciliation_service.py | 295 | Payment reconciliation |
| mollie_webhook_service.py | 272 | Webhook URL management |

**Test style:** Real DB for DocTypes. Mocked Mollie/Ponto/ING API calls.
**Test file:** `tests/payment/test_payment_doctype_coverage.py` (or split per DocType if large)
**Estimated new tests:** ~45

### Batch 2: E-Boekhouden DocTypes

**DocTypes (7 standalone):**

| DocType | Controller LOC | Key Logic |
|---------|---------------|-----------|
| e_boekhouden_migration | 2,141 | Migration orchestration, background jobs |
| e_boekhouden_settings | 1,125 | OAuth2, classification rules, group mappings |
| e_boekhouden_dashboard | 459 | Dashboard calculations |
| e_boekhouden_account_mapping | 194 | Account mapping |
| e_boekhouden_item_mapping | 175 | Item mapping |
| e_boekhouden_payment_mapping | 97 | Payment mapping |
| e_boekhouden_import_log | 38 | Import logging |

**Test style:** Unit tests with mocked SOAP API. Real DB for mapping DocTypes.
**Test file:** `tests/e_boekhouden/test_eboekhouden_doctype_coverage.py`
**Estimated new tests:** ~35

### Batch 3: Chapter Services

**Services (12):**

| Service | LOC | Description |
|---------|-----|-------------|
| chapter_assignment_service.py | 365 | Admin chapter member assignment |
| chapter_board_service.py | 204 | Board member data operations |
| chapter_event_service.py | 236 | Change detection, event emission |
| chapter_matching_service.py | 299 | Chapter matching logic |
| chapter_provisioning_service.py | 142 | Chapter provisioning |
| chapter_query_service.py | 141 | Chapter queries |
| chapter_reference_manager.py | 126 | Reference management |
| chapter_security.py | 180 | Chapter security checks |
| chapter_validation_service.py | 158 | Validation and auto-fix |
| department_sync_service.py | 157 | Department synchronization |
| optimized_chapter_lookup.py | 281 | Optimized lookup queries |

**DocTypes (1 child table with logic):**

| DocType | Controller LOC | Key Logic |
|---------|---------------|-----------|
| chapter_board_member | 244 | after_insert/on_trash hooks, role assignment |

**Test style:** Real DB (EnhancedTestCase). Create chapters + members, test service methods.
**Test file:** `tests/chapter/test_chapter_service_coverage.py`
**Estimated new tests:** ~40

### Batch 4: Volunteer Services

**Services (10):**

| Service | LOC | Description |
|---------|-----|-------------|
| expense_submission_service.py | 823 | Expense claim creation/submission |
| bulk_volunteer_creation_service.py | 488 | Bulk volunteer creation |
| expense_history_batch_processor.py | 317 | Batch expense history processing |
| expense_approver_service.py | 291 | Expense approver management |
| expense_handlers.py | 273 | Expense claim state handlers |
| native_expense_helpers.py | 268 | Native expense processing |
| expense_history_entry_builder.py | 141 | History entry construction |
| volunteer_activation_service.py | 126 | Volunteer activation on approval |
| department_approver_sync.py | 118 | Approver sync |

**Test style:** Real DB (EnhancedTestCase). Create volunteers + expense claims.
**Test file:** `tests/volunteer/test_volunteer_service_coverage.py`
**Estimated new tests:** ~30

### Batch 5: Billing Services

**Services (10, excluding dead billing_debug_utilities.py):**

| Service | LOC | Description |
|---------|-----|-------------|
| dues_schedule_auto_creator.py | 1,095 | Auto-create missing dues schedules |
| invoice_management.py | 1,046 | Bulk invoice generation, cleanup |
| dues_schedule_validation_service.py | 616 | Financial validation |
| dues_schedule_creation_service.py | 565 | Reliable schedule creation |
| invoice_matcher.py | 461 | Payment-to-invoice matching |
| invoice_error_handler_service.py | 434 | Error recovery, retry |
| template_creation_service.py | 352 | Template-based schedule creation |
| coverage_overlap_detector.py | 310 | Overlapping period detection |
| fee_change_tracking_service.py | 198 | Fee change detection |
| sales_invoice_account_handler.py | 125 | Receivable account hook |

**Test style:** Real DB (EnhancedTestCase). Financial assertions need exact decimal matching.
**Test file:** `tests/payment/test_billing_service_coverage.py` (billing tests go in payment/)
**Estimated new tests:** ~35

### Batch 6: Member Services

**Services (11):**

| Service | LOC | Description |
|---------|-----|-------------|
| payment_history_service.py | 746 | Payment history tracking |
| membership_creation_service.py | 728 | Membership creation on approval |
| membership_application_service.py | 572 | Application business logic |
| chapter_management_service.py | 518 | Chapter-related member ops |
| fee_change_recording_service.py | 314 | Fee change deduplication |
| member_role_service.py | 292 | User role management |
| member_address_display_service.py | 267 | Address display formatting |
| membership_duration_service.py | 222 | Duration calculations |
| member_fee_validation_service.py | 215 | Fee amount validation |
| member_donor_integration_service.py | 215 | Donor integration |
| member_item_service.py | 152 | Member item operations |

**DocTypes (3 standalone):**

| DocType | Controller LOC | Key Logic |
|---------|---------------|-----------|
| member_contact_request | 360 | Contact request handling |
| membership_analytics_snapshot | 377 | Analytics calculations |
| membership_goal | 273 | Goal tracking |

**Test style:** Real DB (EnhancedTestCase). Use factory `create_test_member()`.
**Test file:** `tests/member/test_member_service_coverage.py`
**Estimated new tests:** ~40

### Batch 7: Other (Termination, Donation, Team, Account)

**Services (5):**

| Service | LOC | Description |
|---------|-----|-------------|
| termination_execution_service.py | 511 | Termination with idempotency |
| team_service.py | 343 | Team management |
| termination_audit_service.py | 287 | Termination audit tracking |
| dashboard_service.py | 255 | Donation dashboard |
| document_portal_service.py | 1,379 | Document upload portal |

**Test style:** Real DB. Termination services need transaction isolation testing.
**Test file:** Split across `tests/member/`, `tests/donor/` as appropriate.
**Estimated new tests:** ~20

## Cleanup Action

**Delete dead code (Batch 0):**
- `verenigingen/services/billing/billing_debug_utilities.py` (382 LOC) — all `@development_only_api`, zero callers

## Estimated Totals

| Metric | Value |
|--------|-------|
| New test files | ~10-15 |
| New test methods | ~245 |
| DocTypes gaining coverage | +23 (31% → 49%) |
| Services gaining coverage | +48 (60% → 91%) |
| Dead code deleted | -382 LOC |

## Migration Approach

- One commit per batch (7 commits + 1 cleanup)
- Each batch: write tests → verify they pass → commit
- Subagent-driven execution (parallel where independent)
- No backward-compat concerns (new files only)

## Not In Scope

- Converting existing mock-heavy tests to real DB (Phase 4 from audit)
- Testing trivial child tables (13 files, all pass-only)
- JavaScript/frontend test coverage gaps
- Performance test flakiness fixes
