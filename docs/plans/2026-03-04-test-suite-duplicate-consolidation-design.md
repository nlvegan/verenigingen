# Design: Test Suite Phase 2 — Duplicate Consolidation

**Date:** 2026-03-04
**Audit reference:** `docs/audits/test-suite-audit-2026-03-03.md`
**Scope:** Delete duplicate/inferior test file variants (~10K LOC)
**Risk:** Low — delete-only approach, no merging of test methods
**Constraint:** If ANY unique test methods exist in the inferior file, SKIP it

## Strategy

Three-tier classification of 54 candidate files (21,744 LOC total):

- **Tier A** — High-confidence deletes: demos, broken tests, non-TestCase runners, clear subsets
- **Tier B** — Medium-confidence: need method-level comparison to confirm all tests covered by kept file
- **Tier C** — Skip: thematic variants with different focus areas, no consolidation needed

## Tier A — Safe Deletes (17 files, ~3,867 LOC)

### Components (vereiningen/tests/backend/components/)

| File | LOC | Reason | Kept version |
|------|-----|--------|-------------|
| test_anbi_donation_summary_report_minimal_real.py | 199 | Minimal subset | _optimized_real |
| test_overdue_payments_mock_elimination_demo.py | 354 | Educational demo | _real |
| test_overdue_payments_simple_real.py | 130 | Simplified subset | _real |
| test_payment_processing_api_minimal.py | 45 | 3-test stub | main |
| test_payment_processing_api_optimized.py | 139 | Intermediate iteration | main |
| test_fee_override_integration.py | 511 | BROKEN (undefined fields) | N/A |
| test_payment_interval_fix.py | 75 | Micro regression, 1 test | N/A |

### Integration (vereiningen/tests/integration/)

| File | LOC | Reason | Kept version |
|------|-----|--------|-------------|
| test_query_optimization_suite_old.py | 487 | Superseded | _suite.py |
| test_phase4d_mock_elimination_demo_simple.py | 375 | Demo | N/A |
| test_payment_api_a_plus_demo.py | 182 | Demo | N/A |

### Workflows (vereiningen/tests/backend/workflows/)

| File | LOC | Reason | Kept version |
|------|-----|--------|-------------|
| test_member_lifecycle_basic.py | 170 | 1-test simplified subset | _complete |
| test_enhanced_termination.py | 81 | Not a TestCase, runner script | comprehensive |
| test_suspension_system.py | 115 | Not a TestCase, runner script | _api |
| test_suspension_runner.py | 291 | Orchestration, 0 test methods | _api |
| test_suspension_api_import_fallback.py | 221 | 20 @patch, superseded by _real | _real |

### Top-Level (vereiningen/tests/)

| File | LOC | Reason | Kept version |
|------|-----|--------|-------------|
| test_billing_transitions_simplified.py | 321 | Simplified duplicate | _proper |
| test_chapter_members_basic.py | 171 | Basic subset | _enhanced |

## Tier B — Conditional Deletes (17 files, ~7,415 LOC)

Each file requires method-level comparison before deletion. Delete ONLY if all test methods in the inferior file are covered by the kept file.

### Donor Security Group (keep _comprehensive)

| File | LOC |
|------|-----|
| test_donor_security_core.py | 310 |
| test_donor_security_enhanced.py | 807 |
| test_donor_security_enhanced_fixed.py | 655 |
| test_donor_security_working.py | 524 |

### Chapter Board Permissions Group (keep _comprehensive)

| File | LOC |
|------|-----|
| test_chapter_board_permissions.py | 569 |
| test_chapter_board_permissions_fixed.py | 256 |
| test_chapter_board_permissions_final.py | 631 |

### Billing Transitions (keep _proper)

| File | LOC |
|------|-----|
| test_billing_transitions.py | 578 |

### ANBI Report Group (keep _optimized_real)

| File | LOC |
|------|-----|
| test_anbi_donation_summary_report.py | 418 |
| test_anbi_donation_summary_report_real.py | 603 |

### Payment API Group (keep main)

| File | LOC |
|------|-----|
| test_payment_processing_api_real.py | 444 |
| test_payment_api_real_working.py | 170 |

### Overdue Payments (keep _real)

| File | LOC |
|------|-----|
| test_overdue_payments_report.py | 344 |

### Workflow Duplicates

| File | LOC | Notes |
|------|-----|-------|
| test_member_lifecycle.py (backend/workflows/) | 699 | Filename collision |
| test_member_lifecycle_complete.py (backend/workflows/) | 628 | Collision with workflows/ version |
| test_payment_failure_recovery.py | 626 | Check vs financial_workflows |
| test_suspension_simple_real.py | 153 | Check vs _integration_real |

## Tier C — Skip

| Group | Files | LOC | Reason |
|-------|-------|-----|--------|
| Membership Dues | 6 | 3,766 | Thematic by concern, well-organized |
| Volunteer | 5 | 2,691 | Minimal overlap, different focus |
| SEPA Components | 3 | 1,097 | No consolidation needed |
| Chapter Assignment | 2 | 1,313 | Different test approaches |
| Member Status/Lifecycle (components) | 4 | 2,184 | Different scope per file |

## Commits

1. **Tier A**: Delete 17 safe files (~3,867 LOC)
2. **Tier B**: Delete verified-duplicate files (TBD after method comparison, est. ~5-7K LOC)
3. **Cleanup**: whitelist_files.txt + any stale references

## Not In Scope

- Merging unique test methods from inferior files into kept files
- Reorganizing test directories (Phase 3)
- Converting mock-heavy tests to real DB (Phase 4)
- Adding missing test coverage (Phase 5)
