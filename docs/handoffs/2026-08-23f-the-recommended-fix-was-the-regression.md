# Handoff — 2026-08-23f: the recommended fix was the regression, and I never re-fetched

Started from PR #522's handoff (2026-08-23d) and worked its "for whoever picks this up"
list: merged #518, watched #520, then took #523 as the priority.

Two things are worth more than the code that landed.

**The skeptical review was right about the defect and wrong about the fix, and applying
its fix is what proved that.** It found a real ambiguity in my #523 gate and recommended
`is_company_account: 1`, calling it non-breaking because veg11's row has the flag set. It
does. test_site_4's does not. I applied the filter, my own regression test went red, and the
measurement that followed showed the filter *closes the gate outright* wherever the
company's own Bank Account has that flag clear. Verifying a reviewer's recommendation is a
separate act from verifying its finding; only the second one was in my rule.

**I opened a duplicate PR because I never re-fetched `develop` before pushing.** #523 had
been fixed and merged in #538 while I worked. That was not knowable when I branched — the
timeline rules it out — and was trivially knowable before I pushed.

```
15:32  e3e8b7ff  #520 merged -> I branch for #523 from here
15:48  79eff032  #538's #523 fix is authored (another session)
20:09  047be602  #538 MERGED into develop
       ...       I push, open PR #551, and comment on #523 crediting it
       ...       first `git fetch` since 15:32 -> #551 is a duplicate
```

The session had already taught me this twice — a monitor that read #520's stale check
roster and reported the *control* run as the treatment, and #520 being merged out from under
me mid-task. Both were staleness. I still did not fetch before an outward-facing action.

## Landed

| | | |
|---|---|---|
| #518 | #482: the drain no longer strands ledger rows | **merged** `bda38444`, 43/43 green on the correct base first |
| #520 | #508: the settlement payout leg | **merged by Foppe** `e3e8b7ff` at 15:32, 31s before my develop-merge push landed |
| #553 | #544: the settlement gate must not resolve to ONE Bank Account | open, 56/56, `MERGEABLE` |
| #551 | duplicate of #538 | **closed by me**, with the reason |
| #544 #545 #546 #547 #548 | filed from the #523 work | open |

`develop` ran the full suite on the #520 merge: **7/7 workflows, 37/37 check-runs, 12/12
shards.** That answered the question I had been trying to answer through #520's PR — whether
#512 + #518 + #520 coexist — better than a PR merge-ref could.

## #544: both ways of picking one Bank Account are wrong

#538 fixed #523 by resolving the configured GL account to a Bank Account with
`get_value(... {"account": gl})`. That pick is ambiguous. The harness skill has this right —
"that check runs only when `is_company_account` is set but its query ignores the flag" — but
it draws out only the direction I did not need (a flag=0 row blocks a later flag=1 insert).
The direction that bites here is the reverse:

`validate_account()` is reachable only from `validate_is_company_account()`, so it is gated
on `if self.is_company_account:`. `account` carries no `unique` flag and no index. Measured
on test_site_5, rolled back:

```
A  is_company_account=1                    -> inserted
B  is_company_account=0, SAME GL account    -> INSERTED (never validated)
C  is_company_account=1, same GL account    -> rejected, ValidationError   <- the control
get_value picks                             -> B   (Bank Account sorts creation DESC)
```

And the obvious correction is the other failure:

```
test_site_4, the only Bank Account on the company's default GL account:
  unfiltered get_value                 -> 'Mollie Clearing - Mollie Test Bank'
  {"is_company_account": 1} get_value  -> None      <- gate closed
```

So #553 tests **membership** of the set, which needs no choice. Its test reddens against
develop's resolving form *and* against the flag filter — both verified by mutation.

**#538's "behaviourally REDUNDANT" is wrong.** Its message says the unlinked-account guard
only produces an Error Log row, "with nothing resolved, the comparison returns None either
way". `Bank Transaction.bank_account` is **not mandatory**: with the guard removed and a bare
`!=`, `None != None` is False, an accountless transaction falls through, and it is matched at
**0.98 confidence**. Do not remove that guard on the strength of that sentence.

Where #538 is better than what I had: it *logs* the unresolvable-config case. Mine returned
None silently and I had written "nothing surfaces this to an operator" — false for develop.

## The five filed issues, and why they are worth reading together

They are one story: #523's gate had rejected every transaction, so **everything behind it
has never run in production.**

- **#545** — every Mollie API call from veg11 returns HTTP 400 despite a present, correctly
  shaped test key. All four endpoints fail identically; that control is what makes it
  credential/client wiring rather than a settlements bug. So the pipeline is still dead after
  #523, for a different reason. Mollie also documents settlements as needing an Advanced
  token with `settlements.read` — plain API keys are not documented as supported, which may
  make this two problems.
- **#546** — the matcher downloads Mollie's entire settlement history **once per candidate
  transaction**, uncached, inside a daily job. `get_settlement` and `list_settlements` both
  use `get_cached`; this one path does not.
- **#547** — it auto-reconciles on amount + ±3 days + one of three keywords, with **no
  counterparty check**, at 0.98/0.92 against a 0.85 threshold. A wrong match here posts
  accounting.
- **#544** — three production sites now, including develop's own gate.
- **#548** — three tests coupled through Mollie Settings Singles state; the correct tool
  (`_mollie_settings`, which restores originals) exists on the wrong base class, so "restore
  the original value" is currently a breaking change.

Blast radius today is zero: the configured account resolves to a Bank Account with **0**
Pending unallocated transactions. It stops being zero the moment #540 is acted on or #545 is
fixed. **#546 and #547 should be settled before this path runs against a real bank account.**

## My instruments, again

The 23d handoff was about exactly this and it happened three more times.

- **`tail -25` ate the control.** An instrumented run reported **1** call where the
  untruncated log showed **3**. The number I was about to reason from was a truncation
  artifact — same shape as 23d's output cap, in a session that had just read about it.
- **A monitor keyed on the PR rollup, not the commit.** GitHub kept serving the previous
  head's roster after a push, and "all COMPLETED + stable count" was satisfied by it, so I
  reported the *control* run as the treatment. Fix: key on
  `repos/.../commits/<sha>/check-runs`, and refuse to conclude below an expected roster size
  — that floor then fired correctly on a 3-check roster.
- **I fabricated a commit SHA's tail** when restarting that monitor. The API 422s on it, so
  it would have polled a nonexistent commit forever, silently. Caught by `git rev-parse`, not
  by reading what I typed.
- **A console probe's "control" was a `NameError`.** Pasting a closure into `bench console`
  broke scope, so the rejection I read as "the constraint fired" was the variable being
  undefined. A control that fails for the wrong reason is not a control.

## Traps worth carrying

- **`git fetch` immediately before any push, PR, or issue comment** — not only at the start.
  Three failures this session, one public.
- **A green PR check roster can belong to the previous head.** `gh pr view --json
  statusCheckRollup` lags a push; the per-commit API does not. A QUEUED CheckRun also reports
  `conclusion: ""`, truthy in jq.
- **`bench execute` will not take an arbitrary `PYTHONPATH` module**; drive `frappe.init()` +
  `frappe.connect()` from `<bench>/sites` instead. `bench console` mangles function scope on
  paste.
- **Verify a reviewer's recommended FIX, not just its finding.** They are different claims
  and only one was covered by the rule I had.
- A pre-commit hook that reformats after staging aborts the commit with the changes intact —
  re-`git add` and commit again; nothing is lost.

## For whoever picks this up

1. **#553's CI is in flight** — running as of handoff (13 green, 25 pending, 1 neutral) at
   `d39523be`, 56/56 locally. Worth noting the mechanic: only `push`-triggered workflows run
   until a PR exists, so a pushed branch with no PR has never had the shards run against it.
2. **#546 / #547 before the pipeline is switched on.** Not because they are new (they are
   not) but because #523's fix is what makes them reachable, and #547 auto-posts.
3. **#540 first, still.** veg11 has `mollie_bank_account == mollie_clearing_account ==
   '10440 - Triodos 1 - TPIC - TPIC'`, company `TEST-Payment-Integration-Company`. Anything
   this path books there books into a test company's ledger.
4. **The harness skill's `Bank Account` line could carry one more clause.** It is accurate
   as written and I initially mis-read it as wrong — worth noting, since the next reader may
   too. It spells out that a flag=0 row blocks a later flag=1 insert, but not the reverse: a
   flag=0 insert is never validated at all, so it lands *beside* an existing flag=1 row and
   then wins `creation DESC`. That is the direction #544 is about. Per that file's own rule,
   add the measurement if you add the clause.
5. **#544 is not closed by #553.** The two sibling resolvers need a single docname, so
   membership does not apply and they need a deliberate answer. #553 has no coverage for those
   paths, which is why I reverted my first attempt at them.
6. **Handoff PRs are accumulating again** — several were still unmerged when this session
   started, and most landed mid-session; this one adds to the pile.
