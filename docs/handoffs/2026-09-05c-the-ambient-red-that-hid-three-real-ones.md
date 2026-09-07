# 2026-09-05c — the ambient red that hid three real ones, and two more controls that controlled nothing

The session's finding is that **a pre-existing failure on a shared gate is not a neutral
background condition — it is camouflage.** `develop`'s order-dependence baseline was out of
sync with its own tree all day (#886 added two committing helpers, census 1005 → 1007), so
**every open PR failed that gate for an ambient reason.** I read that correctly for 15 PRs and
wrongly for three: #899, #900 and #908 each carried a *genuine* new finding of their own,
superimposed on the ambient one, and I reported all 18 as "red only on the stale ratchet, will
self-heal."

They surfaced only when the branches were merged into one integration tree and the gates were
re-run. Nothing in any individual PR's CI could have shown it.

This is the shard-log rule (*grep for YOUR error strings; a pre-existing red acquits nothing*)
in a new spelling: **when a gate is already red, it cannot tell you anything new until it is
green.** Fixing the ambient failure is not housekeeping to do later — it is a precondition for
reading anything else.

## The ratchet thread, closed

| step | effect |
|---|---|
| #886 added two committing helpers to `test_volunteer_sync_service.py` | census 1005 → 1007, 18 PRs red |
| #912 recorded 1007 instead of fixing it | **merged** — auto-merge fired because the ratchet is *not a required check* |
| **#934** fixed the two sites | tree → 1005, baseline still 1007 → develop red on *shrink* |
| **#937** regenerated the baseline down | develop in sync at 1005, green |

**I was wrong about #912 and said so on the PR.** I wrote "auto-merge will never fire." It
fired. `🔀 Order-Dependence Ratchet` is not in `develop`'s required-status-check list, and
auto-merge waits only on required checks. I established that ruleset fact myself, later, while
building #936 — and never carried it back. *"Cannot go green" and "cannot merge" are different
claims.*

**Load-bearing fact for the next session:** develop's 15 required contexts are Code Quality,
Security Scan, Basic Validation (3.10/3.11), API Security Audit, Documentation Check, API
Contract Validation, Controller Testing, Integration Validation, Quality Gate Summary,
validation, fast-validation, and the three pre-commit ratchets. **Server Tests, Test Summary,
the order-dependence ratchet, Pylint and CodeQL are NOT required.** A red one of those blocks
nothing.

## The review round: 21 PRs, 3 blockers, all of which would have merged green

| verdict | PRs |
|---|---|
| APPROVE | #897 #903 #911 #916 #917 #920 |
| APPROVE + nits | #898 #899 #900 #901 #905 #907 #908 #909 #913 #923 #924 #936 |
| **REQUEST CHANGES** | **#904 #910 #915** |

- **#904** — the auth hoist was right, but it moved `is_current_user` into a `per_user=False`,
  120s **shared** cache: a second board member saw the first caller's identity as "you".
  Reproduced with two real members. Fixed by annotating per caller outside the cache and
  **returning a copy** — `cache_with_ttl` stores by reference, so in-place annotation would
  have written the caller's identity into the shared entry.
- **#915** — its new ratchet's helper called `walk(child)` instead of `yield from walk(child)`.
  Recursion silently discarded; it inspected only top-level nodes. Proved load-bearing by
  reverting two real loop-only guards in `team_management.py` and watching the ratchet stay
  **green**.
- **#910** — its self-check scanned a **file** path, taking the `isfile` branch, so it never
  exercised the `os.walk` codepath every real invocation uses. Mutating that filter left the
  control green while a real scan returned `Total findings: 0`.

**Two of the three blockers are controls that don't control** — the same class as the nine in
the 2026-09-05b handoff, found twice more in one batch.

### The property that separates a working control from a decorative one

#916 passed cleanly, and the reason generalises: **its `run_self_check()` reuses the real
production `scan_file` rather than reimplementing traversal.** #915 and #910 each built a
parallel path — a second `walk()`, a file-vs-directory shortcut — and each got it wrong in a
way its own control could not see.

> A control that reimplements the thing it guards is testing its reimplementation.

Demonstrated three times in one round. This is the most transferable thing in this handoff.

## Merged (4) + one integration PR (23)

Merged: **#934** (order-dependence fix), **#937** (baseline regen), **#891**, **#932** (handoffs).

**PR #943** carries the other 23 as a single CI run instead of 23 — each merge to develop costs
~300 job-minutes, so this saves ~7,000 against a starved queue. All 23 merged with **zero
conflicts**; all five baseline gates pass on the combined tree.

**The cost, stated:** per-merge attribution is lost. A red #943 will not name which of the 23
caused it. That is exactly what `server-tests.yml`'s per-commit trunk concurrency group exists
to preserve, deliberately given up here.

## CI capacity (#935): measured, and my own fix is inert

Queue latency degraded sharply and recently. Measured as **first job `started_at` − run
`created_at`** — `run_started_at` is *always identical to `created_at`* and measures nothing:

| date | day | runs | median wait |
|---|---|---|---|
| 2026-08-21 | Fri | 296 | **1.0 min** |
| 2026-08-28 | Fri | 225 | **0.1 min** |
| 2026-09-04 | Fri | 430 | **57.1 min** |
| 2026-09-05 | Sat | 628 | **≥93.6 min** (78 still queued, 71 over an hour) |

Two traps: **sampling only started runs is survivorship bias** (the naive 09-05 median is
`0.0`, because the delayed runs have no `started_at`), and **day-of-week confounds everything**
— I first compared a Sunday against a Friday and drew the wrong conclusion.

Ruled out: billing (`netAmount 0.0`, public repo, free unmetered), other org repos (all zero),
the Free plan's 20-job cap (only **4** jobs were running), #902's concurrency groups (present),
and an Actions outage. What remains is **capacity-knee vs throttling, and today's data cannot
separate them.**

**PR #936 does not settle it.** Its draft-PR gate is **inert** — 0 of the last 100 PRs are
drafts, 0 of 30 timelines show a draft transition. I proposed that gate as the dominant lever
and never checked whether drafts were used. Only the chaos-weekly half is real (~8,600
job-min/month, ~1.8% of ~465,000). **So a flat latency re-measurement after #936 lands is
evidence of nothing** — recorded on #935 so it is not misread as settling the question.

## Filed (10)

#933 #935 #938 #939 #940 #941 #942 #944 #945 #946 #947

Worth reading first:

- **#945** — the #899 recovery sweep short-circuits on a `Donation` row existing, not on the
  charge being **booked**. The webhook path is safe only because it re-attempts booking
  regardless; the sweep doesn't, so a permanently-failed booking is marked done and never
  retried. Defeats the exact failure class #872 exists to close. **Ships in #943.**
- **#938** — `application_payments.py:140` is the **last** production `operation="submit"` site
  with no partial-write compensation; a failed submit strands a `docstatus=1` membership
  invoice. All five sites swept.
- **#946** — the #908 db-clock validator is a **line regex over raw SQL**, so every `frappe.qb`
  date window is invisible to it. It cannot tell "none exist" from "I can't see them."
- **#947** — three PRs in one round assert a **proxy** instead of the outcome (#924 role
  profiles vs real roles, #898 a query ceiling vs a call count, #900 a pre-seeded vs a
  fresh-install branch).
- **#942** — a test that cannot fail: the fixture self-assigns `mandate_id`, so the
  naming-pattern generator it claims to test is never invoked.

Evidence added rather than duplicated: **#602** (five local `safe_log_error` wrappers that
invert internally, so every call site *looks* correct), **#912**, **#925** (the expulsion
mechanism reproduced end-to-end, plus the fix shape that works).

## What I got wrong

- **"Auto-merge will never fire" on #912.** It fired. The ratchet is not a required check.
- **"Those 18 PRs are red only on the stale ratchet and will self-heal."** True for 15. Three
  carried their own findings, masked by the ambient failure.
- **I proposed a draft-PR gate as the main CI lever without checking whether this repo uses
  draft PRs.** It doesn't. The lever is inert and the experiment I designed around it is void.
- **I dismissed an agent's correct finding** (`partial_write`) because I grepped the working
  tree, which is ~34 commits stale. **Third time today** a stale-tree read misled me — the
  first two were the concurrency-group grep and the Sunday/Friday latency comparison.
- **I read `$?` after a pipe**, got `tail`'s exit code, and both baseline gates looked like they
  passed when one was failing. My own notes name this exact trap.

## For the next session

1. **#943's CI is the only unproven step.** Twenty-three individually-green branches is not
   evidence the combined tree is green — shard co-tenancy is where this repo's failures live.
   If it goes red, attribution is manual: bisect by dropping merges, not by re-reading logs.
2. **Then #893** (re-reviewed APPROVE) is already in #943; **#776, #777, #896, #919, #922**
   are not — each has a real failure or an unmet required check. #896 is pure stale-base (22
   commits behind; both fixes already on develop). #777 adds a reader for a `form_data` key no
   form posts — its own invariant test caught it.
3. **Never grep the main working tree** at `apps/verenigingen` to decide whether a symbol
   exists. It is 34+ commits behind and has produced three false readings in one day. Use
   `git show origin/develop:<path>` or a detached worktree.
4. **When a shared gate is red for an ambient reason, fix it before reading anything else.**
   That is the lesson this session paid for.
