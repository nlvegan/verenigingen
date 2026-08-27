# Handoff — 2026-08-22f: the rollback that put it back

Picked up from `2026-08-22e-the-gate-that-was-only-advisory.md` with one instruction:
#477 is merged, continue with #433.

#433 is fixed and closed. But the fix is the least interesting thing that happened. Three
times in this session something I had measured turned out to be measured with the wrong
instrument — and the third time, the wrong instrument was hiding a whole class of leak
that the ratchet cannot see by construction.

> **An instrument that reads "clean" is not evidence until you know what it would read if
> things were dirty.** `cleanup_status == "skipped"` means "did not exist when I looked",
> not "is gone". An orphan count for stranded ledger rows reads 0 either way once the
> naming series rewinds and the name is reused. Both of those read clean on a defect that
> was leaving two submitted Sales Invoices on the site every single run.

## Landed

| | | |
|---|---|---|
| #486 | the drain fix, 4 changes + 6 tests | **merged** `5816ae6b`, 43/43 green |
| #433 | submitted Membership the drain could not delete | **closed** |
| #482 | `EnhancedTestCase`'s drain has no ledger carve-out | filed |
| #483 | `TestCleanupManager` rolls back and abandons the rest of the cleanup | filed |
| #485 | 34 remaining invisible `frappe.logger()` calls in test `except` handlers | filed |

## What #433 actually was

The issue body blamed a missing cancel-before-delete. The base class already has one. It
ran, and it **raised** — and the CI log had said why all along, one line above the leak:

```
Could not cancel Membership MEMB-26-08-0169 before delete:
  Could not find Membership Type: Test Membership Type XH1L0LOu
```

The previous session's comment on the issue got that far and stopped. The missing step:
**it is not the Membership's link that fails.** `_cancel_if_submitted` sets
`ignore_links`, and `Document._validate_links` returns early on `_action == "cancel"`
anyway. The throw comes from a nested save — `Membership.on_cancel` →
`pause_dues_schedule()` saves a **Membership Dues Schedule**, and *that* document's own
`membership_type` link is what fails.

Which is why every proposed fix aimed at the Membership was going to miss: **a cancel can
be broken by state on a different document entirely.** So the fix stops requiring the
cancel to succeed. When `doc.cancel()` raises and the row carries no ledger rows, roll
back to the savepoint and write `docstatus = 2` directly, so the delete can still remove
it. Cancelling is the means; removing the row is the end.

## Still unreconstructed, and say so

**What deleted that Membership Type in CI is not known.** Within one connection a
transaction-wide rollback removes rows in creation order — it cannot take away a
Membership Type created *before* a Membership that survives, and CI's
`Success 2 | Skipped 1 | Failed 1` requires exactly that. Something *deleted* it.

No local run has ever reproduced it, across two sessions and four test sites: the module
is green because `builder.cleanup()`'s Member cascade removes both Memberships before the
drain ever sees them.

Best remaining candidate is **#483**: `TestCleanupManager.cleanup` (`factories.py:204`)
rolls the whole transaction back and **re-raises on its first error**, reached from
`builder.cleanup()` *before* the drain — and on develop that raise was caught by a logger
that writes nowhere CI reads. The fix does not depend on knowing; change 4 is what will
make the next occurrence readable.

## My own regression: a condition I did not notice was load-bearing

Change 2 moves the drain's transaction-wide rollback out of the per-document loop. I
hoisted it and made it **unconditional**, which looked like a simplification.

It is not. The old rollback was reached only inside `if frappe.db.exists(...)`, so **a
class whose tests track nothing never rolled back at all**. Unconditional, it discards
uncommitted `setUpClass` fixtures — which are not the test's to discard — and kills them
for every later test in the class.

**6 of 12 CI shards red.** Every single failure was a second-and-later test of a class,
dying in `_validate_links` on a fixture its own `setUpClass` had created:

```
Could not find Chapter: Test Chapter 1 - 68755102
```

That is the #330 failure mode, re-created by a one-line widening. The condition is
restored, and `ClassFixturesSurviveTheDrainRollbackTest` now pins it: delete the condition
and it reads `[True, False]` locally — the CI failure, reproduced in 27 seconds.

**Nothing local caught this.** Ten modules and the whole harness self-test suite were
green before that push. It needed shard scale, which is CI's to prove, exactly as
CLAUDE.md says.

## The finding that paid for the session

Chasing the *other* red shard produced this. On **untouched develop**, one instrumented
line of drain output:

```
DRAIN ACC-SINV-2026-03841 status=skipped exists_after_teardown=True docstatus=1
```

Read it slowly. `_cleanup_member_customers` deleted that invoice (uncommitted). The drain
checked `frappe.db.exists`, found it gone, and recorded **`skipped`**. Then a *later*
per-document `frappe.db.rollback()` — one iteration further down the same loop — **put the
row back**, and that iteration's `frappe.db.commit()` made it permanent.

A submitted Sales Invoice, resident on the site, that the drain believes it deleted.

**It is invisible to the leak ratchet by construction**: the ratchet reports rows the drain
FAILED to delete, and this one was never reported as a failure. It is a sibling of the
blind spot `known_test_leaks.txt` already documents ("an orphan whose parent deleted
cleanly"), and nobody had noticed it.

Counted on the same site, both trees:

| tree | submitted Sales Invoices left per run of `test_event_driven_payment_history` | TEST-LEAK lines |
|---|---|---|
| develop | **+2** | 0 |
| #486 | **0** | 0 |

The fix is ordering: one rollback per teardown, **before** `_cleanup_member_customers`,
never interleaved with the deletes. Then the cleanup's deletions are not silently undone.

I did **not** raise a leak baseline. `known_test_leaks.txt` says it plainly — the numbers
may only fall, and an entry there is a debt, not a permit. When the newly-visible leaks
first appeared I was one step away from re-baselining them; reading the file's own header
is what stopped it.

## Two instruments that lied

Both of these were used *by me*, this session, to conclude "no problem here":

1. **An orphan count for stranded ledger rows.** `SELECT ... WHERE NOT EXISTS (parent)`
   read **0** on both trees. It is worthless: `revert_series_if_last` rewinds the series
   when the last voucher in it is deleted, the name is reissued, and the stranded rows
   have a live parent again. The reviewer's probe caught what mine could not — one reused
   `ACC-SINV` name carrying **2, then 4, then 6** GL Entry rows over three runs. Assert on
   the specific voucher, never on a global join.

2. **`cleanup_status == "skipped"`.** See above. It means "did not exist when I looked".

And a third, from the same family, about logging:

3. **`frappe.logger().error(...)` "is seen because ERROR passes the level filter".** It is
   not. A bare logger carries only rotating **file** handlers with `propagate=False`, so
   the record lands in `logs/frappe.log`, which CI does not upload. Canary in both
   directions under `bench run-tests`: `print` → captured output 1×, log files 0×;
   `.error()` → log files 1× each, captured output **0×**. Confirmed against the shard-9
   log of #423 — **zero** occurrences of the swallowed message that produced #433's leak.

   Two teardowns in this repo had already "fixed" a `.warning()` to `.error()` *with a
   comment explaining why that was enough*. CLAUDE.md told them to.

## Read the repo before writing the helper

`verenigingen/tests/harness_logger.py` already exists, does exactly this, and its docstring
already carried the measurement above. I wrote four fresh `print()`s and three copies of
the explanation before a review pointed at it. The pre-implementation checklist's first
line is "search for existing utilities", and I did not.

Census on develop: **39** bare `frappe.logger()` calls inside `except` handlers under
`verenigingen/tests` (24 `.warning` — dropped on level before the handler question even
arises — 8 `.error`, 7 `.info`). Five are fixed here, chosen because they are harness-owned
and the message is the only record of a swallowed failure, including
`singleton_backup.py:201` (`Failed to restore <Single>`, a cross-test contamination vector
that announced itself nowhere). The other 34 are #485.

## What the skeptical review got right, and where I diverged

Run before opening the PR, per the standing rule. It earned it: it found that change 2
made a **pre-existing unguarded force-delete effective**, and reproduced the stranded GL
rows deterministically by simulating CI's worker-free shape. I reproduced it independently
with a test of my own before acting.

I took its diagnosis and **not** its suggested fix. It proposed guarding
`_cleanup_customer_dependencies` with `_has_ledger_rows` and skipping posted vouchers.
Measured, that turned clean removals into reported leaks in two modules. The reason is a
setting nobody had looked at: `delete_doc` removes a voucher's ledger rows only when
`Accounts Settings.delete_linked_ledger_entries` is on (`AccountsController.on_trash`), and
`0` is that field's doctype default. So the cleanup now **takes the ledger rows with the
voucher**, which is what erpnext itself does when asked, and both the strand and the leak
go away.

It also noticed the main checkout — the tree veg11 is served from — was sitting on my
feature branch. It was, and it is back on `develop`.

## For whoever picks this up

1. **#483 is the live thread on #433's root cause.** If that leak ever fires again, the
   log will now say why (change 4). Read the shard log for the *builder cleanup* failure
   before reading anything else.
2. **#482 is a real divergence, not a tidy-up.** `EnhancedTestCase._remove_drained_record`
   has no ledger carve-out, and 805 files mention that base against 304 importing the other
   one.
   The fix belongs with a test that pins the carve-out for **both** drains; it currently
   pins one.
3. **The CLAUDE.md correction is not version-controlled.** `~/frappe-bench/CLAUDE.md` is
   not in any git repo, so the `frappe.logger()` entry I rewrote — and its pointer to
   `harness_logger.py` — lives only on this box. If the bench is rebuilt it is gone.
4. **`test_membership_application` is not a usable signal on `test_site_1`.** It fails on
   both trees and leaks ~35 Chapters per run on both; the failing test name tracks how
   dirty the site is, not the branch. It cost two runs to establish that.
5. Not deployed. The merge is on `develop`, which the live veg11 tree fast-forwards to on
   its own; the change is test-harness-only.
