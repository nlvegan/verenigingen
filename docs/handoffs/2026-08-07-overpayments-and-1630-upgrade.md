# Handoff — 2026-08-07

Supersedes `docs/handoffs/2026-08-06-payment-service-and-flake.md`, which sits on the
unmerged branch `docs/handoff-2026-08-06`. Several items it lists as open are closed
here; one was already closed before it was written. Read §2 before trusting it.

---

## 1. State

**MERGED.** PR **#236** landed on `develop` as merge commit `2e2462ec` (2026-08-07),
40/40 checks green, `mergeStateStatus: CLEAN`.

> **The branch was SPLIT before merging.** The shard-weighting work described in §6 is
> NOT in #236 and is NOT on develop — it lives on **draft PR #237**
> (`ci/parallel-shard-weighting`), because it turns ~103 tests red. **Read §9c before
> acting on §6.** The commit hashes below are the post-split ones; the pre-split hashes
> quoted elsewhere in this document (`c4a84a25`, `7a49f8fc`, `c0a486a4` …) no longer
> exist on any branch.

| Commit | Subject |
|---|---|
| `20efb3c8` | member resolver propagates DB errors instead of reporting "no access" |
| `e3134f13` | Ponto payment-entry builder moved into the services layer |
| `72faf28b` | gateway overpayments recorded; six service defects closed |
| `719dc9eb` | three empty skipped integration stubs deleted |
| `9c28ade0` | review fixes: one misleading comment, two weak tests |
| `0e7f039d` | this handoff |
| `4ea8baa1` | four §6a/§7 gaps closed (see §9a) |
| `1454bd49` | `test_member_permissions` no longer breaks itself on re-run |

On **#237** (draft, NOT merged): `550f5842` patch preserved, `c7dc63c6` shard balancing
wired into CI, `d1bbc8d2` stale warning header dropped.

Bench moved to **erpnext v16.30.0, frappe v16.30.0, builder v1.32.0**. All seven sites
migrated (six test sites + veg11), except veg11 has NOT yet taken the builder migration.

---

## 2. Corrections to the previous handoff

**a. Its §6 item "validate_webhook_user_permissions cannot see role-profile grants" was
ALREADY FIXED before that handoff was written** — four commits on 2026-08-05
(`32ad64a3`, `53c05cc8`, `af535d15`, `eab86d9e`). `_check_docperm_for_roles` no longer
exists; the check uses `frappe.has_permission` and derives `submit` for submittable
doctypes. Do not re-fix it.

**b. Role profiles are not a parallel permission path.** `User.validate` calls
`populate_role_profile_roles()` (`frappe/core/doctype/user/user.py:264`), which
materialises profile roles into ordinary `Has Role` rows and re-syncs `roles` to exactly
the profile's set. The normal permission stack always saw them. The old checker missed
them only because it queried DocPerm for one hard-coded role name.

**c. "Two existing tests assert the overpayment bug and must be rewritten" — false.**
`test_allocation_is_capped_at_the_outstanding_amount` and ING's
`test_overpayment_detected_and_allocation_capped` assert only `allocated_amount`, which
is identical whether the entry records the capped figure or the full cash. They did not
pin the bug; they under-asserted and would have passed unchanged either way. Both were
strengthened with `paid_amount`/`unallocated_amount` assertions.

---

## 3. Overpayments — what shipped and why it is opt-in

A EUR100 payment against a EUR30 invoice used to post a Payment Entry of EUR30. ING,
Mollie dues and Ponto each capped at the invoice outstanding and dropped the rest (ING
alerted; the other two were silent). The gateway clearing account was debited EUR30 while
the gateway had settled EUR100, so it could not reconcile against the settlement file.

`PaymentEntryCreationService.create_payment_entry_from_invoice` now takes an opt-in
`cash_received`. `amount` still means the allocation and still settles the invoice; the
excess lands in `unallocated_amount` as a credit on the customer. ERPNext posts two
debtors credits — one against the invoice, one without — and they cannot merge, because
`get_merge_properties()` keys on `against_voucher`.

**Why opt-in rather than redefining `amount` — this is the load-bearing decision.**
`bank_transaction_reconciliation.create_payment_entry_from_transaction` (`:1022`) passes
a whole bank deposit against a single invoice matched **only by an invoice number
appearing in a description, with no amount check** (`match_by_description`, `:330-336`,
confidence 0.90). Today an oversized deposit throws, is caught, and the transaction is
left Unreconciled for an operator. Under a blanket reinterpretation it would submit
silently, park the excess as an untraceable credit, and stamp the transaction
**Reconciled** — removing it from the sweep pool permanently, since
`reconcile_bank_transactions` only selects Pending rows. **Nothing pinned that behaviour;
a regression test now does.**

Opted in: Mollie dues, ING — both settle into clearing accounts. NOT opted in: Ponto
(posts to a bank account), bank reconciliation, batch processing, direct debit, the
Mollie orphan path (its entry exists as a manual-review beacon; splitting it defeats
that).

### Traps found during review, each now guarded

- `_suppress_early_payment_discount` must receive the **allocation**. Handed the cash,
  its equality test declares a discount on every overpayment — landing on the right
  number by accident on same-currency invoices, and throwing a discount-related error
  across a currency boundary for an invoice with no discount.
- The overpayment path **refuses a currency boundary**. Assigning one gateway figure to
  both sides there makes `set_exchange_gain_loss` absorb the mismatch into a deductions
  row; `difference_amount` still nets to zero and the entry SUBMITS, debiting the
  clearing account a converted figure for unconverted cash.
- `invoice_cannot_absorb(invoice, X)` is `outstanding < X`. Given the full cash, every
  overpayment satisfies it, so unrelated ValidationErrors would be misread as a lost
  race. It is given the allocation.
- The batch reconciliation gate sums `allocated_amount`, not `paid_amount`. It asks
  whether the deposit was ALLOCATED; `paid_amount` answers whether it was RECEIVED,
  which an overpayment satisfies **because of** the excess.

### Decisions taken by the owner

- **Overpayment is a credit, not a donation.** `application_payments.py` no longer
  reports an overpayment as "treating as donation". Members overpay to pay ahead or
  catch up; nothing in an amount expresses intent to give, and the old wording misstated
  income and wrote off the member's claim.
- **`require_invoice` is narrowed.** It gates INVENTING a payment where no invoice was
  ever identified. A matched invoice consumed mid-flight is still recorded, unallocated —
  the cash has been taken, and refusing to record it does not un-take it.

---

## 4. Multi-invoice / catch-up payments — ACTION NEEDED

The credit is correct but **inert**: `Accounts Settings.auto_reconcile_payments` is `0`,
so nothing applies it. Enabling it would apply a member's credit to their most-overdue
invoice first — `get_outstanding_invoices` sorts by `due_date` ascending
(`erpnext/accounts/utils.py:1313`) and `process_payment_reconciliation.py:352-354`
preserves that order into allocation. The null-`due_date` fallback (treated as due today)
is **not** an exposure here: veg11 has 3,327 submitted invoices and 0 without a due date.

**This is a global accounting setting on a live site and was deliberately left OFF for
the owner to decide.**

---

## 5. Version upgrade — erpnext + frappe + builder to the 16.30 line

- **erpnext 16.20 → 16.30.** Adds four `throw=True` permission checks, most importantly
  `frappe.has_permission(reference_doctype, "read", ...)` inside `get_reference_details`
  (`payment_entry.py:2797`), which `validate()` reaches every time via
  `set_missing_ref_details(force=True)`. Any identity creating a Payment Entry now needs
  **document-level** Sales Invoice read. The webhook user has it via the role profile;
  Ponto's `allow_guest` branch is the one to watch.
- **frappe 16.19 → 16.30.** Required: erpnext 16.30 declares `frappe>=16.21.0`. Needed a
  dependency reinstall (`duckdb`, `pyarrow`, `distro` added). The fork remote carries no
  v16 tags — fetch from `https://github.com/frappe/frappe.git` directly.
- **builder develop(2026-02-01) → v1.32.0.** Resolved a duckdb conflict: builder pinned
  `~=1.3.0` against frappe's `~=1.4.3`. v1.32.0 pins `duckdb==1.4.3`, satisfying both.

### Open: click conflict, unresolvable by pinning

builder v1.32.0 pulls litellm, which pins **`click==8.1.8` exactly**, while frappe 16.30
requires **`Click~=8.3.1`**. Mutually exclusive; one is violated whichever you choose.
click is currently 8.1.8, so frappe's declaration loses. **Nothing is broken in
practice** — `migrate`, `run-tests`, `list-apps`, `execute` and `builder_analytics`'s
duckdb import all work, and click underpins the whole bench CLI, so a real break would be
loud. Forcing 8.3.1 would violate litellm's exact pin instead. Left as-is, watch it.

### Trap: stale document locks block every migrate

`sync_fixtures` → `RoleProfile.on_update` re-saves every linked user; if any User doc
holds a lock, the migration dies with `DocumentLockedError`. **A successful migrate leaves
~11 lock files behind, which then break the NEXT migrate.** All six test sites failed this
way and all six succeeded after clearing. Locks live in `sites/<site>/locks/*.lock`; some
found here dated to June 14 and June 25.

    ls sites/<site>/locks/*.lock          # check
    mv sites/<site>/locks/*.lock <backup> # clear (verify no bench process is running)

veg11's 15 locks were cleared on 2026-08-07 in preparation for its builder migration.
Copies of every cleared lock are in this session's scratchpad, not in the repo.

---

## 6. CI shard balancing — was never running

> **STOP — this work is no longer on develop.** It was split onto draft PR **#237**
> after it turned 6 of 12 shards and ~103 tests red. Everything below is still an
> accurate description of the change; what has moved is where it lives and whether it
> is safe to land. **Read §9c.**

The `test_timings.json` weighting had **never affected CI**.
`.github/actions/setup/action.yml` clones `${frappe-user}/frappe` and
`_base-server-tests.yml` defaults that to `frappe`, so CI built against pristine upstream
and sharded by frappe's stock heuristic. The weighting existed only as an **uncommitted
edit to `apps/frappe/frappe/parallel_test_runner.py`** — one `git checkout` from being
lost, with no copy anywhere.

Now: preserved as `scripts/frappe-parallel-test-weights.patch` (self-documenting preamble;
`git apply` ignores text before the first `diff --git`), applied by the setup action, and
**the step fails the job if the patch stops applying** — the ungated failure mode is
silent, since sharding would revert to count-based while every shard still passes.

Scale of the problem it fixes: `test_membership_analytics_functionality` has **24 test
methods and 612 units of measured runtime** — underweighted 25x, while a file of 40
trivial tests outweighed it. That is why shard count kept climbing 4 → 8 → 12.

`test_timings.json` regenerated: 658 → 1307 entries, 192 with measured data. The old table
was not partial by design, only stale (2026-07-23, pre-coverage-sweep); every file missing
from it silently fell back to the count heuristic.

**Regenerating requires CI job logs, not artifacts** — the workflow uploads
`test_output_*.txt` only `if: failure()`, so a green run leaves nothing to download. The
generator now strips GitHub's per-line ISO timestamp; without that its anchored header
regex matched nothing and it would have written a complete-looking table with **zero**
measurements. Commands are in the generator's docstring.

---

## 6a. Review of the implementation — what it caught, and what is still uncovered

A skeptical review of `git diff develop...HEAD` ran AFTER the code was written (the two
earlier reviews looked only at the design). Verdict: no correctness defect on any shipped
path, all suites green — but two comments were confidently WRONG and two tests passed for
reasons other than the ones they claimed. Fixed in `c0a486a4`:

- The shortfall guard claimed ERPNext would not catch `cash_received < amount`. It does
  (`set_difference_amount` + `on_submit`); the reviewer proved it with a live probe. The
  guard is still correct to exist — it fails at input validation instead of after the
  document is built — but for a different reason than stated.
- `test_cash_received_below_the_allocation_is_refused` asserted only the exception TYPE.
  ERPNext raises `frappe.ValidationError` for this anyway (the service's `setup_keywords`
  contains "must be"), so it **passed with the guard deleted**. Now asserts the message.
- `test_overpayment_is_not_mistaken_for_an_early_payment_discount` was **proved not to
  catch the swap it named** — the reviewer simulated it and the test still passed. Handed
  the cash, the helper clears an already-empty deductions table and assigns
  `paid = received = cash`, which the override assigns anyway: an identical document. The
  swap is observable ONLY across a currency boundary. Renamed to
  `test_overpayment_books_no_deductions_row`, with the gap stated in the docstring.

**Still uncovered — deliberately, and worth closing:**

1. **Mollie's `cash_received` opt-in has no test.** ING got `paid_amount` /
   `unallocated_amount` / `difference_amount` assertions; Mollie — the caller with the
   messiest amount/allocation/outstanding triple — got none.
2. **The overpayment currency-boundary refusal is untested.** It needs a
   foreign-currency bank account this suite has no fixture for. It is also the ONLY place
   the discount-argument swap is observable, so that fixture would close two gaps at once.
3. **Stale ERPNext line citations** throughout the payment comments, now that bench is on
   v16.30.0: `payment_entry.py:3269`→3292, `:3293`→3314/3322, `:1085`→1090/1118. Also
   `journal_entry.py:1333` (cited in `ponto/services/payment_entry_service.py:52`) is
   `validate_empty_accounts_table`, not `get_default_bank_cash_account`. The style used in
   the new `cash_received` block — name the function and file, no line number — is the
   one to copy.
4. **`server-tests.yml`'s `paths:` filter is `verenigingen/**/*.py|*.js`**, so
   regenerating `test_timings.json` or editing
   `scripts/frappe-parallel-test-weights.patch` **alone will not trigger the workflow that
   consumes them.** Touch a `.py` file or dispatch manually to see the effect.
5. `book_advance_payments_in_separate_party_account` (default 0) would change the GL shape
   the `cash_received` comment describes: both rows would then carry `against_voucher`.
   Correct today; conditional on that setting staying off.

---

## 7. Open items

*Items 3 and 4 are CLOSED — see §9a. The rest stand. §9d is the current list.*

1. **veg11 has not taken the builder migration.** Locks are cleared, backup is at
   `20260807_041216-veg11_veganisme_org-database.sql.gz`.
2. **`auto_reconcile_payments` decision** (§4) — owner call, currently off.
3. ~~`bank_transaction_reconciliation.py:1022` passes an uncapped deposit~~ — **CLOSED**
   in `4ea8baa1`: explicit deposit-vs-outstanding guard, compared at field precision.
4. ~~`chapter_utils.py:86/241` swallow database errors~~ — **CLOSED** in `4ea8baa1`, and
   the fix went further than this item asked: `get_volunteer_for_member` sits between the
   two and swallowed too. See §9b.
5. **click conflict** (§5) — watch, do not force.
6. **`test_snapshot/clean_v1620-database.sql.gz`** is a clean **16.20** dump. Restoring
   from it now lands a site on the old schema; regenerate or do not trust the name.
7. **The 2026-08-06 handoff is on the unmerged branch `docs/handoff-2026-08-06`.** Merge
   or delete it; it contains corrections that would otherwise be lost, but §2 above
   supersedes part of it.

---

## 8. Process notes

- **A design review is not a code review.** Two skeptical reviews of the *design* forced
  the opt-in redesign and caught a silent-currency-corruption path. Neither looked at a
  line of the implementation. A third, of the diff, then found two false comments and two
  tests that passed for the wrong reason. All three were needed; none would have caught
  what the others did.
- **The best way to test a test is to break the thing it claims to catch.** The diff
  review simulated the exact argument swap a test named and watched it pass. No amount of
  reading would have shown that as convincingly.
- **Two independent reviewers converged on the same blocker** from different angles
  (caller blast radius vs ERPNext mechanics). That agreement was worth more than either
  report alone.
- **A test can pass for the wrong reason and look like coverage.** The two overpayment
  tests asserted `allocated_amount`, which does not change under the bug OR the fix.
- **Check whether a "0 results" diagnostic is even measuring the right thing.** A query
  for orphaned Notification Settings by doc NAME returned 0 on both a healthy site and
  the site that was actively failing. The dangling link was on the `user` FIELD. Validate
  a diagnostic against a known-bad case before trusting a clean result from it.
- **Read the whole test-runner output.** `bench run-tests` prints a separate `Ran N tests`
  block per test category; a `tail` shows only the last one and can look like almost
  nothing ran.
- **`git ls-remote` against a fork proves nothing about upstream tags.** The frappe fork
  here carries no v16 tags; the versions were on `frappe/frappe`.

---

## 9. Continuation session — gaps closed, branch split, PRs opened

Everything below happened AFTER §1–§8 were written. Where it contradicts them, this
section wins; §1 and §7 have been rewritten in place to match.

### 9a. The four gaps from §6a and §7, closed

| Gap | Where it was | What happened |
|---|---|---|
| §6a-1 Mollie `cash_received` untested | `dues_payment_processor` | two tests added |
| §6a-3 stale ERPNext line citations | payment comments | all replaced with function names |
| §7-4 `chapter_utils` swallows DB errors | `services/chapter/` | propagates now |
| §7-3 uncapped deposit | `bank_transaction_reconciliation` | explicit guard |

**Every ERPNext citation had drifted at 16.30** — verified one by one against the
bench's own v16.30.0 source, not against the previous handoff's mapping. The Ponto one
was worse than stale: `journal_entry.py:1333` is `validate_empty_accounts_table`, not
`get_default_bank_cash_account` (which is at 1342). The claim it supported held up;
only the pointer was wrong. **The convention is now file + function, never a line
number** — this is the second time these have rotted.

### 9b. Two findings the review produced that are worth more than the diff

**Fixing `chapter_utils` alone was not enough, and the docstring said otherwise.**
`get_volunteer_for_member` sits one line after `get_member_name_for_user` in the same
resolver chain and still swallowed. A reviewer proved it live: with `frappe.db.get_value`
raising, a DB error on the Volunteer lookup still produced "no chapters". The new tests
could not see it because they patch `frappe.get_all` and that function uses
`frappe.db.get_value`.

Fixing it surfaced something worse than the denial being chased:
**`Volunteer.create_volunteer_from_member` and mijnrood_sync's `volunteer_sync_service`
use that resolver as their DUPLICATE GUARD**, where `None` means "no volunteer exists
yet". A swallowed database error was inserting a second Volunteer for a member who
already had one. All three now propagate.

**`None` from `get_user_accessible_chapters` means "admin — sees ALL chapters".**
`performance_cache`'s module docstring demonstrated wrapping it in `get_or_set()`, which
logs and returns `None` when the getter raises. Following that example would have turned
a database outage into full access for every caller. It also did not match the method's
signature, so it had plainly never been run. Replaced with a warning.
**Never cache a value whose None/empty form is an authorization answer.**

### 9c. THE BRANCH WAS SPLIT — read this before looking for the CI work

§6 describes shard-weighting work that **is no longer on this branch.**

The first CI run of the combined branch failed: **6 of 12 shards, 103 tests**, caught by
the armed `known_test_failures` baseline gate. The failures cluster by fixture, not by
feature — e_boekhouden migration, `test_sepa_reconciliation` (12 × `setUpClass`),
`test_bulk_account_creation`, `test_payment_retry`, `dd_batch_optimizer`,
`mollie_financial_safeguards`, `ponto_bank_account_creator`. Recurring causes, all
company / chart-of-accounts setup:

- `MandatoryError: [Account, Income - EBHMT]: parent_account` — the factory's
  `_get_or_create_income_account` building a group account with `income_parent = None`
- `LinkValidationError: Could not find Default Company: TEST Company 3 - TEST-123`
- `create_test_sales_invoice` failing against `EBH Migration Test Co`

**None of it traced to the payment or resolver changes** — zero references to
`get_volunteer_for_member`, `get_member_name_for_user`, `payment_entry_creation_service`
or `bank_transaction_reconciliation` in any failing traceback, and all the new tests
passed in CI.

**Working hypothesis: those tests were never self-sufficient.** They relied on another
test in their old shard creating a company and its accounts first, and rebalancing
separated them from that accidental provider. This repo has hit the identical pattern
before, when a coverage sweep changed shard composition. If it holds, the weighting did
not break them — it EXPOSED 103 tests passing by accident of ordering.

So the branch was split rather than letting a CI-sharding problem hold the payments work:

- **PR #236** — payments + resolvers, this branch, 8 commits.
- **PR #237** (DRAFT) — `ci/parallel-shard-weighting`, the §6 work, 3 commits.

`c0a486a4` was a MIXED commit — it corrected a stale warning header inside the shard
patch *and* fixed payment comments/tests. It could not simply be dropped; both halves
were separated by hand and both commit messages record it. The split was verified
lossless three ways: identical combined file set, and an empty diff in each direction
when each branch is compared to the pre-split state over its own paths.

### 9d. Still open after this session

1. **PR #237 cannot merge until the ~103 fixture failures are resolved.** Not started.
   Step one is to run one failing module in isolation locally — that distinguishes
   "genuinely broken test" from "lost its accidental provider". Step two is making the
   affected fixtures create their own company and accounts.
2. `Accounts Settings.auto_reconcile_payments` is still `0` (§4). Unchanged, owner call.
3. veg11 still has not taken the builder migration (§5).
4. The foreign-currency fixture (§6a-2) is still missing. It remains the only way to
   observe both the currency-boundary refusal and the discount-argument swap.
5. `test_snapshot/clean_v1620-database.sql.gz` is still a 16.20 dump under a 16.x name.
6. The 2026-08-06 handoff is still on the unmerged branch `docs/handoff-2026-08-06`.

### 9e. Process notes from this session

- **Mutation-test every test you add.** Break the thing it names and watch it fail.
  Three tests here did not survive that: one exercised a role level the permission
  filter excluded anyway (so the skip it claimed to prove was unobservable), one named
  a boundary only visible across a currency boundary, and one asserted an exception
  type ERPNext raises for that input regardless. All three looked fine on review.
- **A fix can be incomplete in the middle of a chain.** Both ends of the resolver chain
  were fixed while the link between them still swallowed — and the docstring asserting
  otherwise was the actual defect. Grep the whole call path, not just the named function.
- **`gh pr edit --body-file` can silently fail.** It emitted a Projects-classic
  deprecation error, exited without applying the change, and left the body untouched
  while looking like it worked. Caught only by grepping the live body afterwards.
  `gh api -X PATCH repos/.../pulls/N -F body=@file` works. Same class as the known
  `gh pr checks --json` trap.
- **Strip ANSI before grepping CI logs.** A grep for `FAIL: test_` returned 0 against
  103 real failures because of colour codes. This trap is now recorded twice.
- **`autoname: field:<x>` makes a fixture name a global unique key.** A test inserting
  one with a literal name is one committed row away from being permanently broken on
  that site. That is what ailed `test_member_permissions`; it is fixed.
- **A green local run still says nothing about CI**, and this session is the clearest
  example yet: every suite touched passed locally, and the branch was still red for
  reasons no local run could reach.
