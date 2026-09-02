# Handoff — 2026-09-03: three ways to pass without checking anything

Continues [2026-09-02b](2026-09-02b-the-gate-that-fails-on-the-good-direction.md), whose
"later the same day" section covers the two CI reds that opened this session. After those
landed, four issues went to parallel agents. **6 PRs merged, zero left open, 3 issues filed,
1 issue closed with no code because its premise was false.**

The title is the pattern that connects almost everything found today. Three times, in three
unrelated places, something reported success **while checking nothing** — and in all three the
green was produced by a different mechanism, so no single habit would have caught them:

| what passed | why it meant nothing | how it surfaced |
|---|---|---|
| a test fixture's amount bracket | it **samples**: `25.0 + n/100` is only sometimes representable, so 968 of 1000 counter values pass and 32 fail | a develop merge shifted the counter onto n=301 |
| `child_table_creation_validator` | it loaded **0 doctypes** from an out-of-bench worktree and printed `✅ No child table creation issues found!` | a class audit of the issue I had filed about a *different* validator |
| two of #758's new tests | a **downstream gate** fixed in the same commit threw for the same reason, so the site under test could be reverted with the test still green | mutation testing in a second review round |

None of the three would have been caught by reading the code, and all three were green in CI.
The generalisation worth keeping: **"the check passed" is not a fact about the code until you
know the check can fail for the reason you care about.** Mutation is the cheap way to find out,
and it is now three-for-three at finding things review-by-reading missed.

## The false premise, and why it was convincing

**#745** claimed a donor who ticks "create periodic agreement" gets the donation and agreement
created, no confirmation email, and an error message — caused by `donation_form.py:230` calling
`.get()` on an `OperationResult` dataclass.

The dataclass genuinely has no `.get`. The issue even carried a probe proving it. But the probe
constructed an `OperationResult` **by hand**; at the real call site the value never arrives in
that form, because `create_periodic_agreement` is wrapped by `@high_security_api`, whose wrapper
calls `.to_dict()` before returning. Live through the whitelisted entry point, the caller gets a
plain dict and `.get()` works.

That is the confirming-vs-discriminating distinction in its purest form yet seen here: the
evidence was real, reproducible, and about the wrong object.

The reported *symptom* has a larger cause. `get_or_create_donor` and `create_donation` pass
`override_user=` to `secure_document_operation` — **a parameter that has never existed**
(`git log -S`). Every call to `process_donation_form` dies with `TypeError` before anything is
created, which also contradicts the issue's claim that the donation and agreement *do* get
created. The two swapped `log_error` calls in that handler are why nobody ever saw the
`TypeError`. Filed as **#755**, including the reachability question: no `Web Form` with
`route="donate"` exists on either site checked, and `/donate` is served by unrelated code.

**Running total: 10 false premises across three sessions, every one pointing toward deleting or
rewriting working code.**

## A gate that refuses is safe. A gate that passes is not.

I filed **#752** after hitting it myself: `doctype_name_validator.py` resolves its DocType
authority by walking up for a directory containing both `apps/` and `sites/`. A worktree under
`/tmp` has no such ancestor, so it loads 0 doctypes and **refuses** with
`RuntimeError: refusing to run`. That refusal is correct — a census against the wrong tree would
be compared to a baseline it has nothing to do with. What made it worth filing is the escape
hatch: it is a pre-commit gate with no `BENCH_APPS` override, so the obvious way past a blocked
commit is `--no-verify`, which disables **every** hook over a location detail.

I wrote "other validators may share this; unchecked" in the issue. They do — **4 sites, and the
third was worse than the one I found.** `child_table_creation_validator.py` does not refuse. It
reports success. Measured from the identical out-of-bench location, same commit:

```
out-of-bench:  📋 Child Table Validator loaded   0 child table DocTypes  →  ✅ passed  (instant)
in-bench:      📋 Child Table Validator loaded 462 child table DocTypes  →  real scan (minutes)
```

**Scope, stated narrowly:** CI checks out as `<root>/apps/verenigingen` beside `<root>/sites`, so
the walk-up resolves there and the merge gate was never blind. The exposure is local pre-commit
runs from worktrees — which is how most agent work in this repo gets committed, so an unknown
number of commits passed that check vacuously. Fixed in **#757** via a shared
`scripts/validation/bench_resolution.py` that falls back to `git rev-parse --git-common-dir`
(which finds the main checkout from any linked worktree), plus a `BENCH_APPS` override and a
refusal message that names the remedy. Verified against the **merged trunk**, both directions:

| validator | pre-fix, out-of-bench | post-fix, out-of-bench |
|---|---|---|
| `doctype_name_validator` | exit 1, `refusing to run: the authority does not know 'User'` | exit 0, passes |
| `child_table_creation_validator` | 0 doctypes, vacuous pass | 462 doctypes, real scan |

A 4th site (`validation_suite_runner.py`) was deliberately **not** fixed — manual stage only,
never blocks, already broken by an unrelated `ModuleNotFoundError`. Saying which one you did not
fix is part of closing a class.

**Operational rule this produces: agent worktrees must live under the bench**, not in `/tmp`.

## The masked test: green CI on a suite that could not fail

**#758** converges four hardcoded `or 16` age fallbacks onto `AgeValidator._get_configurable_min_age`,
whose deliberate no-fallback policy they were defeating. It is the only PR today that changes
production *behaviour* rather than repairing something broken: a missing config now **refuses**
instead of quietly assuming 16, at sites including a guest-reachable volunteer path. It was held
back from merge for that reason alone, and a second reviewer was aimed at the commit that
**answered** the agent's own review — this repo's standing rule, because that round is itself
unreviewed.

It found, by mutation rather than by reading:

- **Two of the four new tests did not test the site they named.** Both call chains reach
  `Volunteer.insert()`, whose `validate_volunteer_age()` was fixed in the same commit and throws
  for the identical config error. Reverting *only* `BulkVolunteerCreationService.minimum_volunteer_age`,
  or *only* `vip_import._validate_volunteer_age`, left both tests green. Reverting both together
  did redden — which is exactly why the original red run looked like proof.
- **The answering round's own additions were untested.** Deleting either newly-added
  `frappe.clear_messages()` caused zero failures, despite the PR citing a precedent (#659) whose
  test *does* assert `message_log == []`.
- **The class was not fully closed** — a third `min_membership_age` reference survived in
  `validate_config()` in the very file the commit edited. A permanent no-op with zero callers, so
  harmless, but it is the "grep the explanation" rule failing at arm's length.

All fixed in round 3: the masked tests split into an isolated test (calling the property/function
directly, never constructing a `Volunteer`) plus a fuller-path test carrying the message-log
assertion. **Independently re-verified here, not taken on report:** mutating only the bulk-service
site now reddens exactly one test, the isolated one, out of 78.

The PR body's original claim — "each call site's test confirmed red against the prior fallback" —
was true only when all sites were reverted *together*. That sentence is what made round 1 look
verified, and correcting it mattered as much as the code.

**CI was green on the version the review rejected.** 47/47.

## What worked in the agent briefs

Four agents, four issues, disjoint file territories chosen so they could not collide on merge
(this repo has had two branches independently write the same fix and conflict). What earned its
place in the brief:

- **"Verify the premise empirically before writing code; if it is false, STOP and report"** —
  cited the 9-then-10 running count. One of four came back with exactly that outcome and opened
  no PR. Without the explicit permission, the likely failure is a plausible fix to a non-bug.
- **"A finding is a class, not an instance; report the count and the disposition of each."**
  #673 found 6 where the issue named 4. #752 found 4 where the issue named 1. Both reported what
  they left undone.
- **"Run a skeptical review before opening the PR."** All four did, and in every case it changed
  the work — a vacuous test, a Redis leak, a false-revert diff, an overstated commit message the
  agent then retracted.
- **Naming the environment traps** — worktrees under the bench, `test_site_2`'s ambient failures,
  the baseline-shrinkage ratchet. #673 hit the shrinkage trap and handled it unprompted.

**One brief gap worth closing.** The #685 agent wrote to **shared, bench-wide Redis** (which veg11
also uses) to clean 13 orphaned `rq:wip:long` entries its own test had leaked. It was surgical —
targeted `ZREM`, not a flush — and verified harmless afterwards (all registries and queue depths
at 0, nothing pending lost). But it was a shared-infrastructure write nobody authorised. Future
briefs should say: **no writes to shared Redis or shared config; report instead.**

Also worth recording: that agent **correctly declined** the brief's nudge toward `frappe.utils`
clock helpers. RQ's `started_at` is timezone-aware UTC, so `datetime.now(timezone.utc)` is right
and the site-local helper would have been wrong. A brief's guidance is a prior, not an instruction.

## Environment

- **The leaked `SEPA Direct Debit Batch Simple Workflow` is deleted from `test_site_2`** (it dated
  from a 2026-08-31 run whose cleanup did not complete). Deliberately narrow: only the `Workflow`
  document; its 6 states and 6 transitions were child rows and went with it. The shared
  `Workflow State` masters were **left intact** — the site's other workflow uses `Draft` and
  `Completed`, so deleting those would have broken something unrelated. Verified after:
  `test_collection_run_not_lost_silently` went from 4 failures to **22 tests, OK**. The code defect
  behind it (**#753**) is unchanged and reappears for anyone who invokes the whitelisted setup.
- A `bench console < file.py` probe reported nothing when its output was grepped; the delete was
  re-verified against the database instead. The repo already records this probe shape lying three
  times in one session — **verify a write by reading it back from the authority, not from the
  tool that performed it.**

## State

**Merged (6):** #749 (fan-out + its fixture's float bracket), #754 (posting_date midnight race),
#751 (handoff), #756 (`clear_stuck_jobs` dead under RQ 2.x — dead twice over: `rq.Connection`
removed *and* a naive/aware datetime subtraction that could only `TypeError`), #757 (bench
resolution, 3 of 4 validators), #758 (age fallbacks, after three review rounds).

**Zero PRs open at session end.** `develop` at `b2cb306e5`.

**Filed (3):** #752 (fixed by #757), #753 (open, decision needed: reconcile the workflow,
reconcile the field, or delete the setup as dead code), #755 (open, from #745's false premise).

**Closed with no code (1):** #745.

`develop` was verified green after each merge — separately from the PR checks, because a baseline
generated on a branch is a statement about that branch and not the trunk it lands on.

## For next session

- **#753 needs a human decision**, not more investigation. The evidence is complete.
- **#755** carries a reachability question with the same shape: fix the donation-form module or
  delete it as dead code.
- The **shrinkage-ratchet problem** from 2026-09-02b is still unfixed. It cost nothing today only
  because #673's agent knew to regenerate the baseline.
- **#672** (eight more age-computation sites) and **#675** (an import cycle) were deliberately left
  by #673's agent and are still open.
