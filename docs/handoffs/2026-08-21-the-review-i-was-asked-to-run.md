# Handoff — 2026-08-21: the review I was asked to run

The brief was one filename: the previous handoff. Its Next list said **#414 first —
the only item that can take money from donors.** #414 turned out to have been fixed
five days before it was filed. Then the two PRs I wrote instead went out without a
skeptical review, and when the user asked "okay, skeptical review performed?" the
honest answer was no. Running it found a real defect in **every** PR, including a
regression I had introduced and would have merged.

## Landed

| PR | | merge |
|---|---|---|
| #419 | trunk pushes get their own concurrency group | `bf1bf6a2` |
| #418 | the Mollie resource list, checked against the installed SDK (#415) | `4a069f0a` |
| #422 | the history manager stops ending the caller's transaction (#411) | `e7be9cf0` |

`develop` is at **`e7be9cf0`** and **RED** — see "The trunk I turned red" below. The live
tree is still at `adae1ddf`, three merges behind, **not deployed**.

| issue | |
|---|---|
| #414 | **closed as already fixed** — see below |
| #415 | closed by #418 |
| #411 | closed by #422 |
| #421 | `payment_mixin._get_invoice_with_retry` commits mid-request, and that one cannot just be deleted |
| #424 | the history manager's `FOR UPDATE` hard-codes `tabMember`, so the Donor path takes **no lock at all** |
| #425 | history writes now ride the caller's transaction; two of the four tables have no integrity sweep |
| #426 | `chaos-shards.yml` has the same pending-cancellation trap |
| #431 | `test_membership_status` borrows a company, so any test-file edit can redden its shard |

## #414 was already fixed, inside the PR that supposedly left it open

The issue body opened *"Merged in #346 with this outstanding."* False. The fix is commit
`8a8566ac`, on `fix/donation-subscription-activation` — **#346's own branch** — and
therefore an ancestor of the `adae1ddf` merge. #415 was the same story: four of its five
items were fixed by the same commit.

Both were filed on 08-20 from a review comment written on 08-15, *before* that commit.

The previous session followed the repo's rule 5 — it read the thread. The missing step is
the next one. **A review comment describes the code as it was when the comment was
written; the authority for what is broken today is the merged tree.** `git log -S"<the
symbol the comment names>"` plus `git merge-base --is-ancestor` settles it in seconds.
That is now a memory entry.

Closed with discriminating evidence, not a reading: 17/17 and 21/21 green, then the guard
mutated out —

```
_find_subscription_for_payment -> return None
  FAIL test_late_retry_after_the_idempotency_key_expires_does_not_duplicate
  AssertionError: 2 != 1 ... got ['sub_FAKE0001', 'sub_FAKE0002']
```

— which reproduces exactly the donor double-charge the issue describes. Green alone would
have been consistent with "fixed" *and* with "the test never looked at it".

## What the skeptical review found

Three agents, one per PR. **All three returned REQUEST CHANGES.**

**#422 — a regression I introduced.** `add_or_update_entry` takes `SELECT ... FROM
tabMember WHERE name = %s FOR UPDATE`, and a row lock lives until the transaction ends.
The commit I removed was what released it. Measured with a control:

```
branch as-is:              second connection -> (1205, 'Lock wait timeout exceeded')
control, commit re-added:  second connection -> acquired
```

Worst precisely where I had put the new commit: one commit at the *end* of
`bulk_update_payment_history` accumulates an X-lock on every member in the batch and holds
them for the whole run, while `_get_invoice_with_retry` sleeps up to 6s per not-yet-visible
invoice inside that window. I was right that the retry loop's *logic* did not depend on the
commit, and wrong about locks — **the claim was true and irrelevant.**

**#419 — my fix was the wrong half.** With `cancel-in-progress: false`, GitHub keeps at
most ONE pending run per group and cancels older pending ones, so gating the flag alone
trades cancelled-while-running for cancelled-while-pending. Simulated against the real
history: 4 still cancelled, 12 delayed by up to 36 min.

**#418 — the coverage check had the defect it was written to catch.** My predicate was
`issubclass(cls, ResourceCreateMixin)`, which misses `Onboarding` — it subclasses
`ResourceGetMixin`, defines its own `create()` calling `perform_api_call(REST_CREATE)`,
and does not even accept `idempotency_key`. A remote create that is non-idempotent by
construction, invisible to the check I had just written to find exactly that.

## The trunk I turned red

Both trunk runs after my merges failed, on **two different pre-existing fixture defects**,
neither of them in the code I merged:

| run | shard | failure | issue |
|---|---|---|---|
| `4a069f0a` (#418) | 12 | `No company with a current Fiscal Year and Income Account found` | #431 |
| `e7be9cf0` (#422) | 4 | `'TEB Bank One - TEBPC' account is already used by ...` | #395 |

The same control holds for both, and it is strong: **the failing shard contains none of the
test modules that PR edited** — 0 occurrences, checked per module — and each victim passes
standalone on the merge commit *and* on the commit before it (14/14 and 50/50). What the
merges changed is the *seating*: shard bins are packed by measured runtime, so editing any
test file re-packs all twelve, and a latent fixture collision moves next to a new neighbour.

**This was predicted and I merged anyway.** Before merging #418 I wrote that the shard
failure "isn't mine" and noted the packing risk in the same breath. Both halves were true,
and the second one is the one that mattered: in a repo with six open fixture-ownership
defects (#390, #392, #394, #395, #406, #431), merging three test-touching PRs in a row is
a near-guaranteed re-pack, and a re-pack is a coin flip on latent collisions.

**The lesson is about sequencing, not attribution.** "Not caused by my code" was the right
answer to the wrong question. The right question was whether landing it would expose
something else, and I had the evidence to answer that before merging. Fix the fixture
family first, or merge one test-touching PR at a time and watch the trunk run between.

## Findings worth keeping

**Documented is not available.** `queue: max` is in GitHub's own workflow-syntax reference
and **this instance rejects it.** I found out by pushing it as the discriminating check
rather than trusting the docs:

```
run 32417392620  created 21:03:15Z  updated 21:03:16Z  jobs: 0  conclusion: failure
                 "This run likely failed because of a workflow file issue"
```

One second, zero jobs — a validation error. The replacement (a per-commit group on push)
was verified the same way: run created **with 13 jobs**. Rule 1 applies to vendor docs too.

**Three of my own measured premises were wrong, and they were in a permanent code
comment.** I had written that a cancelled trunk run leaves the trunk *unverified*. It does
not:

```
cancelled develop runs examined:    16
covered by a later concluded run:   16
not covered:                         0
```

Every cancelled commit is an ancestor of a later commit whose run concluded — the head was
always tested, as part of a superset. What is lost is **per-merge attribution**. Also
"about an hour" was a 36.5-min median, and "10–90 minutes apart" omitted that 6 of 39 gaps
are under a minute — the burst case the new policy handles worst. **A statistic that
survives into a comment gets read as fact for years; measure it before you write it down.**

**Grep the claim, not the phrase you happen to have.** I "fixed the class" of a wrong
comment, found two occurrences, and missed a third — because I grepped the exact wording I
had rather than what it asserted. The missed one said the idempotency key alone makes
re-delivery safe, *"for the same reason as above"*, pointing at a paragraph I had just
rewritten to say something else. This is CLAUDE.md rule 6, violated while consciously
applying it.

**A red shard that does not contain your code.** #418's shard 12 failed with `No company
with a current Fiscal Year and Income Account found`. The module passes standalone on the
branch **and** on untouched develop (14/14 each); a re-run reproduced it identically (as it
must — same co-tenancy); and the failing shard **contains zero occurrences of the module I
edited**. Editing any test file re-packs every bin, so the victim simply landed beside a
different neighbour. Filed as #431. Merged on that evidence.

**Guards need their evasions tried, and then tried again.** #408 taught two evasions;
review found four more that walked past mine — `frappe.db.sql("COMMIT")`,
`c = frappe.db.commit; c()`, `getattr(frappe.db, "commit")()`, and `frappe.db.begin()`
(START TRANSACTION implicitly commits and discards every savepoint — this repo's
`ImplicitCommitError` class). All four now caught, each proven by injection with a control.
The two guards were also copy-pasted and had **already drifted**; they are now one detector.
The remaining blind spot — a commit inside a helper the module calls — is written into the
docstring rather than implied away.

**CI caught something the review did not.** The failed-write ratchet flagged my per-member
commit as a swallowed write: it sat inside the handler that logs a member's failure and
continues. Baselining it would have been the easy wrong answer. A commit does not fail for
member-specific reasons — it fails on 1213 or 2006, where the transaction is already gone,
and continuing lets every later member "succeed" against nothing. Moved outside the
per-member `try`, so it propagates.

## What went wrong in how I worked

**I did not run a skeptical review until asked.** Three PRs were open before anyone
adversarially read the diffs, and the #422 lock regression would have merged. The repo has
both a `requesting-code-review` skill and a dedicated reviewer agent; neither is useful
unbidden. **Review before opening the PR, not after being asked.**

**`git checkout -- <file>` to undo a mutation reverted the whole file**, including
uncommitted work in it. Recovered from the apply scripts. Commit first, or un-apply the
mutation with the same script that applied it.

**I claimed a class was closed after grepping one phrasing.** See above. The tell was
available: the comment I was fixing said "for the same reason as above", which is itself a
pointer to a sibling.

## Next

- **The trunk is red on two counts.** #431 (borrowed company) and #395 (Bank Account
  claiming another fixture's GL account). Neither is in merged code; both are latent
  fixture-ownership defects that a shard re-pack surfaced. These come first — a red trunk
  makes every later red shard unreadable.
- **Do not deploy `develop` while it is red.** The live tree is 3 merges behind at
  `adae1ddf`.
- **#421** is the reason per-member atomicity still does not hold. It is load-bearing —
  under REPEATABLE READ the invoice retry cannot see another session's insert without
  ending the transaction — so it needs a mechanism, not a deletion. Three directions are
  in the issue.
- **#424** is the sharpest of the new ones: a `FOR UPDATE` that matches zero rows is not an
  error, so the Donor path has been running with no concurrency protection at all, silently.
- **#431 / #406 / #390 / #394** are one family. Every one of them taxes unrelated branches.
- The #419 fix is **not yet proven**: no merge burst has happened under the new group. The
  check is a develop run that overlaps the next merge and reaches a conclusion.

## Raw evidence

```bash
# an issue that was already fixed, by the PR that supposedly left it open
git log --oneline -S"_find_subscription_for_payment" -- verenigingen/verenigingen_payments/utils/payment_gateways.py
git merge-base --is-ancestor 8a8566ac adae1ddf && echo "shipped in #346"

# the lock the removed commit was releasing
#   branch: (1205, 'Lock wait timeout exceeded')  control (commit re-added): acquired

# documented != available
gh api repos/nlvegan/verenigingen/actions/runs/32417392620 --jq '.created_at, .updated_at, .conclusion'
gh api repos/nlvegan/verenigingen/actions/runs/32417392620/jobs --jq '.jobs | length'   # -> 0

# the red shard did not contain the change
grep -c mollie_integration_invariants <shard-12 job log>   # -> 0

# every guard evasion, each red before the fix
frappe.db.sql("COMMIT") · c = frappe.db.commit; c() · getattr(frappe.db,"commit")() · frappe.db.begin()
```
