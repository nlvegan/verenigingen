# Handoff — 2026-08-22: the fix that was already written down

The brief was "start on the red trunk". Both halves of it turned out to be the same
shape, and both had a sibling that a name-grep had already walked past — including one
copy that had **already been fixed** three weeks earlier, in a commit whose subject names
the mechanism (`9f8fc666`, 2026-07-29, *"remove three order-dependencies exposed by the
new shard split"*), with a comment naming the exact error string. Then the skeptical review found the same shape a third time, three lines
below my own fix.

## Landed

| PR | | merge |
|---|---|---|
| #441 | Bank Account fixtures keyed on what erpnext constrains (#395) | `a6859a76` |
| #440 | the company and income account owned rather than scanned for (#431) | `deb7a885` |

**`develop` is at `deb7a885` and the trunk is GREEN.** The run on `a6859a76` — after the
first merge, before the second — was **12/12 shards**, the first clean Server Tests on
`develop` since the streak began. #440's own final run was 12/12 and 43/43 checks. The
post-`deb7a885` run was in flight when this was written; it is the one outstanding check.

Merge order was not arbitrary. #440 was red on shard 4 for #395's defect — the thing #441
fixes — while #441's shard 4 was green on the same base. Landing #441 first made #440's
only failure disappear instead of leaving the trunk red through two re-packs.

| open | |
|---|---|
| `docs/verenigingen-test-harness-skill` | repo-local skill, pushed, **no PR opened** |

The live tree is still at `adae1ddf`, **not deployed** — 8 merges / 41 commits behind.

| issue | |
|---|---|
| #431 | closed by #440 |
| #395 | closed by #441 |
| #442 | 26 income-account lookups keyed on `account_type`; 3 fixed, 19 latent |
| #443 | 34 Bank Account creation sites, 16 guarding on a key that is not constrained |
| #444 | `_setup_mollie_*`: byte-identical trio, `@shared_fixture` in one file only |
| #445 | the duplicate-helper ratchet cannot see methods; 72 method families have drifted |

## The two root causes

### #431 — the filter keyed on a field the data does not carry

`_get_company_with_current_fy` scanned every Company for one with a current Fiscal Year
*and* an account with `account_type = "Income Account"`. The borrow half was known
(#394/#390). The half nobody had found:

**ERPNext's standard chart of accounts leaves `account_type` EMPTY on income leaves.**
They carry `root_type = "Income"` and an `account_category`. Measured:

| company | `account_type = "Income Account"` | income leaves |
|---|---|---|
| `_Test Company` | 3 — all planted by fixtures | 8 |
| `_Test Company 1` | **0** | 5 |
| `_Test Company with perpetual inventory` | **0** | 5 |

So the helper resolved **only** when a sibling suite in the same shard had already
created one. `Sales Invoice` requires neither field — `validate_account_head` checks
company and non-group, nothing else.

Reproduced mechanically, which is the part worth copying: blank `account_type` on every
Account site-wide and you have a fresh CI site. On a quiet site (`test_site_3`):

| module | develop | branch |
|---|---|---|
| `test_membership_status` | **FAILED (errors=2)** — the exact CI error, the exact two tests | OK |
| `test_financial_reconciliation` | **FAILED (errors=11)** — called from `setUp` | OK |
| `test_chapter_assignment_comprehensive` | OK | OK |

That third row is the negative control, and it is the whole story of this handoff — see
below.

### #395 — the guard reads one key, the database constrains another

Two fixtures, same shape. erpnext's `Bank Account.validate_account` permits exactly one
Bank Account per GL account; the decoy lookup in `test_sepa_reconciliation` asked only
"Bank-type, non-group, another company" and never whether the account was claimed.
The Mollie clearing fixture guarded on the GL link while the PRIMARY key is
`<account_name> - <bank>`.

Both reproduced by creating the condition rather than waiting for it — seed the
competitor; repoint the squatter:

| | develop | branch |
|---|---|---|
| decoy, competitor seeded | **FAILED (errors=1)** `'...' account is already used by ...` | OK |
| Mollie, squatter repointed | **FAILED (errors=5)** `Duplicate entry 'Mollie Clearing - Mollie Test Bank' for key 'PRIMARY'` | OK |

Non-obvious and measured: `validate_account` runs **only** when `is_company_account` is
set, but its query **ignores that flag** — so a `flag=0` row is never checked itself yet
still blocks a later `flag=1` insert. Excluding all Bank Accounts, not just company ones,
is necessary.

## The lesson, three times in one day

**Grep the claim, not the name you happen to have.**

1. `_get_company_with_current_fy` existed in **three** files.
   `test_chapter_assignment_comprehensive` had **already been fixed** for the
   income-account half, with a comment that reads:

   > …which made it depend on whichever earlier test in the same shard happened to create
   > one… It surfaced as "No company with a current Fiscal Year and Income Account found"
   > once the shard split changed. Create our own instead.

   Its two siblings kept the bug for three more weeks, until it reddened trunk twice.
   **The comment was the search query** — and so was the commit subject.
2. For #395, `test_bulk_transaction_importer_sweep` already carried the identical
   Bank-Account-docname lesson, fixed with `{abbr}`. Nobody searched it either.
3. **Then I did it myself, inside the fix.** `setup_test_accounts` took the new helper's
   company and threw its income account away with `_`, then resolved
   `membership_revenue` — the one entry that reaches a real Sales Invoice item — with
   `acct("Income Account")`, the exact filter my own docstring calls wrong. The skeptical
   review found it.

**Why the ratchet did not catch any of it:** `duplicate_helper_validator.py` is restricted
to private **module-level functions**. All three were methods. A method-aware AST pass
finds **478** duplicated private method names, **72** of them near-identical *with no
exact pair* — i.e. a fix already landed in one copy and not the others. That band is the
work-list, and it is #445.

## The reviews, which I ran before opening the PRs

Both returned findings, and both times the finding survived my own verification:

- **#440 — REQUEST CHANGES**, for the `_` discard above. It also killed
  `assertEqual(invoice.docstatus, 1)`, which `submit()` sets in memory and which this repo
  already knows is not proof of posting — now a GL Entry lookup keyed on the **resolved**
  account, so the test fails if erpnext substitutes a default.
- **#441 — APPROVE with comments**, and its sharpest finding killed a line of mine.
  `order_by="name"` sorts **DESC** (frappe appends the direction — measured:
  `order_by='name'` returns the name-maximum, `'name asc'` the minimum). Its comment
  claimed a determinism it does not provide, and it silently repointed which clearing
  account the suite pins on `Mollie Settings` — a committed Single. Dropped.
  It also caught that my new Mollie gate **skipped itself away**: the first draft skipped
  when the squatter row already existed, which is exactly backwards, because on every warm
  site it does.

Also worth keeping: **a `None` inside `["not in", [...]]` matches ZERO rows.** It becomes
`NOT IN (NULL, ...)`, which is NULL-propagating. Building the list with
`get_all(dt, pluck=field)` on an optional field poisons it silently — the helper becomes a
permanent `skipTest` that reports green forever. How often it bites is site-dependent:
400 of 410 Bank Accounts NULL on `test_site_5`, 0 of 14 on `test_site_1`. That variance is
the danger.

## The skill, and what testing it actually showed

Asked to check whether the 61 `frappe-*` skills would have prevented any of this. They
would not, and one would have hurt:

- They are **framework** skills. `root_type` appears in **0** of them; `Bank Account`
  once, in a Jinja example; `Fiscal Year` twice, in a cache-clearing loop. Three of the
  four root causes were ERPNext **domain** facts.
- The near-miss is instructive: `frappe-errors-database`'s fix for `DuplicateEntryError`
  is *"Check existence first."* That is exactly what the #395 fixtures did — on the wrong
  key.
- **`frappe-testing-unit` is actively wrong here** in three places: "never call
  `frappe.db.commit()` in tests" (several commits are load-bearing — an uncommitted
  restore in `own_settings_company` is discarded by the very next `addClassCleanup` and
  re-creates #312), "IntegrationTestCase always rolls back per test, no cleanup needed"
  (the compat base rolls back per **class**, which is why the drains exist), and "guard
  fixtures with `frappe.flags`" (that is #330 verbatim).

So a repo-local skill went in at `.claude/skills/verenigingen-test-harness/`. **But the
testing changed what it is.** Four fresh agents, given realistic fixture-writing and
review tasks here with no skill loaded, **all four passed** — they reused
`get_eur_test_company()`, wrapped builds in `suspend_insert_capture()`, and derived the
Bank Account autoname collision from erpnext source. A later paired test on a module with
five planted defects was found in full by **both** arms.

The tutorial was therefore not the gap, and the file says so, with the scenarios, to stop
it growing that way. What is in it is what those agents could not have known: the
generic-guidance conflicts and the facts in no skill. It carries an **Iteration log**, and
it has already iterated once — the NULL-`account` figure was written from one site and
read as universal.

`.gitignore` needed `.claude` → `.claude/*` plus `!.claude/skills/`, because git cannot
re-include anything under an excluded **directory**. Verified with a control that
`settings.local.json` and `worktrees` are still ignored.

## What went wrong in how I worked

- **I nearly wrote the wrong document.** My instinct was a fixture-writing tutorial;
  the baseline said agents already get that right. Writing-skills' own rule — *if the
  control does not exhibit the failure, there is nothing to fix* — is the same
  discriminating-evidence rule this repo keeps relearning, applied to documentation.
- **A failure I could not reproduce, and its cause.** One `chapter_assignment` run failed
  once and never again in seven attempts. I then found **another Claude session writing to
  `test_site_1` concurrently**. Everything decisive was redone on quiet sites. I never
  captured that run's error, so I am not claiming interference — only that I cannot
  explain it. Check `pgrep -fa "bench --site"` before trusting a local run.
- **A restore script that could not restore.** My Mollie mutation control replaced a
  unique string with one that then appeared **twice** — the test I had just written
  contained the same literal — so the paired `restore` asserted `count == 1` and refused,
  leaving the file mutated. Un-apply must be keyed on something the apply made unique.
- **I ran a `pkill -f` that matched my own shell** and killed it (exit 144) — the trap
  already in memory, hit anyway.

## Next

- **Confirm the trunk run on `deb7a885`.** It was still running at write time. Both
  merges re-packed all twelve bins, and there are six open fixture-ownership defects
  (#390, #392, #394, #406, #443, #444) that a re-pack can surface. If it goes red, the
  first move is the containment control below, not a bisect.
- **The live tree is 8 merges / 41 commits behind at `adae1ddf`.** Deploying is now a decision
  someone should make deliberately rather than by drift.
- **#443 is the sharpest of the new ones**: 16 of 34 Bank Account creation sites guard on
  a key that is not the constrained one. `test_payment_entry_creation_service.py:762` makes
  three of the same mistakes at once and is one caller away from reachable.
- **#442** is the same shape for income accounts — 19 latent sites that today post to the
  company default instead of the account they think they chose. Green, and wrong.
- **#444** is a live drain hazard: three byte-identical helpers, `@shared_fixture` in one
  file and undecorated in its clone, so whichever module runs first decides whether the
  accounts survive.
- **#445** is the tooling gap that let all of this happen twice. Extending the ratchet to
  walk `ClassDef` bodies is the cheap half; triaging the 72-family drift band is the part
  that wants parallel agents, and the census is already the work-list.
- **The skill wants a PR** if it is to be shared, and it wants iterating — the file asks
  for a measurement with every edit, and says why.

## Raw evidence

```bash
# the fix that was already written down, sitting next to two copies that were not
grep -rn "_get_company_with_current_fy" --include=*.py verenigingen/    # -> 3 definitions

# account_type is not what income leaves carry
#   _Test Company 1: account_type="Income Account" -> 0 rows | root_type="Income" -> 5 rows

# reproduce the CI condition rather than waiting for it
scratchpad/repro/mutate_income_types.py apply <site>       # blank every typed income row
scratchpad/repro/seed_bank_competitor.py apply <site>      # claim the GL the old lookup picks
scratchpad/repro/repoint_mollie_clearing.py apply <site>   # point the squatter elsewhere

# order_by="name" is DESC
frappe.db.get_value("Account", f, "name", order_by="name")      # -> name-MAXIMUM
frappe.db.get_value("Account", f, "name", order_by="name asc")  # -> name-minimum

# a None in the list matches nothing
frappe.db.get_value("Account", {**f, "name": ["not in", [None, "x"]]}, "name")  # -> None
frappe.db.get_value("Account", {**f, "name": ["not in", ["x"]]},       "name")  # -> a row

# the containment control for a red shard
grep -c <module-you-edited> <shard-job-log>    # -> 0 rules your code out first
pgrep -fa "bench --site"                       # another session on your site invalidates the run
```
