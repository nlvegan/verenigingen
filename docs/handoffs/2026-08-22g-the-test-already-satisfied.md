# Handoff — 2026-08-22g: the test that was already satisfied

Fixed #475, the reporting-boundary half of #470, as **#484** (green, 43/43, unmerged). The
issue named three boundaries and the review that produced it found two more; there turned
out to be a further two siblings and a sixth, app-wide one. But the most useful thing this
session produced is a green test of mine that was worthless for a reason reading it could
never expose.

> **A test can be satisfied by an earlier line in the frame it is testing.** Mine asserted
> that a termination request goes back to `Approved` after a deadlock, and named
> `_record_failure_for_retry` as the code it protected. Deleting `_record_failure_for_retry`
> entirely left it **green** — because `_rollback_savepoint`, three lines above, already
> undid the `status = "Executed"` save. The assertion was true before the code under test
> ran. It was not tautological, not stub-defeated, not over-broad; it drove the real service
> end to end and asserted on real persisted state. Only mutation finds this.

## State

| | |
|---|---|
| `develop` | **`3d90ae34`** — moved once mid-session (#477 merged by another session) |
| **veg11 working tree (live)** | **`497ffb56`** on `develop`, **13 behind**, measured at write time. It was briefly checked out to `fix/drain-cancel-failure-leaks-submitted-record` @ `a836352e` mid-session and came back on its own. **Nothing from #475 is live.** |
| #484 | **43/43 SUCCESS**, `CLEAN`/`MERGEABLE`, head `064b045c`, 5 commits, **not merged** |
| Filed | **#481** — the sixth boundary, app-wide |
| Handoff slot | `e` and `f` were taken on unmerged branches; this is `g`. Filename and H1 claimed in one commit. |

## What #475 asked for, and what it was

#470 made 44 handlers under `services/termination/` re-raise a 1205/1213. #475 covered the
frames *above* that fix which turned the error back into an ordinary failure. Three named in
the issue, two added by the review that wrote it, and:

**Boundary 2 is worse than the issue says.** #475 states the dispatcher's generic `except`
branch runs and commits. It does not. With the exception converted to a return value, **no
exception branch runs at all** — `apply_event` takes its *success* path, `event.save()`
followed by `frappe.db.commit()`. The generic branch would at least have rolled back first.

**Boundary 5 was two frames**, because `bulk_suspend_members` catches everything
`process_member_suspension` re-raises. And the review then found **two more siblings**,
`suspend_member` and `unsuspend_member`, two functions above the one being fixed, in the
file already open in the editor. Same shape as #470 and #459 again: an issue names the
instance its author was looking at.

**A sixth boundary is app-wide and is NOT fixed** (#481): `@handle_api_error` has its own
catch-all on 68 endpoints, and `OperationResult.http_status` never assigns
`frappe.local.response.http_status_code` — so its `http_status=500` ships as **HTTP 200**.

## Three claims of mine that were wrong

**"The rollback is what makes the `log_error` below it land."** False. `tabError Log` is
**MyISAM**, therefore non-transactional; the row lands either way (measured with an
interleaved control — the Error Log row survived a rollback, a ToDo inserted alongside it did
not). The rollback is still load-bearing, for the **1205** case, where the half-applied work
is live and Frappe commits it at request end. That is now what the comment says. **An
exemption or a guard whose stated reason is false is how the next person optimises it away** —
the same failure mode as 22f's `_release_savepoint_safe` marker.

**"Guarding `process_member_suspension` alone would be a no-op."** Measurably false: with only
the inner guard, the loop does stop. What the outer frame owns is the rollback. As written,
the comment invited deleting the inner guard.

**The shared error builders "match what MariaDB actually emits."** Backwards. Frappe raises
`QueryDeadlockError(e) from e`, so a real one stringifies as `"(1213, '…')"` — errno included
— and the string matchers that exist (`billing_constants.py`) key on `"1213"`. The builders
are *less* faithful than a raw message, in the opposite direction to the claim.

## The instrument, and its own weakness

| what is enforced | instrument | blind spot |
|---|---|---|
| does a handler in `services/termination/` re-raise | #470's AST ratchet | **cannot see how a guarded handler REPORTS the error** |
| does the reporting survive the frame | the 19 behavioural tests here | one guard bound by nothing (recorded) |

Measured: delete boundary 1's guard and `test_termination_non_resumable_errors` still passes
**10/10**, because the remaining catch-all's `non-resumable-ok` marker stays a *true*
statement — the handler does end in `_handle_error`, which does re-raise. It just re-raises a
`ValidationError`. **The ratchet is a claim about handler shape and nothing else**, and that
is now written into its "what it does not enforce" paragraph, which is the paragraph that
otherwise tells readers they are covered.

One guard in `history_manager_utils` (the retry-after-cleanup path) is bound by no test;
reaching it needs a link-shaped `ValidationError`, `auto_cleanup` on, cleanup that finds
something, *and* the retry to then deadlock. The comment says so rather than letting the guard
above it imply coverage.

## How #484 was verified

Mutations, each applied alone:

| mutation | reddens |
|---|---|
| boundary 1 guard | 3 service tests **+ the composition test** |
| boundary 2 guard | MijnRood deadlock **+ the composition test** |
| boundary 3 guard | API deadlock |
| boundary 4 guard | direct **+ composition** |
| suspension inner | the loop stops |
| suspension outer | the rollback |
| all 10 guards widened to `except Exception` | **exactly the 5 controls, nothing else** |

Boundaries 1 and 2 are **coupled** — fixing MijnRood alone is a no-op while the service masks
the class one frame below — and `test_the_class_survives_the_service_so_mijnrood_can_see_it`
drives both real frames and reddens under either revert. That is the shape worth copying: a
test per frame says nothing about the composition, and the composition is what the fix is for.

Two gaps were found by mutation and by review rather than by writing:

- the **outer suspension guard** was bound by nothing (the inner guard already stops the loop,
  so the "which members were attempted" assertion could not see it);
- the **vacuous revert test** above.

**What this does NOT show:** no real 1213 was produced, here or in #470/#459. The tests inject
the exception *class*.

## Two self-inflicted errors, both repeats

- **`git checkout -- .` destroyed an uncommitted test.** 22f records this exact mistake. I
  read that handoff at the start of the session and still did it, because the destructive call
  was in a mutation-cleanup loop I had written for a different purpose. Commit *before*
  mutating; the cleanup path is where this hides.
- **A second CI-watcher bug, and again not in the query.** 22f's watcher used a `gh pr checks
  --json` flag that does not exist, with `|| continue` swallowing the error. Mine used
  `.conclusion // .state` — and a running CheckRun has `conclusion == ""`, which is **truthy
  in jq**, so the fallback never fires and every in-progress check reads as failed. It
  announced "20 of 39 NOT green" while nothing had failed. **Use `.status`
  (`COMPLETED`/`IN_PROGRESS`) as the completion signal.** The tell was that every offending
  line rendered as a bare name and a colon.

  Both bugs are in how the watcher classifies non-success. Before arming one, ask *what would
  this print if the run had already failed* **and** *what does it print while a check is merely
  running* — if those are the same string, it is broken. `mergeStateStatus: UNSTABLE` does not
  discriminate either.

## What is left

- **#484 is unmerged and green.** It closes #475.
- **#481** — `@handle_api_error` on 68 endpoints, and the `http_status` that never reaches the
  response. Needs its own decision: a one-line guard fixes all 68 but changes every response
  shape.
- **A contract change outside #475's scope**, called out in the PR rather than buried:
  `safe_child_table_update`'s other production caller,
  `fee_change_recording_service.py:158`, previously turned a 1213 into
  `RecordingResult(status="skipped")` and now propagates. Right direction; no test on that
  caller.
- **#469** — same-doctype Member inversion, still open from #468.
- `wt-470` is still live for #480, and this session's `wt-475` for #484. Remove each once its
  PR merges.
- `MEMORY.md` is ~700 bytes over its 24.4KB budget. Three duplicated index lines were dropped
  this session (net reduction) but it was already over.

## For whoever picks this up

- **The skeptical review earned its keep for the third session running, and again needed
  checking.** It found the vacuous test, the two unguarded siblings and the MyISAM correction;
  it also stated one thing loosely ("guarding the inner frame alone is a no-op" was *my* error
  it was correcting, and its own wording of what the inner guard does is the precise part).
  Every finding was reproduced before acting. Brief it to **verify**, then verify it.
- **Mutate by deleting the call the docstring names**, not just by breaking the feature. A test
  that survives deletion of the thing it says it protects is measuring something else. This is
  cheap and it has now caught a defect in three consecutive sessions' instruments.
- `gh pr edit` and `gh issue view --comments` are still broken here (Projects-classic
  GraphQL); use `gh api -X PATCH` and `gh api repos/{o}/{r}/issues/{n}/comments`.
- The harness Error Log guard will fail a test that logs an error without
  `self.expectErrorLog(...)`, and `@critical_api` hands callers a **nested dict**, not the
  `OperationResult` — both bit the controls in this module before they went green.
