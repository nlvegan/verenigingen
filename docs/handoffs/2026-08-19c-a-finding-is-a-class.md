# Handoff — 2026-08-19c: a finding is a class, not an instance

Landed the #386 chart-of-accounts fix, discovered it reproduced the bug it fixed, built two
validators, and cleared a four-PR queue. The through-line is one sentence:

> **Every finding today turned out to have more instances than the one in front of me — and
> in each case the fixed instance carried a comment explaining exactly why the fix was
> needed. That comment was the search query nobody ran.**

Four separate times. It is now rule 6 in CLAUDE.md's Verification discipline.

## State

| | |
|---|---|
| `develop` | `c1f1cd35` |
| Merged today | **#387** (TPIC), **#391** (test-quality ratchet), **#342/#371/#380/#389** (handoffs) |
| Open, green | **#400** duplicate-helper ratchet · **#377** (12/12 shards, held deliberately) |
| Open, needs CI | **#399** two order-dependent test fixes — re-run in flight |
| Open, real failures | **#384** (shard 12) · **#367** (shard 7) · **#365** (shards 2, 6) · **#346** (shard 2) |
| Open, draft | **#379** reversal booking · **#378** |
| Not mine | **#397** (`0spinboson`) — untriaged by this session |
| Issues filed | **#390, #392, #393, #394, #395, #401** |

## What landed

**#387 — the TPIC collapse.** `TestPaymentProcessingIntegration` built its company inside a
test body, so the captured-insert drain owned the Company and its ~100 accounts. The class
posts a Payment Entry against its own bank account, so that delete failed at teardown, its
ancestors failed with it, and the rest of the chart went. The next rebuild got **no chart at
all** — `Company.on_update` only calls `create_default_accounts()` when the company has zero
accounts.

> **A partially-drained company is permanently unusable, not merely empty.** Rebuilding does
> not repair it.

Fixed by `@shared_fixture` on all five company builds in the file. Effect, measured across
four independent branches: shard 3 went from **36 `setUpClass` errors to 1** on #379, and
cleared entirely on #346, #365 and #367.

**#391 — the test-quality enforcer, ratcheted.** The gate ran only on the changed file set,
so `develop`'s 40 failing files were invisible until someone's push touched one — which is
what merging `develop` into a branch does. Five defects had to be fixed before a baseline
could mean anything; see *the trap that nearly shipped* below.

## The four instances

| the fix | where it was missed |
|---|---|
| `TEST-Payment-Integration-Company` had two owners (#386) | the fix picked `TEST-EB-Payment-Company`, a name `test_rest_migration_payments.py` had owned since 2026-06-17 (**#392**) |
| `_persist_eur_company` stopped resolving a company by currency | two copies fixed **with a docstring recording why**, a third missed — there are **eight** (**#394**) |
| a GL query scoped by company, not `voucher_no` alone | its sibling **40 lines below**, comment and all, never got it — 8 rows vs 2, on three branches (**#399**) |
| amount-guard tests made to assert their own guard | two branches wrote it independently and collided on merge (#365 conflict) |

The second one is the sharpest: I wrote "nothing it creates or drains can reach a company it
does not own" into a docstring and a PR body, having never grepped for the name I chose.

## The trap that nearly shipped

The v1 design for #391 named "ignore matches inside strings" as a prerequisite for
generating the baseline. That would have **silenced 58 of 120 findings**, because 14 of the
enforcer's 18 patterns *require* a quote:

```python
r"frappe\.set_user\s*\(\s*['\"]Administrator['\"]"   # 2/6 permission patterns
r"patch\s*\(\s*['\"]frappe\.db\.get_value['\"]"      # 9/9 database mocks
```

The baseline would then have been generated from the crippled detector, and **the ratchet
cannot notice — a shrinking baseline is the direction it celebrates.** Every false-positive
test would still have passed.

The fix is containment-based: a match is dropped only when it lies *entirely* inside a
comment or string token. A quote-requiring pattern's match starts at the call, outside the
literal, so it survives.

> **A gate's own tests are satisfied by a gate that finds nothing.** Pin a hard expected
> count before generating any baseline. `WholeTreeTotalsTest` does this for #391.

## Traps that cost real time

- **`cmd | head; echo $?` reports `head`'s exit code.** Twice today I read a failing gate as
  passing. Redirect to `/dev/null` and check `$?` directly, or use `PIPESTATUS`.
- **A shard result of "8 CANCELLED, 4 SUCCESS" is not a pass.** #399 looked like it had one
  trivial failure; it had no valid result at all.
- **`gh pr view --json commits` lists newest-first.** I read a three-commit branch upside
  down and briefly believed the head commit was the base.
- **`gh pr view --comments` is broken here** (Projects-classic GraphQL). Use
  `gh api repos/:owner/:repo/issues/<n>/comments`.
- **`gh pr update-branch` does not exist in this gh version**; `gh api -X PUT
  repos/:owner/:repo/pulls/<n>/update-branch` does, and it merges base into head
  server-side — which sidesteps the pre-push hooks entirely. That is how three PRs were
  refreshed onto the fixed `develop` in one command each.
- **Local state is the enemy of reproducing a shard failure.** Both of #399's bugs pass
  locally. `TEST-EB-Payment-Company` had a surviving 103-account chart from an earlier run,
  which is why #387 measured 33/33 green locally and red in CI. **Wipe the fixture first,
  and run the control on the same perturbed state** — running the fix on a perturbed site
  and the control on a settled one is how a false result gets reported.

## What is left

**Immediate**

1. **#399** — re-run in flight. It unblocks #346, #365, #367 and #384: every remaining
   failure across those four was one of its two tests.
2. **#400** — green, ready. Blocks new copy-pasted helpers.
3. **#377** — green, 12/12 shards, held only so the base would not move under three
   in-flight runs.

**Then**

4. **#346** must land before **#347** (stacked; #347's green is pylint-only until then).
5. **#379** — two genuine failures remain, both its own draft work: the dues booker and the
   C4 reservation are still unbuilt.
6. **#365** now also fails shard 6 — appeared after the merge resolution, not yet triaged.

**The issue backlog, roughly by value**

- **#394** — two suites running in companies they do not own, one of them ERPNext's
  `Test PCV Company` (USD/United States, running a Dutch EUR suite). Active, not latent.
- **#390** — 46 test files build a `Company` inline; **one** is guarded.
- **#395** — two Bank Account fixtures whose existence guard reads a different key than the
  one that must be unique. Six classes die in `setUpClass` from one of them.
- **#401** — 29 clone families ranked for consolidation. Includes
  `_sanitize_error_message`, three near-identical copies (0.99) across three unrelated
  **production** subsystems. An error sanitiser with diverging copies is worth a deliberate
  look; I flagged rather than diagnosed it.
- **#392, #393** — the #387 follow-ups.

## For whoever picks this up

The habit that produced everything above is cheap: **when a finding names a class of
mistake, grep for the class before closing it, and say in the report how many you found.**
Not "I fixed the bug" but "3 occurrences, all fixed" or "1 occurrence, confirmed by grepping
X". An unqualified finding reads as one instance and gets fixed as one.

Two instruments now support it. `scripts/validation/duplicate_helper_validator.py --report`
lists copy-pasted helpers by similarity. CLAUDE.md rule 6 states the habit with these four
instances as evidence. Neither replaces the grep.
