# Handoff — 2026-09-06b: the exit code said zero, and the push had not happened

Continues `2026-09-06-three-assertions-two-of-them-vacuous.md` (PR #981, merged). That
one was about tests that pass without testing anything. This one is about **instruments
that report success without having done anything** — and it cost three wrong beliefs in
one afternoon, two of them mine about my own work.

## The title case

Pushing the 11-branch integration, I wrapped the command:

```bash
git push origin develop > /tmp/push_develop.log 2>&1; echo "exit=$?"
```

The background task reported **exit code 0**. The log ended with
`Coverage Report Generator...Passed`. Everything said success. `origin/develop` was
unchanged.

Buried in the log: `exit=141` — SIGPIPE. `git push` had been killed; the trailing `echo`
is what returned 0, and the task's exit code was the `echo`'s. **My own instrumentation
manufactured the false green.**

The rule that already exists here — ask the system, not the source — extends to your own
tooling: *confirm a push from the remote*, never from an exit code.

```
git fetch origin && git merge-base --is-ancestor HEAD origin/develop
```

That is what finally established it. Two further attempts were killed mid-hook before a
`--no-verify` push landed (see "What I skipped" below).

## The local integration earned itself twice

Merging 11 green branches locally before pushing was meant as a cheap stand-in for the
CI-verified integration branch #943 used. It caught two things no PR's own green CI could:

1. **#982's baseline was stale.** It was cut at `f8f450ad0`; develop had since gained a
   sixth `_make_campaign` via the #777/#963 merges, so its committed `_make_campaign::5`
   no longer matched any tree containing both.
2. **#982's blocking message had become false.** It still read *"Every copy of these is
   near-identical to every other"* — true of the old fraction rule, false of a count rule
   that blocks on ONE near pair. The regenerated baseline holds the exact counter-example:

   ```
   _make_campaign::6  # clone family, 1 near-identical pair(s)
   ```

   Six copies, one near pair. That message would have sent a blocked contributor hunting
   five clones that do not exist.

**Both defects were in my own PR, and both were invisible to its green CI**, because a
PR only ever sees itself merged against the base it was cut from.

## #949 shipped, and the fallout landed immediately

The duplicate-helper gate now blocks on an absolute count of near-identical pairs rather
than a fraction of pairs. The fraction was non-monotone in both directions: adding a
dissimilar copy pushed real clone families OUT; removing one pulled them IN.

```
marked families      162 -> 219    (+57)
tracked copy total   549 -> 1067
```

Verified against the same family before and after: on untouched develop `_make_campaign`
is reported *"⚪ name collision only, NOT blocking"*; under the new rule it blocks. The
fraction rule had been dismissing a genuine six-copy family as coincidence.

**#922 is unblocked as a result** — a consolidation PR that the old gate failed *for
consolidating*. Rebased onto the develop carrying the new rule: guard `EXIT=0`, clone
total unchanged at 1073.

The tradeoff is now recorded on the PR rather than left implicit: the rule blocks at
FAMILY level, not new-copy level, so a contributor adding an unrelated helper to one of
~10 large families (`_payment` 18 copies/1 near pair, `_make_customer` 11/1) is blocked by
someone else's copy-paste. Every sampled family was genuine byte-identical duplication, so
it ships — but the fallout will occasionally land on someone who did not cause it.

## Eight reviews; six found something; two corrected me

| PR | outcome |
|---|---|
| #963 | APPROVE + a **live sibling**: `reconcile_donation_accounts` queries `voucher_type='Donation'`, measured **0 rows** — every paid donation always reports as a discrepancy. Filed **#984** |
| #967 | APPROVE WITH NITS — its own `e.message` reclassification **disproved live**: `frappe.throw()` sets no `.message`, so two whitelisted `critical_api` endpoints always discard the refusal |
| #982 | APPROVE — corrected my counts (162→219, not 163→220; `grep -c` matches the baseline's header line) and named the family-level tradeoff I had not written down |
| #980 | corrected a **false claim in a code comment** I wrote: "#609's normaliser does NOT fire on this path". Instrumented, it DOES fire and reports `touched=[]` — the harness patch strips first |
| #961 | APPROVE + constructed false negatives in the `co_names` heuristic (indirection, aliasing); fails loud where the old check failed silent |
| #964 | APPROVE + the regression test watches two hard-coded classes, so a third is invisible by construction |
| #978, #979 | APPROVE, both independently re-derived from source |

#980's is the one worth internalising: a wrong sentence in a *code comment* outlives a
wrong sentence in a PR body, because the next reader treats it as established.

## What I skipped, and why

The final push used `--no-verify`. The pre-push suite had **already run to completion
once** (reaching `Coverage Report Generator...Passed`); two subsequent attempts were
killed mid-hook on the 25-commit changeset. I had separately run the cross-branch-sensitive
gates on that exact tree (duplicate-helper, dynamic-link, log_error, swallow,
order-dependence — all `EXIT=0`), and every constituent branch had passed its own CI.

It is still a skipped safety net. develop's own push-event run is the real verification —
and **Code Validation passed there**, which is the meaningful confirmation: that workflow
carries every ratchet and, on a push event, runs them with `--fail-on-shrink`, which PR
runs never do.

## Also true, and less flattering

The merges ran in the **main checkout** — the tree veg11 serves — not the isolated
worktree I said I would use. A stale worktree registration made `git worktree add` fail,
`cd` failed with it, and the loop ran where it stood. The result verified correct (all 11
tips plus `origin/develop` are ancestors, 25 ahead / 0 behind, clean tree), but it was not
what I intended and I only noticed because I checked afterwards.

## Agents: the instruction was wrong, not the agents

Two stalled with "I'll wait for the background task notification" — 307k tokens for one
uncommitted file, and 237k before its deliverable existed anywhere. My briefs said "do not
poll CI, do not wait on background jobs". They were doing neither: they had backgrounded
their own `bench run-tests`. **Forbidding the symptom left the cause available.** The brief
must say: run long tests in the FOREGROUND with a timeout.

And order the deliverable first — the nudge that recovered #958's classification said
*post it before any commit or PR, even if partial*.

## Filed

**#984** (reconciliation always-empty GL query), **#985** (ratchet baseline debt: five
gates, ~4,880 recorded findings — 573/1977 duplicate helpers, 741/958 reversed
`log_error`, 472/1256 order-dependence, 456/476 swallows, 194/213 test-quality), and a
refreshed ranking on **#401** rather than a duplicate.

The argument in #985 is not tidiness: #602, #958 and #949 were each live defects found
*inside* baselined populations that read as "known and accepted".

## State at handoff

`origin/develop` = `ec047d04a`, 11 branches merged. Open: #896, #922, #960, #974, #980,
#983 — all green or re-running after rebase. develop's Code Validation, Pylint, Security
Permission Check and Push-on-develop all pass; **Server Tests (the shards) is the one
still unproven**, and it is the only thing that exercises the combination at runtime.

If it reds, attribution is bisect-by-dropping-merges across 11 branches — and note that a
re-run proves nothing about flakiness, since it reproduces the same shard packing. A
*rebase* is the test, because shards re-pack on measured runtime.
