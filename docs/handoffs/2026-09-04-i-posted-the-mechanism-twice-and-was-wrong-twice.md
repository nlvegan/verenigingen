# Handoff — 2026-09-04: I posted the mechanism twice and was wrong twice

Continues [2026-09-03d](2026-09-03d-one-of-two-hundred-and-twenty-five.md), whose PR (#800) was
still open when this session began and was merged during it.

**9 PRs merged, 9 issues closed, 8 filed, 2 closed unmerged.** Two waves of four agents on filed
issues, then one deep investigation that took the second half of the session.

The title is the session's own failure. #815 is a test-ordering defect I reproduced reliably and
then explained **wrongly, twice, in public comments on the issue**:

| I posted | what was true |
|---|---|
| "the commit is redundant; delete it" | deleting it broke **16 of that module's own 24 tests** — load-bearing for a naming-series deadlock |
| "it leaks by flushing the preceding module's pending rows" | adding `rollback()` before the fixtures fixed nothing — the victim still failed |
| "there is no caching on that path" | `AssignmentQueryBuilder` caches on `frappe.local`, keyed `f"{volunteer_name}:{method_name}"` — **that was the whole bug** |

Both wrong mechanisms were corrected on #815 rather than quietly edited. The third claim is the
one that matters: I read `volunteer.py` and `assignment_service.py`, declared the path cache-free,
and **never opened the third file in the chain**. A dispatched agent found it in one pass.
Reading two of three files and reporting a negative is not a measurement.

## The actual mechanism, for the record

A test shard runs as ONE long-lived `frappe.local`, so a cache Frappe intends to be
request-scoped becomes **shard-global**. When a rolled-back test's naming-series counter reverts,
a later Volunteer can be autonamed the same as an earlier one, and the query builder serves the
earlier volunteer's cached assignments instead of querying. The bare `frappe.db.commit()` I
chased for hours was a **trigger** — it changes *when* the counter reverts — not the cause.

Fixed in #816, merged (test-harness only, no production code). Production is safer than the issue's first
draft implied: `frappe.local` is torn down per request there, and volunteer names are never
reused. #817 records the wider class.

## Gates caught what review passed — three times

1. **#804**: the duplicate-helper ratchet rejected `--update-baseline` on a 15th `_make_account`
   clone. That fix's own review had approved it. Consolidated into
   `verenigingen/tests/support/test_accounts.py`; the gate went 553 → 552.
2. **#816**: the swallowed-exception ratchet caught the #815 fix adding a **`warning`-level log in
   class teardown**, where the `>= ERROR` mirror gate discards it — a smaller instance of the
   silent-handler family the fix existed to close. Two skeptical-review passes had approved that
   diff. Now `error`, with the baseline and `harness_logger.py`'s prose numbers updated
   deliberately.
3. **#818**: the review caught *me*. My new ratchet was **defeatable by self-baselining in the
   same PR** — the shrink gate compares against `git show HEAD:<path>`, the PR's own baseline.
   Every sibling ratchet carries a second step diffing against `pull_request.base.sha`; I had
   omitted it. Reproduced: self-baselined probe → exit 0; honest forgot-to-regenerate → exit 1.

Yesterday's lesson was "a dead gate launders approval". Today's is its complement: **the ratchets
are the highest-yield reviewers this repo has**, and the one I added was worthless until review
found its hole.

## Four instrument failures, all mine

Each reported confidently while measuring something else.

- **`show_test_shards.py` was validated, then silently stopped being valid.** It reproduced CI's
  pre-rebase layout exactly (`test_team_coverage` #110, `test_volunteer` #111, matching the log).
  After the rebase it listed 117 modules where CI ran 116, omitting the very chapter and volunteer
  modules that mattered — and I kept using it. **Taking the order from CI's own log reproduced the
  failure on the first attempt.**
- **Two local sites, both invalid, in opposite directions.** `test_site_4` is migrated but carries
  1326 Members / 1671 Chapters / 49 Volunteers and produced 19 failures CI does not have.
  `test_site_fresh` was clean but **unmigrated** (no unique index on `tabVolunteer.member` — the
  #456 signature). Only after `bench migrate` on the clean site was a replay meaningful. Four
  attempts measured site state, not ordering.
- **`bench run-tests --module A --module B` silently honours ONE module.** 30 tests ran where two
  modules were asked for — the victim's count alone. I nearly reported that as "co-tenancy does
  not reproduce it".
- **`nohup … &` escapes the harness.** The "completed" notification was the *launching shell*
  while the real work was still on early modules. Use Bash `run_in_background` on the command
  itself.

## A near-miss worth reading

`git push --force-with-lease` issued as its own tool call ran in the **main checkout**, which has
`develop` checked out, and attempted `develop -> develop`. **Only branch protection stopped it** —
`--force-with-lease` would have been *satisfied*, since that tree's develop was in sync with the
remote. The shell cwd resets between calls; keep the `cd` and an explicit `origin <branch>` in the
same call. That checkout also serves veg11. A related slip the same hour: a `git worktree add`
with a relative path landed **nested inside another worktree**.

## Other corrections to my own record

- **"0 inbound links, verified with a control"** — measured with `check_if_doc_is_linked` in its
  default `method="cancel"` mode, while `delete_doc` uses `method="delete"`. Different question.
  24 Payment Ledger Entry rows were in fact blocking. The control fired correctly on a Donation,
  so the instrument worked; I pointed it at the wrong question.
- **A deletion script's trailing `frappe.db.commit()`** persisted **52 unintended cancellations**
  on veg11 after every delete in the loop had failed. It now commits per row.
- **"#811 causes this"** — said when the failure survived a rebase. It does not: #802 and #804
  both ran `✔ test_add_activity` in *their* shard 10, which shares only ~63 of 116 modules with
  #811's. #811 changed the layout, nothing more.
- **"a leaked re-entrancy guard would silently disable a sync"** — both guards reset in `finally`.
  Caught before filing #817, so it never shipped.

## What merged

- **#802** (#529) — a test helper called `sepa_xml_service._create_sepa_xml_structure`, which
  exists nowhere; its own `except` swallowed the AttributeError, so **9 SEPA XML compliance
  assertions had never run**. Test-integrity, not a money path — I framed it wrongly at first.
- **#803** (#798) — `_factory` in a filename hid real test modules from every check. Filed #801:
  the `/tests/fixtures/` and `/tests/utils/` markers hide ~38 more, including 2 of the 9 files
  #798 itself named.
- **#804** (#788, #789) — `"Asset"`/`"Income"`/`"Expense"` are `root_type` values written into
  `account_type`. Its review caught that making the P&L scan testable had **exposed a whitelisted
  `company` parameter**, letting any logged-in user read another company's P&L.
- **#805** (#792) — a report filter that silently did nothing. The agent **rejected its own first
  fix**: tightening the vacuous tests to `assertEqual(count, 1)` still didn't discriminate,
  because each fixture had only one overdue invoice.
- **#806** (#679, #772) — 16 of 57 JS call targets dead. #679 had **already been fixed** by #771
  and stayed open only because no commit carried a closing keyword.
- **#807** (#781) — SEPA agreements with no mandate now refused at the API boundary.
- **#816** (#815) — the cache isolation above. Test-harness only: no production code.
- **#818** — the order-dependence ratchet (below).
- **#811** (#809) — the Mollie idempotency unique index, declared as a Data Custom Field so
  `migrate` stops stripping it. Merged after this document was drafted; see below.
- **#800** — the previous handoff.

Four issues stayed open after their PRs merged, because the PR titles referenced them
**parenthetically** — `(#788, #789)` — with no closing keyword. Closed manually with the mechanism
recorded. That is the exact inverse of #792's auto-closure from prose yesterday: GitHub acts on
the keyword, not the intent, in both directions.

## Filed

- **#815** — the order-dependence defect: minimal reproducer, bisection table, mutation control,
  and both of my wrong mechanisms recorded as wrong.
- **#817** — `frappe.local` census; 16 custom attributes are shard-global under the runner.
  Compiling it **found a live defect**: `frappe.local.generation_rejections` has **no writer
  anywhere**, so its `hasattr` guard is always False, `result.rejection_reasons` never leaves its
  dataclass default, and `membership_dues_schedule.py:1144` surfaces that permanently empty key.
  Its test asserts `== {}` — passing *because* of the bug.
- **#812** — 3 dead `frappe.call` targets in doctype-level JS, which **neither** endpoint guard
  scans. (A first pass said 4; two were framework endpoints, and one of the three is a repointable
  wrong path rather than a missing function.)
- **#813** — the donation form reports success when periodic-agreement creation fails; the failure
  is discarded at **two** layers, so a donor sees "Thank you for your donation!".
- **#814** — no doctype-level SEPA/mandate invariant, so both existing guards are boundary-only.
- **#801** and **#809** — the `_is_test_file` directory markers, and the index-scoping problem that
  became #811.

## The 911 bare commits, and why #818 does not sweep them

`scan_order_dependence.py` reports **911** `frappe.db.commit()` sites in test code across 337
files. #818 ratchets the count **upward-only** and fixes none of them, deliberately: #815's commit
was a trigger, removing it broke 16 tests, and 1005 findings have produced exactly one known
defect. Blocking new ones is worth it; paying the debt would trade a latent ordering risk for
hundreds of red tests.

Two things found while building it:

- **The scanner's default root hid its own motivating case.** `verenigingen/tests` yields 808
  findings; the whole package yields 1005. The 179-finding / 63-file difference includes
  `test_contribution_amendment_request_coverage.py` — the #815 file — because test modules also
  live beside the code they cover. A ratchet on the old default would have been born blind. Same
  class as #798.
- **`COUNT` detection is structurally unreachable here.** It fires only from `visit_Compare`, while
  every count assertion in this codebase is `self.assertEqual(frappe.db.count(DT), n)` — an
  `ast.Call`. `COUNT=0` across 337 files means "cannot fire", not "none exist". **Disclosed in the
  scanner docstring and the generated baseline header rather than fixed**, because widening
  detection would add findings in the same PR that introduced the gate — precisely what the new
  "Baseline did not grow" step rejects. It needs its own PR.

The review also reconciled a count I had left unsettled: 1151 raw sites − 240 inside the
documented `_cleanup_`/`_create_`/`tearDown` exemption = **911**, matching the scanner exactly. My
earlier 1101 was a different measure (functions, broader root).

## Duplicate work, and the inventory that caused it

**#808 was closed as redundant.** PR #776 had been open ~14 hours with **#744 in its title**, and I
dispatched an agent onto #744 anyway — the wave-2 shortlist came from open *issues* and I never
checked open *PRs*. Worse, #776's fix is better: it throws on an unmapped payment method where
mine silently coerced any unknown value to `"Other"`, which would have written `"Other"` onto a
signed ANBI agreement. #807 overlapped #776 too but survived — it guards a different entry point.

**Before dispatching, diff open-PR file lists, not just issue numbers.** Two of the three
collisions were invisible from titles.

## Operational, done and verified

- **#797** needed `reload-doctype "Direct Debit Batch"`. The working tree was **42 commits
  behind**, so the JSON was not even on disk. Pulled, reloaded, verified `Partially Collected` in
  both `tabDocField` and the cached meta, then `bench restart` (fresh gunicorn, HTTP 200).
- **veg11's #811 blocker cleared.** 52 leaked Enhanced Factory Payment Entries and their 24
  Payment Ledger Entries deleted after a full backup (`20260904_100848`, 961 MiB). Zero orphaned GL
  or ledger rows afterwards, and #811's own detector confirms the patch would now proceed. Creation
  dates spanned February to June — this leaked repeatedly — and 48 PLE rows for that test customer
  remain, attached to other vouchers.

## For next session

**Resolved before this document was pushed.** #811's run on `5b27dc7db` came back green and it
is merged (`3775742a3`), closing #809. That run was the test of the #815 diagnosis, and the
diagnosis holds: shard 10's log carries `✔ test_add_activity` under
`verenigingen.verenigingen.doctype.volunteer.test_volunteer.TestVolunteer` — the module that was
red — with all 12 shards green. #816 did close #815; no reopening needed. The honest scope: this
proves the test passes under *this* shard packing. Shards re-pack on measured runtime, so it does
not prove the original co-tenancy is now safe — only that the develop-side cache-scoping fix
removed the failure everywhere this run looked.

1. **#817's `generation_rejections`** is the cheapest real fix on the board: populate it, or delete
   the dead read and the always-empty key its consumer exposes, and tighten the test that currently
   asserts the broken state.
2. **The `COUNT` gap** in `scan_order_dependence.py` — its own PR, per above.
3. **#776 and #777** are pre-existing and red. #776 needs a rebase; merge it before #807's
   territory drifts further.
4. **~100 stale worktrees**, several locked. Given this repo's note about a moved branch ref
   desyncing the veg11 tree, clean up deliberately rather than in passing.

**And the habit to carry forward.** Every one of my three wrong mechanisms died to a check I could
have run before posting: import the module and look, run the arm with a control, open the third
file. The agents that succeeded today all did the same thing — instrument the reproduction and read
real values. The ones that produced nothing ended a turn waiting on a background job.

https://claude.ai/code/session_01TS8PzQDJZXjpgmtzhVJo7K
