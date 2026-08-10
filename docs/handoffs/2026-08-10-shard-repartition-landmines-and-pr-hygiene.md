# Handoff — 2026-08-10

## Four shard-repartition landmines, and a PR-queue cleanup

Started as "retrieve the CI status of all our open PRs". Everything below came out of
that one question.

---

## 0. State at handoff

**Everything in this document is MERGED.** `develop` is at `e55b2ac1`.

| PR | What | Merge commit |
|---|---|---|
| #271 | exempt seeded master data from the captured-insert drain (closes #258) | `bda51112` |
| #276 | cost-center tests own their membership type | `04924109` |
| #277 | `Optional[str]` contract on the cached membership type + Mollie config-cache invalidation | `7b67384b` |
| #275 | withdraw board role profile and role when a seat is vacated (closes #211) | `e55b2ac1` |

**Zero open PRs.** 27 open issues (was 26: −#258, −#211, +#272, +#273, +#274).

Filed: **#272** (`resolutions` is dead under npm), **#273** (seven hooks fail in a
worktree), **#274** (branches with no PR). Commented: **#248** (fourth instance),
**#208** (verified still open), **#274** (item 1 now done).

Closed unmerged: Dependabot **#35 #34 #33 #28 #25 #22 #21**.

veg11 serves the git working tree, which is on `develop` at `e55b2ac1` and clean.

---

## 1. The through-line: adding ONE test file re-partitions the shards

This is #248, and it happened **four times in one session**. It is the single most
useful thing in this document.

`bench run-parallel-tests` splits by LPT bin-packing weighted from
`verenigingen/tests/test_timings.json`. #248 measured it: **adding one test file moves
702 of 1307 modules to a different shard.** Every module then runs beside neighbours it
has never run with, and any latent inter-test contamination fires.

#275 adds one test file. It took three rebases to get green, and *not one* of the
failures was in the code it changed:

| round | shard | failure | actual cause | fixed by |
|---|---|---|---|---|
| 1 | 9/12 | 11 errors, `Could not find Payment Method: Mollie` | test deletes+recreates a session seed; the drain force-deletes the recreation | #271 |
| 2 | 3/12 | 5 errors, `No schedule was created with membership` | fixture borrows the last-modified Membership Type | #276 |
| 3 | 3/12 | `AssertionError: '' != None` | production method breaks its own `Optional[str]` contract | #277 |
| 3 | 8/12 | `pe_name is None` | `set_single_value` does not invalidate a Redis-cached settings read | #277 |

**The failures shrank each round** — 11 errors → 5 errors → 2 assertion failures — which
is what progress looks like here, but the generator is untouched. Expect a fifth the
next time someone adds a test file.

### How to triage this shape fast

1. **Partition the failures by shard first.** A cause is almost always shard-local.
2. **Run the failing module standalone, on develop and on the branch.** If it passes both
   ways, the branch is innocent and you are looking at contamination. This took under two
   minutes each time and settled the question every time.
3. **Read the CI log for the *logged* error, not just the assertion.** Shard 8's
   `assertIsNotNone` told us nothing; `Orphan PE Creation Error: ... Mollie Clearing
   Account not configured` named the cause.
4. Only then look for the neighbour that did it.

---

## 2. The drain deletes shared seed data (#271)

`EnhancedTestCase.setUp` monkey-patches `Document.db_insert` to record every insert, and
`_drain_captured_inserts()` force-deletes them all at tearDown. It cannot tell a test's
throwaway record from a **shared** one that production code re-created inside the test
body.

`test_ensure_payment_modes_exist_creates_missing` deletes `Mode of Payment "Mollie"` and
lets `ensure_payment_modes_exist()` re-seed it. The re-seed was captured and drained,
destroying what `tests.setup.before_tests` seeds **once per process**. Everything
downstream in the shard that built a Member with `payment_method="Mollie"` then failed
link validation.

The drain's own docstring predicted this (`enhanced_test_factory.py:2017-2022`).

Fix: `EnhancedTestCase.DRAIN_EXEMPT_DOCTYPES = frozenset({"Mode of Payment"})`, skipped in
the drain.

**Keep that set small — entries in it leak between tests by design.** Checked before
adding: every test that creates a Mode of Payment either tracks it (cleaned by the
separate `_drain_tracked_documents`) or never commits (undone by the drain's opening
rollback).

Reproduce the whole class of bug without CI:

```bash
bench --site test_site_1 run-tests --module verenigingen.tests.services.test_application_helpers
# 41 tests OK — and Mode of Payment "Mollie" is gone from the database afterwards
```

---

## 3. Fixtures that borrow global state (#276)

```python
def _get_any_membership_type():
    types = frappe.get_all("Membership Type", limit=1)   # no order_by
    return types[0].name if types else None
```

No `order_by` → Frappe falls back to the doctype's own sort, and Membership Type declares
`sort_field: modified, sort_order: DESC`. So this returns **whichever type the previous
test last touched**, out of 289 on a warm site. Measured: touching any other type changes
the answer.

Fix: create it through the factory, which generates a unique name and aligns the
auto-created template's `dues_rate`. The `skipTest("No Membership Type exists")` guard
went with it — it could never fire on a seeded site and was masking the borrowing.

**Generalise this.** `get_all(..., limit=1)` with no `order_by` in a fixture is the same
bug wherever it appears. #263/#264 track the membership-type family specifically.

---

## 4. Two Mollie defects (#277)

### 4.1 A method that broke its own contract

`_get_membership_type_cached` is annotated `-> Optional[str]` and documents "None if not
available", but returned the raw Single value. An unset Link on a Single reads back as
`""` once the field has ever been written, and as `None` only if the row was never
created.

**Two tests asserted opposite things about it** — one expected the normalised `None`, the
other the raw `""` — so on any site where the field held `""`, exactly one had to fail.
Normalised at the boundary; aligned the test that had encoded the wrong side.

Worth remembering: *fixing a contract broke a test that had encoded the violation.* If you
tighten a return value, grep for every test asserting on it before assuming you are done.

### 4.2 `set_single_value` does not invalidate a service cache

`MollieConfigurationService` caches Mollie Settings in Redis for 300s under one key.
`MollieSettings.on_update` clears it — but `frappe.db.set_single_value()` writes the
column and **fires no doc hook**, so the write is invisible for the rest of the TTL.

```
warm cache            -> 'Mollie - TPIC'
set_single_value ''   -> db now ''
service still reads   -> 'Mollie - TPIC'   <- stale
after clear_cache()   -> ''
```

Every other Mollie suite that writes these Singles already calls `clear_cache()`; this one
class was the exception. **Any test that configures a Single read through a cached service
must invalidate the cache explicitly.**

Two honest limits on this one:

- **Not reproduced end-to-end.** `bench run-tests` clears the cache at startup, so
  poisoning it from a console is wiped before the suite runs. The mechanism is proven by
  the measurement above, not by a repro. My first attempt *passed*, and reading that as
  "fixed" would have been wrong.
- **A second candidate cause was not ruled out.** `ensure_mollie_bank_gl_account` returns
  `None` when it finds no parent group (`payment_entry_fixtures.py:52-53`) and
  `setUpClass` wrote that unchecked, producing the identical message. The PR now asserts
  the account was ensured, so if *that* is what fired in CI it fails at setup naming the
  cause. Which one actually fired in run `31337755629` is still unknown.

---

## 5. #275 itself — board role withdrawal (closes #211)

Removing someone from a chapter board never withdrew the access the seat conferred.
`handle_board_member_changes` / `..._deletions` recalculated from `Chapter.validate()`,
i.e. **before the child rows were written**, so `get_board_member_profiles()` still saw
the seat active and `sync_user_role_profile()` reported `changed=False`. Every removal
path was affected: desk, `remove_board_member()`, `bulk_remove_board_members()`.

The Frappe **role** was lost the same way for a second reason:
`User.populate_role_profile_roles()` resets `roles` to exactly the attached profiles'
roles on every save, so with the board profile still attached the role went straight back
on.

Fix: defer both halves to the `on_update` flush additions already use, ordered profile
first then role; extract `withdraw_board_member_role_if_unseated(volunteer, exclude_row)`
so the deferred caller runs against persisted state with no self-exclusion.

`_assert_board_access_withdrawn()` now raises `BoardAccessWithdrawalError` when a
volunteer with no active seat still holds board access, and the flush re-raises it.
Grants keep log-and-continue: **a failed grant fails safe, a failed revocation does not.**

The branch had been sitting pushed with no PR since 2026-07-31, 167 commits behind.

---

## 6. Working practices that mattered

- **veg11 serves the git working tree.** Branch work goes in a `git worktree`; a
  `git checkout` in `apps/verenigingen` is a deploy. Where a local test run was needed
  (bench runs the *main* tree, not a worktree) the pattern was: apply the patch, run
  against `test_site_1`, revert immediately, confirm `git status` clean.
- **Seven pre-commit/pre-push hooks fail inside a worktree** — now #273. Four are just
  missing `node_modules` (symlink the main tree's and they pass for real);
  `frappe-hooks-validator` derives the app package from the *directory name* and so breaks
  in any clone not named `verenigingen`; `make-test-quick` needs the bench dir. Verify a
  hook failure is an artifact by running it in the main tree before reaching for `SKIP=`.
- **The test-quality enforcer re-scans the whole file** once any line in it is staged, so
  a one-line fix can be blocked by pre-existing violations elsewhere in the file. In #276
  that meant removing two redundant `ignore_permissions=True` flags rather than skipping
  the gate.
- **Verify pushes.** Every push here compared local and remote SHAs afterwards; force
  pushes used `--force-with-lease` pinned to the prior SHA.

---

## 7. Left open deliberately

- **#248** — the generator of everything in §1. Still open, now with four documented
  instances. The workflow-state problems in its points 1-3 are untouched, including the
  question of whether `Membership Application Workflow` governs `application_status` or is
  a leftover — `lifecycle.py` says one thing and the active row on veg11 says the other.
- **#273** — the worktree hooks. `frappe-hooks-validator`'s directory-name bug is worth
  fixing on its own terms.
- **#272** — delete the dead `resolutions` block. No package is pinned there alone, so
  nothing is lost; four entries already disagree with `overrides`.
- **#274 item 2** — `test/harness-production-fidelity`, 3 commits, pushed, no PR, blocked
  on its own triage. Its handoff records 169 failures; the real number is **236** (the 169
  came from grepping a CI log without stripping ANSI codes). It also touches
  `enhanced_test_factory.py`, which #271 changed — rebasing it will conflict.
- **#208** — verified still open, and the signals that make it look stale are misleading:
  its branch is 0 commits ahead of develop and PR #215's title matches, but `ba441b9b` is
  one of #215's *own* commits. This issue is the piece that PR carved out.
  `volunteer_sync_service.py:988-1003` still withdraws only the team membership.
- **Dependabot security updates are paused** on the repo, so no new security PRs are
  arriving. Worth un-pausing now that the seven stale ones are closed.
