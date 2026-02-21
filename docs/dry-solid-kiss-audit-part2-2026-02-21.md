# DRY/SOLID/KISS Audit Part 2 — Areas Not Covered by Original Audit

**Date:** 2026-02-21
**Scope:** 11 codebase areas not covered by the 2026-02-19 audit
**Method:** 11 parallel audit agents

## Executive Summary

| Severity | Count | Area with Most Issues |
|----------|-------|-----------------------|
| Critical | 28 | Reports (SQL injection), Patches (missing refs), Overrides (monkey-patches) |
| High | 47 | Tests (massive duplication), Scheduler (no idempotency), CSS (color chaos) |
| Medium | 68+ | Templates (XSS), Scripts (dead validators), Hooks (dead references) |
| Low | 45+ | DocType schemas, naming, accessibility |

**Top 5 systemic issues (cross-cutting):**
1. **760 test files with 6 competing factories** and 30+ duplicate test suites (~9,800 LOC in factories alone)
2. **6 SQL injection risks in reports** — string formatting instead of parameterized queries
3. **2 critical monkey-patches** with no version guards — will break on Frappe/ERPNext upgrades
4. **54 scheduled tasks with no idempotency** and 100 `frappe.enqueue` calls with no error handling
5. **98 dead validator files** (2.5 MB) in scripts/validation/archived/ and 42 pre-commit hooks causing 3-4 min commit times

---

## Area 1: Frontend JavaScript Client Scripts

**Files analyzed:** 90+ JS files | **God objects:** 3 (member.js 4,104 LOC, chapter.js 1,833 LOC, dd_batch_management_enhanced.js 1,576 LOC)

### Critical

| # | File | Description |
|---|------|-------------|
| JS-C1 | `member.js:62-85` | Global helpers (unwrapOperationResult, escapeHtml) redefined inline instead of imported from operation-result-helpers.js — duplicated in chapter.js, customer_member_link.js |
| JS-C2 | `donation_form.js:413-462` | Switch statement with 4 near-identical code blocks for SEPA/Bank/Mollie/Cash — duplicates HTML template generation |
| JS-C3 | `dd_batch_management_enhanced.js` | God object: 1,576 LOC combining dashboard, wizard, filtering, conflict resolution, security analysis |
| JS-C4 | `membership_application.js:200-240` | 6 typeof checks for undefined services follow identical pattern — should be factory |

### High

| # | File | Description |
|---|------|-------------|
| JS-H1 | `member.js (4,104 LOC)` | Handles member lifecycle, payments, SEPA, chapters, volunteers, termination — should split into domain modules |
| JS-H2 | `chapter.js (1,833 LOC)` | Manages chapters, boards, members, regions, publication — monolithic |
| JS-H3 | `chapter_email_integration.js:59-150` | Email dialog configuration identical across all_members/board/volunteers methods |
| JS-H4 | `volunteer.js:80-143` | refresh() method 60+ LOC with 7+ custom buttons — should delegate |
| JS-H5 | Multiple files | Business logic hardcoded in JS (donation 5000 limit, expense date range) — should be server-side settings |

### Security

| # | File | Description |
|---|------|-------------|
| JS-S1 | `donation_form.js:583-615` | Form data in global window.formData without sanitization; innerHTML without escaping |
| JS-S2 | `dd_batch_management_enhanced.js` | IBAN masking logic client-side only; banking data exposed via dev tools |
| JS-S3 | `member.js:133-154` | Permission checks client-side only; validation must happen server-side |

---

## Area 2: Test File Quality

**Files analyzed:** 760 test files | **Factory files:** 6 (959-5,304 LOC each) | **Total factory LOC:** ~9,800

### Critical

| # | Pattern | Files | Description |
|---|---------|-------|-------------|
| T-C1 | 6 competing test factories | test_data_factory, enhanced_test_factory, secure_test_data_factory, sepa_mandate_test_factory, ponto_test_data_factory, payment_history_test_factory | create_member(), create_chapter(), create_test_membership() defined independently in 3+ factories. ~40% overlap. No shared interface. |
| T-C2 | 30+ duplicate test suites | test_payment_processing_api*.py (5 variants: _optimized, _real, _minimal, _integration) | Same 25+ test methods copied across files. ~400-800 LOC duplication per variant. |
| T-C3 | 12+ member_lifecycle variants | test_member_lifecycle.py, _complete, _basic, _workflows, _mock_elimination, _comprehensive | Same lifecycle workflows tested in backend/workflows/, backend/components/, root /tests/, and unit/ directories |
| T-C4 | 30+ SEPA test files with overlap | 30+ files matching test_sepa*.py in 6+ directories | Same mandate creation, batch processing, and security tests split without consolidation |

### High

| # | Pattern | Files | Description |
|---|---------|-------|-------------|
| T-H1 | 5+ create_test_iban() implementations | 5 factory files | Identical IBAN generation logic (checksum, bank code) independently implemented |
| T-H2 | @patch('frappe.sendmail') x16 | 16 test files | Same email mocking pattern repeated verbatim — no helper decorator |
| T-H3 | setUp() creating identical fixtures | 50+ test classes | self.test_member = self.create_test_member() + self.test_membership = ... pattern repeated |
| T-H4 | Tautological mock tests | 12+ methods | Tests verify mock.assert_called() — not business logic, just that mock was invoked |

---

## Area 3: DocType JSON Schemas

**Files analyzed:** 131 DocType JSONs | **Oversized DocTypes:** 10 (>50 fields)

### High

| # | DocType(s) | Description |
|---|-----------|-------------|
| DT-H1 | Member (122 fields), Verenigingen Settings (100 fields) | Exceeds single responsibility — Member should split into core + payment + history |
| DT-H2 | Status field in 57+ DocTypes | Inconsistent options: Active/Inactive vs Pending/Active/Rejected vs Draft/Active/Paused/Completed |
| DT-H3 | Membership Dues Schedule (60 fields), Donation (55 fields) | Couple template + instance logic + billing + error recovery |
| DT-H4 | fetch_from duplication | member.full_name fetched in 4+ places (Membership, Dues Schedule, etc.) |

### Medium

| # | DocType(s) | Description |
|---|-----------|-------------|
| DT-M1 | Chapter, Team, Chapter Board Member | Identical role profile configuration pattern repeated without extraction |
| DT-M2 | Member, Donation, Donor | Mollie integration fields duplicated with inconsistent naming (mollie_customer_id etc.) |
| DT-M3 | 3 payment history DocTypes | Near-identical payment logging with different naming (payment_status vs status) |
| DT-M4 | 120/130 child tables | Duplicate permission blocks (System Manager + Admin + Staff repeated) |

---

## Area 4: Web Templates & Portal

**Files analyzed:** 50+ HTML templates | **innerHTML usages:** 60+ | **Inline styles:** 69 HTML files

### Critical (XSS)

| # | File | Description |
|---|------|-------------|
| WT-C1 | `apply_for_membership.html:1515` | innerHTML with user-generated skill data without escaping |
| WT-C2 | `mollie_bulk_payment_creation.html:613,769` | innerHTML with API response data (customer IDs, descriptions) — no sanitization |
| WT-C3 | `mt940_import.html:787,990,1064` | innerHTML of error messages and user input directly — stored XSS risk |
| WT-C4 | `admin_tools.html:1378,1402` | Admin tool results rendered via innerHTML without permission checks or output encoding |

### High

| # | Pattern | Description |
|---|---------|-------------|
| WT-H1 | Alert CSS in 15+ templates | .alert.alert-success/danger/info defined identically — should be in base_portal.html |
| WT-H2 | "No member record" banner x6 | Error UI duplicated in 6+ portal pages |
| WT-H3 | 50+ untranslated strings | 'Processing...', 'Checking...', 'Refresh' not wrapped in _() |
| WT-H4 | frappe.utils.escape_html() used once | Only in personal_details.html:702 — 60+ innerHTML calls unprotected |

---

## Area 5: Custom Reports

**Reports analyzed:** 28 | **SQL injection risks:** 6

### Critical (SQL Injection)

| # | Report | Description |
|---|--------|-------------|
| R-C1 | `anbi_periodic_agreements.py:96,190` | f-string date filter: `f"pda.end_date <= '{future_date}'"` |
| R-C2 | `chapter_members.py:103-130` | Dynamic WHERE clause with string formatting |
| R-C3 | `members_without_active_memberships.py:138` | String concatenation in WHERE for status filter |
| R-C4 | `pending_membership_applications.py:93-104` | Multiple f-string date filters in SQL |
| R-C5 | `volunteer_interest_analysis.py:91-108` | WHERE clause built with string concatenation |

### High

| # | Report | Description |
|---|--------|-------------|
| R-H1 | `account_creation_status.py` (652 LOC) | get_summary_data() is 275 LOC with 6 queries — god method |
| R-H2 | Chart generation in 8+ reports | Identical grouping/transformation pattern duplicated |
| R-H3 | Column definitions in 8+ reports | Identical currency/date/link columns repeated |
| R-H4 | `anbi_expense_report.py:151-189` | N+1 query: separate query per account in loop |

---

## Area 6: Patches & Migrations

**Patches analyzed:** 34 | **Missing from patches.txt:** 5 | **SQL injection risks:** 2

### Critical

| # | File | Description |
|---|------|-------------|
| P-C1 | patches.txt (5 entries) | 5 patches referenced but files don't exist: migrate_contribution_amendment_request, cleanup_workspaces, fix_onboarding_visibility, add_national_board_member_role, rename_amount_to_dues_rate — **will cause migration failures** |
| P-C2 | `remove_membership_legacy_fields.py:57` | SQL injection: f-string for column names in ALTER TABLE DROP COLUMN |
| P-C3 | `add_volunteer_assignment_query_indexes.py` | SQL injection: f-string for table/index names |
| P-C4 | `migrate_financial_settings_to_payments.py:58-74` | No idempotency guard — partial migration on crash leaves inconsistent state |

### High

| # | File | Description |
|---|------|-------------|
| P-H1 | 5 index creation patches (1,123 LOC total) | 90% copy-pasted code — should extract create_indexes_helper() |
| P-H2 | `migrate_membership_type_billing_to_dues_schedule.py:156-193` | Loop with db.set_value() but single commit at end — partial failure risk |
| P-H3 | `cleanup_duplicate_dues_schedule_templates.py:87-106` | Deletes duplicates without audit trail — no recovery path |
| P-H4 | v1_0 + v2_1 settings migrations | Nearly identical SQL patterns copy-pasted — need generic migrate_singleton_fields() |

---

## Area 7: Hooks, Fixtures & Workflows

**Hooks analyzed:** hooks.py + e_boekhouden/hooks.py | **Fixture files:** 8

### Critical

| # | File | Description |
|---|------|-------------|
| HK-C1 | `e_boekhouden/hooks.py:20-21,26,28` | 4 functions referenced but don't exist: daily_sync_check, cleanup_old_logs, validate_account_mapping, sync_invoice_to_eboekhouden — **silent scheduler/doc_event failures** |
| HK-C2 | `critical_operation_rule.json` (43,401 lines) | 2,596 rules with 243 duplicate operation_name entries — 1.6 MB fixture file, maintenance nightmare |
| HK-C3 | `hooks/assets.py:21,30` | operation-result-helpers.js included in BOTH app_include_js and web_include_js — loaded twice |

### High

| # | File | Description |
|---|------|-------------|
| HK-H1 | `e_boekhouden/hooks.py:38` | Uses "dt" key instead of standard "doctype" — inconsistent with main hooks |
| HK-H2 | `hooks/lifecycle.py:27` + `hooks/__init__.py:72-78` | Workflow action handlers reference "Membership Termination Workflow" but workflow setup is DISABLED |
| HK-H3 | `module_profile.json:18-19` | Duplicate module blocking: "E Boekhouden" AND "E-Boekhouden" (different capitalization) |

---

## Area 8: Scripts & Tooling

**Pre-commit hooks:** 42 | **Archived validators:** 98 files (2.5 MB) | **Commit time:** 3-4 minutes

### Critical

| # | File | Description |
|---|------|-------------|
| SC-C1 | `scripts/validation/archived/` | 98 dead validator files, 2.5 MB — 4 versions of ast_field_analyzer, 3 of database_field_reference_validator |
| SC-C2 | `.pre-commit-config.yaml` (522 lines) | 42 hooks unmaintainable — 5 overlapping field validators, 3 competing orchestrators, 2 duplicate security scanners |
| SC-C3 | pytest-coverage-critical on pre-commit | ~60-120s per commit — should be pre-push or CI only |

### High

| # | File | Description |
|---|------|-------------|
| SC-H1 | 5 field validators | legacy_field_validator + doctype_field_validator + sql_field_reference + enhanced_field + ast-field-analyzer all validate same problem |
| SC-H2 | api_security_validator + insecure_api_detector | Both check decorators, both classify risk — unclear division |
| SC-H3 | run_controller_tests.sh + run_mollie_e2e_tests.sh | ~340 LOC total with identical boilerplate (logging, color codes, arg parsing) |
| SC-H4 | `comprehensive_field_reference_validator.py` (1,530 LOC) | 47 functions covering SQL, templates, database fields — should be 3-4 validators |

---

## Area 9: Scheduler & Background Jobs

**frappe.enqueue calls:** 100 | **Scheduled tasks:** 54 | **With idempotency:** 0

### Critical

| # | File | Description |
|---|------|-------------|
| BG-C1 | `hooks/scheduler.py` (54 tasks) | No idempotency checks on ANY task — duplicate processing if scheduler runs twice |
| BG-C2 | `account_creation_manager.py:1489-1853` | Job chaining: if enqueue of next batch fails, entire remaining chain lost with no recovery |
| BG-C3 | `payment_retry.py:176-182` | Missing try/except on frappe.enqueue — retry record saved but job never queued on failure |
| BG-C4 | `bulk_invoice_generation_service.py` | 3600s timeout job with no progress checkpointing — entire batch result lost on timeout |

### High

| # | File | Description |
|---|------|-------------|
| BG-H1 | `background_jobs.py:46-115` | Triple enqueue pattern (queue_member_payment_history_update, queue_expense_event_processing, queue_donor_auto_creation) 99% identical — not consolidated |
| BG-H2 | `scheduler.py:123-129` | financial_history_batch_processor at */10 * * * * * (every 10 seconds) — 8,640 jobs/day |
| BG-H3 | `membership/scheduler.py:99-127` | No batch size limit on process_expired_memberships — blocks worker if 10,000 expire same day |
| BG-H4 | Inconsistent queue selection | payment_retry in "default", bulk_invoice in "long" — no documented policy |
| BG-H5 | 3 exponential retry implementations | All slightly different, no shared utility |

---

## Area 10: CSS/SCSS/Tailwind

**CSS files:** 11 (2,968 LOC) | **Tailwind output:** 342 LOC | **Inline styles:** 69 HTML files | **Hardcoded colors:** 52+

### Critical

| # | File | Description |
|---|------|-------------|
| CSS-C1 | `verenigingen_custom.css:56,174` | .membership-type-card defined twice with identical properties |
| CSS-C2 | Across all CSS | 26+ instances of hardcoded #007bff (Bootstrap blue) conflicting with Tailwind config primary #cf3131 |
| CSS-C3 | `chapter_list.css:4-56` | 12x .text-green-*/.bg-green-* overrides with !important duplicating Tailwind utilities |

### High

| # | Pattern | Description |
|---|---------|-------------|
| CSS-H1 | Tailwind adoption gap | 342 LOC Tailwind vs 2,968 LOC custom CSS — Tailwind barely adopted despite config existing |
| CSS-H2 | `mobile_dues_schedule.css` (658 LOC) | 22% of total CSS — repeated mobile overrides (padding, font-size) 15+ times |
| CSS-H3 | 4 conflicting color schemes | Bootstrap (#007bff), Material Design (#667eea, #2196f3), Tailwind brand (#cf3131), and custom greens |
| CSS-H4 | Dark mode partial | Only in mobile_dues_schedule.css at mobile sizes — no desktop or other-page dark mode |
| CSS-H5 | 32 !important declarations | chapter_list.css alone has 12 — specificity issues |
| CSS-H6 | 69 HTML files with inline styles | style="" attributes instead of CSS classes/Tailwind utilities |

---

## Area 11: Frappe/ERPNext Overrides (Bonus)

**Monkey-patches:** 2 | **DocType overrides:** 1 | **Doc events on ERPNext DocTypes:** 14 handlers on 10 DocTypes

### Critical

| # | File | Description |
|---|------|-------------|
| OV-C1 | `overrides/sales_invoice.py:26-36` | Monkey-patches erpnext.accounts.party.validate_due_date() at import time — no version guards. Affects ALL Sales Invoices globally. Will break on ERPNext upgrade. |
| OV-C2 | `session_cache_fix.py:38` | Monkey-patches frappe.sessions.Session.validate_user — recursive self.resume() could cause infinite loop. Auto-applied to every user session via boot.py. No opt-out. |
| OV-C3 | `boot.py:74-93` | Unconditionally imports session_cache_fix.py, auto-applying monkey-patch. Exception caught but not re-raised — failures silent. |

### High

| # | File | Description |
|---|------|-------------|
| OV-H1 | `overrides/payment_entry.py:17-28` | Empty pass-through override of Payment Entry to counteract HRMS override. Depends on HRMS behavior — fragile. |
| OV-H2 | `doc_events.py:150` + `e_boekhouden/hooks.py:28` | Sales Invoice.on_submit registered in TWO locations. Handlers execute in undefined order. |
| OV-H3 | All overrides | No version guards on any Frappe/ERPNext import — will break silently on upgrade |

---

## Prioritized Action Plan

### Immediate (P0) — Data Integrity & Security

1. **Fix 6 SQL injection risks in reports** (R-C1 through R-C5) — use parameterized queries
2. **Fix 5 missing patches in patches.txt** (P-C1) — remove or create missing files to prevent migration failures
3. **Fix 4 dead function references in e_boekhouden hooks** (HK-C1) — remove or implement
4. **Add version guards to monkey-patches** (OV-C1, OV-C2) — prevent silent breakage on upgrade

### Short-term (P1) — Reliability

5. **Add idempotency to top 10 scheduled tasks** (BG-C1) — start with financial tasks
6. **Add try/except to critical enqueue calls** (BG-C3) — especially payment retry
7. **Fix innerHTML XSS in 4 critical templates** (WT-C1 through WT-C4) — use textContent or escapeHtml
8. **Reduce pre-commit time** (SC-C3) — move pytest-coverage to pre-push (saves 2+ min per commit)

### Medium-term (P2) — DRY Consolidation

9. **Consolidate test factories** (T-C1) — create single TestDataFactory with composition, delete 5 duplicates
10. **Delete 98 archived validators** (SC-C1) — available in git history if needed
11. **Consolidate 5 field validators into 2** (SC-H1) — fast pre-commit + thorough pre-push
12. **Consolidate duplicate test suites** (T-C2, T-C3) — keep _real versions, delete _optimized/_minimal
13. **Clean up critical_operation_rule.json** (HK-C2) — deduplicate 243 operation names
14. **Extract shared CSS variables** (CSS-C2) — replace 52+ hardcoded color values

### Long-term (P3) — Architecture

15. **Split JS god objects** (JS-C3, JS-H1, JS-H2) — member.js into domain modules
16. **Adopt Tailwind consistently** (CSS-H1) — migrate custom CSS to utilities
17. **Split Member DocType** (DT-H1) — extract payment/SEPA/history to linked DocTypes
18. **Consolidate Sales Invoice hooks** (OV-H2) — single location for all handlers
19. **Extract shared report utilities** (R-H2, R-H3) — column definitions, chart generation
20. **Add batch size limits to scheduler tasks** (BG-H3) — prevent worker blocking

---

## Metrics by Audit Area

| # | Area | Files | Critical | High | Medium | Low |
|---|------|-------|----------|------|--------|-----|
| 1 | Frontend JS | 90+ | 4 | 5 | 8 | 6 |
| 2 | Test Quality | 760 | 4 | 4 | 8 | 4 |
| 3 | DocType Schemas | 131 | 0 | 4 | 4 | 8 |
| 4 | Web Templates | 50+ | 4 | 4 | 6 | 3 |
| 5 | Reports | 28 | 5 | 4 | 12 | 6 |
| 6 | Patches | 34 | 4 | 4 | 5 | 4 |
| 7 | Hooks/Fixtures | 8+ | 3 | 3 | 2 | 0 |
| 8 | Scripts/Tooling | 42 hooks | 3 | 4 | 4 | 3 |
| 9 | Scheduler/Jobs | 54 tasks | 4 | 5 | 6 | 4 |
| 10 | CSS/Styles | 11 files | 3 | 6 | 10 | 5 |
| 11 | Overrides | 3 patches | 3 | 3 | 2 | 0 |
| | **Total** | | **37** | **46** | **67** | **43** |
