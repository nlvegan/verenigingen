# Design: Rewire `server-tests.yml` so CI actually runs the test suite

**Date:** 2026-05-23
**Issue:** [#66](https://github.com/nlvegan/verenigingen/issues/66) — CI runs zero tests for the package modules listed in `test-modules`
**Status:** Approved, ready for implementation plan

---

## Problem

`server-tests.yml` declares nine matrix jobs (`critical`, `backend-components`, `backend-workflows`, `sepa-financial`, `security`, `account-creation`, `e-boekhouden`, `payments`, `integration`). Each calls `_base-server-tests.yml` with a `test-modules` input listing one or more **package paths**:

```yaml
test-modules: 'verenigingen.tests.backend.components,verenigingen.tests.backend.unit'
test-modules: 'verenigingen.tests.financial'
test-modules: 'verenigingen.tests.services'  # (not currently listed — see "Missing entirely")
```

`_base-server-tests.yml:135-137` invokes each as `bench --site test_site run-tests --module "$module"`. Frappe's test discovery uses `unittest.TestLoader().loadTestsFromModule()` (`frappe/testing/discovery.py:126`), which **only loads `TestCase` classes defined directly in the named module** — it does not recurse into subpackages. Every `__init__.py` in `verenigingen/tests/*` is empty, so the loader returns 0 tests for each package path.

### Empirical confirmation

```
$ time bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.services
Starting test run with parameters: ...
View detailed logs (using --verbose): /home/frappeuser/frappe-bench/logs/frappe.testing.log

real    0m2.399s
```

No `Ran N tests` line, no `OK`/`FAILED`. `verenigingen.tests.services` contains 31 test files; none ran. Same for every other package-path entry in the matrix.

### Additional discoveries

- **`verenigingen.tests.contracts/` contains zero `.py` files** (only `.json` contract definitions). The "Critical Tests" job — the one whose result is treated as a merge-blocking signal in the `summary` job — has always executed nothing.
- **`verenigingen.tests.backend.unit/` is empty** (no test files at all). Listed in `backend-components` matrix.
- **Eight whole test subdirectories are not referenced anywhere in `server-tests.yml`**: `services/` (31 files), `sepa/` (31), `member/` (40), `payment/` (67), `chapter/` (22), `donor/` (17), `email/` (8), `volunteer/` (4). These were created by the 2026-03-09 test directory reorganization (see `docs/plans/2026-03-09-test-directory-reorganization-design.md`); the CI wiring to match never landed.
- **`tests-hosted.yml`** (workflow_dispatch-only alternate path) has the same bug — runs `--module verenigingen.tests.{contracts,services,integration}`.
- **597 total test files** in `verenigingen/tests/`, **680 across the app**. Approximately none currently execute on PR.

The 5-minute matrix job runtimes seen on recent PRs are bench setup + ERPNext install + teardown, not test execution.

---

## Goal

Restore real CI coverage: every push to `develop`/`main` and every PR should execute the full verenigingen test suite, with results visible per-PR.

Non-goals:
- Fix the failing tests themselves. Suite is reportedly ~17/20 EnhancedTestCase modules red (see `MEMORY.md` → `test-suite-crisis-2026-05-22`). That's downstream work, one PR per cluster.
- Re-architect the workflow files. Existing structure (`server-tests.yml` reusable-calls `_base-server-tests.yml`) is fine.
- Adjust branch protection. Admin-only; PR body flags the required-check name change so the admin knows what to update.

---

## Architecture

### `server-tests.yml` — collapse to single parallel matrix

**Before:** 9 category jobs, each calling `_base-server-tests.yml` with a `test-modules` list resolving to ~0 tests.

**After:** one `tests` job calling `_base-server-tests.yml` with `parallel-runs: 4` and **no** `test-modules`/`test-pattern`. This lands on the already-correct branch at `_base-server-tests.yml:115-123` which invokes `bench run-parallel-tests --app verenigingen --total-builds 4 --build-number ${{ matrix.index }}`. Frappe's `run-parallel-tests` walks the file system (not unittest module discovery) and distributes test files across shards by `build-number`.

Resulting check matrix:
```
Tests (1/4)
Tests (2/4)
Tests (3/4)
Tests (4/4)
Test Summary       ← aggregator (always runs, fails if any shard failed)
```

Other changes to `server-tests.yml`:
- Drop the `test_category` `workflow_dispatch` input (no longer meaningful with collapsed matrix).
- Keep the `enable_coverage` `workflow_dispatch` input (still useful for on-demand coverage runs).
- Simplify the `summary` job: single status check, drop the 9-row markdown table.
- Top-of-file comment: explain the rewire and link to this design doc.

**Deviations during implementation (2026-05-23):**
- **Dropped the `pre-check` job entirely.** The original plan kept it as a "cheap, useful safety net" — but code review during implementation found it was scaffolding: `should_run=true` was unconditional, and the syntax-validation step used `|| true` so it could never fail the workflow. Removed in commit `e42cce87`.
- **Removed the `test-results` aggregator from `_base-server-tests.yml`.** The reusable workflow originally had its own `test-results` job aggregating shard outcomes. After the rewire, `server-tests.yml`'s `Test Summary` job does the same work at the outer layer, producing two redundant FAILURE checks on the PR status rollup. Surfaced in double-review; removed so branch protection only has one aggregator to point at.
- **Deleted `tests-hosted.yml.deprecated`.** A pre-existing `.deprecated` copy of the original `tests-hosted.yml` was sitting in `.github/workflows/` containing the exact `--module verenigingen.tests.{contracts,services,integration}` bug pattern. Footgun if anyone restored it. Removed in the same pass.

### `_base-server-tests.yml` — remove the footgun

The current file has three execution branches:
- `Run Tests (Parallel - All)` — used when `test-modules == ''` and `test-pattern == ''`. Correct.
- `Run Tests (Specific Modules)` — used when `test-modules != ''`. The bug.
- `Run Tests (File Pattern)` — used when `test-pattern != ''`. Theoretically OK, but currently has no callers and shares a brittle find-loop pattern.

**Remove both broken branches and their inputs.** The remaining `run-parallel-tests` branch becomes unconditional. ~50 LOC deleted. This removes the ability for a future change to re-introduce the bug by listing a package path again.

If anyone ever genuinely needs to scope a test run to a subset, they can pass arguments directly to `bench run-tests` in a one-off workflow_dispatch handler — but the default reusable workflow only knows how to run the whole app.

### `tests-hosted.yml` — minimal fix

This file is `workflow_dispatch`-only and has the same bug. It duplicates `server-tests.yml` more broadly: both use GitHub-hosted runners (the self-hosted runner was scrapped — see commit `519be201` / PR #64). Worth noting for follow-up, not in scope to refactor here.

Minimal fix:
- Replace the 3 `bench --site test.localhost run-tests --module verenigingen.tests.{contracts,services,integration}` calls with `bench --site test.localhost run-parallel-tests --app verenigingen --total-builds 1 --build-number 1`.
- Preserve the `run_full_tests` input semantics: when false, skip the full suite; when true, run it.

PR body will flag `tests-hosted.yml` as a deletion candidate for a follow-up.

---

## Validation strategy

This PR is verified by its own CI run. If the new wiring works:
- 4 `Tests (i/4)` job logs each contain at least one `Ran N tests` line with N >> 0.
- Total test execution covers ~597 test files across the 4 shards.
- Jobs likely go **red** because the suite is reportedly ~17/20 EnhancedTestCase modules red. **This is true signal**, not a regression of the rewire. Red means CI is now actually telling us what we already knew — the next step (re-baselining the suite, per the handoff) becomes actionable.

If the wiring is broken:
- No `Ran N tests` line in job logs → discovery path is still wrong.
- Job times collapse back to ~3-5min (bench setup only, no test execution) → same.

Manual pre-merge check: open the PR's "Checks" tab and inspect one shard's logs for the test-output pattern.

---

## Risks & follow-ups

**Branch protection becomes stale.** Required-status-checks list almost certainly references the 9 deleted job names (`Critical Tests`, `Backend Components`, `Backend Workflows`, `SEPA & Financial`, `Security Tests`, `Account Creation`, `E-Boekhouden`, `Payments & Mollie`, `Integration Tests`). These will sit `Expected` forever on new PRs after this lands. Admin needs to update protection rules to require the new names (`Tests (1/4)` … `Tests (4/4)` + `Test Results`). PR body will surface this loudly.

**Parallelism count is a guess.** 4 shards is a reasonable default for ~597 test files. If wall-clock turns out to be excessive (>30min per shard), bump to 6 or 8 in a one-line follow-up. If wall-clock turns out trivial (<5min per shard), drop to 2 to save runner-minutes. Either way: cheap to adjust.

**Lightmode availability.** `bench run-parallel-tests` supports `--lightmode` which skips before-test setup. Not adopted here — the baseline run should exercise the full setup path to surface fixture/migration issues. Can opt in later.

**Coverage handling.** When `enable_coverage` is `true` (workflow_dispatch only), each shard produces a coverage file, and the existing `coverage` aggregator job in `_base-server-tests.yml` (lines 211-246) combines them. That code path is untouched by this PR.

---

## Out of scope

- Triaging the ~17/20 red EnhancedTestCase modules. Separate work per the handoff.
- Issue #65 (`assignment_query_builder.py` hardcoded `'Verenigingen Chapter Board Member'`). Separate one-line fix.
- Deleting `tests-hosted.yml`. Flagged as follow-up candidate; in-scope here is just making it work.
- Re-architecting `_base-server-tests.yml` setup steps. Existing structure is fine.
- Adjusting `quality-assurance.yml` / `code-validation.yml` / `controller-size-check.yml` / `pylint.yml` / `security-permission-check.yml` / `ci.yml`. None of those run tests — they run linters/security scanners. Unaffected by this bug.

---

## Files touched

| File | Change | LOC |
|---|---|---|
| `.github/workflows/server-tests.yml` | Collapse 9 category jobs to single `tests` job; simplify summary; drop `test_category` input | ~-200 / +30 |
| `.github/workflows/_base-server-tests.yml` | Remove `test-modules`/`test-pattern` inputs and their two branches | ~-55 / +0 |
| `.github/workflows/tests-hosted.yml` | Replace 3 broken `--module` calls with `run-parallel-tests` | ~-15 / +5 |
| `docs/plans/2026-05-23-ci-test-discovery-rewire-design.md` | This design doc | +new |

Net: roughly -230 LOC across CI config.

---

## Acceptance criteria

1. PR's own CI run shows 4 `Tests (i/4)` jobs in the matrix.
2. Each `Tests (i/4)` job's log contains at least one `Ran N tests in Xs` line with N > 0.
3. The total test count across all 4 shards is in the high hundreds to low thousands (proxy: it's actually running the suite).
4. `Test Results` aggregator job correctly reflects shard outcomes (red if any shard red, green if all green).
5. `_base-server-tests.yml` no longer accepts `test-modules` or `test-pattern` inputs.
6. PR body documents the branch-protection name change for the admin.
