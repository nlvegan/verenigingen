# Test Suite Comprehensive Audit — 2026-03-03

## Executive Summary

The Vereiningen app has **~330K LOC across ~884 test files** (298K Python, 32K JavaScript). This audit analyzed every test file across 13 dimensions. The findings reveal a test suite that grew organically through iterative development phases, resulting in massive duplication, organizational chaos, and significant dead code — but with a fundamentally sound core that tests real business logic.

### Key Metrics

| Metric | Value |
|--------|-------|
| Total test files (Python + JS) | ~884 |
| Total test LOC (Python) | ~298,000 |
| Total test LOC (JavaScript) | ~32,000 |
| Total test LOC (combined) | ~330,000 |
| Test infrastructure LOC (fixtures, utils, mocks) | ~12,400 (Python) + ~102,000 (JS setup) |
| Estimated deletable LOC | **~120,000–140,000 (36–42%)** |
| Estimated consolidatable LOC (merge, not delete) | ~30,000 additional |
| Files using zero mocks | 74% |
| DocType test coverage | 22% (37/167 DocTypes) |
| Services with zero tests | 28% (24/87 services) |

### Verdict

The test suite is **~2.5x larger than it needs to be**. A healthy target would be ~150K–180K LOC delivering equivalent or better coverage. The bloat comes from:

1. **Iterative file accumulation** — tests named `_fixed`, `_enhanced`, `_working`, `_comprehensive`, `_real`, `_optimized`, `_minimal` without deleting predecessors
2. **Duplicate coverage across directories** — same feature tested in `tests/`, `tests/backend/components/`, `tests/services/`, `tests/integration/`, and DocType directories
3. **Dead scripts and archived files** — ~55K LOC in `scripts/` and `archived/` with zero callers
4. **Mislabeled tests** — "security" tests that only check permissions, "performance" tests that only test functionality

---

## Section 1: Dead Code & Archived Tests

**Source: Agent 1 — Dead/Archived Tests Audit**

### Findings

| Category | Files | LOC | Status |
|----------|-------|-----|--------|
| Archived validation scripts (unused) | 89 | 27,929 | DELETE |
| Archived validators (still in pre-commit) | 8 | 5,050 | KEEP (move to production/) |
| Demo/educational test files | 4 | 1,161 | DELETE |
| `_OLD` test files | 1 | 488 | DELETE |
| Orphaned scripts/testing | ~120 | 25,900 | DELETE |
| Broken archived test | 1 | 256 | DELETE |
| **Total deletable** | **~215** | **~55,734** | |

### Priority Actions

- **Tier 1 (immediate):** Delete 89 archived validators + 4 demo files + 1 broken test = **29,834 LOC**
- **Tier 2 (verify first):** Delete ~120 orphaned scripts = **25,900 LOC**
- **Keep:** 3 active test scripts (pytest runner, coverage report, jest wrapper) + 8 in-use archived validators

---

## Section 2: Component Test Duplication

**Source: Agent 2 — Backend Components Audit**

### Findings

The `tests/backend/components/` directory (75 files, 32,519 LOC) has **iterative test file accumulation** as its primary problem. Multiple files test the same feature at different stages of mock-elimination refactoring.

### Worst Duplication Areas

| Feature Area | Files | LOC | Overlap % | Deletable LOC |
|---|---|---|---|---|
| ANBI Donation Summary | 4 | 1,868 | 70% | 1,521 |
| Payment Processing API | 5 | 1,787 | 65% | 750 |
| Overdue Payments Report | 5 | 1,672 | 68% | 1,134 |
| Membership Dues System | 6 | 3,768 | 55% | 1,956 |
| Volunteer Management | 5 | 2,458 | 50% | 800 |
| Chapter Assignment | 2 | 1,312 | 45% | 300 |
| Member Status/Lifecycle | 4 | 1,854 | 40% | 400 |
| SEPA Integration | 4 | 1,135 | 35% | 250 |
| Financial Reporting | 3 | 1,334 | 25% | 150 |
| **Total** | **38** | **16,388** | **50% avg** | **7,261** |

### Pattern: Iterative File Naming

The naming pattern `test_X.py` → `test_X_real.py` → `test_X_optimized.py` → `test_X_minimal.py` represents mock-elimination refactoring stages where old files were never deleted:

```
test_anbi_donation_summary_report.py           (418 LOC) ← mock-heavy, DELETE
test_anbi_donation_summary_report_real.py       (603 LOC) ← intermediate, DELETE
test_anbi_donation_summary_report_minimal_real.py (199 LOC) ← minimal, DELETE
test_anbi_donation_summary_report_optimized_real.py (347 LOC) ← KEEP (best version)
```

### Broken/Incomplete Tests

- `test_fee_override_integration.py` (511 LOC) — references undefined fields, always fails
- `test_payment_interval_fix.py` (75 LOC) — micro regression test, merge elsewhere

---

## Section 3: Backend Unit Test Quality

**Source: Agent 3 — Unit Test Quality Audit**

### Key Statistics

| Metric | Value |
|--------|-------|
| Total unit test files | 49 |
| Total test methods | 769 |
| Average assertions per test | 2.35 (good) |
| Tests with zero assertions | 33 (4.3%) |
| Tests with only mock assertions | 19 (2.5%) |
| Files with heavy mocking (>5 mocks) | 15 (31%) |

### Quality Distribution

- **High quality (≥2.5 asserts/test):** 17 files (35%)
- **Medium quality (1.5–2.5):** 19 files (39%)
- **Low quality (<1.5):** 13 files (26%)

### Top Offenders

| File | Tests | Asserts | Issue |
|------|-------|---------|-------|
| `test_folder_category_detector.py` | 16 | 0 | Bare `assert` not `self.assert*()` |
| `test_date_extraction.py` | 36 | 0 | Same bare `assert` issue |
| `test_fee_override_hook_service.py` | 15 | 14 | 1.67 mocks/test, thin assertions |
| `test_member_address_service_consolidated.py` | 8 | 5 | Mock-only assertions |
| `test_member_onload_service.py` | 16 | 23 | 26 mocks, zero-assertion tests |

### Anti-Patterns Found

1. **Bare `assert` statements** — ~50 tests invisible to test runner (use `self.assertEqual()`)
2. **Mock-only assertions** — verify wiring, not behavior (`mock.assert_called()` without checking result)
3. **Overmocked services** — `@patch("frappe.db.*")` in service-layer tests
4. **Single-assertion tests** after 20+ lines of setup

### Best-in-Class Files

- `test_member_id_service.py` — 3.9 asserts/test, zero mocks, real DB
- `test_member_user_account_service.py` — 3.3 asserts/test, OperationResult pattern
- `test_enhanced_membership_application_api.py` — 3.2 asserts/test, multi-step flows

---

## Section 4: Integration Test Quality

**Source: Agent 4 — Integration Test Audit**

### Findings

| Directory | Files | LOC | Test Methods |
|-----------|-------|-----|-------------|
| `tests/integration/` | 45 | 20,922 | 452 |
| `tests/backend/integration/` | 18 | 7,707 | 186 |
| **Total** | **63** | **28,629** | **638** |

### Architecture

The two directories serve **different purposes** (not duplication):
- `tests/integration/` — API-centric, HTTP behavior, public endpoints
- `tests/backend/integration/` — Infrastructure, concurrency, third-party systems

### Dead/Broken Tests

| File | LOC | Issue |
|------|-----|-------|
| `test_eboekhouden_integration.py` | 348 | **Entirely SKIPPED** — tests reference wrong DocType schema |
| `test_query_optimization_suite_old.py` | 449 | Superseded by `_suite.py` |
| `test_phase4d_mock_elimination_demo_simple.py` | 465 | Educational demo, not a real test |

### Mock Discipline

- Integration tests have **good mock discipline** — mostly external services mocked
- 86 mock occurrences across 14 files in `tests/integration/`
- 30 mock occurrences across 10 files in `tests/backend/integration/`
- ~15 integration tests violate Tier 2 rules (mock database when they shouldn't)

---

## Section 5: External Integration Tests

**Source: Agent 5 — eBoekhouden, Mollie, ING, Payments Audit**

### Summary by Area

| Area | Files | LOC | Dead/Redundant | Quality |
|------|-------|-----|----------------|---------|
| eBoekhouden | 17 | ~5,900 | 800–1,200 (20%) | 7/10 |
| Mollie | 27 | ~11,300 | 2,500–3,200 (28%) | 5/10 |
| ING Checkout | 6 | ~950 | 0–50 (<5%) | 8/10 |
| Payments Core/SEPA | 45 | ~5,800 | 400–600 (10%) | 7/10 |
| **Total** | **97** | **~23,950** | **3,700–5,050** | |

### Mollie: Worst Offender

35–40% of Mollie tests are spike/debug code:
- `interactive_subscription_test.py` (398 LOC) — manual debugging tool with `print()` statements
- `complete_payment_test.py` (202 LOC) — mock elimination demo
- `page_test_mollie.py` (266 LOC) — HTML page test
- `test_subscription_creation.py` — attempts real API calls with embedded payment ID
- 3 bridge modules that just `sys.path.append()` and re-import (150 LOC total)
- 4 duplicate webhook security test files

---

## Section 6: Service Layer Test Coverage

**Source: Agent 6 — Service Tests Audit**

### Coverage Summary

| Domain | Services | Tested | Coverage |
|--------|----------|--------|----------|
| Member | 45 | 28 | 62% |
| Billing | 12 | 7 | 58% |
| Chapter | 8 | 2 | **25%** |
| Payment | 10 | 8 | 80% |
| Volunteer | 4 | 2 | 50% |
| Termination | 2 | 2 | 100% |
| Donation | 5 | 3 | 60% |
| Communication | 3 | 2 | 67% |

### Critical Gaps

**16+ services with zero test coverage:**
- ChapterBoardService (1,093 LOC!) — only partially tested via volunteer tests
- ChapterEventService, ChapterMatchingService
- ANBIValidationService, TeamService
- TerminationAuditService, MemberDonorIntegrationService
- VolunteerBulkCreationService, MollieReconciliationService

### Duplication Between Directories

5 services tested in 3+ locations:
- SEPAMandateManager: `tests/services/` + `backend/unit/services/` + DocType tests + comprehensive tests
- TerminationApprovalService: same pattern
- MemberChapterDisplayService: tested in both `tests/services/` and `backend/unit/services/`

---

## Section 7: DocType Test Coverage

**Source: Agent 7 — DocType Coverage Audit**

### Coverage Matrix

| Metric | Value |
|--------|-------|
| Total DocTypes | 167 |
| DocTypes with tests | 37 (22.2%) |
| Test files | 38 |
| Test methods | 335 |
| Stub tests (1 method, ~30 LOC) | 8 files |

### Critical Untested DocTypes

**Payment Processing (0% coverage despite financial impact):**
- `direct_debit_batch`, `ing_checkout_*` (4 types), `ponto_*` (5 types), `sepa_payment_retry*` (2 types)

**Accounting (0% coverage):**
- ALL 10 `e_boekhouden/doctype/*` DocTypes

**Member Lifecycle:**
- `member_fee_change_history`, `member_iban_history`, `member_contact_request`

### Quality Tiers

- **Excellent** (8 DocTypes): Member, Chapter, Volunteer, SEPA Mandate, Termination Request, Dues Schedule, MijnRood Import, VIP Import
- **Good** (6 DocTypes): Membership, Donor, Team, Chapter Join Request, Expense Category, Critical Operation Rule
- **Poor** (10 DocTypes): Donation (2 tests!), Volunteer Activity, Region, plus 7 stub-only files

---

## Section 8: Workflow & Comprehensive Tests

**Source: Agent 8 — Workflow/Comprehensive Audit**

### Inventory

| Directory | Files | LOC |
|-----------|-------|-----|
| `tests/` (top-level workflow tests) | 11 | 9,269 |
| `tests/workflows/` | 13 | 6,967 |
| `tests/backend/workflows/` | 17 | ~2,800 |
| `tests/backend/comprehensive/` | 18 | ~4,500 |
| `tests/backend/business_logic/` | 3 | ~600 |
| `tests/backend/features/` | 4 | ~1,200 |
| **Total** | **66** | **~25,336** |

### Severe Duplications

| Feature | Copies | Files | Deletable LOC |
|---------|--------|-------|---------------|
| Member lifecycle | 4 | lifecycle, lifecycle_basic, lifecycle_complete (×2) | ~1,600 |
| Suspension | 4 | system, api, api_import_fallback, api_import_fallback_real | ~1,000 |
| Termination | 3 | enhanced, system_comprehensive, workflow_edge_cases | ~800 |
| Payment failure | 2 | payment_failure_recovery + financial_workflows_complete | ~400 |
| **Total** | | | **~3,800** |

### Finding: Only 5–10% Test Real Frappe Workflows

Most "workflow" tests actually test business logic sequences using `status` fields, not the Frappe workflow engine. Only `test_membership_application_workflow.py` tests actual Frappe Workflow state transitions with permissions.

---

## Section 9: JavaScript/Frontend Tests

**Source: Agent 9 — JS/Frontend Audit**

### Inventory

| Category | Files | LOC |
|----------|-------|-----|
| Cypress E2E tests | 41 | 20,968 |
| Frontend DocType tests (Jest) | 24 | 11,652 |
| Frontend unit tests (Jest) | 13 | 4,554 |
| Unit controller tests (Jest) | 13 | 7,125 |
| Mollie integration tests | 5 | 3,606 |
| Test infrastructure (setup files) | 10 | **102,205** |
| **Total** | **107** | **~150,000** |

### Issues

1. **3 known failing tests:** `test_chapter_controller.test.js` (wrong path `/home/frappe/` vs `/home/frappeuser/`), `test_donation_controller_comprehensive.test.js`, `iban-validator.test.js`
2. **Massive test infrastructure:** 102K LOC in setup files (`frappe-mocks.js` alone is 17.5K LOC)
3. **4 variants of member controller tests** — should be 1–2
4. **HIGH OVERLAP** between Cypress E2E, frontend DocType tests, and unit controller tests for Member, Chapter, SEPA Mandate

---

## Section 10: Test Infrastructure

**Source: Agent 10 — Infrastructure/Fixtures Audit**

### Factory Framework

| Class | LOC | Usage |
|-------|-----|-------|
| CoreTestDataFactory | 1,040 | 12 direct imports |
| EnhancedTestDataFactory + EnhancedTestCase | ~5,640 | **348 imports (53%)** |
| VereningingenTestCase | 2,417 | ~200 tests (30%) |
| Specialized (SEPA, Ponto, Mollie) | ~1,840 | ~40 tests (6%) |
| FrappeTestCase (framework) | — | ~100 tests (15%) |

### Key Finding: Two Competing Philosophies

- **EnhancedTestCase** — Field safety validation, real DB, no mocks (business logic focus)
- **VereningingenTestCase** — CSRF mocking, request simulation, 31 factory methods (operational focus)

47% of tests still create data ad-hoc (308 instances of `frappe.get_doc()`/`frappe.new_doc()` with inline Member creation) instead of using factories.

### Dead Infrastructure

- `TestDataContext` (30 LOC stub, no-op)
- `ExtendedTestDataFactory` (~500 LOC, only 5 tests use it)
- `CoverageReporter` (~750 LOC, likely dead)
- `test_personas.py` (~80 LOC, no imports found)

---

## Section 11: Security & Performance Tests

**Source: Agent 11 — Security/Performance Audit**

### Security Tests (73 files, ~23K LOC)

**50% are mislabeled** — they test role-based access control (`can User X access DocType Y?`), not real security vulnerabilities.

| Category | Files | LOC | Real Security? |
|----------|-------|-----|---------------|
| Genuine vulnerability tests | 15–20 | ~3,500 | Yes (SQL injection, XSS, auth bypass) |
| Permission/RBAC tests (mislabeled) | 30–35 | ~8,000 | No — functional tests |
| Overlapping/duplicate | 18–20 | ~4,000 | Redundant |

**Worst duplication:** 6 donor security files (core, comprehensive, enhanced, enhanced_fixed, working, permissions) — keep only `_comprehensive`.

### Performance Tests (18 files, ~5,900 LOC)

**ALL are timing-dependent and flaky in CI/CD:**
- Use `time.time()` with absolute threshold assertions
- Fail under container CPU throttling
- Not suitable for automated test pipelines

**Recommendation:** Convert to relative comparisons or move to nightly-only runs.

---

## Section 12: Top-Level Miscellaneous Tests

**Source: Agent 12 — Top-Level Tests Audit**

### Finding: Dumping Ground

229 test files (~94,462 LOC) sit directly in `tests/` without organization. This is the **single largest source of bloat**.

### Iterative File Accumulation Pattern

| Domain | Files | Variant Suffixes Found |
|--------|-------|-----------------------|
| Donor security | 6 | `_core`, `_working`, `_enhanced`, `_enhanced_fixed`, `_comprehensive`, `_permissions` |
| Chapter board | 5 | (base), `_fixed`, `_final`, `_comprehensive`, `_document` |
| Billing transitions | 3 | (base), `_simplified`, `_proper` |
| SEPA | 27 | `_lifecycle`, `_lifecycle_service`, `_integration`, `_real`, `_performance`, `_regression`, etc. |
| Member | 20+ | `_comprehensive`, `_workflows`, `_enhanced`, `_fixed` |

### Recommended Disposition

| Action | Files | LOC |
|--------|-------|-----|
| DELETE (clear duplicates/obsolete) | ~30 | ~15,000 |
| MOVE to existing subdirectories | ~150 | ~60,000 |
| KEEP at top-level (cross-cutting) | 10–15 | ~8,000 |

---

## Section 13: Mock Usage Patterns

**Source: Agent 13 — Suite-Wide Mock Analysis**

### Overall Statistics

| Metric | Value |
|--------|-------|
| Files using `@patch` | 190 (25.6%) |
| Total `@patch` decorators | 1,812 |
| Total `with patch()` context managers | 858 |
| Combined mock instances | 2,670+ |
| Files with zero mocks | **552 (74.4%)** |
| Files with 50+ mocks | 7 (0.9%) |

### Mock Density Distribution

| Range | Files | % |
|-------|-------|---|
| 0 mocks | 552 | 74.4% |
| 1–5 | 85 | 11.5% |
| 6–10 | 45 | 6.1% |
| 11–20 | 35 | 4.7% |
| 21–50 | 18 | 2.4% |
| 50+ | 7 | 0.9% |

### Most Mocked APIs

1. `frappe.db.get_value()` — ~50 files
2. `frappe.get_doc()` — ~35 files
3. `frappe.db.exists()` — ~30 files
4. `frappe.get_all()` — ~20 files
5. `frappe.sendmail()` — external service (legitimate)

### Verdict: 70% Real Code, 30% Mock Wiring

The suite leans heavily toward real integration testing (74% zero mocks). The 15 integration tests that mock `frappe.db.*` are violations of the test-quality-enforcer Tier 2 rules.

---

## Consolidated Recommendations

### Phase 1: Dead Code Deletion (est. -80K LOC, 1–2 days)

No risk — these files have zero callers:

| Action | Target | LOC |
|--------|--------|-----|
| Delete archived validators (89 unused) | `scripts/validation/archived/` | -27,929 |
| Delete orphaned test scripts (~120 files) | `scripts/testing/` | -25,900 |
| Delete demo/educational tests (4 files) | `tests/backend/` | -1,161 |
| Delete `_OLD` test files | various | -488 |
| Delete broken archived test | `archived/tests/` | -256 |
| Delete Mollie spike/debug code | `mollie/tests/` | -2,500 |
| Delete bridge modules (sys.path hacks) | `mollie/tests/` | -150 |
| **Subtotal** | | **-58,384** |

### Phase 2: Duplicate Consolidation (est. -25K LOC, 1 week)

Delete older iterations, keeping only the best version:

| Action | LOC |
|--------|-----|
| Components: delete `_real`, `_optimized`, `_minimal` variants | -7,261 |
| Top-level: delete `_working`, `_fixed`, `_enhanced` variants (donor, chapter, billing) | -15,000 |
| Workflow: delete lifecycle/termination/suspension duplicates | -3,800 |
| Integration: delete broken/superseded tests | -1,265 |
| **Subtotal** | **-27,326** |

### Phase 3: Directory Reorganization (est. -0 LOC net, 1–2 weeks)

Move ~150 top-level test files into appropriate subdirectories:

| From | To | Files |
|------|----|-------|
| SEPA tests at top-level | `services/payment/`, `integration/sepa/` | ~15 |
| Donor tests at top-level | `backend/components/donor/` | ~8 |
| Member tests at top-level | `backend/components/member/` | ~15 |
| Payment tests at top-level | `integration/payments/` | ~12 |
| Security tests at top-level | `backend/security/` | ~15 |
| Email tests at top-level | `integration/email/` | ~8 |
| Banking (Ponto) at top-level | `integration/banking/` | ~8 |
| Validation tests at top-level | `backend/validation/` | ~12 |

### Phase 4: Quality Improvements (ongoing)

| Action | Impact |
|--------|--------|
| Fix bare `assert` in 2 files (52 tests) | Tests become visible to runner |
| Fix 3 broken JS test paths | 3 JS tests passing again |
| Add behavior assertions to mock-only tests | 19 tests providing real value |
| Fix 15 integration tests violating Tier 2 mock rules | Better test confidence |
| Consolidate 4 JS member controller variants → 1 | -1,000 JS LOC |
| Mark performance tests as nightly-only | CI reliability |

### Phase 5: Coverage Gap Remediation (2–4 weeks)

| Gap | Priority | New Tests Needed |
|-----|----------|-----------------|
| Payment DocTypes (0% coverage) | HIGH | 25–35 tests |
| eBoekhouden DocTypes (0% coverage) | HIGH | 15–20 tests |
| ChapterBoardService (1,093 LOC, no tests) | HIGH | 25 tests |
| Member history DocTypes | MEDIUM | 12–15 tests |
| 16 services with zero coverage | MEDIUM | 50+ tests |

---

## Summary: Before & After

| Metric | Current | After Phase 1–3 | Reduction |
|--------|---------|-----------------|-----------|
| Python test LOC | ~298,000 | ~185,000 | -38% |
| Python test files | ~777 | ~500 | -36% |
| JS test files | 107 | ~95 | -11% |
| Top-level test files | 229 | ~15 | -93% |
| Dead/archived code | ~58K LOC | 0 | -100% |
| Duplicate test variants | ~27K LOC | 0 | -100% |
| DocType coverage | 22% | 22% (Phase 5: 35%+) | — |
| Service coverage | 62% | 62% (Phase 5: 90%+) | — |
| Test infrastructure LOC | 12,400 | 11,000 | -11% |

---

## Appendix: File-Level Deletion Candidates (Top 50 by LOC)

Files that can be deleted immediately (zero callers, clear duplicates, or broken):

| # | File | LOC | Reason |
|---|------|-----|--------|
| 1 | `scripts/validation/archived/ast_field_analyzer_original.py` | 1,766 | Superseded |
| 2 | `scripts/validation/archived/ast_field_analyzer_improved_complete.py` | 1,703 | Superseded |
| 3 | `scripts/validation/archived/ast_field_analyzer_complete.py` | 1,622 | Superseded |
| 4 | `scripts/validation/archived/legacy_field_validator.py` | 1,134 | Replaced |
| 5 | `scripts/validation/archived/ast_field_analyzer_improved.py` | 1,084 | Iteration |
| 6 | `tests/test_donor_security_enhanced.py` | 808 | Keep `_comprehensive` |
| 7 | `tests/test_donor_security_comprehensive.py` → KEEP | — | — |
| 8 | `tests/test_donor_security_working.py` | 524 | Name says it all |
| 9 | `tests/test_donor_security_core.py` | 367 | Superseded |
| 10 | `tests/test_chapter_board_permissions_comprehensive.py` → KEEP | — | — |
| 11 | `tests/test_chapter_board_permissions_final.py` | 632 | Superseded |
| 12 | `tests/test_chapter_board_permissions.py` | 569 | Superseded |
| 13 | `tests/test_chapter_board_permissions_fixed.py` | 397 | Superseded |
| 14 | `tests/test_billing_transitions.py` | 578 | Keep `_proper` |
| 15 | `tests/test_billing_transitions_simplified.py` | 350 | Keep `_proper` |
| 16 | `tests/backend/components/test_anbi_donation_summary_report.py` | 418 | Keep `_optimized_real` |
| 17 | `tests/backend/components/test_anbi_donation_summary_report_real.py` | 603 | Intermediate |
| 18 | `tests/backend/components/test_anbi_donation_summary_report_minimal_real.py` | 199 | Minimal |
| 19 | `tests/backend/components/test_overdue_payments_mock_elimination_demo.py` | 354 | Demo |
| 20 | `tests/backend/components/test_overdue_payments_simple_real.py` | 130 | Superseded |
| 21 | `tests/backend/components/test_payment_processing_api_minimal.py` | 45 | Stub |
| 22 | `tests/backend/components/test_payment_processing_api_optimized.py` | 139 | Intermediate |
| 23 | `tests/backend/components/test_fee_override_integration.py` | 511 | BROKEN (undefined fields) |
| 24 | `tests/backend/comprehensive/test_comprehensive_suite_demo.py` | 247 | Demo |
| 25 | `tests/backend/workflows/test_member_lifecycle_basic.py` | ~200 | Simplified duplicate |
| 26 | `tests/backend/workflows/test_member_lifecycle_complete.py` | ~450 | Duplicate of tests/workflows/ |
| 27 | `tests/integration/test_query_optimization_suite_old.py` | 449 | Superseded |
| 28 | `tests/integration/test_phase4d_mock_elimination_demo_simple.py` | 465 | Demo |
| 29 | `tests/integration/test_eboekhouden_integration.py` | 348 | BROKEN (wrong schema) |
| 30 | `archived/tests/test_payment_optimization.py` | 256 | Broken imports |
| 31–50 | ~90 more `scripts/validation/archived/*.py` | ~24,000 | All superseded |

---

*This audit was conducted by 13 parallel analysis agents examining the complete test suite from different angles. Findings were cross-referenced and deduplicated before integration.*
