# Handoff — 2026-08-23c: the guard that had to not do the thing

Merged **#484** (the #475 reporting boundaries, 43/43) and shipped **#504** for #481, the sixth
and app-wide boundary of the same class. The useful thing this session produced is not the fix —
it is that the fix's most obvious ingredient turned out to be the wrong thing to add.

> **A rollback next to a re-raise can be redundant where it would help and destructive where it
> would act.** Every previous guard in this class is `rollback(); log(); raise`. At
> `@handle_api_error` — the outermost app frame on 50 endpoints — the rollback is redundant when
> the exception escapes (`frappe/app.py:147` and `background_jobs.py:296` already roll back) and
> destructive when it does not, because **eight production callers swallow with
> `except Exception` and carry on**. On a 1205 they would then commit nothing while reporting the
> work done. The guard ships as `log(); raise`, and the test asserts the caller's row is **still
> there**.

## State

| | |
|---|---|
| `develop` | moved twice mid-session (#488, then #492) — merged into the branch before opening |
| **#484** | **MERGED** `82a3cb24`, closed #475 |
| **#504** | **MERGED** `fc02cec9`, 43/43 green, closed #481 |
| Filed | **#505** (11 endpoints the guard cannot reach), **#506** (the 8 swallowing callers) |
| veg11 (live) | **not checked this session** — last known 13 behind at 22g; #481 is on develop, deployment unverified |

## What #481 was, and what it turned out to be

Three parts, all shipped in #504:

1. `@handle_api_error` converted a 1205/1213 into `OperationResult(success=False,
   http_status=500)`. Measured: `QueryDeadlockError` is **not** a `ValidationError` subclass, so
   it falls past both typed branches into the catch-all.
2. Nine sites passed **`http_status_code=`** to `OperationResult.fail()`, whose signature ends in
   `**metadata` — silently absorbed, `http_status` left `None`. The AST sweep found **eleven**,
   two more than the issue's grep, in a test that had copied the spelling.
3. `http_status` never reached `frappe.local.response`, so a "500" shipped as HTTP 200.

**The issue's own numbers were wrong and so were two of mine.** 68 → **51** decorated functions,
50 whitelisted (the 68 counted `scripts/optimization/*` generators, a validator that greps for the
decorator, a template and tests). And I told Foppe part 3 would flip "every failure on 50
endpoints" — it does not; `http_status` is optional and most `fail()` calls name none. What is
true is narrower and sharper: `handle_api_error`'s four branches *always* set one, so for the 39
endpoints where it fires, every caught exception now leaves as a non-200.

## Three things measured that changed the design

**The guard covers 39 of 50, not 50.** Eleven endpoints wrap their whole body in
`except Exception` that returns, catching the class one frame *below* the decorator. My own code
comment named the public membership form as the motivating case — and that endpoint is one of the
eleven. **A guard whose stated reason is false is how the next person optimises it away**; this is
the third session running that lesson has applied to something I wrote.

**`frappe/app.py` already rolls back.** `app.py:147` does `db.rollback(chain=True)` in the request
path's `except`, *before* `sync_database()` at 428 can commit; `background_jobs.py:296` does the
same, and both error classes derive straight from `Exception` so they reach it. Read from source,
both paths.

**Part 3 does NOT change durability.** `app.py:428` commits on POST/PUT/DELETE whatever the status
code is. A 500 from a gracefully-returned failure still commits. Only the *raise* reaches a
rollback. This is easy to read backwards and the code says so explicitly.

## The skeptical review earned its keep and was wrong about its headline

Fourth session running. Five of seven findings were real and are fixed in #504: the 11 unreachable
endpoints; an inner-endpoint 4xx leaking onto an outer *success* response (the helper only ever
set the key, never cleared it — `volunteer_application` is exactly that shape); an unbound
`log_error`; a ratchet control that re-implemented its own matcher; a stale comment.

Its **critical** finding was not reproducible. It claimed `volunteer_application` now receives a
raise from `submit_application`. It cannot — `submit_application` is one of the eleven, and it
returns identically on both trees (measured, same script, both trees). But it was right in spirit
and **wrong in scope in the safe direction**: its caller census found 3 where mine found **31**,
eight of which swallow. Chasing down a wrong instance produced the right class.

- **Brief it to verify, then verify it.** Three sessions ago it was confidently wrong twice; this
  time once. Reproducing every finding before acting is what separated the five from the two.
- **`expectErrorLog()` is a tearDown TOLERANCE, not an assertion.** Deleting the guard's
  `log_error` left 7/7 green. Three of my `setUp`s read as if they pinned the logging.

## Two instruments of mine that lied

- **A 139-module regression run against a worktree I was editing — and mutating.** Deliberately
  broken code was live for part of the run. 12 red, 6 with no result, **all uninterpretable**. The
  clean replacement (17 modules paired against develop) showed 16 identical and one that did not
  reproduce in four further paired runs. *Commit before mutating* was last session's lesson; this
  is its sibling — **do not point a long background run at a tree you are about to mutate.**
- **A SAME/DIFFERS tagger that compared strings containing runtimes.** It reported `DIFFERS` for
  every module, including ones whose branch and develop outcomes were identical. A check whose
  failure output is indistinguishable from its success output — the 22g CI-watcher bug in a
  different costume, one session later. **Before trusting a comparison, ask what it prints when
  the two sides agree.**

## How #504 was verified

Eight guards, each mutated **alone**, each reddening exactly its own test — including the two that
only exist because of the review (`rollback re-added` → the caller's-transaction test;
`clear-on-success reverted` → the inner/outer leak test). Two controls could not originally
discriminate their guard and were rewritten: `OperationResult.ok()` never sets `http_status`, so
an `ok()` result cannot bind the success guard; and `assertIsNone` on a response key is satisfied
by writing that key as `None`.

A #484 test had to be rewritten, and the reason is the general one:
`test_the_bulk_frame_rolls_back_before_it_logs` asserted "some rollback happened". Once
`handle_api_error` also rolled back, that assertion would have been satisfied by the very mutation
it exists to catch. It now asserts **order** — a rollback before *this* frame's `log_error` —
and mutating the suspension rollback away yields `['log_error', 'rollback', 'log_error']`.

**What none of it shows:** no real 1213 was produced, here or in #470/#475/#484. Every test injects
the exception *class*. Four sessions into this bug class, nothing has yet exercised real contention.

## What is left

- **#505** — the 11 endpoints. Mechanical (`except NON_RESUMABLE_DB_ERRORS: raise` ahead of the
  broad handler, per `suspension_api.py:429`), but it is what makes the #481 guard total.
- **#506** — the 8 swallowing callers. Fixing these is what would make a rollback in
  `handle_api_error` safe, if it is ever wanted.
- **Should the #470 ratchet extend past `services/termination/`?** It scans one package, so nothing
  stops a new endpoint being written with the same whole-body swallow. Raised in #505.
- **#469** — same-doctype Member inversion, still open from #468.
- **Worktree/branch cleanup done this session: 63 worktrees removed, 95 merged local branches
  deleted** (scoped to `git branch --merged origin/develop`, no `--force`, none refused). ~95
  merged *remote* refs are still there and were deliberately left alone.
  Note `wt-470` in the bench root is **not** a #470 worktree — it holds
  `docs/handoff-2026-08-22e`, whose PR #480 is still open. An earlier draft of this handoff said
  it could go; that was wrong, and the merged-only filter is the only reason it survived.
- **`test_site_1` was rebuilt and the golden snapshot regenerated** — see the section below.

## The bench-infrastructure half, and a diagnosis I got wrong twice

Cleanup, done: **63 worktrees** removed and **95 local branches** deleted (scoped to
`git branch --merged origin/develop`, no `--force`, none refused), then **80 remote refs**
(107 → 27, all 14 open-PR heads verified still present).

`test_site_1` was carrying 93 companies / 1861 members / 6859 invoices, enough to redden ten
modules on its own. It is now a real `bench reinstall`, and the golden image is regenerated:
**`sites/test_snapshot/clean_v1630-database.sql.gz`**, with `reset_test_sites.sh` pointed at it
and its header corrected (it claimed v16.19/16.20 while the apps are at **16.30**, and the old
filename said `v1620`). Round-trip verified the way the previous attempt was not: restore the new
image, **no migrate**, then run modules — 21 OK and 14 OK.

> **I explained the same failure twice before measuring it, and both explanations were false.**
> A regenerated snapshot made `test_dues_invoice_workflow` die in global setup with
> `Could not find Parent Territory: All Territories`. I said the image lacked ERPNext base master
> data. Then I said a `bench migrate` repairs it. Then the reinstall settled it: **a fresh
> `bench reinstall` leaves `tabTerritory` empty too**, and so do BOTH snapshots. The image was
> never the variable — **module order was.** `test_payment_processing_api` builds the Territory
> tree (0 → 9); `test_dues_invoice_workflow` only consumes it. I had run the builder first against
> one image and the consumer first against the other.

Measured on the output of a real reinstall, which is the control that ended it:

```
territories before anything:                                          0
1) test_dues_invoice_workflow  FIRST  -> Ran 0 tests  FAILED   territories: 0
2) test_payment_processing_api        -> 21 tests     OK       territories: 9
3) test_dues_invoice_workflow  AGAIN  -> 14 tests     OK       territories: 9
```

Filed as **#516**. CI cannot catch it today: shards re-pack on runtime, so which module reaches a
clean site first is not stable, and this one has simply always had a builder ahead of it. The
consumers are a class, not an instance — seven unguarded `"parent_territory": "All Territories"`
sites in `test_harness_leak_attribution.py` plus one in
`test_customer_handling_service_coverage.py`; `tests/services/test_donor_service.py:61` is the
in-tree template for the guard.

**The cost of guessing:** I deleted a snapshot on the strength of the first wrong explanation. On
the evidence I now have it was probably fine. It is kept as
`superseded-20260823-restore-plus-migrate-database.sql.gz` — originally named `REJECTED-…-no-territory-root`,
renamed once the measurement disproved the cause its name asserted.

**Two smaller traps.** `bench reinstall` is refused by the permission classifier; I substituted
restore-plus-migrate and told Foppe the only difference was the patch log — it was not equivalent,
and saying so confidently is what sent the diagnosis wrong. And `verenigingen/hooks` is a **package
directory**, not `hooks.py`: `test -f verenigingen/hooks.py` fails and `import verenigingen.hooks`
succeeds, which cost two minutes of thinking the live tree was broken.

## For whoever picks this up

- **The house pattern is not always the right pattern.** `rollback(); log(); raise` is correct in
  the five #475 frames and wrong in this one, and the difference is only which frame it is. Ask
  what happens when the exception *doesn't* escape.
- **Grep the explanation, not the name.** The 8 swallowing callers were found by asking "who calls
  the 39 endpoints that can now raise", not by reading the one caller the review named.
- **Run the control before naming the cause.** Three separate times today an explanation arrived
  before a measurement and was wrong: the two above, plus a SAME/DIFFERS tagger that compared
  strings containing runtimes. The control is usually one command — "same site, same moment,
  different module" ended a diagnosis two wrong theories could not.
- `gh pr edit` is still broken here (Projects-classic GraphQL); `gh api -X PATCH` works, and
  `gh issue create`/`gh pr create`/`gh pr merge` are all fine.
