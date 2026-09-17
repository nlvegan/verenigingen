# 2026-09-18 — six rounds, and every blocking defect was in the instrument, not the fix

**State at handoff:** `develop` at `de2aaa394`. **#1152 merged** (closing **#1150**),
**#1155 merged** (#1154's drain sweep). Two issues filed: **#1153** (SEPA LIKE-escape
ordering, a money path) and **#1154** (the Company-orphan class, left open with its
remainder written down). **#1154's own producer list was corrected by measurement after I
filed it** — see below; do not work it from the issue body alone.

The session began with one question: run the skeptical reviewer on #1152's answering
commit. It ended six review rounds later, and the shape never changed.

---

## The through-line

**The fixes were fine. The things that were supposed to prove the fixes worked were
defective, six times, and four of those were mine.**

| round | what was wrong | how it was caught |
|---|---|---|
| #1152 r1 | every assertion was against a return value `tearDown` discards; deleting the `.error()` call left all 5 tests green | skeptical review |
| #1152 r2 | the residue check enumerated the doctypes `Company.on_trash` **does** clean — so the instrument reported clean on the exact failure it existed to catch | skeptical review, from this branch's own CI log |
| #1152 r3 | the property the commit message **led with** ("the sweep runs whether or not the delete raised") had no test; a one-line `return` left 25/25 green | skeptical review |
| #1152 r4 | my own new test published the **real** alarm tag, so `grep PROBE-RESIDUE` still returned this suite's noise first | CI, after merge-ready green |
| #1155 r1 | the drift guard built its probe under `ignore_chart_of_accounts` — the flag every hrms Company hook returns on — so it could never see the drift it existed for; and exempting `Company` disabled the whole fix with 68/68 green | skeptical review |
| #1155 r2 | the per-source control I added **in response to r1** asserted the helper returned rows, not that the aggregate included them — dropping the source entirely still passed | my own mutation of my own control |

The last row is the one to internalise. A control written to close a review finding *feels*
verified, because a reviewer just described the defect precisely. Describing a defect is not
testing the fix for it. **After adding or fixing any control, mutate the thing it is
supposed to catch and watch it redden** — budget one mutation run per control, not per
commit.

The same trap fired twice on the same PR: on #1152 I wrote that a cosmetic control had been
"replaced" when it was still sitting in the file, still unable to fail.

---

## #1150 / #1152: the instrument reported clean on its own case

The original PR made a swallowed teardown failure loud. Its CI run was green and the
diagnostic printed nothing for the real probe company — four minutes before four
`setUpClass` calls died on a dangling link to it.

Reading the shard-12 log of `936e54bc6` (run `35210287807`, job `105166193352`) settled it:
**every `PROBE-` line in that log came from the PR's own control tests.** The real teardown
emitted nothing. For a diagnostic-only PR that is the worst available outcome — a false
clean that would lead the next reader to rule out stranded rows as the mechanism.

The reasoning error is worth naming because it is general: the residue check enumerated
Cost Center / Warehouse / Mode of Payment Account **because `Company.on_trash` sweeps
them**. Backwards. Rows a cleanup deletes are the least likely residue; **residue is
whatever nothing deletes.**

### The actual mechanism, read from the refs CI resolves

Local hrms is `develop` (2025-11) and does not contain the function at all, so none of this
is visible on this bench:

* hrms `version-16` `Company.on_update` → `set_expense_claim_type_accounts` appends an
  `Expense Claim Account` child row — `company` + `default_account` — to **every**
  `Expense Claim Type`.
* `Company.on_trash` → hrms `handle_linked_docs` deletes only the nine doctypes in
  `company_data_to_be_ignored`. That list does not include it, and erpnext's own
  `Company.on_trash` never mentions Expense Claim.

So a `force=True` delete strands rows whose `company` and `default_account` both dangle,
and the next Company insert dies in `_validate_links` while hrms re-saves the shared
Expense Claim Type. That shared parent is what makes this doctype different from every
other survivor — a stranded Account is standalone and nothing re-saves it.

**Measured across a real force-delete of all 190 doctypes carrying a `company` Link field:
exactly one survivor.** With one caveat found in review and now in the docstring: that holds
only for a company with **no GL Entry**. erpnext gates its Account/Cost Center/Budget/Party
Account cleanup on `if not rec` from `tabGL Entry` (`company.py:763`); with one GL row the
same probe survives carrying `{'Cost Center': 2, 'GL Entry': 1}`.

---

## #1154: I filed the issue, and its producer list was wrong in both directions

The list came from reading call sites. Measuring them changed it substantially.

**Method, with a two-way control before trusting any verdict.** `ignore_chart_of_accounts`
is the discriminator — hrms's row-writer returns on it as its first line. In a throwaway
worktree, `verenigingen/tests/__init__.py` (imported before any test module) wrapped
`Company.db_insert` / `on_update` / `on_trash`, recording per company: inserted here? CoA
suppressed? trashed? Producer = CoA-bearing **and** inserted **and** trashed. Every verdict
was cross-checked against a second channel — whether the company still exists on the site.

```
control, known producer      TEST-EB-Payment-Shared-Probe-5e2f05 : False
control, known non-producer  ZZ Foreign Co 299                   : True
```

**~5–6 producers, not 8 — but two create a company per test**, so `test_cost_center_creation`
alone is ~125 stranded rows in CI, not one. Three of the original eight are not producers at
all: they create companies and never delete them.

**Two confounds that will bite the next person:**

1. **A dirty site hides producers.** `test_site_5` carries **58 leftover companies**.
   `test_chapter_board_permissions_comprehensive` and `test_cost_center_parsing` both
   get-or-create the literal name `"Test Company"`, which is among them — so their insert is
   skipped and the probe sees nothing. Read "no activity" as "not a producer" and you will
   be wrong.
2. **The three false positives are a different defect, and it is self-inflicting.** In
   `ChapterBoardTestFactory.ensure_test_company`, `track_doc` sits **inside the created
   branch** of the get-or-create — so once the row exists it is never tracked and never
   cleaned. The get-or-create leaks the row it then reuses forever. That is #390's
   territory, cross-linked there rather than duplicated here.

---

## #1155: the fix, and what the review changed about it

One sweep in `EnhancedTestCase._remove_drained_record` — the choke point both
`_drain_captured_inserts` and `_drain_tracked_documents` delete through, with `Company`
deliberately not in `DRAIN_EXEMPT_DOCTYPES`. Plus one at
`test_sepa_test_company._delete_company`, which the review found: it force-deletes a
**chart-bearing** company built inside `_suspend_insert_capture()`, so the drain never sees
it and the choke point cannot reach it.

Grepped app-wide there are **four** `delete_doc("Company", …)` sites, and all four now
sweep. Note the count: the review reported three, because its grep matched only the
single-line call form and missed the multi-line one at
`test_rest_migration_payments.py:731` — which is the #1150 probe teardown itself, the
original instance. I repeated the number into the PR body before checking it. A class
sweep is only as wide as its pattern, which is this repo's most expensive recurring
mistake and it recurred here in the act of documenting a class sweep.

`purge_company_orphans` is a deliberate sibling of `purge_ledger_rows`, placed beside it and
called from the same spot. The difference is recorded: `ledger_rows` is data-driven because
its doctype set grows every erpnext release; this one is a measured constant, and the
190-doctype scan lives in the **test**, where it runs once instead of once per teardown.

**Three review findings worth carrying forward:**

* **A guard built on a suppressed hook cannot detect drift.** The scan's probe company was
  built under `ignore_chart_of_accounts`, which is the first thing every hrms Company hook
  checks — so no hrms hook fired at all, and a *new* hook (which will also need a chart)
  would have been skipped too. It asserted "nothing survived" about a state where nothing
  could.
* **One line silently disables everything.** Both drains consult `DRAIN_EXEMPT_DOCTYPES`
  before `_remove_drained_record`, and the tests call that method directly — so adding
  `"Company"` to the frozenset left 68/68 green. The file already records that Company was
  exempted once and that it was wrong. Now guarded, as a sibling of
  `test_ledger_derivatives_are_NOT_exempt`.
* **`return 0` stayed green.** The sweep's count, and the `if swept:` log branch it gates,
  were entirely unexercised.

### The census gate earned its keep

The new log line uses the module `logger`, which **is** `get_harness_logger` — so it sits in
a class-teardown route below the `>= ERROR` stderr mirror and **will not appear in a CI
log**. The census forced that into the open. It is kept at WARNING, matching the ledger
sweep, and the constant's comment now justifies it by the sweep's blast radius being bounded
by construction (it filters on a just-deleted unique docname), not by "successes need no
record".

It also forced the thing it exists for: six prose sites in `harness_logger.py` and the
census test still said *seventeen of twenty* after the constants moved to *eighteen of
twenty-one*. The suite stayed green because every assertion keys on the constant — which is
exactly the failure its own docstring describes, and its failure message literally says
*"Update the paragraph, not just the baseline."*

---

## #1153 — filed, unworked, and on a money path

`services/payment/sepa_mandate_manager.py:447` escapes LIKE wildcards in the **wrong order**
(`%`, `_`, then `\`), so it doubles its own backslashes. Measured against MariaDB, the
result matches **neither** the literal it protects nor the over-match it blocks:

| pattern built from `ABC%DEF` | matches `ABC%DEF` | over-matches `ABCZZZDEF` |
|---|---|---|
| this file's order → `ABC\\%DEF` | **0** | 0 |
| correct order → `ABC\%DEF` | **1** | 0 |

The lookup it feeds allocates the mandate-reference sequence, so a `member_id` containing
`%` or `_` re-allocates `0001` forever and defeats the surrounding `FOR UPDATE`.
**Reachability is unproven** — I found no live `member_id` with those characters — and the
issue says so.

**Do not fix it three times.** Three copies of the idiom exist (`periodic_donation_
operations.py:456` and `reversal_idempotency.py:66` are correct); this PR added a fourth in
test code. The fix worth making is one shared helper. A test asserting only "the escaped
literal still matches" cannot catch it — on a bench with no colliding row, correct and
incorrect escaping return identical rows, which is precisely how the existing control passed
for a round.

---

## If you do one thing

**Finish #1154.** What is left is the non-drain half: `test_cost_center_parsing` and
`test_volunteer_portal_integration` create chart-bearing companies and never delete them
(#390). And the open question this PR explicitly could not answer — **how often the sweep
actually fires in CI** — is not obtainable from a shard log today, because the line that
would report it is a WARNING. If you want that number, raise the level deliberately for one
run rather than guessing.

## Operating notes that cost something this session

* **`gh pr checks <n>` exits 1 when a check failed.** A monitor branching on its exit status
  goes quiet on exactly the runs that matter. Read the JSON.
* **`gh pr checks --json` works on gh 2.100.0.** An older memory note said otherwise; that
  was the 2.45 era and it is now corrected.
* **Re-running a shard is not a flake test.** It reproduces the same co-tenancy and order.
  The informative run is develop's own CI after the merge, where shards re-pack.
* **Restore mutations from a `cp` snapshot, never `git checkout`.** `git checkout` restores
  to HEAD, deletes uncommitted work, and exits 0 — it cost ~170 lines of new tests here.
  `grep -c MUT` afterwards to prove nothing was left behind.
* **A local green says nothing about this sweep.** The local hrms predates the row-writing
  function, so the new code is a no-op on this bench. Its firing is proven by seeded unit
  tests; its harmlessness by a 25-company run.
