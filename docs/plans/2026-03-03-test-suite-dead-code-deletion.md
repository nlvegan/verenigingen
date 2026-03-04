# Test Suite Phase 1: Dead Code Deletion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Delete ~62K LOC of verified-dead test files, scripts, and archived validators across 6 commits.

**Architecture:** Pure file deletion + whitelist cleanup. All targets have zero imports/callers (verified via `grep -r`). Each commit is self-contained and independently revertable.

**Tech Stack:** git, bash (file deletion only — no code changes)

---

### Task 1: Delete unused archived validators (~36K LOC)

**Files:**
- Delete: 88 files in `scripts/validation/archived/` (all EXCEPT the 9 listed below)
- Delete: `scripts/validation/archived/__pycache__/` (entire directory)
- Keep: `block_inappropriate_mocks.py`, `codanna_deprecated_checker.py`, `database_field_reference_validator.py`, `doctype_field_validator.py`, `email_template_precommit_check.py`, `frappe_api_confidence_validator.py`, `frappe_hooks_validator.py`, `method_resolution_validator.py`, `validation_orchestrator.py`

**Step 1: Delete the 88 unused files**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

# Delete all .py files EXCEPT the 9 we keep
KEEP="block_inappropriate_mocks.py|codanna_deprecated_checker.py|database_field_reference_validator.py|doctype_field_validator.py|email_template_precommit_check.py|frappe_api_confidence_validator.py|frappe_hooks_validator.py|method_resolution_validator.py|validation_orchestrator.py"

find scripts/validation/archived/ -maxdepth 1 -name "*.py" | grep -Ev "$KEEP" | xargs rm -f
```

**Step 2: Delete __pycache__**

```bash
rm -rf scripts/validation/archived/__pycache__
```

**Step 3: Verify only the 9 kept files remain**

```bash
ls scripts/validation/archived/*.py | wc -l
# Expected: 9
ls scripts/validation/archived/*.py
```

**Step 4: Commit**

```bash
git add -A scripts/validation/archived/
git commit -m "chore(tests): delete 88 unused archived validation scripts (-36K LOC)

Phase 1 of test suite dead code deletion. These are development
iterations of validators that have been superseded by production/
and framework/ versions. 9 validators still referenced in
.pre-commit-config.yaml are preserved.

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 1"
```

---

### Task 2: Delete orphaned scripts/testing (~27K LOC)

**Files:**
- Delete: 122 files across `scripts/testing/` subdirectories (all EXCEPT 3 active files)
- Delete: All `__pycache__/` directories in `scripts/testing/`
- Delete: All `__init__.py` files in emptied subdirectories
- Delete: Empty subdirectories after file removal
- Keep: `scripts/testing/pytest_precommit_runner.py`, `scripts/testing/test_coverage_report.py`, `scripts/testing/jest-precommit-wrapper.sh`
- Clean: Remove 21 stale entries from `whitelist_files.txt`

**Step 1: Delete all files except the 3 we keep**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

KEEP="pytest_precommit_runner.py|test_coverage_report.py|jest-precommit-wrapper.sh"

# Delete all .py and .sh files except the 3 active ones
find scripts/testing/ -type f \( -name "*.py" -o -name "*.sh" \) | grep -Ev "$KEEP" | xargs rm -f
```

**Step 2: Delete all __pycache__ directories**

```bash
find scripts/testing/ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
```

**Step 3: Delete empty directories (bottom-up)**

```bash
find scripts/testing/ -type d -empty -delete 2>/dev/null
```

**Step 4: Verify only the 3 kept files remain**

```bash
find scripts/testing/ -type f | sort
# Expected:
#   scripts/testing/jest-precommit-wrapper.sh
#   scripts/testing/pytest_precommit_runner.py
#   scripts/testing/test_coverage_report.py
```

**Step 5: Clean whitelist_files.txt**

Remove all 21 `scripts/testing/` entries from `whitelist_files.txt`. Also remove the 2 stale Mollie spike entries (`./verenigingen/utils/complete_payment_test.py` and `./vereiningen/utils/interactive_subscription_test.py`) since those files no longer exist at those paths.

**Step 6: Commit**

```bash
git add -A scripts/testing/ whitelist_files.txt
git commit -m "chore(tests): delete 122 orphaned test runner scripts (-27K LOC)

Phase 1 of test suite dead code deletion. These are one-off test
runners, phase4 refactoring scripts, and monitoring scripts with
zero callers. 3 active files referenced in .pre-commit-config.yaml
are preserved. Also cleaned 23 stale whitelist_files.txt entries.

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 1"
```

---

### Task 3: Delete broken archived test (256 LOC)

**Files:**
- Delete: `archived/tests/test_payment_optimization.py`
- Delete: `archived/tests/__pycache__/`
- Delete: `archived/tests/` directory (if empty after)
- Delete: `archived/` directory (if empty after)

**Step 1: Delete file and clean up**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

rm -f archived/tests/test_payment_optimization.py
rm -rf archived/tests/__pycache__
rmdir archived/tests 2>/dev/null
rmdir archived 2>/dev/null
```

**Step 2: Verify deletion**

```bash
ls archived/ 2>/dev/null || echo "archived/ directory removed"
```

**Step 3: Commit**

```bash
git add -A archived/
git commit -m "chore(tests): delete broken archived payment optimization test (-256 LOC)

Test imports from non-existent payment_mixin_optimized module.
Removes the archived/tests/ directory entirely.

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 1"
```

---

### Task 4: Delete demo/educational test files (~1,200 LOC)

**Files:**
- Delete: `vereiningen/tests/backend/comprehensive/test_comprehensive_suite_demo.py`
- Delete: `vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py`
- Delete: `vereiningen/tests/integration/test_payment_api_a_plus_demo.py`
- Delete: `vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py`

**Step 1: Delete the 4 demo files**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

rm -f vereiningen/tests/backend/comprehensive/test_comprehensive_suite_demo.py
rm -f vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py
rm -f vereiningen/tests/integration/test_payment_api_a_plus_demo.py
rm -f vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py
```

**Step 2: Verify deletion**

```bash
find . -name "*demo*" -path "*/tests/*" -name "*.py" 2>/dev/null
# Expected: no output
```

**Step 3: Commit**

```bash
git add vereiningen/tests/backend/comprehensive/test_comprehensive_suite_demo.py \
        vereiningen/tests/backend/components/test_overdue_payments_mock_elimination_demo.py \
        vereiningen/tests/integration/test_payment_api_a_plus_demo.py \
        vereiningen/tests/integration/test_phase4d_mock_elimination_demo_simple.py
git commit -m "chore(tests): delete 4 demo/educational test files (-1,200 LOC)

These were mock-elimination refactoring demonstrations. The patterns
they taught have been incorporated into the production test suite.

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 1"
```

---

### Task 5: Delete Mollie spike/debug files (~850 LOC)

**Files:**
- Delete: `vereiningen/vereiningen_payments/mollie/tests/interactive_subscription_test.py`
- Delete: `vereiningen/vereiningen_payments/mollie/tests/complete_payment_test.py`
- Delete: `vereiningen/vereiningen_payments/mollie/tests/page_test_mollie.py`

**Step 1: Delete the 3 spike files**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen

rm -f vereiningen/vereiningen_payments/mollie/tests/interactive_subscription_test.py
rm -f vereiningen/verenigingen_payments/mollie/tests/complete_payment_test.py
rm -f vereiningen/verenigingen_payments/mollie/tests/page_test_mollie.py
```

**Step 2: Clean their __pycache__ entries**

```bash
rm -f vereiningen/vereiningen_payments/mollie/tests/__pycache__/interactive_subscription_test*.pyc
rm -f vereiningen/verenigingen_payments/mollie/tests/__pycache__/complete_payment_test*.pyc
rm -f vereiningen/verenigingen_payments/mollie/tests/__pycache__/page_test_mollie*.pyc
```

**Step 3: Verify deletion**

```bash
ls vereiningen/vereiningen_payments/mollie/tests/interactive_subscription_test.py 2>/dev/null || echo "deleted"
ls vereiningen/vereiningen_payments/mollie/tests/complete_payment_test.py 2>/dev/null || echo "deleted"
ls vereiningen/vereiningen_payments/mollie/tests/page_test_mollie.py 2>/dev/null || echo "deleted"
```

**Step 4: Commit**

```bash
git add vereiningen/vereiningen_payments/mollie/tests/interactive_subscription_test.py \
        vereiningen/vereinigen_payments/mollie/tests/complete_payment_test.py \
        vereiningen/vereiningen_payments/mollie/tests/page_test_mollie.py
git commit -m "chore(tests): delete 3 Mollie spike/debug test files (-850 LOC)

interactive_subscription_test.py: manual debugging with print()
complete_payment_test.py: mock elimination demo with hardcoded personas
page_test_mollie.py: HTML page test for debugging

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 5"
```

---

### Task 6: Delete superseded _OLD test file (~450 LOC)

**Files:**
- Delete: `vereiningen/tests/integration/test_query_optimization_suite_old.py`

**Step 1: Delete the file**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen
rm -f vereiningen/tests/integration/test_query_optimization_suite_old.py
```

**Step 2: Verify the replacement exists**

```bash
ls -la vereiningen/tests/integration/test_query_optimization_suite.py
# Expected: file exists (this is the newer version)
```

**Step 3: Commit**

```bash
git add vereiningen/tests/integration/test_query_optimization_suite_old.py
git commit -m "chore(tests): delete superseded query optimization test (-450 LOC)

Replaced by test_query_optimization_suite.py which has enhanced
context managers, query counters, and memory profiling.

Ref: docs/audits/test-suite-audit-2026-03-03.md Section 4"
```

---

### Task 7: Post-deletion verification

**Step 1: Run pre-commit to verify nothing is broken**

```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen
SKIP=whitelist-type-safety,jest-testing,javascript-doctype-validator pre-commit run --all-files
```

Expected: All checks pass (SKIP flags for known pre-existing failures per MEMORY.md).

**Step 2: Count LOC deleted**

```bash
git diff --stat HEAD~6 HEAD | tail -1
```

**Step 3: Update MEMORY.md with results**

Add entry to test debt reduction progress section with commit references and LOC counts.
