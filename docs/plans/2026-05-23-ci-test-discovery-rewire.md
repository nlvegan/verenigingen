# CI Test Discovery Rewire — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `server-tests.yml` actually run the verenigingen test suite instead of returning ~0 tests per matrix job, by collapsing 9 broken category jobs into a single `run-parallel-tests --app verenigingen` parallel matrix.

**Architecture:** Three CI workflow files change. `_base-server-tests.yml` loses its `test-modules`/`test-pattern` inputs and the two broken execution branches that consumed them — only the working `run-parallel-tests` branch remains. `server-tests.yml` collapses to a single `tests` job with `parallel-runs: 4`. `tests-hosted.yml` (workflow_dispatch alternate) gets the same minimal fix. No production code changes; verification is the PR's own CI run.

**Tech Stack:** GitHub Actions YAML; `bench run-parallel-tests` (Frappe's file-system-walking test runner); existing `.github/actions/setup` action; PyYAML for local syntax check.

**Spec:** `docs/plans/2026-05-23-ci-test-discovery-rewire-design.md` (committed 7e24bac4 on branch `fix/ci-test-discovery-issue-66`).

---

## Pre-flight context

The implementer must be on branch `fix/ci-test-discovery-issue-66` (already created in the brainstorm phase). The design doc is already committed. All edits below are on this branch. No worktree needed — this is a CI-config-only change with no risk of cross-contaminating other work.

Verify before starting:
```bash
cd /home/frappeuser/frappe-bench/apps/verenigingen
git branch --show-current   # expect: fix/ci-test-discovery-issue-66
git log --oneline -1         # expect: 7e24bac4 docs: design doc for Issue #66
```

---

## File Structure

Three files modified, no files created (design doc already exists):

| File | Responsibility after this PR |
|---|---|
| `.github/workflows/_base-server-tests.yml` | Reusable workflow that sets up bench+ERPNext, runs `run-parallel-tests` against the whole app for one shard of a matrix. No other modes. |
| `.github/workflows/server-tests.yml` | Top-level workflow: pre-check + `tests` job (4-shard matrix call into `_base-server-tests.yml`) + `summary` aggregator. |
| `.github/workflows/tests-hosted.yml` | `workflow_dispatch`-only alternate; runs the full parallel suite via `run-parallel-tests` when `run_full_tests: true`. |

---

### Task 1: Strip `test-modules` and `test-pattern` from `_base-server-tests.yml`

**Files:**
- Modify: `.github/workflows/_base-server-tests.yml`

**Context for this task:** Current file has three execution branches selected by `if:` guards: `test-modules == '' && test-pattern == ''` (correct, calls `run-parallel-tests`), `test-modules != ''` (the bug — calls `bench run-tests --module <package>`), and `test-pattern != ''` (find-based, no current callers). Removing the two broken branches makes the remaining branch unconditional and removes the inputs that drove them. This eliminates the surface where the bug could re-appear.

- [ ] **Step 1: Read the current file**

```bash
cat .github/workflows/_base-server-tests.yml | head -50
```

Confirm `test-modules` is defined at lines ~38-41 and `test-pattern` at ~42-45.

- [ ] **Step 2: Apply the edit — delete the two inputs**

Remove these lines (currently 38-45) from the `inputs:` block:

```yaml
      test-modules:
        description: 'Specific test modules to run (comma-separated, empty for all)'
        type: string
        default: ''
      test-pattern:
        description: 'Test file pattern for pytest (e.g., test_account_creation*)'
        type: string
        default: ''
```

So that `inputs:` ends with `enable-coverage:` and goes directly to `jobs:`.

- [ ] **Step 3: Apply the edit — delete the two broken execution branches**

Currently `_base-server-tests.yml` has three steps inside the `integration-tests` job:
- `Run Tests (Parallel - All)` — keep, but rename and remove its `if:`
- `Run Tests (Specific Modules)` — DELETE
- `Run Tests (File Pattern)` — DELETE

Replace the three-step block (currently lines ~115-170) with this single step:

```yaml
      - name: Run Tests
        run: |
          source ${GITHUB_WORKSPACE}/env/bin/activate
          bench --site test_site run-parallel-tests \
            --app ${{ github.event.repository.name }} \
            --total-builds ${{ inputs.parallel-runs }} \
            --build-number ${{ matrix.index }} \
            ${{ inputs.enable-coverage && '--with-coverage' || '' }}
```

Note: removed the `if: ${{ inputs.test-modules == '' && inputs.test-pattern == '' }}` guard since both inputs no longer exist.

- [ ] **Step 4: Verify YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/_base-server-tests.yml'))"
```

Expected: no output (success). Any YAMLError means the edit produced malformed YAML — re-check indentation.

- [ ] **Step 5: Verify no callers reference the removed inputs**

```bash
grep -rn "test-modules\|test-pattern" .github/workflows/
```

Expected: zero matches. If any match exists in another workflow file, that workflow would fail at runtime. (At this point in the plan, `server-tests.yml` still references them — that's fixed in Task 2. The grep should show ONLY matches from server-tests.yml; matches from any other file are problems.)

Acceptable output at this point: matches inside `server-tests.yml` only.

- [ ] **Step 6: Verify the file is well-formed structurally**

```bash
wc -l .github/workflows/_base-server-tests.yml
```

Expected: ~190 lines (was 247). A drop of ~55 lines confirms the deletions landed.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/_base-server-tests.yml
git commit -m "ci(base-tests): drop test-modules/test-pattern inputs

Removes the two execution branches in _base-server-tests.yml that drove
the zero-test-discovery bug. The 'Run Tests (Specific Modules)' branch
invoked bench run-tests --module <pkg> against a package path, which
unittest.TestLoader.loadTestsFromModule() does not recurse into, so it
returned 0 tests. The 'Run Tests (File Pattern)' branch had no callers.

The reusable workflow now only knows one execution mode: run-parallel-tests
against the whole app, sharded by matrix index. Removing the broken
branches prevents anyone re-introducing the bug by listing a package path
in a future test-modules entry.

Refs #66"
```

Note: `whitelist-type-safety` and similar pre-commit hooks will skip cleanly for YAML-only changes. If pre-commit blocks the commit for an unrelated reason, prefix with `SKIP=<hook-id>`.

---

### Task 2: Collapse `server-tests.yml` to a single parallel matrix

**Files:**
- Modify: `.github/workflows/server-tests.yml`

**Context for this task:** Currently has 9 category jobs each calling `_base-server-tests.yml` with broken `test-modules` arguments. After Task 1, those inputs no longer exist — every caller would now fail. This task replaces all 9 jobs with one that uses the only remaining (working) mode in the reusable workflow.

- [ ] **Step 1: Read the current file to confirm scope**

```bash
wc -l .github/workflows/server-tests.yml   # expect: 282 or 283
grep -c '^  [a-z-]*:$' .github/workflows/server-tests.yml   # job count
```

- [ ] **Step 2: Replace the entire file**

Overwrite `.github/workflows/server-tests.yml` with the following content. This is a near-total rewrite — easier to replace than to edit-in-place because 9 jobs collapse to 1 and the summary changes shape.

```yaml
name: Server Tests (GitHub Hosted)

# Runs the verenigingen test suite via bench run-parallel-tests, sharded
# across 4 matrix jobs. See docs/plans/2026-05-23-ci-test-discovery-rewire-design.md
# for the history (Issue #66 — the previous per-category matrix was
# discovering 0 tests per job because each entry was a package path and
# Frappe's run-tests --module uses unittest.TestLoader.loadTestsFromModule()
# which does not recurse into subpackages).

on:
  push:
    branches: [main, develop]
    paths:
      - 'verenigingen/**/*.py'
      - 'verenigingen/**/*.js'
      - 'pyproject.toml'
      - '.github/workflows/server-tests.yml'
      - '.github/workflows/_base-server-tests.yml'
      - '.github/actions/setup/**'
  pull_request:
    branches: [main, develop]
    paths:
      - 'verenigingen/**/*.py'
      - 'verenigingen/**/*.js'
      - 'pyproject.toml'
      - '.github/workflows/server-tests.yml'
      - '.github/workflows/_base-server-tests.yml'
      - '.github/actions/setup/**'
  workflow_dispatch:
    inputs:
      frappe_branch:
        description: 'Frappe branch to test against'
        required: false
        default: 'version-15'
      erpnext_branch:
        description: 'ERPNext branch to test against'
        required: false
        default: 'version-15'
      enable_coverage:
        description: 'Enable coverage collection'
        type: boolean
        default: false

concurrency:
  group: server-tests-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  pre-check:
    name: Pre-flight Check
    runs-on: ubuntu-latest
    outputs:
      should_run: ${{ steps.check.outputs.should_run }}
    steps:
      - uses: actions/checkout@v4

      - name: Check for Python changes
        id: check
        run: |
          echo "should_run=true" >> $GITHUB_OUTPUT

      - name: Python Syntax Validation
        run: |
          python -m py_compile $(find verenigingen -name "*.py" -type f 2>/dev/null | head -100) || true

  tests:
    name: Tests
    needs: pre-check
    if: needs.pre-check.outputs.should_run == 'true'
    uses: ./.github/workflows/_base-server-tests.yml
    with:
      python-version: '3.12'
      node-version: 18
      frappe-branch: ${{ inputs.frappe_branch || 'version-15' }}
      erpnext-branch: ${{ inputs.erpnext_branch || 'version-15' }}
      parallel-runs: 4
      enable-coverage: ${{ inputs.enable_coverage || false }}

  summary:
    name: Test Summary
    needs: tests
    if: always()
    runs-on: ubuntu-latest
    steps:
      - name: Report Result
        run: |
          status="${{ needs.tests.result }}"
          echo "## Test Results" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          if [ "$status" == "success" ]; then
            echo ":white_check_mark: All test shards passed." >> $GITHUB_STEP_SUMMARY
            exit 0
          elif [ "$status" == "skipped" ]; then
            echo ":fast_forward: Tests were skipped." >> $GITHUB_STEP_SUMMARY
            exit 0
          else
            echo ":x: One or more test shards failed. Check individual job logs above." >> $GITHUB_STEP_SUMMARY
            exit 1
          fi
```

- [ ] **Step 3: Verify YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/server-tests.yml'))"
```

Expected: no output (success).

- [ ] **Step 4: Verify no stale references**

```bash
grep -n "test-modules\|test-pattern\|test_category\|critical:\|backend-components:\|sepa-financial:" .github/workflows/server-tests.yml
```

Expected: zero matches. Any match means cruft from the old structure leaked through.

- [ ] **Step 5: Cross-check against `_base-server-tests.yml`**

```bash
grep -n "test-modules\|test-pattern" .github/workflows/
```

Expected: zero matches across all workflow files. After Tasks 1 and 2 both the producer and consumer are clean.

- [ ] **Step 6: Confirm the matrix shape**

```bash
python <<'PY'
import yaml
with open('.github/workflows/server-tests.yml') as f:
    wf = yaml.safe_load(f)
jobs = wf['jobs']
print('jobs:', list(jobs.keys()))
print('tests.with.parallel-runs:', jobs['tests']['with']['parallel-runs'])
PY
```

Expected output:
```
jobs: ['pre-check', 'tests', 'summary']
tests.with.parallel-runs: 4
```

If parallel-runs is not 4, or there are extra jobs, the rewrite drifted from the spec.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/server-tests.yml
git commit -m "ci(server-tests): collapse 9 category jobs to single 4-shard matrix

The previous matrix's 9 category jobs (critical, backend-components,
backend-workflows, sepa-financial, security, account-creation,
e-boekhouden, payments, integration) each passed a package-path
test-modules list that resolved to ~0 discovered tests via Frappe's
unittest-based module loader (see #66). 'Critical Tests' has never
actually run anything: tests/contracts/ contains only .json files.

Replaces all 9 jobs with one 'tests' job calling _base-server-tests.yml
with parallel-runs: 4, landing on the run-parallel-tests --app
verenigingen branch which discovers test files by walking the file
system. Result: ~597 test files now actually execute, distributed
across 4 sharded jobs (Tests (1/4) ... Tests (4/4)).

Drops the test_category workflow_dispatch input (was used to scope to
one broken category; now meaningless). Keeps enable_coverage. Summary
job simplifies from 9-row markdown table to a single pass/fail line.

BRANCH PROTECTION: required-status-checks entries referencing the old
job names (Critical Tests, Backend Components, Backend Workflows,
SEPA & Financial, Security Tests, Account Creation, E-Boekhouden,
Payments & Mollie, Integration Tests) must be updated to require the
new names (Tests (1/4) ... Tests (4/4) and Test Summary) or removed.
This is an admin-only repo settings change.

Refs #66"
```

---

### Task 3: Fix `tests-hosted.yml` (same bug, workflow_dispatch alternate)

**Files:**
- Modify: `.github/workflows/tests-hosted.yml`

**Context for this task:** This is a workflow_dispatch-only file that builds its own bench from scratch and runs `bench --site test.localhost run-tests --module verenigingen.tests.{contracts,services,integration}` — same package-path bug as server-tests.yml. It's largely a duplicate of `server-tests.yml` since both use GitHub-hosted runners; flagging for deletion in a follow-up is appropriate, but not in scope. Minimal fix: replace the three broken `--module` calls with `run-parallel-tests`.

- [ ] **Step 1: Read the affected section**

```bash
sed -n '107,127p' .github/workflows/tests-hosted.yml
```

Confirm the three `Run … Tests` steps target `verenigingen.tests.contracts`, `verenigingen.tests.services`, `verenigingen.tests.integration`.

- [ ] **Step 2: Replace the three test steps**

Replace lines 107-127 (the three `Run Critical Tests` / `Run Service Tests` / `Run Integration Tests` step blocks) with this single step:

```yaml
      - name: Run Tests
        run: |
          cd frappe-bench
          if [ "${{ inputs.run_full_tests }}" == "true" ]; then
            bench --site test.localhost run-parallel-tests \
              --app verenigingen \
              --total-builds 1 \
              --build-number 1
          else
            echo "Skipping full test suite. Re-run this workflow with run_full_tests=true to execute tests."
          fi
```

Rationale for the `if`: the original file had `Run Critical Tests` always run and the other two gated on `run_full_tests`. Since "Critical Tests" was never running anything meaningful (it pointed at the empty `tests.contracts/` package), there's no real coverage to preserve — the choice is binary now (skip or run full).

- [ ] **Step 3: Verify YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/tests-hosted.yml'))"
```

Expected: no output.

- [ ] **Step 4: Verify no `--module verenigingen.tests` references remain**

```bash
grep -n "module verenigingen.tests" .github/workflows/tests-hosted.yml
```

Expected: zero matches.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/tests-hosted.yml
git commit -m "ci(tests-hosted): fix the same zero-test-discovery bug

tests-hosted.yml had three 'bench --site test.localhost run-tests --module
verenigingen.tests.{contracts,services,integration}' steps with the same
loadTestsFromModule package-path bug as server-tests.yml (#66). The
'Critical Tests' step in particular always discovered 0 tests because
tests/contracts/ contains only .json files.

Replaces the three broken steps with a single run-parallel-tests call
gated on the existing run_full_tests workflow_dispatch input.

Note: this file is workflow_dispatch-only and duplicates server-tests.yml
(both use GitHub-hosted runners since the self-hosted runner was retired
in PR #64). It is a deletion candidate for a follow-up PR.

Refs #66"
```

---

### Task 4: Local pre-flight before pushing

**Files:** none modified — verification only.

- [ ] **Step 1: Confirm all three commits land cleanly**

```bash
git log --oneline develop..HEAD
```

Expected: 4 commits (1 docs + 3 ci) on top of develop:
```
<sha> ci(tests-hosted): fix the same zero-test-discovery bug
<sha> ci(server-tests): collapse 9 category jobs to single 4-shard matrix
<sha> ci(base-tests): drop test-modules/test-pattern inputs
7e24bac4 docs: design doc for Issue #66 (CI runs zero tests)
```

- [ ] **Step 2: Cross-workflow sanity check**

```bash
grep -rn "test-modules\|test-pattern\|verenigingen\.tests\.contracts\|--module verenigingen" .github/workflows/
```

Expected: zero matches across all workflow files. If anything remains, fix it now (the relevant edit was missed).

- [ ] **Step 3: All-YAMLs parse**

```bash
for f in .github/workflows/*.yml; do
  python -c "import yaml; yaml.safe_load(open('$f'))" && echo "OK: $f" || echo "FAIL: $f"
done
```

Expected: every workflow file says `OK:`. (Skip `.disabled` and `.deprecated` files.)

- [ ] **Step 4: Verify pre-commit hooks haven't blocked anything silently**

```bash
git status --short
```

Expected: only the unrelated `?? docs/plans/2026-05-18-payments-v2-migration-design.md` (from a prior session — not ours). Nothing else uncommitted.

---

### Task 5: Push branch and open draft PR

**Files:** none modified.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/ci-test-discovery-issue-66
```

If push fails on a pre-push hook (jest-testing, javascript-doctype-validator, pytest-coverage), retry with:

```bash
SKIP=jest-testing,javascript-doctype-validator git push -u origin fix/ci-test-discovery-issue-66
```

Per MEMORY.md, these hooks have pre-existing failures unrelated to this change.

- [ ] **Step 2: Open the PR as draft**

```bash
gh pr create --draft --base develop --title "fix(ci): make server-tests.yml actually run the test suite (Issue #66)" --body "$(cat <<'PRBODY'
Closes #66.

## Problem

`server-tests.yml`'s 9 matrix jobs each passed a package path (e.g. `verenigingen.tests.backend.components`) as the `test-modules` argument to `bench --site test_site run-tests --module <pkg>`. Frappe's test loader uses `unittest.TestLoader.loadTestsFromModule()`, which **does not recurse into subpackages**. Every `__init__.py` in `verenigingen/tests/*` is empty, so each job discovered ~0 tests.

Verified locally:

```
$ time bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services
... real 0m2.4s
```

No `Ran N tests` line. `verenigingen.tests.services` contains 31 test files. None ran.

Additionally:
- `verenigingen.tests.contracts/` contains zero `.py` files (only `.json` contract definitions). "Critical Tests" — the gate that determined PR mergeability in the old summary — has always passed by running nothing.
- `verenigingen.tests.backend.unit/` has zero test files.
- 8 whole test subdirectories (`services/`, `sepa/`, `member/`, `payment/`, `chapter/`, `donor/`, `email/`, `volunteer/` — 200+ files combined) were not referenced anywhere in the matrix. These came from the 2026-03-09 test reorganization; CI wiring was never updated to match.

## Fix

- **`_base-server-tests.yml`**: drop the `test-modules` and `test-pattern` inputs and the two broken execution branches that consumed them. Only the working `run-parallel-tests --app` branch remains.
- **`server-tests.yml`**: collapse the 9 category jobs into one `tests` job that calls `_base-server-tests.yml` with `parallel-runs: 4`. Resulting check matrix: `Tests (1/4)` … `Tests (4/4)` + `Test Summary` aggregator.
- **`tests-hosted.yml`**: same bug, fixed minimally. (This file duplicates `server-tests.yml` and is a deletion candidate for a follow-up.)

Design doc: `docs/plans/2026-05-23-ci-test-discovery-rewire-design.md`.

## Validation

This PR's own CI run is the verification. Check the run for:
1. Four `Tests (i/4)` jobs in the matrix.
2. At least one `Ran N tests in Xs` line per shard with N > 0.
3. Total test count across shards in the high hundreds to low thousands.

**The suite is reportedly ~17/20 EnhancedTestCase modules red** (see `MEMORY.md` → `test-suite-crisis-2026-05-22`). So this PR's CI will likely go red. **That is true signal**, not a regression — it means CI is finally telling us what we already knew. Triaging those failures is downstream work, one cluster per PR.

## ⚠️ Required: branch protection update (admin-only)

Required-status-checks rules almost certainly reference the deleted job names:
- ❌ `Critical Tests` (was always lying)
- ❌ `Backend Components`
- ❌ `Backend Workflows`
- ❌ `SEPA & Financial`
- ❌ `Security Tests`
- ❌ `Account Creation`
- ❌ `E-Boekhouden`
- ❌ `Payments & Mollie`
- ❌ `Integration Tests`

These will sit `Expected` forever on new PRs after this lands. **Please update branch protection to require:**
- ✅ `Tests (1/4)`
- ✅ `Tests (2/4)`
- ✅ `Tests (3/4)`
- ✅ `Tests (4/4)`
- ✅ `Test Summary`

…or drop required-status-checks for tests entirely until the suite is re-baselined.

## Not in this PR

- Triaging the red EnhancedTestCase modules. Separate work per the handoff.
- Fixing Issue #65 (`assignment_query_builder.py` hardcoded DocType name).
- Deleting `tests-hosted.yml`. Flagged as follow-up.
- Adjusting branch protection itself (admin-only).
PRBODY
)"
```

- [ ] **Step 3: Capture the PR URL**

```bash
gh pr view --json url -q .url
```

Save this for the next steps.

---

### Task 6: Observe the CI run and verify the wiring works

**Files:** none modified.

**Context:** This is the verification step. We cannot run GitHub Actions locally — the only way to confirm the rewire works is to watch the PR's own CI run.

- [ ] **Step 1: Wait for the workflow to start**

```bash
gh run list --branch fix/ci-test-discovery-issue-66 --limit 5
```

Look for an active run of `Server Tests (GitHub Hosted)`. The run will take roughly 8-15 minutes (bench setup ~5min + test execution).

If polling: use a long-fallback ScheduleWakeup (1200s+) rather than tight polling, because cache TTL is 5min.

- [ ] **Step 2: Once the run completes (or fails), check matrix shape**

```bash
gh run view --branch fix/ci-test-discovery-issue-66 --log | grep -E "^Tests \([0-9]+/4\)" | head -20
```

Expected: 4 distinct job names `Tests (1/4)`, `Tests (2/4)`, `Tests (3/4)`, `Tests (4/4)`.

- [ ] **Step 3: Verify each shard actually executed tests**

For each shard, the log should contain at least one `Ran N tests in Xs` line with N >> 0:

```bash
gh run view --log | grep -E "Ran [0-9]+ tests"
```

Expected: 4+ matches, each showing a substantial test count (likely >100 per shard, possibly much higher).

If you see zero `Ran N tests` lines, the rewire did not work — diagnose by:
- Checking the raw log for the `Run Tests` step's stdout
- Confirming `bench run-parallel-tests --app verenigingen` was actually invoked (not `bench run-tests --module …`)

- [ ] **Step 4: Record the test counts**

Sum the `Ran N tests` totals across all shards. Add this number to the PR as a comment so future maintainers can see what the baseline coverage looks like:

```bash
gh pr comment --body "**CI verification:** New wiring discovered and executed <SUM> tests across 4 shards (run #<RUN_ID>). $( [ <RED_COUNT> -gt 0 ] && echo "Shards red — expected per the handoff. Suite re-baselining is downstream work." || echo "All shards green.")"
```

(Fill in `<SUM>`, `<RUN_ID>`, `<RED_COUNT>` from the run output.)

- [ ] **Step 5: Mark the PR ready for review**

If the verification confirms the wiring works (regardless of whether tests pass or fail — what matters is that they're now running):

```bash
gh pr ready
```

- [ ] **Step 6: Tag the brainstorming/follow-up notes**

Add a follow-up comment listing what the run surfaced that's downstream work:

```bash
gh pr comment --body "**Downstream follow-ups surfaced by this run** (separate PRs):
- Re-baseline the ~17/20 EnhancedTestCase modules reported red in the 2026-05-22 handoff
- Issue #65: assignment_query_builder.py hardcoded 'Verenigingen Chapter Board Member' DocType
- Delete tests-hosted.yml (duplicates server-tests.yml)
- Update branch protection required-status-checks to the new job names"
```

---

## Acceptance criteria (from spec)

| # | Criterion | Where verified |
|---|---|---|
| 1 | PR's CI run shows 4 `Tests (i/4)` jobs | Task 6 Step 2 |
| 2 | Each job's log contains `Ran N tests in Xs` with N > 0 | Task 6 Step 3 |
| 3 | Total test count is in the high hundreds to low thousands | Task 6 Step 4 |
| 4 | `Test Summary` aggregator reflects shard outcomes | Task 6 Step 2 |
| 5 | `_base-server-tests.yml` no longer accepts `test-modules`/`test-pattern` | Task 1 Step 5, Task 4 Step 2 |
| 6 | PR body documents branch-protection name change | Task 5 Step 2 |

---

## Rollback plan

If after merge the new wiring causes CI to be unusable in a way that blocks other work (rather than just exposing red tests, which is true signal):

```bash
git revert <merge-commit-sha>
```

…then open a follow-up that re-introduces the old categorized matrix without re-introducing the bug (e.g., by listing individual test file paths rather than package paths). The design doc (`2026-05-23-ci-test-discovery-rewire-design.md`) discusses why this approach was rejected.

Branch protection notes will need to be re-reverted at the same time.
