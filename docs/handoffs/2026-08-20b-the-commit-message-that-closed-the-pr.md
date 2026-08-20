# Handoff — 2026-08-20b: the commit message that closed the pull request

Session brief was two words — "merge and monitor CI". It became eleven merges, seven
defects fixed and five issues filed, because every time the queue cleared, the next
layer of the same defect class surfaced. The most expensive hour went not to any of
that but to a closing keyword I put in a commit message.

## Landed

| PR | | merge |
|---|---|---|
| #400 | duplicate-helper ratchet | `e297da56` |
| #377 | a failed field lookup no longer disables validation for good (#253) | `ce7b4e54` |
| #402 · #403 | handoffs | `1562e777` · `d8f9d7dd` |
| #399 | the two order-dependent failures blocking four PRs | `4b2535eb` |
| #367 | dead docstatus filters made every donation aggregate return zero | `ab827194` |
| **#405** | **five fixture-isolation defects, each fixed as a class** | `c634f352` |
| #365 | retire test_self_service_fee_adjustment as duplicated coverage | `5051b480` |
| #384 | require every secure_document_operation result to be checked | `b200f784` |
| **#408** | **batch processor: a failed member rolled back the whole transaction** | `d69d2138` |
| #346 | recurring donations never became a subscription (regression) | `adae1ddf` |

**#347** is retargeted onto develop, conflicts resolved, and running its full suite
for the first time — it had only ever run pylint while stacked on #346.

| issue | |
|---|---|
| #406 | 16 test files insert the same Region docname with three different codes |
| #407 | `_purge_orphan_claims` deletes inside the test transaction; rollback resurrects it |
| #411 | `member_financial_history_manager` commits mid-request, destroying savepoints |
| #414 | **duplicate Mollie subscriptions: idempotency guard expires at 1h, retries run 26h** |
| #415 | four holes in the Mollie invariant tests, plus the still-unscanned `form_data` boundary |

**Deployed.** The live tree is at `adae1ddf`, clean, and contains #397's
`_DeadlockError` fix. That was the open item from the previous handoff.

## The trap that cost the most

I wrote this in an #408 commit message:

```
Closes #346's shard-5 failure, where a stale queue entry naming a deleted member ...
```

I meant *closes that failure*. GitHub read **`Closes #346`**. Two seconds after #408
merged, PR #346 was closed automatically.

Everything downstream looked like a different problem each time:

- the PR head froze at `de45c620` while the branch was demonstrably at `4aa40d8d`
- `update-branch` returned `422 merge conflict` — twice — when a local merge of the
  same two commits was clean
- my push triggered only Pylint, because `server-tests.yml` runs on feature branches
  via `pull_request`, and a closed PR emits no synchronize event
- the PR's check rollup kept serving the **pre-#408** run, which I nearly reported as
  my own fix failing

The tell was the run ID: the "new" failure I fetched was `32357996877`, a run I had
already read hours earlier. **A result that names a commit you did not build is not a
result.** Check `event=` and `headSha=` on the run, not just the rollup.

Reopening the PR fixed all four symptoms at once. Audited the rest of the day's
merged commits for closing keywords: one occurrence, this one.

## What #405 and #408 actually fixed

**#405 — five defects, each a class.** In every single case the instance CI reported
was not the only one: the seeded-row bug had **seven** sites, the drain priority
**eight**, the region code **six**. Evidence that this mattered rather than being
tidiness: with the naming series poisoned locally, the first run failed on the Sales
Invoice and the second on the Payment Entry; and #346 independently hit the same
defect on `ACC-SINV-2026-00001` while #365 hit it on `-00002`. A narrower fix would
have moved each failure, not removed it.

**#408 — the batch processor promised per-member atomicity and delivered the
opposite.** Both handlers ended in a bare `frappe.db.commit()` and, on failure, a bare
`frappe.db.rollback()`. Both transaction-**wide**. The dispatch loop catches per-member
exceptions and continues, so the code believes a failure is isolated — by then the
rollback has discarded every other member processed in that run plus the caller's
in-flight work, and the caller swallows the exception, so the run reports success.

Reachable in production through RQ jobs and the history subscribers. Control:

```
stale entry for a missing member + caller's uncommitted member in flight
  before:  caller's member DESTROYED
  after:   caller's member SURVIVED
```

## Findings worth keeping

**A guard whose evasion you have not tried is not a guard.** #408's AST source guard
is the *only* thing pinning the savepoint invariant — the behavioural test
short-circuits on the missing-member skip. Review defeated it with two one-line edits:
`rollback(save_point=None)` (frappe branches on `if save_point:`, so `None` **is** the
transaction-wide path) and the aliased `db = frappe.db; db.rollback()`. Both now
caught, all three mutations verified red.

**Per-member atomicity still does not hold, and saying so is the point.**
`member_financial_history_manager` commits on its first successful save, destroying
the savepoint — measured on 10 of 10 batches. Past that the scoped rollback is a
no-op. What holds unconditionally is that a failure never *escalates*. The docstrings
now claim only that. #411.

**`except Exception` around a savepoint rollback is too broad.** 1305 (savepoint gone
after an inner commit) is benign. 1213 (deadlock) and 2006 (server gone) are not — the
whole transaction is already discarded, and continuing to feed members into it lets
each one "succeed" against nothing. Gate on the code.

**Not every tracker is priority-ordered.** Review suggested adding `track_doc` to the
Expense-Claim-before-Employee invariant. It would have been wrong:
`VereningingenTestCase` cleans `reversed(self._test_docs)` — LIFO, no priority — so
registration order already handles it, and the check reported a false positive on
`test_document_links.py`. Restricted to `track_document` / `_track_test_document`.

**A detector is code and needs the same class check as a fix.** The first invariants
matched only the shapes already fixed. Widening series detection past `naming_series:`
(to `format:` and expression autonames like `ACC-GLE-.YYYY.-.#####`) found 4 unnamed
GL Entry seeds; replacing the region regex with an AST rule found 2 unchecked hex-slice
codes; rewriting the priority check in AST caught the omitted-`priority=` case the
regex could not see. **Nine instances in total that the first version missed.**

**The trunk suite is cancelled by every merge.** `concurrency: server-tests-${{
github.ref }}` with `cancel-in-progress` is right for PRs and wrong for `develop`: the
suite takes ~an hour, merges came 10–90 minutes apart, and the run that verifies the
merge that just landed is killed by the next one. Gate it:
`cancel-in-progress: ${{ github.ref != 'refs/heads/develop' }}`.

## What went wrong in how I worked

**I merged a PR without reading its thread.** #346 carried a comment listing
outstanding work including a **BLOCKER** — Mollie caches idempotency keys for 1 hour
while its retry ladder runs 26 hours, so attempts 8–10 can create duplicate
subscriptions that each charge the donor every period. I ran `--comments` piped to
`tail -150` *in the same command as the merge*, saw the first line, and merged. The
repo's own rule says the body is the source and the thread is the system. Recovered as
#414 and #415, but the fix is procedural: **read the thread as its own step, never in
the same command as the merge.**

**I misattributed my own regression, confidently.** Four CI failures appeared after I
removed the batch processor's `commit()`, so I restored it and wrote a commit message
explaining why it was load-bearing. Wrong: those failures came from the run *before*
the savepoint handling became defensive, and the 1305 was masking the real error. A
controlled two-state experiment — commit absent in both arms, defensiveness the only
variable — showed the commit was never needed. Kept both commits rather than amending
the wrong turn away.

**Two false signals in a row, from different causes.** GitHub's stale rollup, then my
own monitor's filter treating an empty `conclusion` as a failure. Either would have had
me report the fix as ineffective on evidence that was never about it.

**I over-applied `black`** to files already unclean on develop — the stray reformat the
repo explicitly warns against — and had to revert it. Check base-unclean *before*
formatting, then format only your own files.

## Next

- **#414 first.** It is the only item here that can take money from donors.
- #411 blocks real per-member atomicity and forces the defensive savepoint handling.
- #406 is deterministic, not probabilistic: 16 files, one docname, three codes,
  whichever runs first wins.
- The `cancel-in-progress` change above is two lines and stops the trunk from going
  unverified across a merge burst.

## Raw evidence

```bash
# the closing keyword, and its two-second cascade
git log -1 --format='%b' 2a091423 | grep -n "346"      # -> "Closes #346's shard-5 failure"
gh pr view 408 --json mergedAt   # 14:30:23Z
gh pr view 346 --json closedAt   # 14:30:25Z

# a result that describes another commit
gh run view <id> --json event,headSha   # check BOTH before believing a rollup

# the batch-processor control (probe in the session scratchpad)
#   base: caller's uncommitted member DESTROYED
#   fix:  caller's uncommitted member SURVIVED

# the guard's evasions, all three now red
frappe.db.rollback()                 # caught before
frappe.db.rollback(save_point=None)  # was GREEN
db = frappe.db; db.rollback()        # was GREEN

# the purge that could not work (#407), measured not argued
orphan claims before purge: 1 / after purge: 0 / after rollback: 1
```
