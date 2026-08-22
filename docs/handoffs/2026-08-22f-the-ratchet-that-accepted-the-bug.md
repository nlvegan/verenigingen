# Handoff — 2026-08-22f: the ratchet that accepted the bug it blocks

Fixed #470 and merged it as **#474**. The issue asked for a three-line change in one
handler; the handler it named was the wrong one, and the ratchet I built to stop the
problem recurring turned out to accept the defect it existed to block.

> **A ratchet that reads the shape of a fix rather than its behaviour can be satisfied by
> the bug.** Mine checked that each catch-all was preceded by an
> `except NON_RESUMABLE_DB_ERRORS` clause. It never looked at the body, so
> `except NON_RESUMABLE_DB_ERRORS: frappe.log_error(...); return False` — the #470 defect
> wearing the right clause — passed. The docstring above it had already started telling
> people they were covered.

## State

| | |
|---|---|
| `develop` | **`73004afd`** — #474 merged. Moved three times during this session (`57318010` → `497ffb56` → `ff09648d` → merge) |
| **veg11 working tree (live)** | **`497ffb56`**, measured 2026-08-22 after the merge — **8 behind**. It was `df43b092` at session start and nobody moved it; that tree fast-forwards on its own, so re-measure in the same breath as any sentence about it. **#470 is not live.** |
| CI on #474 | **43/43 SUCCESS** on head `ac71c61b`, `mergeStateStatus: CLEAN`, no conflicts against the twice-moved base |
| Merged | **#474** (closes #470), 3 commits |
| Filed | **#475** five reporting boundaries · **#476** an inflated board-position count |
| Still open from #468 | **#469** same-doctype Member inversion |

## What #470 asked for, and why it was nearly a no-op

`TerminationExecutor.execute` catches every exception per operation, records it, and runs
the next one. #470 asked for a re-raise there. But each of the fourteen operations
delegates to a `*_safe` helper in `termination_integration.py`, and those catch first:

```python
try:
    chapter_doc.save()              # the Volunteer+Member lock from #459
except Exception as e:
    frappe.logger().error(...)      # the 1213 lands HERE
# the loop continues, saving further chapters on the discarded transaction
return positions_ended              # the caller records an ACTION, not an error
```

`chapter_doc.save()` is the call #459 established takes both row locks — the likeliest
deadlock site in a termination — and the executor's handler never sees it. The fix is 44
guards across the package, not one.

**The generalisation, and it is the same one as #459/#468:** an issue names the instance
its author happened to be looking at. Before implementing what an issue asks for, find the
layer that actually receives the error. Here that was one `grep` for what the operations
call.

## Three claims of mine that were wrong, and what caught each

**"Thirty-seven handlers."** It was 44. I counted `termination_integration` (35) and
`termination_operations` (2) before deciding to include `termination_utils` (7), and never
re-counted. Caught by the skeptical review, which counted two independent ways.

**"Reached from the innermost of three nested handlers."** It is the middle one; the
innermost wraps only a `frappe.get_doc`. Single-guard mutation is what settled it — and the
same mutation showed **two of the 44 guards have no behavioural coverage at all**, the
ratchet being the only thing holding them. That is fine as defence in depth, but the
mutation table read as if the tests covered more than they did.

**"`# non-resumable-ok: cleanup after the failure"`** on `_release_savepoint_safe`. Its two
call sites are the idempotency early-return and the success path; it is never called after
a failure. The exemption was right for a different reason (`RELEASE SAVEPOINT` takes no row
locks). **An exemption marker with a false reason is how a ratchet starts dying**, because
nothing machine-checks the reason — I measured that "because I said so" is accepted.

## The instrument, and its own weakness

Same progression as #424 → #436 → #459: each instrument was wrong for the previous one's
question.

| what is being enforced | instrument | its blind spot |
|---|---|---|
| does this handler re-raise | AST walk for a preceding `NON_RESUMABLE_DB_ERRORS` clause | reads the clause, never the body — accepts a guard that logs and returns |
| ...including future handlers | same, plus `BaseException` in the catch-all set | cannot check that an exemption's stated reason is true; that stays human |

Both holes are now pinned in `test_the_ratchet_sees_a_swallow_the_package_no_longer_contains`,
which feeds the walker literal source. That synthetic control is load-bearing for the same
reason as #459's: **once the package is clean, the ratchet passes on an empty list, which is
also exactly what a walker that silently matched nothing produces.** The exemption and
ordering branches are unreachable from the real files.

## How #474 was verified

Four mutations, each reddening its own test and no unrelated one:

| mutation | reddens |
|---|---|
| drop the guards in `end_board_positions_safe` | its helper test + ratchet |
| drop the guard on the duration recalc | its operation test + ratchet |
| drop the guard on `TerminationExecutor.execute` | executor test **and** end-to-end test + ratchet |
| plant an unguarded catch-all | ratchet only, naming the exact line |

Every non-resumable test has an ordinary-`Exception` twin. Without them the change is
equally consistent with "everything propagates now" — which is different, and wrong: partial
execution on ordinary errors is deliberate and load-bearing.

**247 tests green across 13 modules.** The suspension suites are in that list only because
the skeptical review pointed out `suspend_member_safe` and the team helpers are **shared**,
so this diff changes the suspension API surface too — something I had not considered.

## Two mistakes worth not repeating

- **`git checkout -- <file>` on uncommitted work.** I used it to revert a mutation and
  destroyed 35 guards, an import and a docstring. CLAUDE.md warns about exactly this. The
  edits were script-generated so it cost a minute — but the rule is simple: **commit before
  mutating**, then revert freely.
- **Two of my four controls asserted wrong values** (`Voluntary` maps to `Quit`, not
  `Terminated`; `end_board_positions_safe` returns 1, not 0, when the save fails). Both
  failed on the first run and both were *my* error, not the code's. The second one is now
  **#476** — a control that fails for an unexpected reason is a finding, not a nuisance.

## What is left

- **#475 — five reporting boundaries.** Three named in the plan (the service's
  `frappe.throw` masking the class as `ValidationError`; `MijnRoodTerminationSyncService`
  returning `{"success": False}`, which defeats the `except NON_RESUMABLE_DB_ERRORS` the
  dispatcher was deliberately given; `api/termination_api.py` at the HTTP boundary) plus two
  the review found (`safe_child_table_update`, `api/suspension_api.py`). Each needs its own
  decision about what to hand a caller, which is why they were not bundled.
- **#476 — the inflated count.** Swept the pattern: four functions increment in a loop, one
  is wrong.
- **#469 — same-doctype Member inversion**, still open from #468.
- **Nothing from #470 is live.** veg11 is far behind; re-measure before saying so.
- **No live deadlock has ever been reproduced** through the application, on #459 or #470.
  The tests inject the exception *class*. That opposite orders deadlock, and that 1213
  discards the transaction, is InnoDB semantics — not something this work shows.

## For whoever picks this up

- **The skeptical review earned its keep again, and needed checking again.** It found the
  ratchet hole — the most valuable finding of the session — and three false statements. I
  reproduced every one before acting; all four held. Brief it to *verify*, then verify it.
- **When a validator's own message suggests `--update-baseline`, read the baseline's
  header first.** The duplicate-helper gate failed on a second `_termination_request`, and
  regenerating was the obvious fix. The header forbids it: the file "should only ever
  SHRINK", it is "a to-do list, not a permission slip", and "consolidating never fails the
  gate". Consolidating into `tests/support/termination_request.py` left it at 568, unchanged.
- **`gh pr checks --json` does not exist in this `gh` build** — and I wrote a CI monitor
  around it anyway, with `|| { sleep 60; continue; }` swallowing the usage error. It looped
  for an hour and reported nothing, which is indistinguishable from "CI is still running".
  The fact was already in memory. Use `gh pr view --json statusCheckRollup`, and when a
  watcher's only output is good news, **ask what it would print if the thing had already
  failed.**
- `gh issue view --comments` is still broken here (Projects-classic GraphQL); use
  `gh api repos/{o}/{r}/issues/{n}/comments`. `gh pr edit` is still broken; use
  `gh api -X PATCH`.
- `verenigingen/tests/unit/test_termination_non_resumable_errors.py` is the gate for any new
  catch-all under `services/termination/`. Its class docstring states exactly what it does
  and does not enforce.
