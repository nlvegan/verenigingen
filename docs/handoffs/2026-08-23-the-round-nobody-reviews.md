# Handoff — 2026-08-23: the round nobody reviews

Picked up from `2026-08-22f-the-rollback-that-put-it-back.md`: merge #488, then #483, with
agents on #482 and #485.

#483 is fixed and merged. The interesting part is what happened *after* the first review.
The commit that answers a skeptical review is the round least likely to be reviewed — and
when this one finally was, it carried **four false claims**, one of which cited a **closed
issue** as its authority for a design decision.

> **A right answer resting on a dead reason is invisible.** `cleanup_savepoint.py` said the
> duplicate-helper ratchet "counts private module-level functions, so methods are invisible
> to it (#445)". #445 is closed; the validator's own docstring has read "functions AND
> methods" since `275a906a`. The *conclusion* was still correct — that ratchet cannot find
> these two copies — but for two different reasons (one copy is inline code, and it keys on
> the name). Nothing about that is greppable: both statements read confidently.

## Landed

| | | |
|---|---|---|
| #488 | handoff 22f | **merged** `b0cd9ac6` |
| #492 | #483: one undeletable document must not abandon the cleanup | **merged** `d68b17e3`, 43/43 green |
| #483 | closed by the merge | **closed** |
| #485 | branch `fix/485-harness-logger-conversions` @ `061228aa` | pushed, **PR not opened** |
| delete auditor | branch `test/delete-resurrection-auditor` @ `66adffa6` | pushed, **PR not opened** |
| #482 | investigation posted as a comment | open |
| #489 #490 #491 #498 #499 | filed this session | open |

## What #483 actually was

The issue described `TestCleanupManager.cleanup()` rolling the transaction back and raising
on its first undeletable document, abandoning the rest. True, and the smaller half.

**Four of the five `tearDown`s that call `builder.cleanup()` do not wrap it, and all five
call it before `super().tearDown()`.** So the raise skipped the base class's entire teardown:
the drain, the Error Log capture, the leak report, the request-context cleanup and the mock
restoration. The review measured the consequence rather than reading it — a probe with an
unwrapped tearDown, exactly as those four are written:

| cleanup body | first test | mock patches leaked into the second |
|---|---|---|
| develop (rollback + raise) | **ERROR** | **3** (`_cleanup_test_mocks` never ran) |
| the fix | pass | **0** |

Fix: a savepoint per document, failures collected and returned, each announced through
`get_harness_logger`. `rollback_on_error` removed rather than kept and ignored.

**And it is latent.** The raising branch fired in **none** of the five caller suites — zero
`Cleanup failed:` across nine paired module runs. That grep has a positive control (the new
tests produce the string against unpatched code), so it is an instrument that can read
non-zero. What the fix removes is a teardown-wide failure mode, not an observed leak. Say
that plainly; #483 said the frequency was never measured and it still is not.

## Two reviews, and the second one earned more than the first

Both ran before their PR was opened, per the standing rule. The second reviewed only
`33780d18` — the commit that answered the first — and provoked a **real 1213 and a real
1205** with two connections, which nobody had done:

```
1213 -> frappe.QueryDeadlockError; whole tx rolled back, savepoints included
        rollback(save_point=...) afterwards raises 1305, NOT a deadlock error
1205 -> frappe.QueryTimeoutError; only the failed STATEMENT rolled back
        (innodb_rollback_on_timeout = OFF here); rollback to savepoint SUCCEEDS
```

So keying the deadlock decision off the **original** exception is right, and excluding 1205
from it is right rather than a rationalization. Three claims in `transaction_errors.py`'s
docstring are now measured instead of inferred.

It then found the thing that matters more:

- **`delete_doc:148` takes a `FOR UPDATE NOWAIT` and rewrites BOTH 1205 and 1213 into
  `frappe.QueryTimeoutError`**, discarding the original. So the deadlock branch is
  **unreachable for the most likely 1213 on this path**. Behaviour is identical to before the
  branch existed — it fails safe — but the docstring claimed coverage it did not have.
- **#483's own defect was still open on two paths of the function its first fix reshaped.**
  The existence check and `frappe.db.savepoint()` sat *outside* the `try`, so a deadlock or a
  lost connection from either still skipped the caller's `super().tearDown()`.
- **C2, the one that stings:** the commit whose message invokes *a finding is a class*
  corrected "four of the five callers discard the returned list" in `factories.py` and left
  the identical sentence **eleven lines above its own edit** in the other file.
- **Three fixes were pinned by nothing.** Deleting the logging line, deleting
  `release_cleanup_savepoint`, and *inverting* the `is_submittable` gate all left every test
  green.

## The stale sentence, and where it came from

I did not invent the #445 claim. It came from
`.claude/skills/verenigingen-test-harness/SKILL.md:68`, where it sat as current fact for a
month after the fix landed, and got copied into fresh code as justification.

**A skill file is read as current fact by everyone who loads it, and a stale line there is
copied outward rather than merely believed.** Fixed in the skill, in the new module, and in
the memory entry that described #445's blind spot as live. The skill's iteration log carries
the rule: **when a fix closes a blind spot, retire the sentence describing it.**

## The instrument, and the two defects it found cancelling each other out

Three issues in this repo are one defect — a delete inside the test transaction, undone by a
later rollback (#407, #486, #489) — and each was found by hand with a probe that was then
thrown away. So the probe is now a tool: `scripts/testing/delete_audit/` on
`test/delete-resurrection-auditor`.

It asks the only question the harness cannot answer about itself: **for every delete that
reported success, is the row actually gone?** Two processes — the probe appends
`(doctype, name, creation, test)` during the run; a separate checker asks the site afterwards,
so it sees only *committed* state, which is the contamination question.

`creation` is recorded *before* the delete because **a docname is not an identity**. The first
census flagged `Chapter::Test Amsterdam Chapter`, which looked exactly like a get-or-create
fixture being rebuilt. It was not — same `creation`, the same row back — and only the
timestamp could tell those apart. `RECREATED` and `UNVERIFIABLE` are separate verdicts, and
"cannot tell" is never reported as "resurrected". `selftest.sh` plants all four cases and
asserts all four.

That survivor is **#498**, and it is the session's best finding:

`with_chapter` is a get-or-create whose two branches converge on the same unconditional
`register(...)`, so a test that **reuses** the shared chapter registers it for deletion, and
`builder.cleanup()` deletes it. It is harmless today *only because* the delete is never
committed and the rollback puts it back. **So #489 and #498 cancel out.** Give `cleanup()`
the commit #489 asks for and the shared chapter is deleted for real, taking every later test
that resolves it — the #330 / #390 failure mode. **#489 cannot be fixed on its own.**

First census: **12 module runs, 611 deletes recorded, 1 survivor.**
`test_event_driven_payment_history` read 0 of 9 — the negative control on real code, since
that is #486's module, fixed on develop.

Deliberately **not a gate**. No baseline, nothing fails on a survivor, and a survivor is a
question rather than a verdict — a test that intentionally deletes a row inside its own
transaction is reported too. Gating needs a suite-wide census first, which is exactly the
mistake #485's ratchet made.

## #482 is live, and the obvious fix is a trap

Measured on the same posted invoice through each drain:

```
EnhancedTestCase._remove_drained_record   {GL:2, PLE:1} -> {GL:4, PLE:2}, parent deleted
VereningingenTestCase (control)           {GL:2, PLE:1} -> unchanged, row left submitted
```

Reproduced in ordinary runs via an import-hook probe:
`test_fee_change_settled_invoice_isolation.py:191` and `test_sepa_reconciliation` each strand
**+2 GL / +1 PLE per occurrence**, on a `voucher_no` the naming series then reissues.

Three things for whoever fixes it:

1. **There is a false claim in the code.** `enhanced_test_factory.py:2063-2069` says cancelling
   "removes the derived ledger rows". It writes more. That docstring is why this keeps being
   re-derived.
2. **A straight copy of the carve-out creates a different defect.** With it, the parent
   survives submitted while the captured-insert drain still force-deletes its own GL/PLE rows
   — a resident submitted invoice with no ledger, the #328 shape. *Inference from two
   measurements, not observed; verify before acting.*
3. The handoff's "805 vs 304" compared mentions against imports. Apples to apples: **1748 test
   classes** on the unguarded base vs 476 on the guarded one. Magnitude right, comparison
   wasn't.

## Corrections I had to make mid-session

Recorded because all three are the same shape — a number or a claim relayed one hop without a
control.

- I told the user a `tabCompany` count was **0** on two sites. It is **51 and 40**. The
  original report said "no Company *named* `Test Vereniging`" and I compressed it wrongly
  while briefing an agent.
- I relayed a review's finding that "ruff inspected zero of the 10 files" as fact. The agent
  that owned the branch probed it with a positive control on a rule the repo actually selects
  and showed `ruff check --config pyproject.toml` **does** lint them. The true, narrower claim:
  the repo's own *tooling* never lints them, because the pre-commit hook adds
  `--force-exclude` and its regex also matches `.*test.*\.py`.
- I posted an **unconditional** 12-vs-0 measurement on #490. It is order-dependent: it needs
  `test_webhook_user_setup` to have run first and left
  `Verenigingen Payments Settings.webhook_user` pointing at a deleted User. On a clean site it
  reads 0. Corrected in place with the edit disclosed — and the precondition is the better
  finding, because it makes it cross-test contamination via a Single rather than a standalone
  bug.

The rule that keeps earning its place: **an agent's report is not evidence until you have
checked the one number you are about to repeat.**

## For whoever picks this up

1. **#498 blocks #489.** Do not fix #489 alone. Grep the other eight `register(` sites in
   `factories.py` for the same unconditional shape before closing #498.
2. **#485 is one step from a PR, and its agent was stopped mid-verification.** Branch
   `fix/485-harness-logger-conversions` @ `061228aa` is pushed; its worktree
   (`scratchpad/485/wt-485`) has **three uncommitted files** — the review edits applied but
   not verified or committed: the `HARNESS_FILES` addition of `test_sepa_reconciliation.py`,
   its f-string normalisation, and the `singleton_backup.py:212` double-prefix fix. Verify the
   ratchet passes for all nine entries, re-run `test_harness_logger` and
   `test_sepa_reconciliation` both ways, then open the PR. The commit message still needs the
   ruff correction and the S2 precondition above.
3. **The auditor has no PR.** `test/delete-resurrection-auditor` @ `66adffa6`. It is
   report-only by design; the decision to make is whether a census across the whole suite is
   worth running before anyone considers a gate.
4. **#490 now has two instances**, and neither is known to fire in CI. The webhook user's name
   is site-derived (`webhook-user@test-site-3.local`), so CI's `test_site` may behave
   differently — that is what decides whether these are 31 always-vacuous tests in CI or only
   locally.
5. **#499** tracks converging the two remaining savepoint copies. Both now point at it. Note
   that giving them the deadlock branch is a behaviour change in code carrying 1748 test
   classes.
6. **`innodb_rollback_on_timeout` was read on this bench only.** It is a server global and CI
   runs a different MariaDB; it is the MariaDB default so it almost certainly matches, but
   nothing here proves it there.
7. **The live tree dirt resolved itself.** `membership_termination_request.json` was modified
   in the veg11 checkout earlier in this session (file `2026-08-23 03:54`, the live DB's
   DocType still `2026-06-20 12:13` — the documented "test runs export fixtures into the live
   tree" trap). It was clean again by the end, and **nobody reverted it deliberately.** The
   live checkout was still on `b0cd9ac6` at that moment, i.e. it had not yet fast-forwarded to
   the #492 merge. Re-check rather than trusting this sentence: it is a claim about a moment.
8. `test_fee_change_settled_invoice_isolation` and `test_harness_leak_attribution` each fail on
   one test site and pass on another, on **both** trees. Site dirt, not a branch signal — it
   cost two runs to establish, twice.
