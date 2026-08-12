# Handoff 2026-08-12 — measured premises, and tools that lie quietly

Eleven PRs merged, four issues closed, two new issues filed. The through-line worth carrying
forward is not any single fix: **three of the four issues worked here had a premise that did
not survive measurement, and in two cases the issue's own suggested fix would have done
nothing.** Two of the defects were in code shipped earlier in this same session.

---

## 1. What merged

| PR | | Merge |
|---|---|---|
| #296 | swallow ratchet learns this repo's error helpers | `7c771291` |
| #294 | previous handoff | `380e4ebc` |
| #301 | closes **#297** — failed-write guard learns the same helpers | `b9abc571` |
| #293 | retire the dead membership-type billing patch | `11e77353` |
| #300 | midnight date-rollover flake, 5 sites | `7eba2ce8` |
| #302 | closes **#299** — harness stops adopting a Company it does not own | `a775516d` |
| #303 | `show_test_shards.py`, the shard-layout replicator (#291 strand 1) | `15684f28` |
| #304 | #303's tests were location-dependent, and CI was not running them | `1f00c52a` |
| #305 | closes **#266** — `sync_team_with_volunteers` fan-out scoping (security) | `879fca82` |
| #306 | closes **#269** — one Member per User | `6990be42` |
| #307 | #303 could report a fallback layout as authoritative | `d39513c0` |

Closed: **#266, #269, #297, #299**. Partially addressed: **#291** (strand 1 done, A and B
split out). Filed: **#308, #309**.

---

## 2. The pattern: measure the premise, not just the fix

### #297 — the predicted improvement was zero

The issue said the failed-write guard's 162-site baseline "likely contains false positives"
from not knowing `handle_error`/`handle_service_error`, and that the delta would be the
false-positive rate. **Measured: 162 before, 162 after.** 32 in-scope broad handlers do call
those helpers, but **all 32 have zero persistence calls in their `try`**, so condition (1)
had already excluded every one. There were no false positives of that kind to remove.

The rule change still landed — condition (3) is now correct rather than accidentally correct
— but the PR says the prediction was refuted rather than dressing up a null result. **Zero
baseline churn is a better outcome than a regenerated baseline**, and would have been hidden
by "regenerate and move on".

`handle_error` is defined **three times** with different contracts, and the AST matches by
bare name:

| Definition | Propagates? | Off-switch |
|---|---|---|
| `services/infrastructure/base_service.py` | yes, `raise_error=True` default | `raise_error=False` |
| `verenigingen_payments/core/error_handler.py` | always — ends in `raise error` | none |
| `verenigingen_payments/utils/financial_error_handler.py` | only when `user_facing=True` | **`user_facing=False`** |

Porting #296 verbatim would have mis-handled the third. **#296 as merged still has that
blind spot** — currently harmless because `user_facing=False` appears only in test files,
which both validators skip.

### #299 — the stated mechanism was wrong, which killed the stated fix

The issue blamed "whatever order the database returns rows in". It is not arbitrary:
`Company` declares `sort_field: creation, sort_order: ASC`, and frappe applies the doctype's
meta sort whenever `order_by` is omitted (`db_query.set_order_by`). The query
**deterministically returned the oldest company**.

That matters because the issue's first suggestion — add an `order_by` — would have changed
**nothing**. The problem was borrowing at all.

| Site | Oldest Company (what the harness adopted) | |
|---|---|---|
| `test_site_1` | `_Test Company` | harness-owned, fine |
| **veg11** | `Nederlandse Vereniging voor Veganisme` | **140 accounts of real data** |

It escaped deletion only because that company happens to have both a non-group Receivable
and Payable account, so `_ensure_company_chart_of_accounts` early-returns. One missing
account and it would `DELETE FROM tabGL Entry` and force-delete all 140.

**And the guard I reached for first would not have helped.** I built "refuse if the company
has GL entries", then measured: the live company has **zero**. It is kept as defence in
depth for the caller-supplied path, with the PR stating plainly that picking by name is the
load-bearing fix.

### #269 — I got it wrong first and corrected it

Found 11 Members sharing one user on test_site_1, created inside a **17-second window**, and
concluded one run produces 11 duplicates so CI would break. **Wrong.** On test_site_2 with
the index actually built, per-test cleanup deletes each Member before the next is created,
**0 rows remain** after a full run, and all 12 tests pass **with no fixture change**. Those
11 rows are debris from a run that died before cleanup.

The fixture change was kept on the narrower claim that survives: under the new index a
leaked Member makes the **next** run's first test fail on a collision it did not cause — and
test_site_1, the bench default where developers run tests by hand, holds 11 such leftovers.

Of the two write paths #269 flagged, one held and one did not:

- `member_user_account_service.py` links an existing User with **no** check that it is free
  — the real defect, and it goes through `save()` so the new guard catches it.
- `account/account_creation_service.py` **already refuses** a User linked to another member.
  Its `db.set_value` bypasses `validate()` so only the index covers it, but its own check was
  never missing.

### #266 — demonstrated rather than argued

`sync_team_with_volunteers()` with no `team_name` fanned out over `frappe.get_all("Team")`,
gated only by `has_permission("Team", "write")` **with no doc** — role layer only, and
`team.json` grants `Team Lead` write with no `if_owner`.

Against the old line: **`AssertionError: 5 != 1`.** Five teams synced, one of them theirs.

The audit the issue requested came back **clean** — the other three endpoints in the module
are already doc-scoped (including `get_role_profile_preview`, which the issue suspected), and
`team_admin_utilities.py`'s `get_all` fan-outs are gated to `@require_roles(ADMIN_PAIR)`, the
same roles `_is_team_admin` grants all-teams access to. Recorded so nobody redoes the search.

---

## 3. Tools that lie quietly — both mine, both shipped this session

`show_test_shards.py` (#303) replicates CI's 12-way shard layout. It had two defects that
only appeared when it was *used*:

**#304 — a location-dependent test about location handling.** `_bench_root()` hopped a fixed
number of `..` from `__file__`, right for the installed checkout and wrong from a worktree.
Its unit test asserted the **cwd's** bench wins, which is backwards; it passed only because
it ran from a worktree where `__file__` is outside any bench. Installed, the correct branch
took over and the test broke. And **nothing was running those tests**: `get_all_tests()` only
walks `apps/verenigingen/verenigingen`, so tests under `scripts/` are invisible to the app
suite — #303 passed 26 checks without executing one of them. Now wired into
`code-validation.yml` beside the `scripts/validation/tests` steps.

**#307 — a fallback layout presented as authoritative.** frappe's `_get_measured_weights`
locates `test_timings.json` by splitting on `"/apps/"` and returns `{}` on `ValueError`. An
app imported from anywhere outside a directory called `apps` gets **no** measured weights and
every file falls back to the `def test_` count heuristic:

| Source | Files | Total weight |
|---|---|---|
| installed checkout | 1310 | **17094** |
| worktree under `/tmp` | 1310 | **22584** |

Both printed `patched=True`. Now reports `measured weights: N/M files` always, plus a loud
warning at zero. **My first version of that check could not fire** — it used the corrected key
derivation and reported 1306/1310 even in the broken case. A check for "what will frappe
find?" must ask frappe, not reimplement the lookup correctly.

**Rule:** for anything whose behaviour depends on its own location, the **install path is a
test case**. Verifying only from the worktree you built in is not verifying.

---

## 4. Durable facts measured here

- **`frappe.get_all` ordering is META-driven, not `modified desc`.** `db_query.set_order_by`
  takes the DocType's own `sort_field`/`sort_order`, falling back to `creation desc` only when
  the doctype declares none. `Company` declares `creation ASC` → **oldest row**. This is the
  opposite direction from `frappe.db.get_value` with a filter dict, which is `creation DESC`
  → newest row. **Never call an omitted `order_by` "arbitrary order"** — grep the doctype
  JSON's `sort_field` first.
- **`frappe.get_list` does not truncate.** Its docstring claims a default page length of 20;
  measured, 92 Companies come back with or without `limit`. The 20 applies to the REST path.
  `limit_page_length` is deprecated for v17 — use `limit`.
- **`handle_api_error` converts exceptions to `OperationResult.fail`** rather than raising, so
  a `frappe.throw` inside a decorated endpoint returns a failure object.
- **`MemberValidationService.execute_validation` returns `OperationResult.fail` and
  `Member.validate()` discards it.** A validation that must refuse a write has to `throw`; a
  collected error does nothing.
- **`bench run-tests` works against a worktree via `PYTHONPATH` shadowing.** CLAUDE.md says
  branch work "is verified by CI, not by running the suite from the worktree" — that is
  overly pessimistic. This is what allowed red→green proof for #302, #305 and #306 locally.
  Caveat: `get_all_tests()`/`get_app_path()` follow the import, so the shadow must be explicit.
- **`gh issue view` and `gh pr edit` fail on this repo** with a GraphQL projects-deprecation
  error. Use `gh api repos/.../issues/N` instead; issue creation via `gh api ... -X POST` works.
- **`bench run-parallel-tests` has no `--shuffle`/`--seed`/`--order`** flag
  (`frappe/commands/testing.py:383-405`). Order can only be changed via `--total-builds`, by
  patching `split_by_weight`, or by driving `ParallelTestRunner` with an explicit list.
- **`develop` is not branch-protected** (`gh api .../branches/develop/protection` → 404); the
  only ruleset blocks deletion and non-fast-forward. No required check names are pinned.
- **There is only one `patches.txt`**: `verenigingen/patches.txt`. Earlier notes referring to
  `verenigingen/verenigingen/patches.txt` are stale — that file does not exist.

---

## 5. Traps that cost time here

- **`gh pr merge --delete-branch` deletes nothing if a worktree holds the branch.** It fails at
  the *local* delete **after** the remote merge succeeded, and leaves the remote branch alive.
  Remove the worktree first, or clean up both refs by hand and verify.
- **`git stash push <untracked-file>` stashes nothing, so the following `pop` restores an
  unrelated pre-existing stash.** This pulled someone else's stash into a worktree and left
  `email_brand.css` in a conflicted `UU` state. Nothing was lost (the conflicted pop keeps the
  entry) but check `git stash list` before and after any scripted stash dance.
- **`test-quality-enforcer` permits `ignore_permissions=True` and `frappe.set_user` only in
  factory-style helpers**, matched by name: `_grant_`, `_make_`, `_insert_`, `_as_` (**with**
  the trailing underscore — `_sync_all_teams_as` fails, `_sync_all_teams_as_user` passes).
- **Bash tool calls time out at 2 minutes** regardless of an inner `timeout 1200`; pass the
  tool's own `timeout` (max 600000 ms) for suite runs.
- **Adding a step to an orchestration method breaks its mock-based unit tests**, whatever the
  step does. `TestMemberValidationServiceExecute` patches every DB-touching sub-validator and
  drives `execute_validation` with a `MagicMock`; a new step that queries the DB gets a truthy
  MagicMock as a filter value. Before inserting a step into a shared method, grep its callers
  for mock-based ones — verifying only the paths whose behaviour changed misses this entirely.
- **A fixed-email fixture loses an ad-hoc `Has Role` row** if granted before other fixtures:
  building volunteer/team rows re-saves the User, which re-syncs roles from role profiles and
  drops it. Grant the role **last**. A fixture guard asserting the actor passes the gate is what
  caught this — without it the test would have passed against the vulnerable code by never
  reaching the branch under test.

---

## 6. Open threads

**#308 (was #291 strand A)** — round 1's six failures are root-caused from the recovered CI
logs plus a replicated layout (victims landed in shards 3, 7, 8, 11 — the exact four CI
reddened). Two pollution, two dependencies, one of them *inverted* (a test that breaks when a
fixture **exists**). All five reduce to one anti-pattern: **a test resolves a shared fixture by
querying for it instead of owning it** — and `get_list("Company", limit=1)[0].name` appears
20+ times across the test tree. Note: all four modules **pass solo on test_site_1** because of
committed state; that is not evidence.

**#309 (was #291 strand B)** — 12 swallowed setup handlers with individual recommendations (8
should raise). Do the logger first: **every `.warning()` in `enhanced_test_factory.py` is
discarded**, because a bare `frappe.logger()` resolves to level ERROR under `bench run-tests`.
Until that is fixed, "make it fatal" is the only observable change. Highest-value single
handler: line **3606**, the root `Department "All Departments"` — the Territory bug verbatim.

**#291 strand C** — recommendation posted, not filed. Vary the shard count to **13, not 7** (at
7 the heaviest shard nears the 60-minute timeout); own `concurrency` group; **separate
baseline** because `known_test_failures.txt` is order-agnostic. Cheaper first step:
`--first` already names the 12 files with no predecessor, and a rotating solo-on-fresh-site
sweep is the only variant that catches the inverted dependency.

**Not fixed by #269:** `get_member_name_for_user` still falls back to matching `Member.email`
when the `user` link is absent (`utils/member_utils.py:102-108`). A unique index on `user` does
not constrain that fallback, so identity can still resolve by email inside an authorization
gate.

**Operator actions:**
- `bench --site test_site_1 migrate` will now **abort** with a list of 7 affected users until
  the leaked fixture Members are cleared. That is #306's patch working as designed.
- **Production has not been checked for `Member.user` duplicates.** veg11 is clean but is a test
  instance, and #268 was clean on production too while CI still found a live duplicate-producing
  path.
- `~/branch-recovery/2026-08-11/` holds the restore scripts for ~90 deleted branches, copied out
  of a session scratchpad. They are the only record of those SHAs.

---

## 7. Verification notes

#302, #305 and #306 were verified with red→green proof, not just a green run:

- **#302** — a planted company backdated so the *old* rule selects it: fails on old code with
  `'ZZ Foreign Co 299' not found in (...)`, passes on new. The sibling assertion passes either
  way on a test site, which is why the planted case exists.
- **#305** — `5 != 1` against the old `get_all` line.
- **#306** — verified on test_site_2 with the unique index **actually built** (`reload-doctype`
  from the worktree, `Non_unique=0` confirmed on `tabMember.user`), plus the patch exercised in
  both directions: no-op on a clean site, abort on test_site_1 naming 7 users.

#306 needed a second commit, and the failure is worth recording because it shows a gap in how
I verified. CI shard 3/12 caught:

    ERROR test_executes_all_validations
    _validate_unique_user_link -> frappe.db.get_value("Member", filters, "name")
    filters = {'user': <MagicMock name='mock.user'>, 'name': ('!=', 'MEM-001')}

`TestMemberValidationServiceExecute` is a pure orchestration test over a MagicMock member: it
patches every DB-touching sub-validator and asserts only that each key reaches the result. The
new step was not in that patch stack, so `mock_member.get("user")` returned a truthy MagicMock
which went to `frappe.db.get_value` as a filter value. Fixed by adding it to the stack, the
convention the test already used for the other four.

**The gap:** before opening the PR I ran the Member module, the SEPA module and the patch
itself against a real unique index — i.e. every path whose *behaviour* I had changed. I did not
run the paths that merely *call* the method I inserted a step into. A mock-based orchestration
test breaks on any new DB-touching step regardless of what that step does, and
`grep -rn "execute_validation"` would have found the one mock-based caller in seconds.
`tests/services/test_member_validation_service.py`, which drives `execute_validation` on real
Members, passed on that same CI run — which is what established the guard was in the right
place and only the mock caller needed touching.

Both PRs were green on all checks before merge (#306 across all 12 shards and Test Summary,
with shard 3 re-verified specifically).
