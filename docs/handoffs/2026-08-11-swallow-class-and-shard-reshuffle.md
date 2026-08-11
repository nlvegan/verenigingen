# Handoff — 2026-08-11 (second session)

## The swallow class, the shard reshuffle, and what the branch list was hiding

Continues from `2026-08-11-select-field-bug-class.md`. That handoff closed with two
flags: *Weekly has never run end to end*, and *the swallow is the real bug class, not the
Select*. Both were followed. Both were right, and both turned up something the flag did
not predict.

---

## 0. State at handoff

`develop` is at `03b9d8f1`. The working tree — which is the veg11 deploy — is clean and
current.

| PR | What | State |
|---|---|---|
| #282 | previous handoff (worktree hooks + in_import triage) | MERGED `9f29fd26` |
| #288 | previous handoff (Select-field bug class) | MERGED `90389858` |
| #292 | failed-write ratchet: new validator, baseline, advisory hook | MERGED `03b9d8f1` |
| #289 | Weekly + Semi-Annual billing frequency | **OPEN**, CI running |
| #293 | retire the dead membership-type billing migration | **OPEN** |

New issues: **#290** (Mollie recurring e2e), **#291** (shard order-dependence).

Remote branches went from 84 to 13. A restore script for every deleted branch
(`git push origin <sha>:refs/heads/<name>`, 72 entries) is in the session scratchpad —
copy it somewhere durable if that matters.

---

## 1. The headline: a green ratchet was never covering this class

The repo has had a `🕳️ Swallowed-Exception Guard` since #241, ratcheted at 422 sites.
It detects exactly one shape: a broad `except` that logs and returns a **falsy** value
from a function that elsewhere returns a real one.

**It cannot see the shape that produced the nine #280 defects, and not by accident.**
`scan_file()` in `scripts/validation/error_swallow_validator.py` skips four cases:

| line | exclusion | why it hides a failed write |
|---|---|---|
| 274 | function never returns a real value | skips void writers entirely (defect #1, MollieAuditLogger) |
| 300 | handler has `continue`/`break` | "nothing falsy reaches a caller" — the dropped row **is** the bug |
| 307 | any return is truthy | `return {"success": True}` after a failed save is the worst case |
| 312 | non-trailing `try`, no return | resumes as if the write happened |

Driving that baseline to zero would not have touched one of the nine. **Do not read a
green swallow ratchet as coverage for failed writes.**

#292 adds the sibling that does see them: `scripts/validation/failed_write_validator.py`,
baseline **132 functions / 162 sites**, advisory pre-commit hook.

### The two calibrations that matter

Measured, not guessed. A naive scan gives 578 hits; almost all the reduction is these:

1. **`{"success": False, "error": str(e)}` is TRUTHY but is a CORRECT error report.**
   Failing to exclude it inflated one class 239 → 19. Same for
   `OperationResult(success=False)` and any dict carrying an `error`/`errors` key.
2. **A handler that records the failure where the caller reads it is not a swallow**,
   however it exits — `results["errors"].append(...)`, `results[k]["success"] = False`,
   `error_count += 1`. This cleared most `continue` sites;
   `services/billing/invoice_management.py:473,747` are fine.

And one trap for anyone extending it:

3. **A bare `return True` can mean FAILURE.**
   `member_history_update_service.py:263` `_step_save_history_changes` returns `True` for
   "the save failed" and marks every result failed. Never assume truthy == success.

### Residual noise, stated honestly

~15–20% of the weakest class (`FALLS_THROUGH`, 141 of 162) are sites that want a
`# failed-write-ok:` annotation rather than a fix — deliberate best-effort writes like
`eboekhouden_improved_item_naming.py:38` (documented fallback to `"Services"`) and
`ponto/services/oauth2_service.py:477` (commented "non-critical, UI visibility only").

### The guard is currently half-armed

The sibling runs as a **whole-tree CI check**, so `git commit -n` cannot slip past it.
The new one has **no CI gate at all** and is advisory. So today it will *report* a new
failed-write swallow and *nothing* prevents one landing. Flipping `--strict` and adding
the whole-tree CI step are a pair; until both land, the ratchet does not ratchet.

---

## 2. Verified instances (production checked, not assumed)

Two worst cases were checked against veg11 rather than argued from code alone. **Neither
has corrupted data. Report them as latent risk, not loss.**

- `patches/v2_0/migrate_membership_type_billing_to_dues_schedule.py:191` — logs +
  `continue` per row, **no counts**, prints "Migration completed!", commits. Ran on veg11
  2025-11-21, so it is in `tabPatch Log` and can never re-run. All 1660 dues schedules
  have a `billing_frequency` (Annual 1087 / Quarterly 563 / Monthly 10, **no Weekly**).
  **See §5 — someone had already worked out something stronger about this patch.**
- `doctype/member/member_id_manager.py:124` — on any exception returns
  `int(time.time()*1000) % 1000000`, an ID not drawn from the counter, without advancing
  it. Bounded by `member_id` being `unique: 1` (index confirmed `Non_unique=0`) plus the
  `_get_max_numeric_member_id()` self-heal; veg11 clean at 748/748 distinct. Converts to
  a **misattributed** DuplicateEntryError on the Member save, not silent corruption.

Legitimate, do **not** "fix": `_save_with_retry` (retry loop), `_acquire_lock_internal`
(lock retry, rolls back, gives up), the `invoice_management` cleanups (append to
`results["errors"]`).

---

## 3. "Weekly has always been handled" was false

`_calculate_next_invoice_date()` had branches for Daily/Monthly/Quarterly/Semi-Annual/
Annual and an `else` returning `add_months(today(), 1)`. **Weekly hit that else**, so a
Weekly schedule was billed **monthly**. Same fall-through in
`dues_schedule_health_manager.py`.

Then the same defect one branch over: the health manager had **no `Semi-Annual` branch
either** — six months billed as one. It was a second copy of a table
`_calculate_next_invoice_date()` already owned, and the copy had drifted. Fixed by
**deleting the copy**, not by adding a third branch to it.

**The test is an invariant, and this is the part worth copying.** The existing tests list
one frequency each by hand — which is precisely why Weekly was missing from the table
*and* from its test, and nothing failed. The new test reads the options off the
`billing_frequency` Select and asserts every declared option produces its own interval
(`Monthly`/`Custom` pinned as deliberate fallbacks). Run against `develop`, where the
Weekly branch does not exist, it flags exactly `['Weekly']` — verified discriminating
rather than assumed.

No production impact either way: veg11 has no Weekly and no Semi-Annual schedules.

---

## 4. Adding one test file reddened four unrelated shards

#289 went red with six failures in mt940 import, a Mollie coverage sweep, e-boekhouden
cleanup, and ERPNext integration. **None touched billing frequency.** The instinct to
blame the branch was wrong.

- Identical failures on the same shards at **both** commits → deterministic, not flaky.
- Both testable ones **pass in isolation against clean `develop`**.
- `scripts/frappe-parallel-test-weights.patch` replaces `split_by_weight` with **global
  LPT bin-packing** over `tests/test_timings.json`, falling back to
  `TEST_WEIGHT_OVERRIDES.get(...) or 1` for unmeasured files. Because LPT is global,
  **adding any file re-packs every bin** — shard membership shifts repo-wide.

So these are pre-existing order-dependent failures the reshuffle exposed. Filed as
**#291**. #289 was unblocked by giving the new file a weight entry (18, estimated against
comparable fixture-heavy dues tests), but **that re-rolls the split, it does not fix
anything** — the next new test file reshuffles them again.

**The attribution hazard is the real cost:** the failure looks like it belongs to
whichever branch happens to add the next test file. Partition by shard and check
in-isolation behaviour *before* blaming a diff.

---

## 5. The branch list was hiding live work

84 remote branches; 68 were true ancestors of `develop` and were deleted, then three more
after a content check.

**A method error worth recording.** I first used `git diff develop...branch` to decide
whether a branch had unique content. That three-dot diff shows a branch's own changes
**whether or not they already landed**, so it called three fully-merged branches "live".
`git cherry` compares by **patch-id** and is the right tool: `+` = not upstream,
`-` = an equivalent patch is already in. Stacked PRs that landed in rewritten form still
show `+`, so confirm those **by content** (do the files/changes exist on `develop`?)
before deleting.

The audit turned up one genuinely live branch, pushed 2026-07-30 with **no PR ever
opened**: `fix/retire-dead-membership-billing-patch`, now **#293**.

Its analysis is better than §2's and supersedes it. From the code, not the data: every
`hasattr()` guard in that patch now fails, so the else-branches write
`contribution_mode="Calculator"` (and `"Tier"`) — values the Select rejects — the insert
throws, and the per-type `except` swallows it. **It could only ever have been a silent
no-op.** Consistent with the veg11 numbers in §2; the mechanism is the real answer.

Also still out there, unmerged and unproposed: three handoff documents
(`docs/2026-07-31-clock-and-allocation-handoff`, `docs/in-import-fallout-triage`,
`docs/server-tests-red-baseline-triage`) — same category as #282/#288, which sat unmerged
until today. `fix/edge-session-user-patch` was deliberately rejected (PR #76 closed).

---

## 6. Rules this session produced

1. **A green swallow ratchet says nothing about failed writes.** §1.
2. **`{"success": False, "error": e}` is truthy and correct.** Any swallow detector that
   treats truthy as success is 12× too noisy.
3. **`git cherry`, never a three-dot diff, to ask "did this branch land?"** §5.
4. **Restores written in `tearDown` before `super().tearDown()` are discarded.**
   `_cleanup_document_with_retry` (`tests/utils/base.py:199-204`) rolls back *before* each
   tracked delete and commits *after* — so the restore is lost while `setUp` pins become
   durable, and the leak fails a *different* test file. Use `addCleanup` + explicit commit.
   (Found by review on #289, not by a failing test.)
5. **Enumerate invariants from the schema, not by hand.** A per-case test list cannot fail
   for the case nobody added. §3.
6. **A new test file perturbs every shard.** Give it a `test_timings.json` entry, and do
   not attribute a reshuffle's failures to the diff that triggered it. §4.

---

## 7. Open threads

- **#289** — CI running on `832875f9`/`6c957e36`. A different set of order-dependent
  failures is a plausible outcome of the re-rolled split; that is §4, not a regression.
- **#293** — ready; re-verified against today's `develop` (successor patch present at
  `patches.txt:46`, merges clean, no lingering references).
- **#291** — the order-dependence itself. The higher-value of the two test findings.
- **#290** — Mollie recurring e2e. Note the constraint that shapes it: SEPA DD with a test
  key stays `pending` with no success callback, so the test must drive **credit card**
  with `Recurring`; a SEPA-DD test would hang or pass vacuously.
- **Flip the failed-write guard to `--strict` + add a whole-tree CI gate** once the 162
  sites are annotated. Until then it is advisory with no CI backstop.
- **`Custom` still falls back to monthly** in `_calculate_next_invoice_date`. Left
  deliberately (a Custom frequency plausibly carries its own interval); the new invariant
  test now pins that as intentional rather than accidental.
