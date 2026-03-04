# Test Suite Phase 2: Duplicate Consolidation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Delete ~10K LOC of duplicate/inferior test file variants using a delete-only approach (no merging).

**Architecture:** Two-tier deletion. Tier A: 17 high-confidence files (demos, broken, runners, clear subsets) deleted unconditionally. Tier B: up to 17 files deleted only after verifying every test method exists in the kept version. Each tier is one commit.

**Tech Stack:** git, bash, grep (file deletion + method-level comparison)

---

### Task 1: Delete Tier A component test duplicates (7 files, ~1,453 LOC)

**Files to delete:**
- `vereiningen/tests/backend/components/test_anbi_donation_summary_report_minimal_real.py` (199 LOC — minimal subset of _optimized_real)
- `vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py` (354 LOC — educational demo)
- `vereiningen/tests/backend/components/test_overdue_payments_simple_real.py` (130 LOC — simplified subset)
- `vereiningen/tests/backend/components/test_payment_processing_api_minimal.py` (45 LOC — 3-test stub)
- `vereiningen/tests/backend/components/test_payment_processing_api_optimized.py` (139 LOC — intermediate iteration)
- `vereiningen/tests/backend/components/test_fee_override_integration.py` (511 LOC — BROKEN, references undefined fields)
- `vereiningen/tests/backend/components/test_payment_interval_fix.py` (75 LOC — micro regression, 1 test)

**Files kept (verify these exist first):**
- `vereiningen/tests/backend/components/test_anbi_donation_summary_report_optimized_real.py`
- `vereiningen/tests/backend/components/test_overdue_payments_report_real.py`
- `vereiningen/tests/backend/components/test_payment_processing_api.py`

**Step 1: Verify kept files exist**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen
ls vereiningen/tests/backend/components/test_anbi_donation_summary_report_optimized_real.py \
   vereiningen/tests/backend/components/test_overdue_payments_report_real.py \
   vereiningen/tests/backend/components/test_payment_processing_api.py
```

Expected: All 3 files listed without errors.

**Step 2: Delete the 7 files**

```bash
rm -f vereiningen/tests/backend/components/test_anbi_donation_summary_report_minimal_real.py
rm -f vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py
rm -f vereiningen/tests/backend/components/test_overdue_payments_simple_real.py
rm -f vereiningen/tests/backend/components/test_payment_processing_api_minimal.py
rm -f vereiningen/tests/backend/components/test_payment_processing_api_optimized.py
rm -f vereiningen/tests/backend/components/test_fee_override_integration.py
rm -f vereiningen/tests/backend/components/test_payment_interval_fix.py
```

**Step 3: Verify deletion**

```bash
ls vereiningen/tests/backend/components/test_anbi_donation_summary_report_minimal_real.py 2>/dev/null && echo "STILL EXISTS" || echo "deleted"
ls vereiningen/tests/backend/components/test_fee_override_integration.py 2>/dev/null && echo "STILL EXISTS" || echo "deleted"
```

Expected: Both print "deleted".

---

### Task 2: Delete Tier A integration test duplicates (3 files, ~1,044 LOC)

**Files to delete:**
- `vereiningen/tests/integration/test_query_optimization_suite_old.py` (487 LOC — superseded by _suite.py)
- `vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py` (375 LOC — demo)
- `vereiningen/tests/integration/test_payment_api_a_plus_demo.py` (182 LOC — demo)

**File kept (verify first):**
- `vereiningen/tests/integration/test_query_optimization_suite.py`

**Step 1: Verify kept file exists**

```bash
ls vereiningen/tests/integration/test_query_optimization_suite.py
```

**Step 2: Delete the 3 files**

```bash
rm -f vereiningen/tests/integration/test_query_optimization_suite_old.py
rm -f vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py
rm -f vereiningen/tests/integration/test_payment_api_a_plus_demo.py
```

---

### Task 3: Delete Tier A workflow test duplicates (5 files, ~878 LOC)

**Files to delete:**
- `vereiningen/tests/backend/workflows/test_member_lifecycle_basic.py` (170 LOC — 1-test simplified subset)
- `vereiningen/tests/backend/workflows/test_enhanced_termination.py` (81 LOC — not a TestCase, runner script)
- `vereiningen/tests/backend/workflows/test_suspension_system.py` (115 LOC — not a TestCase, runner script)
- `vereiningen/tests/backend/workflows/test_suspension_runner.py` (291 LOC — orchestration, 0 test methods)
- `vereiningen/tests/backend/workflows/test_suspension_api_import_fallback.py` (221 LOC — 20 @patch, superseded by _real)

**Files kept (verify first):**
- `vereiningen/tests/backend/workflows/test_member_lifecycle_complete.py`
- `vereiningen/tests/backend/workflows/test_suspension_api.py`
- `vereiningen/tests/backend/workflows/test_suspension_api_import_fallback_real.py`

**Step 1: Verify kept files exist**

```bash
ls vereiningen/tests/backend/workflows/test_member_lifecycle_complete.py \
   vereiningen/tests/backend/workflows/test_suspension_api.py \
   vereiningen/tests/backend/workflows/test_suspension_api_import_fallback_real.py
```

**Step 2: Delete the 5 files**

```bash
rm -f vereiningen/tests/backend/workflows/test_member_lifecycle_basic.py
rm -f vereiningen/tests/backend/workflows/test_enhanced_termination.py
rm -f vereiningen/tests/backend/workflows/test_suspension_system.py
rm -f vereiningen/tests/backend/workflows/test_suspension_runner.py
rm -f vereiningen/tests/backend/workflows/test_suspension_api_import_fallback.py
```

---

### Task 4: Delete Tier A top-level test duplicates (2 files, ~492 LOC)

**Files to delete:**
- `vereiningen/tests/test_billing_transitions_simplified.py` (321 LOC — simplified duplicate of _proper)
- `vereiningen/tests/test_chapter_members_basic.py` (171 LOC — basic subset of _enhanced)

**Files kept (verify first):**
- `vereiningen/tests/test_billing_transitions_proper.py`
- `vereiningen/tests/test_chapter_members_enhanced.py`

**Step 1: Verify kept files exist**

```bash
ls vereiningen/tests/test_billing_transitions_proper.py \
   vereiningen/tests/test_chapter_members_enhanced.py
```

**Step 2: Delete the 2 files**

```bash
rm -f vereiningen/tests/test_billing_transitions_simplified.py
rm -f vereiningen/tests/test_chapter_members_basic.py
```

---

### Task 5: Clean whitelist and commit Tier A

**Step 1: Clean whitelist_files.txt**

Remove any entries referencing deleted files:

```bash
grep -v "test_payment_interval_fix" whitelist_files.txt > whitelist_files.txt.tmp && mv whitelist_files.txt.tmp whitelist_files.txt
```

**Step 2: Stage and commit all Tier A deletions**

```bash
git add -u vereiningen/tests/backend/components/ \
           vereiningen/tests/integration/ \
           vereiningen/tests/backend/workflows/ \
           vereiningen/tests/ \
           whitelist_files.txt

git commit -m "chore(tests): delete 17 duplicate/broken test files — Tier A (-3.9K LOC)

Phase 2 of test suite cleanup. Tier A = high-confidence deletes:
- 7 component tests (demos, subsets, broken _fee_override_integration)
- 3 integration tests (demos, superseded _old)
- 5 workflow tests (runner scripts, mock-heavy fallback)
- 2 top-level tests (simplified/basic subsets)
Cleaned 1 stale whitelist_files.txt entry.

Ref: docs/plans/2026-03-04-test-suite-duplicate-consolidation-design.md"
```

---

### Task 6: Tier B — Verify donor security group (4 candidates)

**Kept file:** `vereiningen/tests/test_donor_security_comprehensive.py`
**Candidates:** `test_donor_security_core.py`, `test_donor_security_enhanced.py`, `test_donor_security_enhanced_fixed.py`, `test_donor_security_working.py`

**Step 1: Extract test methods from kept file**

```bash
grep "def test_" vereiningen/tests/test_donor_security_comprehensive.py | sed 's/.*def //' | sed 's/(.*//'' | sort
```

**Step 2: For each candidate, extract test methods and check coverage**

For each of the 4 candidate files, run:

```bash
grep "def test_" vereiningen/tests/test_donor_security_VARIANT.py | sed 's/.*def //' | sed 's/(.*//'' | sort
```

**Step 3: Decision logic**

For each candidate file:
- Extract its test method names
- Check if the kept file tests the same behaviors (method names may differ, so compare semantically)
- If ALL behaviors are covered → mark for deletion
- If ANY unique behavior exists → SKIP (do not delete)

**Step 4: Delete confirmed duplicates**

```bash
rm -f vereiningen/tests/test_donor_security_CONFIRMED_DUPLICATE.py
```

---

### Task 7: Tier B — Verify chapter board permissions group (3 candidates)

**Kept file:** `vereiningen/tests/test_chapter_board_permissions_comprehensive.py`
**Candidates:** `test_chapter_board_permissions.py`, `test_chapter_board_permissions_fixed.py`, `test_chapter_board_permissions_final.py`

Same process as Task 6:
1. Extract test methods from kept file
2. Extract test methods from each candidate
3. Delete only if ALL methods are covered by kept file
4. SKIP if any unique methods exist

---

### Task 8: Tier B — Verify remaining top-level/component groups

**Groups to verify:**

1. **Billing transitions** — kept: `_proper.py`, candidate: `test_billing_transitions.py` (578 LOC)
2. **ANBI report** — kept: `_optimized_real.py`, candidates: `test_anbi_donation_summary_report.py` (418 LOC), `test_anbi_donation_summary_report_real.py` (603 LOC)
3. **Payment API** — kept: `test_payment_processing_api.py`, candidates: `test_payment_processing_api_real.py` (444 LOC), `test_payment_api_real_working.py` (170 LOC)
4. **Overdue payments** — kept: `_real.py`, candidate: `test_overdue_payments_report.py` (344 LOC)

Same process: extract methods, compare, delete only fully-covered files.

---

### Task 9: Tier B — Verify workflow duplicates

**Groups to verify:**

1. **Member lifecycle collision** — `backend/workflows/test_member_lifecycle.py` (699 LOC) vs `backend/workflows/test_member_lifecycle_complete.py` (628 LOC) vs `workflows/test_member_lifecycle_complete.py` (438 LOC)
2. **Payment failure** — `backend/workflows/test_payment_failure_recovery.py` (626 LOC) vs `workflows/test_financial_workflows_complete.py`
3. **Suspension** — `backend/integration/test_suspension_simple_real.py` (153 LOC) vs `test_suspension_integration_real.py` (297 LOC)

Same process: extract methods, compare, delete only fully-covered files.

---

### Task 10: Commit Tier B deletes and verify

**Step 1: Stage all Tier B deletions**

```bash
git add -u vereiningen/tests/
```

**Step 2: Commit with list of deleted files**

```bash
git commit -m "chore(tests): delete N verified-duplicate test files — Tier B (-X.XK LOC)

Phase 2 Tier B: method-level comparison confirmed all test behaviors
in these files exist in their superior counterparts.

[List specific files deleted and their kept counterpart]

Ref: docs/plans/2026-03-04-test-suite-duplicate-consolidation-design.md"
```

**Step 3: Run pre-commit**

```bash
SKIP=whitelist-type-safety,jest-testing,javascript-doctype-validator pre-commit run --all-files
```

Expected: All checks pass.

**Step 4: Count total LOC deleted**

```bash
git diff --stat HEAD~2 HEAD | tail -1
```

**Step 5: Update MEMORY.md**

Add Phase 2 entry to test debt reduction progress section.
