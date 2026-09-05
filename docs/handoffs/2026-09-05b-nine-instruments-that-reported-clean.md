# 2026-09-05b — nine instruments that reported clean while checking nothing

The session's finding is not any single defect. It is that **nine separate guards,
scanners, tests and log calls in this repo were reporting success while having checked,
recorded, or run nothing** — and not one of them ever produced a red test.

| what | how it reported clean |
|---|---|
| `scan_order_dependence.py` given a FILE path | `os.walk` on a file yields nothing → `Total findings: 0`, exit 0 |
| its COMMIT exemption | keyed on a bare function *name*; a rename erased a finding with no trace |
| the #481 `NON_RESUMABLE_DB_ERRORS` guard | unreachable for **16 of 50** endpoints — their own `except Exception` catches it one frame below |
| the swallow guard's `_is_falsy_return` | reachable only from `ast.Return`; a handler that *assigns* a sentinel was invisible |
| `_is_test_file()`'s directory markers | hid **40** real `test_`-prefixed modules from the quality enforcer |
| 19 test bodies | wrapped their own assertions in `except Exception`, so they could not fail |
| `frappe.db.exists(dt, dt)` | **always truthy for a Single** — every "seed if missing" branch was dead |
| `_check_period_anchor`'s except branch | logged through a level-filtered `LazyServiceLogger`; not even the file CI never reads |
| 7 `frappe.log_error(message, title)` calls | swap heuristic only fires on a newline, so the diagnostic landed truncated in the wrong column |

Each was found the same way: **by asking what the code does on its own failure path.**
Six of today's PRs therefore ship a *standing control* — a planted known-bad input the
instrument must catch on every run, each proved by breaking the instrument and watching
the control fail (#910, #915, #916, #920, #922, plus ratchets in #908 and #913).

## Merged (29)

#827 #834 #836 #839 #840 #843 #844 #847 #848 #849 #855 #858 #859 #862 #864 #869 #871
#874 #876 #877 #879 #880 #881 #883 #886 #887 #888 #895 #902

Two that changed the day:

- **#902** — CI concurrency. develop had **43 of 83 active runs**, jobs queued 5h+ never
  assigned a runner. Not an outage, not billing, not cross-repo (all ruled out by API).
  Five workflows had **no concurrency group at all**, so each of ~7 merges/hour stacked.
  Per-ref groups + `cancel-in-progress`; `server-tests.yml` deliberately untouched, since
  its per-commit group buys per-merge attribution. Also scoped `pylint.yml`, the only
  workflow with a bare `on: [push]` — it was firing a 3-job matrix on every branch push.
  **Result: develop 43 → 11 active runs.**
- **#895** — two e_boekhouden suites shared bare ledger IDs (`8100`/`4100`/…). `E-Boekhouden
  Ledger Mapping` is global, so whichever `setUpClass` ran first won, and the other's type-7
  fixtures hit "Account does not belong to Company". Ambient across **six** PRs.

## Open (29 PRs)

**Blocked on one merge:** **#912** (one line, regenerates the order-dependence baseline
after #886 added two commits in test *bodies*) unblocks six PRs failing a gate none of them
tripped. Auto-merge is armed; `develop` is governed by **rulesets**, not classic branch
protection, so `gh api .../branches/develop/protection` returns 404 while merges are still
gated.

Billing: #892 (#890) reviewed APPROVE · #893 (#882 guard, silent-logger defect fixed) ·
#898 (#885) · #919 (#796)
Security: #896 (#878) · #903 (#693) · #904 (#785) · #915 (#505) · #924 (#692)
Money: #899 (#872, revised after review) · #905 (#863) · #907 (#856) · #909 (#711)
Instruments: #908 (#668) · #910 (#851/#825) · #913 (#490) · #916 (#601) · #920 (#801) ·
#922 (#496, reviewed APPROVE + CI enforcement added)
Other: #900 (#889) · #901 (#631) · #911 (#852) · #917 (#821) · #923 (#845/#846)

## Filed today (12 new)

#894 #906 #914 #918 #921 #925 #926 #927 #928 #929 #930 #931

Worth reading first:

- **#925** — an **expulsion** claims to strip roles to Guest; `User.validate()` re-derives
  `roles` from `role_profiles` on that same save and silently undoes it. Measured: the
  terminated volunteer kept *every* Volunteer-tier role, only `enabled=0` changed.
- **#926** — a failed `cancel()` still writes `docstatus=2` before `on_cancel` runs, so the
  exception tells you nothing. The three JE discard helpers always return `None` and cannot
  report which happened.
- **#906** — `process_application_refund` builds a Payment Entry with no `paid_from`, so the
  refund path fails at `insert()` and **cannot reach** the submit defect #863 is about.
- **#921** — eight `test_`-prefixed modules with nothing runnable; one defines `test_*()`
  functions outside any TestCase, so they never execute.

## For next session

### 1. Merge order

**#912 first** — six PRs are red on a gate none of them tripped. Then **#898**, because
develop currently carries a query-count cap of 300 while the bug lands at 277: *the gate
cannot catch its own regression right now.*

### 2. The billing thread is still unmeasured against production

#882's query was run and **could not answer the question**. veg11's invoice history arrived
*with* the data copy (newest invoice 2026-07-04; the site's own Error Log starts 2026-07-26),
so it measures another test system, and carries uncleaned remnants that cannot be filtered.
The scripts are read-only and re-runnable — **run them against production**.

What *was* established, and it changes #884's proposed fix: **a span check is the wrong
test.** All 431 coverage-stamped invoices span exactly one quarter, and 427 of them are
anchored to the *calendar* rather than the member's cycle. A length-only assertion passes on
every one. Assert the period **START**.

### 3. #884 is now unblocked-ish

It touches `membership_dues_coverage_analysis.py`, which #892 holds. Safe once #892 lands.

## What I got wrong

- **Three of ~25 dispatches were unworkable**: #370 and #601 already fixed (never closed),
  #778 not yet built (depends on unmerged #777). All three preventable by two greps —
  `git log origin/develop --grep="#<n>"`, and a grep for the issue's central symbol to
  confirm it exists on develop. **Now a standing instruction in CLAUDE.md.**
- **I relayed "three shadows are live today" as fact.** Review found two of three don't
  hold — and the PR's own hook description said "all latent", contradicting its body.
- **I reported #879/#883/#886 as open PRs blocked by an ambient failure.** They were merged;
  I measured "behind develop" against stale remote-tracking refs without pruning.
- **I reported CI as "0 jobs running"** from a truncated `gh run list` sample — the same
  truncation trap the previous handoff records. Real figure: 83 active runs.
- **I said pushing a branch triggers no CI**, and briefed ~12 agents on that basis. `pylint.yml`
  was `on: [push]` unqualified with a 3-version matrix — roughly 36 jobs I added to a starved
  queue while carefully holding PRs back. Fixed in #902.
- **I mis-framed #796**: its issue is mostly a deferred *design* decision; I briefed only the
  failure case. The agent fixed what was fixable and named what it wasn't deciding.

## What worked

**Briefs that demanded the premise be re-verified.** The issue text was wrong or incomplete
in #852 (wrong collision mechanism — it's a global `random.seed(12345)` making co-tenants
draw *identically*, not a 1-in-3 clash), #885 (the "~227 baseline" everyone quoted was already
wrong pre-#844; real control is 257), #668 (90 not 94, wrong in both directions), #505 (16 not
11, including a genuine writer), #496 (issue *and* its own review both undercounted), #692
(premise depended on a hook withdrawn the day after filing).

**Agents catching their own tests being inadequate**, unprompted: #821 mutation-tested its
assertion and found it green whether or not the fix worked; #872 found its test double had
flattened away the pagination it was meant to exercise; #496's first guard draft reproduced
the exact `BaseTestCase` trap the issue's reviewer had flagged.

**Naming the file another PR owns, in every brief.** It stopped #778 from duplicating #777's
field, and kept #852 out of `enhanced_test_factory.py`.

**Skeptical review changed the outcome on 4 of 5 PRs reviewed** — #872's sliding-window sweep,
#893's silent logger, #922's overstated claim plus its missing CI enforcement, #897's
per-process caveat.
