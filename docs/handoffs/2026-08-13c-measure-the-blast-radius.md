# Handoff — 2026-08-13c: measure the blast radius, not the module

Session goal was "the next logical open item". That turned out to be #309, which
completed; the work then followed the evidence into test isolation (#291/#308) and
produced a new instrument, a suite-wide measurement, and one blocked PR that must not
be merged as it stands.

## Landed

| PR | | merge |
|---|---|---|
| #320, #325 | the two open handoffs | `d9cf97ca`, `0c8f64a8` |
| #326 | #309: fixture-load + root-department swallows | `2cf9e76e` |
| #327 | #309: the remaining 14 handlers | `7472fd8f` |
| #329 | leak attribution — the instrument everything below rests on | `de859300` |

**#309 is complete**: 18 swallowed handlers converted, 3 kept as genuinely best-effort
(the two silent ones now log). Filed #328 (detect order-dependence methodically) and
added two evidence comments to #308.

## Blocked, deliberately: #330

`fix/drain-cancels-and-orders`. Measured benefit is real — one module went 49 leaked
records → 2, and the submitted-record class it removes is **94% of the whole census**.
It still must not merge: it **wipes a company's Chart of Accounts**.

`Account` is tracked for draining at priority 1
(`enhanced_test_factory.py:6454`), unlike the income-group and receivable accounts at
`-1` ("shared infrastructure, skip"). Those deletes always *failed* before, because GL
Entries and Bank Accounts still referenced the accounts, and the drain swallowed the
failure. Cancel-first removes exactly those referencing documents — the point of the
change — so the delete now **succeeds**, and every later test class in the shard dies in
`setUpClass` with

```
no is_group Bank account to parent new bank accounts under.
Its Chart of Accounts is missing or was wiped
```

That string appears in **zero** earlier shard logs (develop, #326, #327). It is new.

### The lesson that produced it

**Every measurement I made was single-module.** A Chart-of-Accounts wipe is invisible
inside one module — it only harms the *next* class in the same process. A leak count
that improves 49 → 2 can coexist with a change that breaks a whole shard. Module-scale
evidence cannot see shard-scale damage, and this is the failure mode #328 exists to
describe: I reproduced the thing I had just documented.

## The census

`bench run-tests --app verenigingen` with the #329 instrument. **It did not finish** —
killed (`EXIT=137`, SIGKILL, likely OOM) after 3h12m, having reached 681 modules. Treat
the totals as a floor. Note the background-task notification said "exit code 0"; that
was the wrapper's trailing `grep`, not the run.

**2,097 leaks, produced by just 54 modules.**

| Doctype | | Reason | |
|---|---|---|---|
| Membership | 1,520 | **submitted record** | **1,976 (94%)** |
| Sales Invoice | 395 | linked Address | 74 (4%) |
| Customer | 77 | compliance refusal | 15 (1%) |
| Bank Transaction | 23 | document lock | 9 |

The concentration is the useful part: this is not diffuse sloppiness across a thousand
files, it is 8% of the modules reached. Re-run the census *after* a fix lands, not
before — it will be faster and will measure what remains. A complete run probably needs
sharding rather than one sequential process.

## Findings worth keeping

**`PYTHONPATH=<worktree>` runs worktree code under `bench run-tests`.** The whole
`verenigingen` package resolves from the worktree (measured via `__file__`). Both
CLAUDE.md files say branch work can only be verified by CI; that is true only of an
unqualified `bench`. This made real red/green TDD possible without putting a branch in
the live tree.

**Both cleanup gates are dead.** `_cleanup_stale_test_data` requires `developer_mode`
**and** a site in `["dev.veganisme.net", "test_site"]`. CI has `developer_mode=0`;
locally the default site is `test_site_1`, which is not in the list. It runs nowhere.
Do **not** "fix" it: it covers none of the doctypes that actually leak, and its raw
`frappe.db.delete` on Member would manufacture the orphans it is meant to drain.

**Shards re-pack on measured runtime.** Editing an existing test file is enough — no new
file needed. Shard *numbers* can stay put while the module *set* changes, so diff the
sets, not the numbers.

**Triage rule that settles attribution fastest:** grep the shard log for the error
strings *your* change introduces — including any path that re-raises without one. On
#326 and #327 they fired zero times, which ruled out my code before any other analysis.
Then run the module against your branch **and** untouched develop.

**Re-running a shard does not test for flakiness.** It reproduces the same co-tenancy
and order, so a deterministic order-dependent failure repeats identically. CI's "re-run
if it looks flaky" advice does not discriminate for this class.

**The savepoint idea is blocked, and not by anything fixable in Python.** MariaDB DDL
implicitly commits and destroys all savepoints; `frappe.db.sql_ddl` is explicitly
written to defeat suppression (it zeroes `_disable_transaction_control`, commits, runs
the DDL, restores). Reachable from test bodies today —
`create_custom_fields` is called directly inside
`test_bulk_transaction_importer_sweep.py:111` and
`test_mollie_bulk_transaction_consumer_data_qa.py:87`. Also: frappe 16.30 rolls back per
**class**, not per test; the per-method rollback is this repo's own code.

**CI is worker-free.** The setup action deletes every `^worker` line from the Procfile
and errors if it finds none. An earlier memory note headlined "CI RUNS RQ WORKERS" is
pre-fix; it records the fix further down, and I quoted the headline without it. The dev
box *does* run workers, which is why cancel-related lock timeouts appear locally and not
in CI.

## What went wrong in how I worked

**Five of my tests were ineffective, and mutation testing caught every one.** Two
asserted `inspect.getsource(...)` contents and passed with the fixes deleted, because
the literals survived in comments. Three replacements also survived: a Territory
stand-in proved nothing (`Document.cancel()` merely sets docstatus=2 with no submittable
check, so cancelling a Territory *succeeds* — the failure needs a controller that
refuses, i.e. a real GL Entry), and an ordering test fed its own priorities to a fake
factory, exercising the drain's sort rather than the factory's tracking.

**I masked my own regression.** `docstatus == 1` is not a test for "submitted" —
erpnext calls `gle.submit()` on `GL Entry`, which is `is_submittable = 0`. My
cancel-first check tried to cancel GL Entries, failed, and I "fixed" those 18 leaks by
*exempting* GL Entry and Payment Ledger Entry — reporting that as the win that took the
module 21 → 2. It made previously-removable rows persist *and* stop being reported.
Caught only by review.

**I lost uncommitted work to `git checkout` twice**, both times while mutation-testing.
Commit before mutating.

**A reviewer verified a ref and then measured a tree.** Its headline finding ("develop
leaks 0") came from running against the installed checkout, which was three merges
behind and had no instrument — zero by construction. It retracted in full when shown.
The same trap in both directions: check what the runner actually loads.

## Next

1. **#330**: exempt `Account` from the drain (or track bank accounts at `-1`), fix the
   GL Entry test to own its fixtures, and re-verify at **shard** scale.
2. **#328** mechanism 2 (isolation diff: run each module alone *and* in-suite — the two
   directions are different bugs) and mechanism 3 (seeded shuffle, so a red shard is
   reproducible).
3. **#308**: the four collisions catalogued with their polluter named, plus the document
   lock class the drain still cannot clear.
