# DRY/SOLID/KISS Comprehensive Audit — 2026-02-19

**Scope:** Entire Verenigingen app (~302,818 LOC, 2,243 Python files)
**Method:** 10 parallel audit agents covering all layers

## Executive Summary

| Severity | Count | Est. Hours |
|----------|-------|------------|
| Critical | 19 | 35-45h |
| High | 37 | 60-80h |
| Medium | 55+ | 40-60h |
| Low | 30+ | 15-20h |

**Top 5 systemic issues (cross-cutting):**
1. ~5,600 LOC of test/debug scripts committed as production API endpoints (32+ files)
2. 6 parallel SEPA mandate services (~4,141 LOC) doing the same thing
3. 3 competing member ID implementations across 3 directories
4. Inconsistent return types: `OperationResult` vs plain dicts split across ~180 files
5. ~120 LOC of identical singleton boilerplate repeated in 20+ services

---

## Critical Findings

### BUGS (Runtime Failures)

| # | File | Description | Agent |
|---|------|-------------|-------|
| C1 | `membership.py:1274` | `NameError`: `membership_type` undefined in `revert_to_standard_amount` — will crash on unhappy path | DocTypes |
| C2 | `sepa_duplicate_prevention.py:930-943` | `NameError`: `oldest_keys` referenced outside its defining `if`-block + cache write outside mutex | API |
| C3 | `member_subscribers.py:171-408` | 5 bare `except Exception:` blocks reference unbound `e` — swallows real errors | Hooks/Events |
| C4 | `payment_gateways.py:631-634` | `NameError`: `member` undefined in `get_subscription_status` exception handler | Payments |
| C5 | `payment_gateways.py:785` | Missing f-string prefix: `"MAND-{donation.name}"` produces literal string | Payments |

### SECURITY

| # | File | Description | Agent |
|---|------|-------------|-------|
| C6 | `member_import_cleanup.py:24-26` | Developer-mode safety guard disabled ("TEMPORARILY") — `nuclear_cleanup_all_members` callable in production | Utils |
| C7 | `volunteer.py:1073-1113` | SQL injection surface: `.format()` used for query structure in whitelisted endpoint | DocTypes |
| C8 | 32+ files in `api/` | Test/debug scripts as whitelisted API endpoints — ~347 endpoints in production, 32+ are test/debug | API |
| C9 | `migration_helper.py:61-86` | `test_event_system()` whitelisted endpoint fires fake events with hardcoded test data | Hooks/Events |

### ARCHITECTURAL (Data Integrity)

| # | File | Description | Agent |
|---|------|-------------|-------|
| C10 | `webhook_wrapper_service_unified.py` | Two incompatible financial entry architectures (BT+JE vs Payment Entry) in one class — corrupts trial balances | Payments |
| C11 | `dues_payment_processor.py:822-831` | Deprecated Payment Entry mode silently redirected to Bank Transaction — wrong accounting with no error | Payments |
| C12 | `eboekhouden_rest_full_migration.py:3796,3803` | Hardcoded database-specific primary key IDs for ledger accounts — silent wrong debit/credit on other instances | e-Boekhouden |
| C13 | `payment_entry_handler.py:347-376` | Monkey-patches ERPNext `PaymentEntry` class methods at runtime under threading lock — unsafe in multi-worker | e-Boekhouden |
| C14 | `eboekhouden_rest_full_migration.py:3100-3102` | Creates 0.01 amount Payment Entry to bypass validation — fabricated accounting entry | e-Boekhouden |

### DRY (Duplicate Code with Divergence Risk)

| # | File(s) | Description | Agent |
|---|---------|-------------|-------|
| C15 | `membership_application.py:829` + `membership_application_review.py:523` | Duplicate `reject_membership_application` — different signatures, different logic, different return types | API |
| C16 | `mollie_debug_service.py:1492-1834` | `create_subscription` / `create_scheduled_subscription` near-duplicate — financial logic | Top-level Services |
| C17 | `eboekhouden_rest_full_migration.py:1377-1814` | `_import_opening_balances` / `_import_opening_balances_from_data` — 250 lines near-identical | e-Boekhouden |

### GOD OBJECTS

| # | File | LOC | Methods | Description | Agent |
|---|------|-----|---------|-------------|-------|
| C18 | `mollie_debug_service.py` | 3,088 | 41 | 7 responsibilities including production financial writes in a "debug" service | Top-level Services |
| C19 | `eboekhouden_rest_full_migration.py` | 4,549 | 75 | 17 responsibilities — incomplete processor extraction | e-Boekhouden |

---

## High Priority Findings

### DRY Violations

| # | Pattern | Files | LOC Savings | Agent |
|---|---------|-------|-------------|-------|
| H1 | 3 member ID implementations | `core/member_id_service.py`, `identification/member_id_service.py`, `member_id_manager.py` | ~161 | Cross-cutting |
| H2 | `create_customer_for_member` diverges (one creates Contact, other doesn't) | `application_payments.py`, `customer_handling_service.py` | ~110 | Cross-cutting |
| H3 | `get_member_for_customer` duplicated | `member_utils.py:542`, `financial_utils.py:172` | ~20 | Cross-cutting |
| H4 | Deadlock retry logic in 3 places | `account_creation_manager.py` (2x), `retry_utilities.py` | ~60 | Utils |
| H5 | Payment status determination logic diverges | `member_history_update_service.py:611`, `payment_history_service.py:444` | ~25 | Services/Member |
| H6 | `_batch_fetch_with_chunking` in 3 places | `member_history_update_service.py`, `payment_history_service.py`, `payment_mixin.py` | ~50 | Services/Member + DocTypes |
| H7 | `_emit_*_event` / `_get_*_subscribers` copied 5 times | All event emitter files | ~100 | Hooks/Events |
| H8 | Bulk-mode guard logic copied 15+ times with inconsistent flag names | All event files | ~60 | Hooks/Events |
| H9 | ISO datetime parsing pattern in 8 files | Across payments layer | ~40 | Payments |
| H10 | `type_names` dict defined 5 times in same file | `eboekhouden_rest_full_migration.py` | ~25 | e-Boekhouden |
| H11 | `_create_sales_invoice` / `_create_purchase_invoice` share 60 lines | `eboekhouden_rest_full_migration.py` | ~60 | e-Boekhouden |
| H12 | Notes-field append pattern repeated 16 times | `termination_integration.py`, `application_helpers.py` | ~30 | Utils |
| H13 | `_safe_int` duplicated in both MijnRood services | `event_application_service.py`, `polling_service.py` | ~8 | MijnRood |
| H14 | Two near-identical batch workers | `event_application_service.py:2172-2276` | ~80 | MijnRood |
| H15 | JSON unpack guard repeated 6 times | `event_application_service.py` | ~30 | MijnRood |
| H16 | Error-handling boilerplate in 12 `_ensure_*` methods | `event_application_service.py` | ~60 | MijnRood |
| H17 | Hardcoded role lists in 8+ locations across 6 files | API + DocType + service layers | ~40 | API + DocTypes |

### SRP Violations

| # | File | LOC | Issue | Agent |
|---|------|-----|-------|-------|
| H18 | `event_application_service.py` | 2,276 | God class: 45 methods, 6 distinct responsibilities | MijnRood |
| H19 | `payment_gateways.py` | 2,177 | 8 responsibilities: gateway abstraction + subscription activation + webhook routing + API endpoints | Payments |
| H20 | `application_helpers.py` | 1,573 | Utils bag: 6 unrelated concerns | Utils |
| H21 | `account_creation_manager.py` | 2,356 | Duplicated pipeline linking between `_link_records_phase` and `link_records` | Utils |
| H22 | `document_portal_service.py` | 1,381 | 4 concerns: authorization + file validation + storage + queries | Top-level Services |
| H23 | SEPA mandate domain split across 6 classes | 6 files, ~4,141 LOC total | At least 4 separate `get_active_mandate` implementations | Payments |

### Performance

| # | File | Issue | Agent |
|---|------|-------|-------|
| H24 | `membership_application_review.py:626-683` | N+1 query in `get_user_chapter_access` — 18+ queries per page load | API |
| H25 | `membership.py:380-500` | `Membership Type` fetched 4 times per validate cycle | DocTypes |
| H26 | `mollie_payment_orchestrator.py` | `get_mollie_bank_account_config()` called 4 times without caching | Payments |
| H27 | `sepa_admin_reporting.py:188-228` | Correlated subquery anti-pattern: 3,000 subqueries for 1,000 mandates | Payments |

### Dead Code

| # | File | Issue | Agent |
|---|------|-------|-------|
| H28 | `membership.py:749-817` | Dead `on_submit_legacy`/`on_cancel_legacy` methods | DocTypes |
| H29 | `membership_dues_schedule.py:287-299` | `validate_template_fields` is a no-op, never called | DocTypes |
| H30 | `member_history_update_service.py` | 3 deprecated methods returning hardcoded values, still called | Services/Member |
| H31 | `payment_history_queue.py` | 461-line orphaned queue system, never called from hooks or scheduler | Hooks/Events |
| H32 | `analytics_engine.py:1132-1395` | 15+ placeholder methods returning fabricated data | Utils |
| H33 | `background_jobs.py:856` | `queue_expense_event_processing_handler` calls defunct manager | Hooks/Events |

### Inconsistency

| # | Pattern | Issue | Agent |
|---|---------|-------|-------|
| H34 | 3 competing singleton patterns | `global` keyword (10 files) vs new-instance-per-call (14 files) vs `__new__` (1 file) | Services/Member |
| H35 | Competing approval orchestrators | `member_lifecycle_service` vs `member_approval_service` vs `membership_application_review` API | Services/Member |
| H36 | `application_helpers.py` has inconsistent tier labels | `get_membership_type_fee_info` vs `get_membership_type_details` use different multipliers and names | Utils |
| H37 | `membership_application_review.py:769-810` | Commented-out security filter — chapter permission check collects data then ignores it (`pass`) | API |

---

## Medium Priority Findings (Top 20 of 55+)

| # | Category | File/Pattern | Description |
|---|----------|--------------|-------------|
| M1 | DRY | `_send_*_notification` x4 identical | `member_subscribers.py:279-408` |
| M2 | DRY | `chapter_subscribers` — 3 identical role profile functions | Lines 363-393 |
| M3 | DRY | `expense_events.py` — volunteer lookup x4 | Same file, 4 identical patterns |
| M4 | DRY | `mollie_debug_service` — result dict boilerplate x17 | Across all API methods |
| M5 | DRY | `mollie_debug_service` — limit sanitization x6 | Same logic, inconsistent caps |
| M6 | DRY | `mollie_debug_service` — optional attr serialization x25 | `getattr(obj, attr, None)` pattern |
| M7 | DRY | `_get_or_create_generic_customer/supplier` identical | `eboekhouden_rest_full_migration.py:908-1081` |
| M8 | DRY | Pagination loops x4 in `eboekhouden_api.py` | Same while-loop structure |
| M9 | SRP | `termination_integration.py` mixes 9 domains | 1,422 LOC with 9 concerns |
| M10 | SRP | `membership.py:76-238` `create_or_update_dues_schedule` | 163 lines, 5+ responsibilities |
| M11 | SRP | `membership_dues_schedule.py:44-66` validate() inconsistency | 12 validators, inconsistent template guards |
| M12 | KISS | `application_helpers.py:240-309` excessive debug logging | 7 debug log calls per JSON parse, PII risk |
| M13 | KISS | Deprecated `approve_membership_application` uses `warnings.warn` | Never surfaces in HTTP context |
| M14 | KISS | `membership.py:412-500` `set_renewal_date` | 68 lines, 4 nesting levels, self-defeating `self.renewal_date = None` |
| M15 | KISS | `lifecycle.py:32-36` patches run on every migrate | Should be in `patches.txt` |
| M16 | KISS | `scheduler.py:122-126` 6-field cron expression | Possibly unsupported by Frappe |
| M17 | OCP | `document_portal_service.py` org-type `if/elif` chain x3 | Adding org type requires 3 edits |
| M18 | OCP | `event_application_service.py` string-based dispatch | `getattr(self, f"_apply_{action}_{table_key}")` |
| M19 | Bug | `lifecycle_service.py:495` retry path sets `member.rejection_reason` (field doesn't exist) | Should be `review_notes` |
| M20 | Bug | `eboekhouden_rest_full_migration.py:1090` hardcoded timestamp in production query | Returns zero results after date passes |

---

## Positive Observations

The audit agents consistently noted these strong patterns:

1. **Transaction handling** — FOR UPDATE locks, savepoints, and explicit commit/rollback documented in CLAUDE.md are correctly followed
2. **Chapter validators** — `ValidationResult.merge()` pattern is exemplary
3. **`BaseHistoryManager._with_doc()` callback protocol** — clean template method pattern
4. **Query optimization** — `PaymentHistoryService` reduced 81 queries to 3; `mt940_import` batch preloads
5. **Security decorators** — `@critical_api`, `@high_security_api`, `@development_only_api` consistently applied
6. **`OperationResult` adoption** — well-typed in newer services (email, payment validation)
7. **Billing domain** — cleanly decomposed into focused single-responsibility services
8. **`TerminationExecutionService`** — correct transaction safety with savepoints and FOR UPDATE locks
9. **SSH auth abstraction** in MijnRood — clean, correctly shared
10. **Checksum-based polling** in MijnRood — efficient delta detection

---

## Prioritized Action Plan

### Phase 1: Fix Bugs (1-2 days)
- Fix 5 `NameError` bugs (C1-C5)
- Fix unbound `e` in exception handlers (C3)
- Restore developer-mode safety guard (C6)
- Fix f-string bugs in `cancel_je_1345.py`

### Phase 2: Security Hardening (2-3 days)
- Move 32+ test/debug files out of API layer (C8, C9)
- Fix SQL injection surface in `volunteer.py` (C7)
- Remove commented-out security filter or document reasoning (H37)

### Phase 3: Architectural Derisking (1-2 weeks)
- Resolve BT+JE vs Payment Entry conflict (C10)
- Remove monkey-patching of PaymentEntry (C13)
- Consolidate 6 SEPA mandate services to 2 (H23)
- Consolidate 3 member ID implementations to 1 (H1)
- Fix `create_customer_for_member` divergence (H2)

### Phase 4: DRY Consolidation (1-2 weeks)
- Extract shared event emitter base (H7, H8)
- Consolidate deadlock retry logic (H4)
- Extract hardcoded role constants (H17)
- Consolidate payment status determination (H5)
- Add `@singleton` decorator to base service (Pattern 9)
- Standardize return types (H34, Pattern 4)

### Phase 5: God Object Decomposition (2-3 weeks)
- Split `mollie_debug_service.py` into 5 focused services (C18)
- Complete `eboekhouden_rest_full_migration.py` processor extraction (C19)
- Split `event_application_service.py` into 6 handlers (H18)
- Split `payment_gateways.py` (H19)
- Decompose `application_helpers.py` (H20)

### Phase 6: Dead Code Removal (1 week)
- Delete dead legacy methods (H28-H33)
- Delete placeholder/stub methods in analytics (H32)
- Remove orphaned payment history queue (H31)
- Clean deprecated function wrappers

---

## Metrics by Audit Area

| Area | Files | LOC | Critical | High | Medium | Low |
|------|-------|-----|----------|------|--------|-----|
| API Layer | 88 | ~36,700 | 4 | 7 | 5 | 3 |
| Services/Member | 56 | ~15,100 | 2 | 5 | 7 | 4 |
| Utils | 253 | ~14,000 | 2 | 4 | 5 | 2 |
| DocType Controllers | ~30 | ~7,600 | 2 | 6 | 7 | 4 |
| Payments Layer | ~40 | ~15,000 | 3 | 7 | 10 | 5 |
| e-Boekhouden | ~100 | ~42,000 | 4 | 8 | 8 | 5 |
| MijnRood Sync | ~20 | ~4,750 | 0 | 5 | 11 | 6 |
| Hooks/Events/Tasks | ~30 | ~5,500 | 2 | 4 | 9 | 4 |
| Top-level Services | ~25 | ~6,500 | 2 | 5 | 5 | 3 |
| Cross-cutting | all | 302,818 | 0 | 4 | 4 | 3 |
