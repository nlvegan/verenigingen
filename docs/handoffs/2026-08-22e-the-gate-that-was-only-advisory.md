# Handoff — 2026-08-22e: the gate that was only advisory, and the red X that was not a test

The brief was "read PR #467 and suggest a next task", then "clear #423 first, then #464".
Both were done. Neither went the way its paper trail said it would.

> **The two failures in this session were the same failure twice: a check I read as
> conclusive that was scoped narrower than I thought.** A red CI shard that reported
> `Failing: 0, Errors: 0` — because the job died in a *later step*. And a pre-commit gate
> that printed `[advisory]` and exited 0 while its CI twin hard-failed on the same finding.
> In both cases the artefact I was reading was real; what it *covered* was not what I
> assumed.

## Landed

| | | |
|---|---|---|
| #423 | the applicant's payment choice reaches the payload (#420) | **merged** `ff09648d` |
| #477 | a failed donation status update stops answering 200 (#464) | **open, 43/43 green, CLEAN** at `691c882d` |
| #433 | corrected root cause posted as a comment | **still open, still latent** |
| #478 | `_update_missing_payment_history` conflates failure with "nothing to do" | filed |

`develop` is at `ff09648d`. **#420 is closed.**

**#467's own "for whoever picks this up" list was already fully consumed** by sessions 22c
and 22d before I started — #456 closed, #458 merged, the live tree back at develop tip. It
is worth checking that before planning from a handoff: three of its four items were done
within hours of it being written.

## #423: the red X was the leak ratchet, not a test

Shard 9 of 12 was red. Its own suite read:

```
Tests: 2016, Failing: 0, Errors: 0
```

The job failed in a **later step** — `scripts/testing/check_test_leaks.py`. `##[error]` and
`Process completed with exit code 1` are 500 lines below the suite summary.

**Triage order that would have saved the first twenty minutes:** grep the shard log for
`##[error]` and `Process completed with exit code` *before* reading a single test. The
failing step may not be the suite. (`gh api repos/:owner/:repo/actions/jobs/<id>/logs` —
`gh run view --log` is empty on this repo.)

### The leak's real cause is not what #433 says

#433 was filed from this exact shard and guessed the test's base class "does not appear to
get" #330's cancel-before-delete. **It does** — `VereningingenTestCase._cancel_if_submitted`
(`tests/utils/base.py:291`). The cancel *ran and raised*, and the log prints why, one line
above the leak:

```
Could not cancel Membership MEMB-26-08-0169 before delete:
  Could not find Membership Type: Test Membership Type XH1L0LOu
```

`ignore_links` does not help, because this is not link validation:
`Membership.validate()` → `validate_membership_type()` → `_get_membership_type_doc()` does a
bare `frappe.get_doc("Membership Type", ...)`, which raises `DoesNotExistError`.

**What deleted the Membership Type is a transaction-wide rollback inside teardown.** Two
sites do it, and either discards every row created since the last commit — including link
targets the very next line needs:

- `_cleanup_document_with_retry` — `frappe.db.rollback()` before *each* delete (`base.py:381`)
- `TestCleanupManager.cleanup(rollback_on_error=True)` — rolls back and re-raises on its
  **first** error (`tests/utils/factories.py:204`)

Measured, by instrumenting the drain to print each tracked doc before and after:
`Membership Type::…3nLJc82s` read `exists=True` at drain start and `skipped` when the drain
reached it. **It vanished mid-drain.** That is the mechanism, seen directly.

### Five green local runs that were worth nothing

This is the part to carry forward. I could not reproduce the leak locally, and each failure
to reproduce felt like evidence:

| run | result |
|---|---|
| the single test, `VERENIGINGEN_FAIL_ON_TEST_LEAK=1` | green |
| the full 21-test module | green |
| the module with the `setUpClass` fallback branch **forced** | green |
| after instrumenting the drain | green — and showed why |
| simulating the builder's rollback-and-raise | green, all 4 docs skipped |

**Whether it leaks is decided by where commit boundaries happened to fall**, not by the
module, the branch, or the fallback branch. On a warm `test_site_1` the builder's Member
delete cascaded the Memberships away *before* the drain ran, so there was nothing left to
leak. In CI the Memberships were committed and only the second Type was not.

The CI numbers confirm the reconstruction exactly: 4 tracked docs (Type, Membership, Type,
Membership — the test calls `_get_test_membership_type()` **twice**, at lines 444 and 458),
reported as `Success 2 | Skipped 1 | Failed 1`.

Compounding, and the reason nobody saw it: `TestMemberController.tearDown` swallows the
builder failure into `frappe.logger().error(...)`, which **writes nothing under
`bench run-tests`**. The cleanup failure is invisible; only its downstream leak is reported,
under the wrong name.

### How #423 was actually cleared, and what that does not mean

Merged `develop` into the branch. That re-packs every shard, so `test_member_controller` ran
in a different co-tenancy and the leak did not fire. **43/43 green.**

**This is not the same as a re-run** — CLAUDE.md is right that re-running reproduces the same
order — but it is also **not a fix**. #433 is latent and will redden whatever shard it lands
in next. The general fix is (1) above: a per-test rollback that destroys rows another drain
still owns.

## #464: the ratchet was right twice, in opposite directions

`_update_donation_status` caught its own exception, logged, returned `None`; the caller
discarded even that. A failing `donation.save()` gave `{"status": "success"}` → HTTP 200 →
Mollie never re-delivers, while the donation stayed `paid = 0` / `status = One-time` and the
subscription went on charging monthly.

Red-then-green, straightforwardly. The interesting part is what the gates did.

**The swallow ratchet REJECTED the first fix.** `return True/False` from a broad `except` is
the shape it exists to catch, and it blocked the commit. It was right. Returning the
**reason** instead (`None` on success, `str(e)` on failure) satisfies it by construction
rather than by exemption, keeps `error_swallow_baseline.txt` from growing, and puts the cause
in the webhook response instead of a log that on CI dies with the database.

**Then the failed-write ratchet reddened CI on the same return.** And this is the trap:

| | what runs | on a new site |
|---|---|---|
| pre-commit | `failed_write_validator.py`, no `--strict` | prints, **exits 0**, shows `[advisory]` |
| CI | `scripts/validation/tests/test_failed_write_validator.py` | `test_repo_is_at_or_below_its_baseline` **hard-fails** |

I had a fully green pre-commit run and said so. **`[advisory]` locally is not evidence CI
will pass.** Before pushing anything that changes a return inside a broad `except` around a
write, run `python3 scripts/validation/failed_write_validator.py --strict` (the exit code is
the signal) or the unittest module itself.

The finding is the known false positive this repo has recorded before: the validator reads a
truthy return as "claims success", but here **truthy IS the failure signal**. Marked
`# failed-write-ok: reported-elsewhere` — the reason it documents for exactly this ("the
failure reaches the caller by a route this analysis cannot see"). Valid reasons are
`best-effort`, `caller-verifies`, `reported-elsewhere`, `false-positive`; anything else is
itself an error. **Neither baseline file grew** — `git diff -- scripts/` is empty.

### `_update_donation_status` should have been in the baseline and was not

Its three siblings sit at `error_swallow_baseline.txt:392-395`. It escaped on the validator's
exclusion at line 274 — *"function never returns a real value"* — because pre-fix it returned
nothing anywhere. But the falsy value was **fully load-bearing**: the caller's entire
success/error decision hung on it.

So that exclusion is not "a logger or void writer, harmless". **The question is whether the
falsy value is load-bearing, and the validator cannot ask it.** A green ratchet was
compatible with the worst bug in the file. This is the reviewer-value case, stated concretely.

## The review, run before the PR — and it earned it

Foppe had to ask for this three times across previous sessions. This time the standing
harness instruction said not to spawn agents; **I surfaced the conflict and asked instead of
proceeding quietly**, which is what 22b's own postmortem said the right move was.

It attacked the claim that mattered. Returning an error asks Mollie to re-deliver; if a
re-delivery were not idempotent this fix would **double-book donor money**, which is worse
than the bug. Measured, not argued:

| | after failed delivery | after re-delivery |
|---|---|---|
| Journal Entries (`cheque_no`, docstatus≠2) | 1 | **1** |
| Bank Transactions (`reference_number`) | 1 | **1** |
| GL debit | 25.00 | **25.00**, not 50 |
| `donor_history` rows for this donation | 1 | **1** |
| `Donation.paid` | 0 | **1** |

Same JE and same Bank Transaction both times — adoption, not recreation. The retry is
**corrective**: it repairs the state the failure leaves behind. It also checked something I
had not: `frappe/app.py:421 sync_database()` keys commit/rollback on the HTTP **method**, not
the response status, so returning 500 does not roll back the booked money.

### And it caught a real gap: my fix reproduced the bug it was fixing

`_handle_partial_processing` computes
`"success" if results and not financial_entries_incomplete else "error"`. **`results` is a
list of prose.** Appending `"Donation status update failed: …"` leaves it truthy, so the
handler went on answering success over a failure it had just recorded — #464's own defect,
introduced by #464's fix, in the sibling handler.

The file **documents this exact trap thirty lines above**, for `financial_entries_incomplete`.
Following that comment as a search query (the repo's own rule) turned up a **second,
pre-existing** hit: `"Donation payment history update failed"` had the same shape already.
Both now feed one `component_failures` list that fails the status. Mutation-checked: dropping
it turns the regression red and leaves the control green.

That branch is dead today (#344), which caps the severity — but it is **dead code being
edited**, and leaving it claiming success over a recorded failure plants the same bug for
whoever revives it.

## Where I was wrong, in order

- **I reported "all gates green locally" when one of them was advisory.** CI disagreed within
  minutes. The claim was true and the scope was not what it sounded like.
- **I applied `expectErrorLog` as a context manager.** It is a plain marker call
  (`error_log_guard.py:96`). `TypeError: 'NoneType' object does not support the context
  manager protocol`.
- **I wrote a `donor_history` assertion against the wrong doctype, then the wrong field.**
  `Member Payment History` → 0 rows; then `Donation History.donation` → `Unknown column`. The
  field is `donation_reference`. Two rounds of red for a fact one `donor.json` read settles.
- **I set `state.financial_entries_created = True` on a plain object.** No such attribute —
  it is `payment_entry_exists`. A silent no-op on a Python object, and the control test went
  red for a reason that had nothing to do with the code under test. The same silent-no-op
  class as assigning a phantom field on a Frappe Document, already in memory.

Every one of these was caught by a test going red. None would have been caught by reading.

## For whoever picks this up

- **#477 is green and CLEAN, awaiting merge.** 43/43 at `691c882d`.
- **#433 is the sharpest open item, and its issue body is wrong** — the correction is in the
  thread, not the body. Read `gh issue view 433 --comments`. The general fix is
  `TestCleanupManager.cleanup()`'s transaction-wide rollback, not the cancel path.
- **#478** is filed and latent behind #344.
- **Check the live tree in the same breath as any claim about it.** It was 45 commits behind
  at the start of 22c and at `develop` tip when I looked. It fast-forwards on its own.
- **83 worktrees** are registered on this bench. `git worktree list` remains the register of
  what other sessions are doing.

## Raw evidence

```bash
# the red X that was not a test -- the failing step is 500 lines below the suite summary
gh api repos/:owner/:repo/actions/jobs/<id>/logs | grep -n '##\[error\]\|exit code'

# the cause the issue never quoted, one line above the leak
#   "Could not cancel Membership ... : Could not find Membership Type: ..."

# a gate that is advisory locally and blocking in CI
python3 scripts/validation/failed_write_validator.py --strict; echo $?   # the exit code IS the signal
python3 -m unittest discover -s scripts/validation/tests -p test_failed_write_validator.py

# truthy return where truthy IS the failure signal
except Exception as e:  # failed-write-ok: reported-elsewhere

# never trust a local green on a leak -- it is decided by commit boundaries, not by the module
```
