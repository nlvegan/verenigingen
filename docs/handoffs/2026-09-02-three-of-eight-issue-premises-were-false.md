# Handoff — 2026-09-02: three of eight issue premises were false

Eight of the oldest open issues, worked by parallel agents. **Seven PRs open (#725, #727,
#728, #729, #730, #732, #734), one issue closed without code (#618), three follow-up issues
filed (#726, #731, #733).**

The useful finding is not any single fix. It is that **three of the eight issues were wrong
about the fact that made them issues**, and in each case the wrongness pointed the fix in a
direction that would have removed working code. CLAUDE.md already says a "Suggested fix"
section has been wrong 8-for-8. This session extends that: **the premise is unreliable too,
not just the proposed remedy.**

| issue | the premise | what was actually true |
|---|---|---|
| #562 | two modules depend on a tree root nobody seeds | one does. The other calls `ensure_prerequisites()` immediately before its assertion, which **self-heals** the row. Left untouched. |
| #596 | Frappe never runs a child DocType's `validate()` | too broad. A child loaded and saved **standalone** (`frappe.get_doc(child).save()`) *does* dispatch it — and two production sites do exactly that. Blanket deletion would have removed live validation. |
| #619 | the method has **no production caller**, so this is only a doc defect | it has two. `invoice_generation_orchestrator.py:66` → `EligibilityChecker.check_eligibility()` → `eligibility_checker.py:372` → `membership_dues_schedule.py:568` → the target. Deleting it — which the framing invited — would have cut live invoice-eligibility code. |

All three were caught by re-verification the agents were *told* to do before fixing. None
would have been caught by reading the issue carefully.

## The rule that earned its keep: review the round that answers the review

Every first-round PR had a skeptical review, and in every case **the review changed the
fix**. But the commit that *answers* a review is itself unreviewed, and this repo has
recorded that failure before. Second reviewers were dispatched on the answering rounds of
#725, #727, #728, #729. Two of four found real defects:

- **#728** — two confirmed defects, including one I had flagged and the reviewer nailed down
  with a measurement I had not made (below).
- **#725** — a whole error class left silently unhandled (below).
- **#727** — approve, plus a second writer of the new sentinel that the author never found.
- **#729** — approve, clean.

Round 1 of #729 also claimed to be "comment-only" and **was not** — it silently changed a
returned `reason` string and broke a test. A review that only reads the commit message would
have passed it.

## Three findings worth keeping

**1. A guard can protect the wrong branch.** #728 added
`if original_default is not None: frappe.db.commit()` in a test's `finally`. It reads like
caution. It skips the commit exactly when there is nothing to restore, and fires exactly when
the company *has* a bank default — the normal case. Measured across all five disposable
sites: `_Test Company` (test_site_1–4) has NULL, but **test_site_5's default company has a
real one and no `Mollie` account, so the test's `skipTest` does not fire and the commit
does**, committing that test's own untracked Donor/Donation/Customer rows. That is the #581
TEST-LEAK mechanism the commit message itself cited as the thing to avoid. The precedent it
named for the same operation (`test_sepa_reconciliation.py:1608-1637`) does not commit at all.
Removed; the branch now adds **zero** commits.

**2. `frappe.log_error` inside a wildcard `doc_events` handler is infinite recursion.** #609's
normaliser needed visibility, and `log_error` writes an Error Log **document** — whose insert
re-triggers the same `"*"` handler. Reproduced as a real `RecursionError`. Use a plain file
logger in any `"*"` handler. This is new; it is not in CLAUDE.md.

**3. `NON_RESUMABLE_DB_ERRORS` is `(QueryDeadlockError, QueryTimeoutError)` — 1213 and 1205
only.** #572 named a third class, lost connection (2006/2013), and it is still swallowed at
`eboekhouden_rest_full_migration.py:3214`, `:3248`, `:3733`. Verified empirically by
constructing real `MySQLdb.OperationalError(2006/2013, …)` on this bench: `is_deadlocked`,
`is_timedout` and `is_interface_error` are all False, and the pymysql backend matches only
MariaDB server-side codes, never client-side `CR_SERVER_GONE_ERROR`/`CR_SERVER_LOST`. **Not**
fixed in #725: that tuple is imported by **32 production files**, so widening it inside a
narrow eBoekhouden PR repeats the mistake #572's own body warned against. Filed as **#731**,
with `KNOWN GAP (#731)` markers at all three sites so #572 cannot close looking complete.

## #609 is live, and it taxes unrelated PRs

PR #729 is comment-only and byte-identical in behaviour, and its shard still went red:

```
TimestampMismatchError: ACC-SINV-2026-00007 (Sales Invoice) has been modified after you
have opened it (2026-09-02 04:05:30, 2026-09-02 04:05:30.127247)
```

at `test_erpnext_integration_comprehensive.py:514`, an `insert()`→`submit()` with no reload —
#609's site #1. Grepping the shard log for #729's own identifiers returns **0**, which per
CLAUDE.md's rule rules out its code. CI reported `Failing: 0, Errors: 1` then
`NEW (regressions): 1`, reddening a PR that could not have caused it.

**The fingerprint did not match the issue's**, and that mattered. #609 documents memory
holding `'…000000'` against a whole-second DB value. Here the **DB** side is the whole second
and memory carries `.127247`. Handing that discrepancy to the agent forced two corrections:
the wildcard hook moved `after_insert` → `on_update` → finally **`on_change`**, the only
unconditional event (`on_update` misses `db_set`, `cancel()`, and saves on already-submitted
docs). A normaliser keyed only on `.000000`-in-memory would have closed #609 while the
observed failure kept happening.

Also corrected: **CI runs frappe 16.33.0**, not 16.31.0 as #609 states.

## Read CI carefully before blaming a branch

`Tests (4/12)` failed on **four unrelated PRs** (#725, #727, #729, #730) on the same test,
`test_batch_validation_service_coverage.TestValidateCollectionDate.test_within_window_is_valid`.
That file uses `datetime.now().date()` — the process clock, UTC in CI — while the code reads
the site clock (Asia/Kolkata, +5:30). The jobs ran 22:36–23:52 UTC, inside the documented
**18:30–24:00 UTC** red window. This is #722, and **PR #724 already fixes that exact file and
is unmerged.** Merging #724 removes this failure from every open PR.

#730's *other* five shard failures were **not** ambient — 11 errors concentrated in Chapter
Board Member / Team Member / Volunteer territory, exactly where it turned dead validation back
on. Root-caused and fixed (`5147ba4b1`); they split cleanly in two, and both halves are worth
knowing:

**10 of 11 were a real `TypeError`, and it reveals a trap.** `Team.validate_team_member_rows()`
and `Member.validate_iban_history_rows()` compared dates with a bare `<`. **`frappe.utils.today()`
returns a `str`, while a DB-loaded row's Date field is a `datetime.date`** — so the idiomatic
`row.to_date = today()` on an already-loaded row makes the comparison raise `TypeError`, not
`ValidationError`. The save *crashes* instead of validating. This was latent in the dead code
all along: it never ran, so it never crashed. Reviving it exposed it. Fixed by normalising
through `getdate()` on both sides.

**1 of 11 was a genuinely too-strict new rule.** `test_board_members_only_respects_is_active_and_term_end`
deliberately saves a board row with `is_active=1` and a past `to_date`, because the segmentation
feature's design assumes that stale combination occurs (a direct Desk edit sets one field without
the other) and defends with date filtering rather than forbidding the state. The new
`validate_single_board_member()` made that a blocking error, rendering the Chapter unsaveable in
a state the rest of the codebase treats as ordinary. **The test was right and the rule was wrong** —
downgraded `add_error()` → `add_warning()`, no test changed.

That ratio is the lesson: when newly-live validation reddens a suite, most of it is usually the
revived code's own latent bugs, not the tests being wrong. Blanket-updating the tests to match
would have buried a real crash.

## Environment: this bench does not isolate agents

Two agents independently hit this, and it is a real risk for any future multi-agent session:

- Other sessions **wrote code directly into another agent's worktree**.
- A stray `git checkout origin/develop` **wiped a branch out of a working directory** (recovered
  from the pushed remote — commit and push early, as CLAUDE.md already says).
- `test_site_1`'s **Redis hook cache was poisoned twice** by a concurrent branch's `bench`
  activity, producing transient `ModuleNotFoundError`s. Fix: `bench --site test_site_1 clear-cache`.
- `test_site_1` was **contended** by a concurrent test run (found via `pgrep`); `test_site_2`
  was clean. A red run there is not evidence until you check who else is on the box.

Also: **`/home/frappeuser/frappe-bench/CLAUDE.md` is not under version control.** `frappe-bench`
is not a git repo. #602's trap entry was written there — correct location, but it exists only
on this box: not in any PR, not in CI, not visible to anyone else. Anything that must survive
belongs in `apps/verenigingen/CLAUDE.md`.

## State

| PR | issue | note |
|---|---|---|
| #725 | #572 | abort+report on non-resumable; gap #731 marked in code |
| #727 | #562 | 3 roots seeded via harness bases; gate conjunct moved off a forgeable row |
| #728 | #582/#583 | zero commits added; converged on `get_eur_bank_account` |
| #729 | #619 | comment-only, verified byte-identical |
| #730 | #596 | 6 rules moved to parents, 9 deleted, ratchet added; 11 CI errors root-caused and fixed |
| #732 | #602 | 152 sites swept, 774 baselined, validator + CI |
| #734 | #601 | narrow heuristic; 35 sites classified, none fixed (per #589 precedent) |

Follow-ups: **#726** (`_retry_transient_failures` swallow), **#731** (2006/2013),
**#733** (4 assign-swallow sites that poison a cache or lose an audit trail).

Unclosed by choice: #602 leaves **774** sites baselined; #601 fixes **none** of its 35, matching
how #589 handed off to #593; #619's class grep traced 7 of 66 — start any follow-up at
`events/subscribers/member_subscribers.py:88`, same shape, bulk call site never traced.

Merge order: **#730 and #734 both edit `.pre-commit-config.yaml`** (additive; second one rebases).
Merge **#724 first** — it clears a failure currently red on four of these PRs.
