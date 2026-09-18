# 2026-09-18b — the red belonged to none of them, and two reported findings did not reproduce

**State at handoff:** `develop` at `9edf36a9d`, **green** — Server Tests 14/14 at the tip,
every other develop run success. **Seven PRs merged**: #1139, #1141 (docs), #1157 (closing
#1153), #1160, #1145, #1147, #1148. **Four issues filed**: #1158, #1159, #1161, #1162.
Nothing is left mid-flight.

---

## The through-line

**A report is a claim. Three of this session's findings arrived from someone else, and two of
them did not survive being checked.**

| claimed | by | what checking it showed |
|---|---|---|
| four PRs red on their own defects | the PR list | red on **#1154**, which none of them caused — a **docs-only PR failing identically** was the control |
| `TEST-LEAK` reproduces "deterministically on develop", broadening #1137 | a review of #1148 | **did not reproduce** — same command, installed tree, two sites, clean both times. Almost certainly residue from the reviewer's own preceding branch run. Nothing was added to #1137 |
| `SubscriptionAudit` also writes 2 Error Log rows | a review of #1145 | **1 row here** — the bare constructor *raises* before `run_audit()` can catch anything. The count depends on whether construction sits inside the caller's `try` |
| `mollie_member_reconciliation` writes 2 rows | a review of #1145 | **reproduced exactly**, 2 rows, on a third site. Filed as #1162 |

The fourth row is why the first three matter: the same reviewer produced one claim that held
and one that did not, in the same report. There is no reviewer-level trust to extend — only
per-claim checking. **Re-derive anything you are about to act on or repeat into an issue.**

Every review verdict itself ("sound") was correct. It was the incidental observations,
offered in passing and outside the PR's diff, that were unreliable — which is exactly where
scrutiny is weakest, because they read as bonus findings rather than as the thing under test.

---

## The shard-12 red: the control was already sitting in the PR list

#1141, #1145, #1147 and #1148 each failed one check — `Tests / Tests (12/12)` — and each had
review comments treating it as their own problem.

**#1141 changes exactly one file, `docs/.../*.md`.** A docs-only PR cannot break a test shard.
That alone settles attribution, and it cost nothing to notice; the four had been sitting red
since 2026-09-17.

The shard-12 log then names the mechanism directly: `hrms.overrides.company.
set_expense_claim_type_accounts` dying on `expense_account = 'Expense Claims - EBBA'` — a
dangling account from a dead e-boekhouden probe company — erroring four `setUpClass` calls in
`test_rest_orchestration_batch` and `test_tegenrekening_mapper`. The #1150 signature.

All four branches were cut before `de2aaa394` and so carried no #1155. **Rebasing was the
whole fix**, and it is now confirmed twice: shard 12 green on all six PRs that run shards,
and green again on merged develop where the shards re-pack.

**Before attributing a red shard to the branch, look for a PR in the same list whose diff
cannot possibly cause it.** A docs-only PR is a free control.

---

## #1153 → #1157: the premise held, and the helper's contract did not

Dispatched. The agent measured the premise against MariaDB before touching code (broken order
matches 0/0, correct order 1/0), wrote a behavioural red test (`member_id="001%002"`
allocating `0001` twice), and consolidated **all four** copies of the idiom onto one
`escape_sql_like_wildcards()` so no copy of the escape logic survives.

An independent review re-derived every claim — including re-running the class sweep with a
wider pattern and its own mutation of both test files — and found one thing the author's
self-review did not: **the helper coerced with an unconditional `str(value)`, looser than one
of the three sites it replaced.** `sepa_mandate_manager` wrote `str(member_id)` deliberately
(a member_id can be an int), but `periodic_donation_operations` called `.replace()` straight
on `file_stem`, so `None` raised `AttributeError` at once. Consolidating on the permissive
form turned that into `LIKE 'None%'` — a query returning nothing **while looking like it
worked**.

Unreachable today. Fixed anyway (`d8519e24c`): a new shared contract with four callers and
more to come should not answer a programming error with an empty result set.

**Generalisable:** consolidating N copies onto one helper silently adopts the *loosest*
behaviour of the N unless someone checks. Diff the pre-existing call sites' input handling,
not just their output.

---

## #1154 → #1160: the sweep was on the success path only

#1155 put `purge_company_orphans` at the choke point both drains delete through. It ran only
when `frappe.delete_doc` **returned**.

frappe removes the row in `delete_from_table` and then keeps going: `after_delete`,
attachment removal, `delete_dynamic_links` (**synchronous under test** — `now=frappe.in_test`),
`add_to_deleted_document`'s `db_insert`, `notify_update`/`insert_feed`. A raise from any of
those leaves the row **gone** and the orphans **stranded**, with the sweep unreached. Both
drains then `_record_leak(...)` — naming a Company row that no longer exists, while the rows
that actually survived go unnamed and poison the next Company insert in the shard.

Reproduced by patching `add_to_deleted_document` — a **real** step of frappe's own
`delete_doc`, not an invented failure — with `assertFalse(frappe.db.exists(...))` as the
control proving the raise lands *after* the row removal. Red → green, same command, 70 tests.

Both new tests mutation-proved, **each reddening only its own control**: dropping the
`db.exists` guard reddens the before-removal test; dropping the error-path sweep reddens the
after-removal test. Mutations restored from a `cp` snapshot; `grep -c MUT` = 0 after.

The sibling `purge_ledger_rows` sits in the identical position and fails open the same way.
**Not fixed here** — its blast radius is every submittable doctype and the existing comment
says re-ordering it needs its own measurement. Filed as **#1158** with the evidence.

---

## My own PR went red on a gate the local hook skipped

`pre-commit run --files <changed>` printed

```
🕳️  Swallowed-Exception Guard (ratchet)......................(no files to check)Skipped
```

and exited **0**. CI's job of that name runs the harness-logger teardown census, which
reddened with 4 failures; the `validation` job runs the same suite, so **one cause appeared
as two red checks**.

The new log line was at `WARNING`, making it a 19th below-`ERROR` class-teardown record.
**Promoted to `ERROR` rather than renumbering the residual limit** — reaching that line means
the row is already gone *and* the sweep did not run, so orphans are certain to strand and a
later shard dies. That is the condition the `>= ERROR` stderr mirror exists to carry out of a
teardown. The census moves 21/3 → 22/4 and `RESIDUAL_BELOW_ERROR` **stays 18**: the gate's
rationale is unchanged rather than still-true-by-luck.

**Decide the level before the numbers.** WARNING grows the residual; ERROR moves `MRO_ERRORS`
with the call count.

### The prose was already stale, and nothing asserts it

`harness_logger.py` read *"they reach **TWENTY** logging calls ... of which **THREE** are at
ERROR"* and *"the 20 at 3"*. Both were **already wrong on develop**: #1154's first sweep had
moved the census to 21/3 and the paragraph was never updated. The census pins the *constants*
and only *quotes* the paragraph in a failure message — so the prose rots exactly the way the
paragraph below it claims cannot happen. Corrected, the fourth ERROR site named alongside the
other three, and the rot recorded in place.

---

## Merging a batch: check the combined tree, not the PRs

Several of these pin **tree-wide baselines** (order-dependence, harness-logger census,
log_error). Each was green alone — which is how a batch of green PRs makes develop red.

Before merging, all five code branches were merged into a throwaway worktree and the
aggregating gates run **on the combined tree**: census 9/9, order-dependence in sync with
gated total **1004** (no growth), log_error 951, duplicate-helper clean, swallow ratchet
clean. It found nothing, and it is still the only check that would have.

---

## Operating notes that cost something

* **`git checkout -B` bypasses git's worktree branch-lock.** Plain `checkout` refuses with
  `fatal: already used by worktree`; `-B` **succeeds**, checks the branch out in a second
  worktree, moves the ref, and the original silently desyncs into phantom `M`/`D` entries that
  look exactly like uncommitted WIP. Verified with a throwaway probe, not inferred. A rebase
  loop did this to five stale worktrees. **To tell phantom from real, diff the worktree
  against its ORIGINAL sha, not HEAD** — empty means nothing is at risk. Prefer
  `git worktree add --detach` for branch test runs: it takes no lock.
* **Merging a batch back-to-back stacks a CI run per push.** Seven merges produced **four**
  Server Tests runs, three for commits that were no longer the tip, and the only run that
  mattered sat queued behind them for over an hour. Cancel the superseded ones (their SHAs
  stay in history if anything needs bisecting) or space the merges.
* **An unfinished job's `conclusion` is the empty string, not `null`.** A filter testing
  `conclusion != null` reads it as finished and non-failing. Match explicit
  `failure|timed_out|cancelled` instead. Same family as `gh pr checks` exiting 1 on failure.
* **`gh pr merge --delete-branch` also removes the local worktree holding that branch** — four
  vanished this way — but **skips one holding untracked files**.
* **`server-tests.yml` only triggers on** `verenigingen/**/*.py|js`, `pyproject.toml`, or the
  workflow files. A docs-only PR showing zero shard checks is correct, not the
  "reads green while running almost nothing" trap. Check the paths filter before assuming.

---

## If you do one thing

**#1162.** It is a live 2-rows-per-failure amplification on a reachable page, its first row is
argument-inverted so it records no traceback (#602's class), and — the part that generalises —
**the path cannot be exercised by any test in this repo**, because `MollieBaseClient.__init__`
substitutes a dummy key whenever `frappe.flags.in_test` is set and `bench run-tests` always
sets it. No CI run, however thorough, reaches it. It was found by real invocation in a console.

That last property is worth a sweep of its own: **how much other `in_test`-gated production
code has never executed under any test?**

## Issues filed, with their boundaries

* **#1158** — `purge_ledger_rows` fails open identically. Mechanism established; *frequency*
  unmeasured, and the fix is probably not a straight copy.
* **#1159** — `test_documents` in the Mollie bulk-consumer suite: appended to 24 times, never
  read. The drain is what actually cleans that module. Low severity, misleading evidence.
* **#1161** — `get_member_primary_chapter`: three test-local shadows drop two of production's
  three filters, on the **invoice-attribution** path. *Not established:* whether any test
  currently passes only because of the looser rule — the discriminating fixture was not built.
* **#1162** — above. *Not established:* the population outside `verenigingen_payments/`, since
  #1144's census is directory-scoped and this was found by reading, not by a sweep.

Still open on **#1154**: the non-drain half is #390, and **how often the sweep fires in CI
remains unknown**. Note that `VERENIGINGEN_TEST_LOG_LEVEL` sets the *logger's* level, not the
`>= ERROR` mirror gate, so setting it alone would not surface the line — that number needs a
deliberately instrumented run.
