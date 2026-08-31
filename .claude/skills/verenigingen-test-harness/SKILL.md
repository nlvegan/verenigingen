---
name: verenigingen-test-harness
description: Use when writing, reviewing, or debugging tests and fixtures in the verenigingen app — a red CI shard, a fixture that works alone but not in a suite, a get-or-create that collides, a DuplicateEntryError from a test, a query that returns the wrong row or none, or a review that flags frappe.db.commit() in a test.
---

# Verenigingen Test Harness

This app's test harness **isolates by deletion, not by rollback**, and several rules from
the generic `frappe-testing-unit` skill are therefore wrong here. Where they conflict,
this file wins.

Everything below was measured on this bench. Nothing here is inferred from framework
source alone — that is how most of these defects got written in the first place.

## Where generic Frappe testing guidance is WRONG here

| Generic rule | Why it is wrong in this app |
|---|---|
| "NEVER call `frappe.db.commit()` in tests" | Several commits are load-bearing. `own_settings_company._write` commits because `addClassCleanup` is LIFO and the framework registers `_rollback_db` first — an uncommitted restore is discarded by the very next cleanup, the pin leaks permanently, and you have re-created #312. `ReconBase.setUpClass` commits because `EnhancedTestCase.tearDown` rolls back after **every** test method, so uncommitted class fixtures die at the first teardown and every later method runs without them. |
| "IntegrationTestCase ALWAYS rolls back after each test — no cleanup needed" | The base classes here extend the **compat** `FrappeTestCase`, whose only rollback is one `addClassCleanup(_rollback_db)` — per **class**, not per test. `EnhancedTestCase` adds a per-test rollback *and* two drains, because production code under test commits and rollback cannot reach those rows. `_drain_captured_inserts` itself ends in a `commit()`. |
| "ALWAYS use `frappe.flags` to guard fixture creation" | A flag-guarded, lazily-built **shared** fixture is exactly the #330 bug: the captured-insert drain claims it for whichever test called first and deletes it, taking it from every later class in the shard. Use `@shared_fixture` (decorating a get-or-create) or `suspend_insert_capture()` (wrapping an inline build). `track_document(..., priority=-1)` is **not** sufficient — it binds only the tracked drain. |
| "ALWAYS prefix test data with `_Test`" | Necessary, nowhere near sufficient. A fixed prefix does not make a name unique, and several doctypes here autoname on a field with no company component (below). |

## Facts absent from all 61 `frappe-*` skills

Checked: `root_type` appears in **0** of them; `Bank Account` once (a Jinja example);
`Fiscal Year` twice (a cache-clearing loop). They are **framework** skills. ERPNext
accounting semantics are not in them, and three of the four root causes behind the
2026-08-21 red trunk were ERPNext domain facts.

- **ERPNext's standard chart of accounts leaves `account_type` EMPTY on income leaves.**
  They carry `root_type = "Income"`. Measured: `_Test Company 1` has 5 income leaves and
  **0** rows matching `account_type = "Income Account"`; every typed row on a test site
  was planted by a fixture. So `{"account_type": "Income Account"}` resolves only when a
  sibling suite in the same shard already created one. `Sales Invoice` requires neither —
  `validate_account_head` checks company + non-group and nothing else. (#431, #442)
  **The EXPENSE side is the same defect and now has numbers** (test_site_5, 2026-08-31):
  **44 of 57** companies have zero `account_type = "Expense Account"` rows; the typed
  lookup returns `None` on **44/44** of those, while a `root_type = "Expense"` fallback
  resolves **43** (the 44th has no expense leaves at all). `Payable` *is* typed, which is
  why only the expense side of a paired lookup breaks — a useful discriminator. Three
  tests passed locally and failed in CI on exactly this, and the typed rows that made
  them pass were planted by other suites (one named `Mollie Fees (owned by BTR
  coverage)`). Fix shape, already in `test_document_links.py` and propagated by PR #691:
  `account_type=... OR root_type=...`, **plus an explicit `order_by`** — see the next
  bullet, or which typed row you get depends on what a sibling created last. (#442, #691)
- **`order_by="name"` sorts DESC.** Frappe appends the direction, so a bare field name
  gives you the maximum. Write `order_by="name asc"` if you meant ascending. And an
  omitted `order_by` on `db.get_value` is `creation DESC`, while `get_all` is
  meta-driven — `Company` sorts `creation ASC`, i.e. the opposite.
- **A `None` inside `["not in", [...]]` matches ZERO rows.** It becomes
  `NOT IN (NULL, ...)`, which is NULL-propagating. Building the list with
  `get_all(dt, pluck=field)` on an **optional** field poisons it. `Bank Account.account`
  is optional and suites here create such rows deliberately
  (`tests/payment/test_mt940_import_integration.py:186`), so how often it bites depends
  on the site — measured the same week: 400 of 410 rows NULL on `test_site_5`, 0 of 14 on
  `test_site_1`. That variance *is* the danger: it looks fine until the wrong module runs
  first. Always `[x for x in ... if x]`, and say why — it looks removable. An empty list
  is fine; the `or [""]` sentinel people add is dead code.

## The guard-key rule

**A get-or-create's existence check must be keyed on the thing that is actually
constrained.** Every fixture collision in this repo has been the same shape: the guard
reads one key, the database constrains another, so the guard passes and the insert dies.

Before writing one, name the constraint out loud:

- `Bank Account` autonames `account_name + " - " + bank` — **no company component**, so a
  fixed `account_name` is a *global* unique key. It also permits exactly one Bank Account
  per GL account; that check runs only when `is_company_account` is set but its query
  **ignores the flag**, so a `flag=0` row still blocks a later `flag=1` insert.
- `Account` autonames `account_name + " - " + abbr`, and `Company.abbr` is **not unique**.
- `Company.default_bank_account` is a Link to **Account**, not to Bank Account. Guards
  that read it as a Bank Account are dead branches that can never be true.

`scripts/validation/duplicate_helper_validator.py` may not help you find the sibling
copies, but **not** because methods are invisible to it -- that was true until #445 was
fixed (`275a906a`) and this file said so for a month afterwards. It sees module-level
functions **and** methods. What it cannot see is a copy that is not a function at all
(inline code in an `except`), or a duplicated *explanation* under two different helper
names: it keys on the name.

## Own the fixture; never scan for one

| need | call |
|---|---|
| a company with a usable chart of accounts | `get_eur_test_company()` (`tests/support/sepa_test_company.py`) — owns `TEST-Payment-Integration-Company` by name, repairs a stale Fiscal Year, raises rather than returning a chart-less company |
| its Bank Account | `get_eur_bank_account(company)` |
| harness company on a `VereningingenTestCase` | `self.settings_company`, pinned by `setUpClass` |
| an income account | `self._get_or_create_income_account(company)` |
| a Fiscal Year | already done — `ensure_test_fiscal_year_for_all_companies()` runs in `setUpClass` and covers every company |

**Never** select a company by scanning (`frappe.get_all("Company", ...)`, or by currency).
Which one wins then depends on what else ran first in the shard, and shard bins re-pack on
measured runtime — so editing *any* test file can redden a module your branch never
touched. Worse, a company another suite partially drained can **never** be repaired:
`Company.on_update` skips `create_default_accounts()` while any account for it survives
(#390).

## Proving a fix

- **Reproduce by damaging the fixture first.** A run with the fixture intact proves
  nothing, because on every warm test site it is intact. Blank the rows, seed the
  competitor, delete the account — then run. Restore with the same script that applied it;
  `git checkout -- <file>` reverts the whole file and has already cost a session its
  uncommitted work.
- **Assert on `GL Entry` rows, not `docstatus`.** `db_update()` runs before `on_submit`,
  so a submit that throws leaves `docstatus = 1` behind a half-posted ledger — and that is
  true of the **persisted** row too, not just the in-memory doc.
- **Run on `test_site_1`..`test_site_5`, never `veg11.veganisme.org`** — not because it is
  production (it is **not**; it is a test site with no real users), but because it carries
  a **copy** of production data and is served out of the git working tree, so the suite
  would trash data worth keeping. Both `CLAUDE.md` files were corrected on 2026-08-28
  after this file's earlier "it is the live site" framing made at least one session treat
  routine changes there as risky production work; the reason to stay off it is data, not
  danger. Check `pgrep -fa "bench --site"` first — another session sharing your site
  produces failures that will never reproduce.
- To run a branch's own tests without checking it out:
  `PYTHONPATH=<worktree> bench --site test_site_N run-tests --app verenigingen --module <m>`.
  Always diff a red run against the same command with **no** `PYTHONPATH`.

## What this skill deliberately does NOT cover

Measured 2026-08-21, four fresh agents given realistic fixture-writing and review tasks in
this repo, with no skill loaded:

| scenario | result |
|---|---|
| build a company + income account + Bank Account + posted invoice | **passed** — reused `get_eur_test_company()`, wrapped the build in `suspend_insert_capture()`, asserted on GL Entry |
| same for a SEPA batch | **passed**, and cited the `order_by` DESC trap unprompted |
| "a teammate says remove these `frappe.db.commit()` calls" | **passed** — defended them, and found a stale comment nobody had noticed |
| write a new `Bank Account` get-or-create, idempotent across classes | **passed** — derived the autoname collision from erpnext source and checked `abbr` uniqueness in the DocType JSON |

So a "how to write fixtures in this repo" tutorial is **not** what was missing; CLAUDE.md
and the repo's own docstrings already carry it. Do not grow this file in that direction.
What the agents could not have known are the items above: the generic-guidance conflicts,
and facts that exist in no skill and no docstring.

**When you add to this file, add the measurement too** — the scenario, the control, and
what an agent did without it. A line here that nobody has watched an agent fail without is
a line that will be trusted for years on no evidence.

## Iteration log

**2026-08-21, created.** Baselines above (4/4 passed) set the scope: conflicts and hard
facts only, no tutorial.

Then a paired review test — one fixture module with five planted defects (dead docname
guard, cross-company aliasing, `account_type` income lookup, NULL-poisoned `not in`,
`order_by="name"` with a comment claiming ascending), reviewed by one agent **with** this
file and one **without**.

**Both found all five.** The control measured its way there independently: it ran the
inserts and caught the `DuplicateEntryError`, counted 0 typed income accounts site-wide,
and proved the NULL poisoning with a control of its own. So this file did **not** change
the verdict — it changed the route, turning discovery into recognition, and the agent that
had it said two defects "would have looked fine" without it.

Read that honestly before adding anything: on this codebase a careful agent already finds
these. The case for a line here is that it is a fact no amount of reading the diff would
surface, not that it is a good practice worth restating.

That test also produced the first correction — the NULL-`account` figure above was written
from one site and read as universal. It is now stated as a range, because the variance is
the point.

**2026-08-23, one correction, found by a review of a change that copied it.** The
`duplicate_helper_validator` sentence above said methods were invisible to the ratchet.
That was true when it was written and **stopped being true when #445 was fixed**
(`275a906a`) -- the validator's own docstring has read "functions AND methods" since.
Measured: `_private_helpers` on `tests/utils/base.py` returns 31 helpers and finds
`_rollback_cleanup_savepoint` among them.

The cost was not the stale line itself. A new module in PR #492 quoted this file as its
authority for a design decision, so the wrong mechanism got copied into fresh code and a
**closed** issue was cited to justify it. The conclusion ("the ratchet will not find these
copies") was still right, for two different reasons -- inline code is not a function, and
the ratchet keys on the name.

So: **when a fix closes a blind spot, retire the sentence describing it.** A skill file is
read as current fact by everyone who loads it, and a stale line here is copied outward
rather than merely believed. Nothing about this was findable by grep -- both copies said
it confidently.

**2026-08-29, one correction, by the same rule.** This file called
`veg11.veganisme.org` "the live site". Both `CLAUDE.md` files were corrected on 2026-08-28
-- it is a test site carrying a copy of production data, with no real users -- and this
file was not, so a skill that is loaded *instead of* reading CLAUDE.md kept serving the
retired framing. The cost of the wrong version is not caution, it is misplaced caution: it
made a session treat `console`, `migrate` and backups on veg11 as risky production work
while leaving the actual hazard (running the suite there, which deletes) stated no more
firmly. The rule this file already carries -- retire the sentence when the fact changes --
applies to corrections made **elsewhere**, not only to fixes that close the blind spot the
sentence describes. When CLAUDE.md is corrected, grep the skills.
