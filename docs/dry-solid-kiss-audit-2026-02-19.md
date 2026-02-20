# DRY/SOLID/KISS Comprehensive Audit — 2026-02-19

**Scope:** Entire Verenigingen app (~302,818 LOC, 2,243 Python files)
**Method:** 10 parallel audit agents covering all layers
**Last updated:** 2026-02-20 (Phases 1-2, 3 (continued), 4 (continued), 6 complete)

## Executive Summary

| Severity | Count | Fixed | Remaining |
|----------|-------|-------|-----------|
| Critical | 19 | 14 | 5 |
| High | 37 | 18 | 19 |
| Medium | 55+ | 12 | 43+ |
| Low | 30+ | 0 | 30+ |

**Additional fix not in original audit:** Reversed decorator order across 27 files (102 endpoints) — `@frappe.whitelist()` must be outermost or HTTP calls fail with "Method Not Allowed".

**Top 5 systemic issues (cross-cutting):**
1. ~~\~5,600 LOC of test/debug scripts committed as production API endpoints (32+ files)~~ **MITIGATED** — 14 test/debug files restricted to `@development_only_api`
2. 6 parallel SEPA mandate services (~4,141 LOC) doing the same thing
3. 3 competing member ID implementations across 3 directories
4. Inconsistent return types: `OperationResult` vs plain dicts split across ~180 files
5. ~120 LOC of identical singleton boilerplate repeated in 20+ services

---

## Critical Findings

### BUGS (Runtime Failures)

| # | File | Description | Status |
|---|------|-------------|--------|
| C1 | `membership.py:1274` | `NameError`: `membership_type` undefined in `revert_to_standard_amount` — will crash on unhappy path | **FIXED** `d4a5cf78` |
| C2 | `sepa_duplicate_prevention.py:930-943` | `NameError`: `oldest_keys` referenced outside its defining `if`-block + cache write outside mutex | **FIXED** `d4a5cf78` |
| C3 | `member_subscribers.py:171-408` | 8 bare `except Exception:` blocks reference unbound `e` — swallows real errors | **FIXED** `d4a5cf78` |
| C4 | `payment_gateways.py:631-634` | `NameError`: `member` undefined in `get_subscription_status` exception handler | **FIXED** `d4a5cf78` |
| C5 | `payment_gateways.py:785` | Missing f-string prefix: `"MAND-{donation.name}"` produces literal string | **FIXED** `d4a5cf78` |

### SECURITY

| # | File | Description | Status |
|---|------|-------------|--------|
| C6 | `member_import_cleanup.py:24-26` | Developer-mode safety guard disabled ("TEMPORARILY") — `nuclear_cleanup_all_members` callable in production | **DEFERRED** — still in staging testing |
| C7 | `volunteer.py:1073-1113` | SQL injection surface: `.format()` used for query structure in whitelisted endpoint | **FIXED** `d4a5cf78` |
| C8 | 32+ files in `api/` | Test/debug scripts as whitelisted API endpoints — ~347 endpoints in production, 32+ are test/debug | **MITIGATED** `f2d9f5ea` — 14 files restricted to `@development_only_api` |
| C9 | `migration_helper.py:61-86` | `test_event_system()` whitelisted endpoint fires fake events with hardcoded test data | **FIXED** `d4a5cf78` |

### DECORATOR ORDER (Discovered during fix, not in original audit)

| # | File(s) | Description | Status |
|---|---------|-------------|--------|
| NEW | 27 files, 102 endpoints | `@security_decorator` above `@frappe.whitelist()` — Frappe uses object identity (`fn in set`) so reversed order causes "Method Not Allowed" on all HTTP calls | **FIXED** `4a7e1a25` + `799de536` |

### ARCHITECTURAL (Data Integrity)

| # | File | Description | Agent |
|---|------|-------------|-------|
| C10 | `webhook_wrapper_service_unified.py` | Two incompatible financial entry architectures (BT+JE vs Payment Entry) in one class — corrupts trial balances | Payments | **FIXED** — orphaned PE method deleted; BT+JE is canonical |
| C11 | `dues_payment_processor.py:822-831` | Deprecated Payment Entry mode silently redirected to Bank Transaction — wrong accounting with no error | Payments | **FIXED** — upgraded from silent warning to `frappe.log_error()` |
| C12 | `eboekhouden_rest_full_migration.py:3796,3803` | Hardcoded database-specific primary key IDs for ledger accounts — silent wrong debit/credit on other instances | e-Boekhouden | **FIXED** — dead code deleted (~70 LOC); function `_should_debit_increase` was never called |
| C13 | `payment_entry_handler.py:347-376` | Monkey-patches ERPNext `PaymentEntry` class methods at runtime under threading lock — unsafe in multi-worker | e-Boekhouden | KEEP — well-engineered workaround for ERPNext float bug; no native alternative |
| C14 | `eboekhouden_rest_full_migration.py:3100-3102` | Creates 0.01 amount Payment Entry to bypass validation — fabricated accounting entry | e-Boekhouden | **FIXED** — dead code deleted (~92 LOC); function `_create_zero_amount_payment_entry` was never called |

### DRY (Duplicate Code with Divergence Risk)

| # | File(s) | Description | Agent |
|---|---------|-------------|-------|
| C15 | `membership_application.py:829` + `membership_application_review.py:523` | Duplicate `reject_membership_application` — different signatures, different logic, different return types | API | PARTIAL — legacy version marked DEPRECATED with warning log; canonical is `membership_application_review` |
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

| # | Pattern | Files | LOC Savings | Agent | Status |
|---|---------|-------|-------------|-------|--------|
| H1 | 3 member ID implementations | `core/member_id_service.py`, `identification/member_id_service.py`, `member_id_manager.py` | ~161 | Cross-cutting | PARTIAL — `generate_application_id()` duplicate consolidated; architecture is actually clean layered delegation (not competing) |
| H2 | `create_customer_for_member` diverges (one creates Contact, other doesn't) | `application_payments.py`, `customer_handling_service.py` | ~110 | Cross-cutting | |
| H3 | `get_member_for_customer` duplicated | `member_utils.py:542`, `financial_utils.py:172` | ~20 | Cross-cutting | **FIXED** — `financial_utils` delegates to `member_utils` |
| H4 | Deadlock retry logic in 7 places (not 3) | `account_creation_manager.py` (2x), `retry_utilities.py` (2x), `invoice_generator.py`, `payment_entry_handler.py`, `bank_transaction_creator.py` | ~60 | Utils | DEFERRED — implementations differ (raise vs return, some rollback) |
| H5 | Payment status determination logic diverges | `member_history_update_service.py:611`, `payment_history_service.py:444` | ~25 | Services/Member | **FIXED** — extracted `determine_payment_status()`, fixed bug (missing `outstanding_amount <= 0` check) |
| H6 | `_batch_fetch_with_chunking` in 3 places | `member_history_update_service.py`, `payment_history_service.py`, `payment_mixin.py` | ~50 | Services/Member + DocTypes | **FIXED** — extracted `batch_fetch_with_chunking()` to `utils/__init__.py` |
| H7 | `_emit_*_event` / `_get_*_subscribers` copied 5 times | All event emitter files | ~100 | Hooks/Events | PARTIAL — copy-paste bug in `chapter_events.py` **FIXED**; full refactor deferred |
| H8 | Bulk-mode guard logic copied 20+ times with inconsistent flag names | All event files | ~60 | Hooks/Events | DEFERRED — inconsistent flag names need design decision |
| H9 | ISO datetime parsing pattern in 8 files | Across payments layer | ~40 | Payments | |
| H10 | `type_names` dict defined 5 times in same file | `eboekhouden_rest_full_migration.py` | ~25 | e-Boekhouden | **FIXED** — extracted to `MUTATION_TYPE_SINGULAR` / `MUTATION_TYPE_PLURAL` constants |
| H11 | `_create_sales_invoice` / `_create_purchase_invoice` share 60 lines | `eboekhouden_rest_full_migration.py` | ~60 | e-Boekhouden | |
| H12 | Notes-field append pattern repeated 18 times | `termination_integration.py`, `application_helpers.py` | ~100 | Utils | **FIXED** — extracted `append_to_text_field()` utility, 18 patterns replaced |
| H13 | `_safe_int` duplicated in both MijnRood services | `event_application_service.py`, `polling_service.py` | ~8 | MijnRood | **FIXED** — extracted to `mijnrood_sync/utils.py` |
| H14 | Two near-identical batch workers | `event_application_service.py:2172-2276` | ~80 | MijnRood | **FIXED** — consolidated into `_batch_event_worker()` with `approve_first` parameter |
| H15 | JSON unpack guard repeated 9 times | `event_application_service.py` | ~30 | MijnRood | **FIXED** — extracted `safe_json_load()` to `mijnrood_sync/utils.py` |
| H16 | Error-handling boilerplate in 12 `_ensure_*` methods | `event_application_service.py` | ~60 | MijnRood | DEFERRED — methods vary too much (different log levels, branching); decorator would reduce clarity |
| H17 | Hardcoded role lists in 138+ locations across 40+ files | API + DocType + service layers | ~40 | API + DocTypes | DEFERRED — massive scope (138+ instances), needs Roles constants file |

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
| H24 | `membership_application_review.py:626-683` | N+1 query in `get_user_chapter_access` — 18+ queries per page load | API | **FIXED** — replaced N+1 with 3 flat queries |
| H25 | `membership.py:380-500` | `Membership Type` fetched 4 times per validate cycle | DocTypes | **FIXED** — cached in `_get_membership_type_doc()` per validate cycle |
| H26 | `mollie_payment_orchestrator.py` | `get_mollie_bank_account_config()` called 4 times without caching | Payments | **FIXED** — per-instance cache via `_get_bank_account_config()` eliminates 3 redundant validations |
| H27 | `sepa_admin_reporting.py:188-228` | Correlated subquery anti-pattern: 3,000 subqueries for 1,000 mandates | Payments | **FIXED** — replaced 3 correlated subqueries with 1 pre-aggregated LEFT JOIN (~50-100x speedup) |

### Dead Code

| # | File | Issue | Agent | Status |
|---|------|-------|-------|--------|
| H28 | `membership.py:749-817` | Dead `on_submit_legacy`/`on_cancel_legacy` methods | DocTypes | **FIXED** — deleted ~68 LOC |
| H29 | `membership_dues_schedule.py:287-299` | `validate_template_fields` is a no-op, never called | DocTypes | **FIXED** — deleted ~13 LOC |
| H30 | `member_history_update_service.py` | 3 deprecated methods returning hardcoded values, still called | Services/Member | **FIXED** — deleted methods, wrappers in member.py, dead tests (~200 LOC) |
| H31 | `payment_history_queue.py` | 461-line orphaned queue system, never called from hooks or scheduler | Hooks/Events | **FIXED** — deleted file + DocType + fixtures (~630 LOC) |
| H32 | `analytics_engine.py:1132-1395` | 15+ placeholder methods returning fabricated data | Utils | DEFERRED — dashboard depends on it; needs fake-data replacement |
| H33 | `background_jobs.py:856` | `queue_expense_event_processing_handler` dead `on_update_after_submit` branch | Hooks/Events | **FIXED** — dead branch removed |

### Inconsistency

| # | Pattern | Issue | Agent |
|---|---------|-------|-------|
| H34 | 3 competing singleton patterns | `global` keyword (10 files) vs new-instance-per-call (14 files) vs `__new__` (1 file) | Services/Member |
| H35 | Competing approval orchestrators | `member_lifecycle_service` vs `member_approval_service` vs `membership_application_review` API | Services/Member |
| H36 | `application_helpers.py` has inconsistent tier labels | `get_membership_type_fee_info` vs `get_membership_type_details` use different multipliers and names | Utils |
| H37 | `membership_application_review.py:769-810` | Commented-out security filter — chapter permission check collects data then ignores it (`pass`) | API | **FIXED** `f2d9f5ea` — dead code removed; `Verenigingen Staff` added to bypass roles in `chapter_security.py` (`4a7e1a25`) |

---

## Medium Priority Findings (Top 20 of 55+)

| # | Category | File/Pattern | Description |
|---|----------|--------------|-------------|
| M1 | DRY | `_send_*_notification` x4 identical | `member_subscribers.py:279-408` — **FIXED** (→ `_send_member_status_notification`) |
| M2 | DRY | `chapter_subscribers` — 3 identical role profile functions | Lines 363-393 — **FIXED** (→ `_sync_board_role_profile`) |
| M3 | DRY | `expense_events.py` — volunteer lookup x4 | Same file, 4 identical patterns — **FIXED** (→ `_resolve_volunteer_and_member`) |
| M4 | DRY | `mollie_debug_service` — result dict boilerplate x17 | Across all API methods |
| M5 | DRY | `mollie_debug_service` — limit sanitization x6 | Same logic, inconsistent caps |
| M6 | DRY | `mollie_debug_service` — optional attr serialization x25 | `getattr(obj, attr, None)` pattern |
| M7 | DRY | `_get_or_create_generic_customer/supplier` identical | `eboekhouden_rest_full_migration.py:908-1081` — **FIXED** (→ `_get_or_create_generic_party`) |
| M8 | DRY | Pagination loops x5 in `eboekhouden_api.py` | Same while-loop structure — **FIXED** (→ `_paginated_fetch()`) |
| M9 | SRP | `termination_integration.py` mixes 9 domains | 1,422 LOC with 9 concerns |
| M10 | SRP | `membership.py:76-238` `create_or_update_dues_schedule` | 163 lines, 5+ responsibilities |
| M11 | SRP | `membership_dues_schedule.py:44-66` validate() inconsistency | 12 validators, inconsistent template guards |
| M12 | KISS | `application_helpers.py:240-309` excessive debug logging | 7 debug log calls per JSON parse, PII risk — **FIXED** (removed PII-leaking logs) |
| M13 | KISS | Deprecated `approve_membership_application` uses `warnings.warn` | Never surfaces in HTTP context — **FIXED** (→ `frappe.logger().warning()`) |
| M14 | KISS | `membership.py:412-500` `set_renewal_date` | 68 lines, 4 nesting levels, self-defeating `self.renewal_date = None` — **FIXED** |
| M15 | KISS | `lifecycle.py:32-36` patches run on every migrate | FALSE POSITIVE — patches correctly reference `execute()` functions |
| M16 | KISS | `scheduler.py:122-126` 6-field cron expression | FALSE POSITIVE — croniter supports 6-field (seconds) format |
| M17 | OCP | `document_portal_service.py` org-type `if/elif` chain x3 | Adding org type requires 3 edits |
| M18 | OCP | `event_application_service.py` string-based dispatch | `getattr(self, f"_apply_{action}_{table_key}")` |
| M19 | Bug | `lifecycle_service.py:495` retry path sets `member.rejection_reason` (field doesn't exist) | Should be `review_notes` — **FIXED** |
| M20 | Bug | `eboekhouden_rest_full_migration.py:1123` hardcoded timestamp in production query | Returns zero results after date passes — **FIXED** (→ 90-day lookback) |

---

## Positive Observations

The audit agents consistently noted these strong patterns:

1. **Transaction handling** — FOR UPDATE locks, savepoints, and explicit commit/rollback documented in CLAUDE.md are correctly followed
2. **Chapter validators** — `ValidationResult.merge()` pattern is exemplary
3. **`BaseHistoryManager._with_doc()` callback protocol** — clean template method pattern
4. **Query optimization** — `PaymentHistoryService` reduced 81 queries to 3; `mt940_import` batch preloads
5. **Security decorators** — `@critical_api`, `@high_security_api`, `@development_only_api` consistently applied (NOTE: 102 had reversed order with `@frappe.whitelist()`, fixed 2026-02-20)
6. **`OperationResult` adoption** — well-typed in newer services (email, payment validation)
7. **Billing domain** — cleanly decomposed into focused single-responsibility services
8. **`TerminationExecutionService`** — correct transaction safety with savepoints and FOR UPDATE locks
9. **SSH auth abstraction** in MijnRood — clean, correctly shared
10. **Checksum-based polling** in MijnRood — efficient delta detection

---

## Prioritized Action Plan

### Phase 1: Fix Bugs (1-2 days) — DONE `d4a5cf78`
- ~~Fix 5 `NameError` bugs (C1-C5)~~ **DONE**
- ~~Fix unbound `e` in exception handlers (C3)~~ **DONE** (8 instances, not 5)
- ~~Restore developer-mode safety guard (C6)~~ **DEFERRED** — still in staging testing per user request
- ~~Fix f-string bugs in `cancel_je_1345.py`~~ **DONE** (2 missing f-prefixes)

### Phase 2: Security Hardening (2-3 days) — DONE `f2d9f5ea` + `4a7e1a25` + `799de536`
- ~~Move 32+ test/debug files out of API layer (C8, C9)~~ **DONE** — 14 files restricted to `@development_only_api`
- ~~Fix SQL injection surface in `volunteer.py` (C7)~~ **DONE** (Phase 1)
- ~~Remove commented-out security filter or document reasoning (H37)~~ **DONE** — dead code removed, `Verenigingen Staff` added to bypass roles
- ~~Fix reversed decorator order~~ **DONE** — 102 swaps across 27 files (discovered during review)

### Phase 3: Architectural Derisking (1-2 weeks) — PARTIAL (2026-02-20)
- ~~Resolve BT+JE vs Payment Entry conflict (C10)~~ **DONE** — orphaned PE method deleted
- ~~Upgrade silent PE redirect to error logging (C11)~~ **DONE** — `frappe.log_error()` replaces silent warning
- ~~Remove monkey-patching of PaymentEntry (C13)~~ **KEEP** — necessary for ERPNext float precision bug
- ~~Consolidate 3 member ID implementations to 1 (H1)~~ **PARTIAL** — duplicate `generate_application_id()` consolidated; architecture is clean layered delegation
- Consolidate 6 SEPA mandate services to 2 (H23) — DEFERRED (complex domain, needs separate session)
- Fix `create_customer_for_member` divergence (H2) — DEFERRED (needs design decision on Contact creation)

### Phase 4: DRY Consolidation — CONTINUED (2026-02-20, -92 -120 net LOC)
- ~~Dedupe `_safe_int` in MijnRood services (H13)~~ **DONE**
- ~~Dedupe `get_member_for_customer` (H3)~~ **DONE**
- ~~Extract `append_to_text_field` utility (H12)~~ **DONE** — 18 patterns replaced
- ~~Extract `safe_json_load` utility (H15)~~ **DONE** — 9 patterns replaced
- ~~Extract `type_names` constants (H10)~~ **DONE** — 5 inline dicts → 2 module constants
- ~~Extract `determine_payment_status` utility (H5)~~ **DONE** — fixed bug in payment_history_service (missing `outstanding_amount` check)
- ~~Extract `batch_fetch_with_chunking` utility (H6)~~ **DONE** — 3 implementations → 1 shared function
- ~~Consolidate batch workers (H14)~~ **DONE** — 2 near-identical workers → 1 parameterized function
- ~~Cache Membership Type in validate cycle (H25)~~ **DONE** — `_get_membership_type_doc()` eliminates 3 redundant DB fetches
- ~~Fix N+1 query in `get_user_chapter_access` (H24)~~ **DONE** — 3 flat queries replace nested loops
- ~~Consolidate `_get_or_create_generic_customer/supplier` (M7)~~ **DONE** — single `_get_or_create_generic_party`
- ~~Fix self-defeating `self.renewal_date = None` (M14)~~ **DONE** — dead conditions removed
- Extract shared event emitter base (H7, H8) — DEFERRED (copy-paste bug found, needs design)
- Consolidate deadlock retry logic (H4) — DEFERRED (7 implementations with different semantics)
- Extract hardcoded role constants (H17) — DEFERRED (138+ instances across 40+ files)
- Extract `_ensure_*` error decorator (H16) — DEFERRED (methods vary too much; ~40 LOC savings not worth clarity loss)
- Add `@singleton` decorator to base service (Pattern 9)
- Standardize return types (H34, Pattern 4)

### Phase 5: God Object Decomposition (2-3 weeks)
- Split `mollie_debug_service.py` into 5 focused services (C18)
- Complete `eboekhouden_rest_full_migration.py` processor extraction (C19)
- Split `event_application_service.py` into 6 handlers (H18)
- Split `payment_gateways.py` (H19)
- Decompose `application_helpers.py` (H20)

### ~~Phase 6: Dead Code Removal~~ **DONE** (2026-02-20, -1,123 LOC)
- ~~Delete dead legacy methods (H28-H33)~~ **DONE** (H28, H29, H30, H31, H33 deleted)
- Delete placeholder/stub methods in analytics (H32) — DEFERRED (dashboard dependency)
- ~~Remove orphaned payment history queue (H31)~~ **DONE**
- ~~Clean deprecated function wrappers~~ **DONE**

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

---

## Change Log

### 2026-02-20: Phases 1-2 Complete

**Commits:**
- `d4a5cf78` — Phase 1: Fix 5 NameErrors (C1-C5), 8 unbound exceptions (C3), SQL injection (C7), test endpoint guard (C9), f-string bugs
- `f2d9f5ea` — Phase 2: Restrict 14 test/debug API files to `@development_only_api` (C8), remove dead permission code (H37), fix broken import in `test_monitoring.py`
- `4a7e1a25` — Code review fixes: Restore `Verenigingen Staff` to bypass roles in `chapter_security.py` (H37 regression), fix decorator order in 2 files
- `799de536` — Fix reversed decorator order across 25 additional files (102 endpoints total)

**Key discovery:** `@frappe.whitelist()` MUST be the outermost decorator. Frappe checks whitelist status via object identity (`fn in set`). When a security decorator wraps the function first, the module-level name points to the wrapper — not in the whitelist set — causing silent "Method Not Allowed" on all HTTP API calls. This affected 102 endpoints across 27 files. Frappe has no native developer-mode API guard; `@development_only_api` is entirely custom.

**Deferred:** C6 (`member_import_cleanup.py` developer-mode guard) — still needed for staging testing.

### Phase 6: Dead Code Removal (2026-02-20)

**Impact:** -1,123 LOC across 16 files

| Item | What was removed | LOC removed |
|------|-----------------|-------------|
| H28 | `on_submit_legacy`/`on_cancel_legacy` from membership.py | ~68 |
| H29 | `validate_template_fields` from membership_dues_schedule.py | ~13 |
| H30 | 3 deprecated volunteer expense methods from service + member.py + dead tests | ~200 |
| H31 | `payment_history_queue.py` (461 LOC) + `PaymentHistoryUpdateQueue` DocType + fixture entries + broken import | ~630 |
| H33 | Dead `on_update_after_submit` branch from background_jobs.py | ~6 |

**Deferred:** H32 (`analytics_engine.py` placeholder methods) — dashboard depends on it; needs stub replacement, not deletion.

### Phase 4 (partial): DRY Consolidation (2026-02-20)

**Impact:** -92 net LOC across 7 files + 1 new utility file

| Item | What was done |
|------|--------------|
| H3 | `financial_utils.get_member_for_customer` now delegates to `member_utils` canonical version |
| H10 | 5 inline `type_names` dicts → 2 module-level constants (`MUTATION_TYPE_SINGULAR`, `MUTATION_TYPE_PLURAL`) |
| H12 | `append_to_text_field()` utility extracted, 18 copy-paste patterns replaced across `termination_integration.py` + `application_helpers.py` |
| H13 | `_safe_int` extracted to `mijnrood_sync/utils.py`, removed from both MijnRood service classes |
| H15 | `safe_json_load()` extracted to `mijnrood_sync/utils.py`, 9 inline guard patterns replaced |

**New utility files:**
- `verenigingen/mijnrood_sync/utils.py` — `safe_int()`, `safe_json_load()`
- `verenigingen/utils/__init__.py` — `append_to_text_field()` (alongside existing `safe_child_table_update`)

**Deferred items (explored, too complex for safe batch):**
- H4: Deadlock retry — 7 implementations (not 3), each with different error handling semantics
- H7/H8: Event emitter — copy-paste bug found in `chapter_events.py` (checks `bulk_member_operations` instead of `bulk_chapter_operations`)
- H17: Hardcoded roles — 138+ instances across 40+ files, needs architectural decision on Roles constants

### Phase 4 (continued): DRY Consolidation + Bug Fixes (2026-02-20)

**Impact:** ~-120 net LOC across 8 files

| Item | What was done |
|------|--------------|
| M19 | Fixed bug: `member.rejection_reason` → `member.review_notes` in `member_lifecycle_service.py` (field doesn't exist on Member DocType) |
| M20 | Fixed bug: hardcoded `'2025-08-05 06:00:00'` → `DATE_SUB(NOW(), INTERVAL 90 DAY)` in `eboekhouden_rest_full_migration.py` (date passed 197 days ago) |
| H5 | `determine_payment_status()` extracted to `utils/__init__.py`; fixed bug in `payment_history_service.py` (missing `outstanding_amount <= 0` check that the other implementation had) |
| H6 | `batch_fetch_with_chunking()` extracted to `utils/__init__.py`; removed from `member_history_update_service.py`, `payment_history_service.py`; `payment_mixin.py` and `member.py` now delegate to shared utility |
| H14 | `_batch_approve_and_apply_worker` and `_batch_apply_worker` consolidated into `_batch_event_worker()` with `approve_first` parameter |

**New utilities in `utils/__init__.py`:**
- `determine_payment_status(invoice, paid_amount)` — shared payment status determination
- `batch_fetch_with_chunking(doctype, name_list, fields, filters, chunk_size)` — chunked IN() queries

**Deferred:**
- H16: `_ensure_*` error boilerplate — methods vary too much (different log levels, some use `frappe.log_error`, complex branching); decorator would reduce clarity for ~40 LOC savings
- H9: ISO datetime parsing — 45 occurrences across 21 files, needs separate focused session
- H11: Invoice creation — only 63% identical with significant financial logic differences

### Phase 4 (batch 3): Performance + DRY + KISS (2026-02-20)

**Impact:** ~-50 net LOC, 4 redundant DB calls eliminated per Membership validate, N+1 query eliminated

| Item | What was done |
|------|--------------|
| H25 | `_get_membership_type_doc()` cache method added to Membership; 4 `frappe.get_doc("Membership Type", ...)` calls → 1 per validate cycle |
| H24 | N+1 query in `get_user_chapter_access()` replaced with 3 flat queries (volunteers → board members → roles); eliminates 18+ DB calls per page load |
| M7 | `_get_or_create_generic_customer/supplier` consolidated into single `_get_or_create_generic_party(party_type, ...)` with thin wrappers |
| M14 | Self-defeating `self.renewal_date = None` removed; dead `not self.renewal_date` condition simplified in 2 places |

### Phase 4 (batch 4): KISS + DRY cleanup (2026-02-20)

**Impact:** ~-90 net LOC

| Item | What was done |
|------|--------------|
| M8 | 5 identical pagination while-loops in `eboekhouden_api.py` consolidated into `_paginated_fetch(endpoint, params, safety_limit)` |
| M12 | Removed 7 PII-leaking debug log calls from `parse_application_data()` in `application_helpers.py`; kept structural validation only |
| M13 | Replaced `warnings.warn()` with `frappe.logger().warning()` in deprecated `approve_membership_application` shim — `warnings.warn` never surfaces in HTTP context |
| M15 | Investigated and closed as FALSE POSITIVE — lifecycle.py correctly references patch `execute()` functions |

### Phase 3 (partial): Architectural Derisking (2026-02-20)

**Impact:** ~-32 LOC dead code + architectural clarity

| Item | What was done |
|------|--------------|
| C10 | Deleted orphaned `_create_unified_payment_entry()` (32 LOC) from `webhook_wrapper_service_unified.py` — BT+JE is the canonical architecture, PE-only was never called |
| C11 | Upgraded silent `frappe.logger().warning()` to `frappe.log_error()` in `dues_payment_processor.py` — deprecated PE mode fallback now creates Error Log entry for operator visibility |
| C13 | Investigated and closed as KEEP — thread-safe monkey-patch of `PaymentEntry.set_total_allocated_amount()` and `set_unallocated_amount()` is a well-engineered workaround for ERPNext floating-point precision bug; no Frappe-native alternative exists |
| H1 | Duplicate `generate_application_id()` in `application_helpers.py` now delegates to canonical implementation in `services/member/core/member_id_service.py`; architecture is actually clean layered delegation (not competing) |

**Deferred:**
- H2: `create_customer_for_member` divergence — utility version creates Contact record, service version doesn't; needs design decision on Contact creation requirement
- H23: SEPA mandate consolidation — 9 files, complex domain; `SEPAMandateRepository` still imported by `performance_measurement.py`

### Phase 4+3 (batch 5): Dead code + Performance + Deprecation (2026-02-20)

**Impact:** ~-162 LOC dead code + major query performance fix

| Item | What was done |
|------|--------------|
| C12 | Deleted dead `_should_debit_increase()` (~70 LOC) from `eboekhouden_rest_full_migration.py` — function with hardcoded instance-specific IDs was never called |
| C14 | Deleted dead `_create_zero_amount_payment_entry()` (~92 LOC) from `eboekhouden_rest_full_migration.py` — fabricated 0.01 PE hack was never called; `_create_import_log_entry()` is the correct fallback |
| C15 | Added DEPRECATED warning log to legacy `reject_membership_application` in `membership_application.py` — canonical version is in `membership_application_review.py` |
| H26 | Added per-instance cache `_get_bank_account_config()` in `MolliePaymentOrchestrator` — eliminates 3 redundant `validate_all_mollie_accounts()` calls per payment |
| H27 | Replaced 3 correlated subqueries with 1 pre-aggregated LEFT JOIN in `sepa_admin_reporting.py` — reduces ~3,001 queries to 1 for mandate lifecycle report (~50-100x speedup) |
| M16 | Investigated and closed as FALSE POSITIVE — Frappe's croniter supports 6-field (seconds) cron expressions |
