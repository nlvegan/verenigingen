# 2026-08-23b — the fixes that removed a guarantee

Continues `2026-08-23-the-fix-sections-that-were-hypotheses.md`. That one ended with seven
reviews delivered and nothing applied. This is the applying, plus three backlog items. Four
PRs merged, six open, three issues filed.

The first handoff's lesson was *an issue's evidence is authority, its suggested fix is a
hypothesis*. Applying the reviews produced a sharper one.

---

## 1. A fix can remove an accidental guarantee

Twice today, code that was wrong in a way that *happened to enforce something* was fixed, and
the enforcement went with it. Neither was caught by the fix's own author.

**#524 — `ensure_root_territory` made a sentinel forgeable.**
`ensure_erpnext_base_masters()` gated a whole master set (BootStrapTestData,
`enable_all_roles_and_domains()`, `set_defaults_for_tests()`,
`ensure_test_fiscal_year_for_all_companies()`) on one existence check. That row was a *sound*
proxy, because erpnext's `get_preset_records("India")` creates "All Territories", "All Customer
Groups", "All Item Groups" and "All Supplier Groups" in one batch — so any one implied the batch.
Creating the root on its own broke the proxy: a class on either harness base running first would
forge the sentinel, and the 30+ modules calling `ensure_member_test_masters()` afterwards would
early-return and seed **nothing**.

The causal bit is the point: **this was impossible before, because a missing root RAISED — and
that raise *is* #516.** Fixing the raise is what made the sentinel forgeable.

Closed in the same change, verified: `_erpnext_base_masters_present()` (new in #524, absent on
develop) now gates on a conjunction, and `"All Supplier Groups"` is unforgeable —
**0 creation sites for `Supplier Group` in the app**, 31 references, all reads.

**#526 — the lazy stderr handler removed accidental visibility.**
Binding the handler to `sys.stderr` *by value* was the bug. But a bound handler **bypassed**
frappe's per-test captures, so records written from `tearDownClass` were always visible.
Resolving lazily fixed the bug and put those records into a buffer `stopTestRun` never drains.
Nine harness-logger-backed class-teardown sites, including one of the 13 that #512 had just
converted.

**How to apply:** when a fix removes a raise, a failure, or an indirection, ask what that
misbehaviour was accidentally guaranteeing. `grep` the row/flag/stream for *gates elsewhere*
before making it creatable, and prefer gating on something you do not create.

## 2. Red shards on these PRs are not evidence about the PR

Four PRs went red on modules they never touched; two others were fully green on the same base.

| PR | red shard | failing module | in the diff? | on a green sibling |
|---|---|---|---|---|
| #526 | 5/12 | `tests.integration.test_dutch_business_rules_phase3` | no | **ran and passed** |
| #527 | 1/12 | `tests.www.test_dues_www_pages_coverage` | no | **ran and passed** |
| #524 | 3/12 | `member_id` duplicate — now #549/#550 | no | — |
| #524 | 8/12 | **its own guard, true positive** | **yes** | — |

`known_test_failures.txt` has **0 active entries**, so any of these fails the gate. Re-running
does not help — it reproduces the same packing. The procedure that actually settles it, in order:
grep the shard log for the strings your change introduces (#527: zero hits for all six); check
whether the module passed on a sibling PR **by reading the log, not by absence from a failure
list**; then diff the module *sets*. `scripts/testing/notes/526-shard5-unique-predecessors.txt`
holds the 25-module bisect list for the one still open.

**#524's shard 8 is the instructive exception** — it *was* the change, and benignly so: the new
AST guard can see classes the old substring version could not, and flagged a
`unittest.TestCase` naming the root. It only appeared in CI because **the file arrived on develop
after the branch's base**; the agent tested the base, CI tests the merge.

## 3. Applying a review corrects the reviewer too

Every one of the three review-application agents overrode part of its brief, and was right.

| brief said | measured |
|---|---|
| #524: "the AST guard is what would have caught C1" | **No** — both guards are per-file, and that file already seeds at five other sites. Kept the fix, rewrote the comment to state the limit |
| #527: "19 bodies / 58 assertions" | **18/57.** `test_api_regression` is 6/15; the extra candidate's handler asserts the exception type, so the failure survives — and including it gives 7/**17**, so my figure was internally inconsistent |
| EUR C1: "in `finally`, DELETE then assert it is gone" | **Non-discriminating** — the row *looks* gone before teardown. Used a **second connection** (#424/#436 idiom) instead |
| EUR C2: "prefer `_Test Company`" | That company is **INR**; `_Test Company 2` is EUR. Preferring INR silently drops the EUR preference `_seed_default_leaf_customer_group` needs for Price List selection |

And two issues I filed were wrong: **#531** (only one of the two assertions had a literal
cross-reference; the other was a one-liner) and **#530** (both halves of my "cannot be exercised
locally" reasoning were false — the seeder runs mid-suite from 47 call sites, and a test already
exercises it). Both corrected on the issues.

## 4. The census is always bigger

| I filed | actual |
|---|---|
| #533: 4 chapter names with 2 owners | **9**, and `Test Chapter` has **4** owners |
| #530: 13 currency scans, 2 safe to allowlist | 13 → **0**; the "safe" one was the most dangerous |
| #532: the class takes the oldest | only the `get_all` half; `get_value("Company", {}, …)` takes the **newest** |

**#533's collisions were live, not latent.** `Inactive Chapter` and `Active Chapter` are committed
rows from **2026-02-21**; `Amsterdam` is a **2026-01-30** CSV-import artifact with **103** roster
rows shared by four files. One module built **0** chapters on develop and 13 on the branch — it had
never created a fixture, only adopted six-month-old rows. And the earlier "the drain never fires,
0 `Deleted Document` rows against a control of 63" was **test_site_3-specific**: test_site_5 has
**3775**.

---

## Traps worth remembering

- **`git stash` on a clean worktree saves nothing, and the paired `pop` applies a stranger's
  stash.** I did this to get a control and conflicted on an unrelated file. Nothing was lost —
  pop keeps the entry — but the right tool is `git show <ref>:<file>`. This is already in
  CLAUDE.md; I walked into it anyway.
- **One run per side is not discriminating.** I called a Ponto failure "a real regression" off one
  observation each way. Three consecutive runs since: 30 OK. It was a flake.
- **The duplicate-helper check's name misleads.** That job has four steps; the whole-tree ratchet
  passed (exit 0) on #527, #541 and #543 while *"baseline is in sync with the tree"* failed. The
  growth gate counts only `# clone family` lines, which is what separates recording a name
  collision (legitimate) from laundering a clone family (the abuse it exists to stop). All three
  were 170 → 170. **#541 did not even add a copy** — `_persist_eur_company` stayed at 17 and only
  its similarity share moved 32% → 33%.
- **A source guard matching a string is satisfied by a comment.** Demonstrated on #524; the AST
  rewrite is what closed it.
- **`BootStrapTestData()` runs at module scope**, once per process. Seeding is unrecoverable
  within a process — filed as **#554**.

## Where things stand

`develop` @ `f7633f89`. **Merged this session:** #511, #512, #525, #527.

| PR | State | Remaining |
|---|---|---|
| **#524** territory root | **43/43 CLEAN** | ready |
| **#542** chapter collisions | **44/44 CLEAN** | ready |
| #541 EUR sweep | re-running, ratchet fixed | — |
| #543 SingletonBackup | re-running, baseline fixed | — |
| #526 harness logger | 41/43 | document the class-teardown loss; bisect the co-tenant |
| #550 member_id collision | running | not from this session's work |

**Issues filed:** #554 (BootStrapTestData import cache). Earlier in the day: #528–#533, #535, #537.
**Corrected after filing:** #530, #531, #532, #533.

## Process notes

- Three agents died mid-implementation on an **org monthly spend limit**. Resuming them by message
  preserved their verified findings and partial edits — better than restarting. Nothing had been
  committed, so the PRs were untouched.
- Every agent was briefed to **verify each finding before implementing** and to report
  NOT-REPRODUCED rather than implement a claim that does not hold. That instruction fired six times
  today, four of them on claims I had relayed.
