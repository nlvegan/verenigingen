# Handoff — 2026-08-21b: the lock that locked nothing

Fixed #424 — a `SELECT ... FOR UPDATE` that had been protecting nothing on the Donor path
because the table was hard-coded — then spent the rest of the session on a red shard that
had nothing to do with it. The through-line:

> **Absence of a lock is invisible to every gate this repo has.** No test failed, no
> validator fired, no error was raised. A `FOR UPDATE` matching zero rows is not an error,
> so the only way to tell a lock that was taken from one that was not is to have a second
> connection try to take it.

## State

| | |
|---|---|
| `develop` | `a6859a76` (picked up **#441** mid-session) |
| Open, CI re-running | **#438** — the #424 fix, merged onto the fixed base as `f7b08b15` |
| Closed as superseded | **#446** — my fix for the shard-4 collision; **#441** landed the same fix first |
| Opened from reviewing #441 | **#447** — #441's regression test skips under the very condition it guards |
| Issues filed | **#436** — `BaseHistoryManager` takes no row lock at all |
| Commented | **#443** — an 18-site census of the scan-then-claim shape |
| Memory written | `lock-probe-second-connection-2026-08-21.md` |

## What #424 was

`MemberFinancialHistoryManager.add_or_update_entry` locks the parent row before it reloads
and rewrites the child table. It spelled the table by hand:

```python
frappe.db.sql("SELECT name FROM `tabMember` WHERE name = %s FOR UPDATE", (self.member.name,))
```

The manager is constructed with whatever document the caller has, and the Mollie webhook
builds it with a **Donor**. A Donor name is not a Member name, so the statement matched zero
rows and took no lock on anything it was about to write. Two concurrent webhooks for the
same donor could interleave read-modify-write on `donor_history` and lose an entry.

Fixed by taking the table from the document — `frappe.db.get_value(self.doc.doctype,
self.doc.name, "name", for_update=True)` — and by renaming `member_doc`/`self.member` to
`doc`/`self.doc`, since that naming is what let a `tabMember` lock sit on the Donor path
through review. `self.member.doctype` was the tell.

## The instrument

Nothing observable distinguishes a lock that was taken from one that was skipped, so the
test opens a **second connection** and tries to take it: 1205 (`ER_LOCK_WAIT_TIMEOUT`) means
held, an immediate result means free. `verenigingen/tests/payment/test_history_manager_row_lock.py`.

Three traps, all hit:

- **This bench's frappe runs `mysqlclient`, not pymysql.** `pymysql.connect(**frappe.db.
  get_connection_settings())` dies on `multi_statements`. `frappe.db.create_connection()`
  uses the site's own driver and cannot drift from how the site actually connects. Both
  drivers are installed, which is what makes the hand-rolled version look like it works.
- **The fixture must be COMMITTED before probing.** An uncommitted INSERT holds an implicit
  exclusive lock of its own, so every probe returns True and every assertion passes
  vacuously. `VereningingenTestCase` rolls back once per CLASS, so an ordinary `insert()`
  is not enough.
- **Probe a known-free row in the same test.** Without that control, "the donor row is
  locked" and "the probe returns True for everything" look identical.

The skeptical review then ran three mutations the tests had to survive, and the third is the
one I would not have thought to run: **right table, wrong row.** It reddens both the donor
and the member test, which is what proves the assertions discriminate on row rather than
merely on table. It also closed two vacuity paths I had argued rather than measured —
`update_child_table` never touches the parent row, and this schema has **zero** foreign-key
constraints, so no FK can lock the parent as a side effect.

## What went wrong in how I worked

**I updated the explanation in one file and left its twin quoting deleted SQL.** `06015ef8`
had written the lock trade-off into two places; my first commit fixed one. The other still
cited `SELECT ... FROM tabMember WHERE name = %s FOR UPDATE`, a literal that now greps to
nothing. This is CLAUDE.md rule 6 — *if the fix deserved an explanation, that explanation is
a search query* — and I broke it inside the commit that repairs a bug caused by exactly that
class. The skeptical review caught it, not me.

**I read `git rev-parse HEAD` as my branch and it was not.** Another session had checked out
over the shared working tree; I was querying CI for the wrong SHA for several minutes. That
tree is what serves veg11, so whatever is checked out there is deployed. Check
`git branch --show-current` before trusting anything derived from `HEAD` on this bench.

**Two sessions fixed the same bug in parallel.** #441 and my #446 diagnosed the shard-4
failure identically and landed different fixes within an hour of each other (#441 created
06:54Z, merged 07:54Z; I started mine at ~07:1xZ). I *did* check for prior art, twice, and
both checks failed in a way worth naming:

- I searched issues and saw `#441 [open] test: key the Bank Account fixtures ...` — and read
  it as an issue. **`/repos/{o}/{r}/issues` returns pull requests too.** It was an open PR
  against the file I was about to edit, and the one row that would have stopped me.
- I then listed open PRs explicitly — at ~07:5xZ, *after* #441 merged. So it was correctly
  absent, and its absence read as "nobody is on this."

`git worktree list` had shown `fix/395-bank-account-fixtures-guard-wrong-key` the whole
time. **On this bench that listing is the register of what other sessions are doing**, and it
is the check that does not depend on catching a PR inside its open window.

## The red shard, which was not the code

Shard 4 failed on #438 and I nearly reported it as mine. It was not:

| | #438 (`1ffa7fd3`) | develop (`e7be9cf0`) |
|---|---|---|
| failing test | `test_the_bank_account_is_owned_not_borrowed` | same |
| exception | `'TEB Bank One - TEBPC' account is already used by ...` | byte-identical |

Triage order that settled it in minutes, per CLAUDE.md: my module never ran in shard 4 (zero
hits), and the error strings my change could produce appeared **5×** on the PR against **7×**
on develop — fewer, not more. Then the same test on the base commit's own push run, with the
same traceback.

Root cause (independently found by #441): the test plants a decoy Bank Account and took the
GL account for it by scanning for "Bank-type, another company's", excluding nothing already
claimed. erpnext permits exactly one Bank Account per GL account, and `get_value` orders
`creation DESC` — so it preferred the newest foreign bank account, which is precisely the one
a sibling suite had just created and claimed. Green for months, red the moment the bins
re-pack.

**A fixture bug is still a bug: reproduce it before fixing.** On `test_site_3` the module
passed 50/50, because the account it picked happened to be free. Seeding a Bank Account onto
the newest foreign bank GL account produced the same `ValidationError` on the same line.

**And control for the fix neutering the test it repairs** — making a failing test pass is
trivially achievable by making it test nothing. Reverting `_owned_bank_account` to a
borrowing lookup still failed on *"resolved a foreign Bank Account -- still borrowing"*.

## What #441 could still learn from #446

Asked to compare the two fixes rather than just concede the race. One thing survived, and
it is not the thing I had flagged.

**What I flagged and then withdrew.** Closing #446 I claimed a residual: #441's
`_unclaimed_foreign_bank_gl()` returns `None` when every foreign bank GL account is claimed,
and the test then skips silently. True in principle; measured, it is not a path CI reaches —
**18 to 27 unclaimed foreign bank GL accounts** on each of `test_site_1`, `2`, `3` and `5`.
An argument from reading, retracted by one query.

**What survived is one level down.** #441's *new* regression test picks the account it plants
its competitor on with the **pre-fix query** — newest foreign bank GL, claimed or not — and
skips when that one is already claimed:

```python
if not target or frappe.db.get_value("Bank Account", {"account": target.name}, "name"):
    self.skipTest("needs a foreign, unclaimed bank GL account to claim")
```

That is exactly the co-tenancy it exists to guard. Seeding a Bank Account onto the newest
foreign bank GL on `test_site_3` — the CI condition — turns it from a run into a **skip**,
with the bug live and the run green.

Fix ported from #446: **create the target instead of finding one.** Nothing can claim an
account that did not exist a moment ago, so the skip disappears rather than narrowing, and
it owes nothing to the helper under test — which was #441's stated reason for not picking the
target with the SUT. It is also the stronger target: created moments ago it is the newest
bank GL on the site, so a `creation DESC` lookup blind to claims *must* return it.

All four cells measured, not inferred:

| | correct lookup | pre-fix lookup |
|---|---|---|
| unseeded | passes | fails |
| seeded (CI condition) | passes | fails |

Against #441 as merged, the seeded/pre-fix cell is a **skip** — the one cell that matters.

> **A guard that selects its own target with the buggy query inherits the bug's blind spot.**
> The rule this repo already has — a check without a control proves nothing — has a corollary:
> a control that can be skipped by the condition under test is not a control.

**The superseded PR was repurposed, not discarded.** #446 lost the race on the fix itself, but
the idea it was built on — *own the account instead of competing for one* — is the one #441
had no equivalent for, and it is what #447 carries. Losing a race is not the same as being
wrong, and the useful question when it happens is not "who was first" but "what does the
merged version still not do".

Worth being explicit about why #447 is a new branch rather than a reopened #446, since the
instinct to reuse the branch is reasonable:

- #446 branches from `e7be9cf0`, **before** #441, and rewrites the same three methods #441
  rewrote — reopening it means resolving a conflict against a fix that already works, to no
  benefit.
- What survives from #446 is **one helper**, not its diff. `_make_foreign_bank_gl()` is ~20
  lines; the rest of #446 is now redundant with #441.
- The two PRs also say different things. #446 said "this fixture races for a scarce
  resource"; #447 says "the regression test for that goes silent under the condition it
  guards". Landing the second under the first's title would bury it.

## What is left

- **#438** — CI re-running on `f7b08b15`. Green ⇒ merge (already approved). The only failure
  on the previous run was the shard-4 collision #441 has since fixed.
- **#436** — `BaseHistoryManager._with_doc` does `get_doc` → mutate → `safe_child_table_update`
  with **no row lock anywhere**. `DonationHistoryManager` writes the same `donor_history`
  table through it, so #424 serializes the Mollie webhook against itself while
  `sync_donor_history` still races it. One line in the base class covers all three
  subclasses, but lock lifetime (#411) and lock ordering need deciding first, and
  `sync_donation_history` is the sharp one — its callback does `donor.donor_history = []`
  and rebuilds, so a concurrent write is dropped wholesale.
- **#443** — 18 sites share the scan-then-claim shape; census posted as a comment. Two are
  production code where claiming an unclaimed account may be intended.
- **The webhook discards `add_or_update_entry`'s `False`** and reports success
  (`webhook_wrapper_service_unified.py:1903-1912`). Pre-existing, but #424 makes a
  previously-unreachable failure branch reachable: contention on the Donor row could not
  occur while no lock was being taken. No HTTP call is held under that lock (checked), so
  the window is DB-only work. Unfiled.
- **#447** — awaiting CI. Everything in the section above.
  The `_unclaimed_foreign_bank_gl()` residual I noted on #446 and #443 is **withdrawn**:
  measured, 18–27 free accounts per site, so that skip is not reachable. The comment on #443
  says so; the one on #446 does not, and should be corrected if anyone leans on it.

## For whoever picks this up

- `test_site_1` has **stale doctype metadata**: `tabDocField` was missing
  `Donation.recurring_origin_donation` while the DB column existed, erroring 12 tests in
  `test_mollie_gap_unified_webhook_handlers`. `reload-doctype "Donation"` fixed it. If that
  site is meant to be migrated, it has drifted — I did not investigate how far.
- Adding a test file re-packs every shard bin. #438 adds one, so expect unrelated shards to
  move on its next run.
- The lock probe is reusable: `row_is_locked_from_another_connection(doctype, name)` in
  `test_history_manager_row_lock.py`. Pointing it at a `DonationHistoryManager` write is a
  few lines, and that is the test #436 wants.
