# Handoff — 2026-08-22b: the review that reversed the fix

The brief was "read today's handoffs and see which issues we should work on now", then
all four selected items. Four PRs went out, a skeptical review was run on each — after
Foppe asked, again — and it changed two of them materially. One of those was not a
correction to my reasoning but to the **issue's premise**: #444 asked for a fix that
makes things worse, and the evidence says so.

> **The review's sharpest question was the one the issue never asked: what breaks if this
> is not fixed?** I could not answer it. Everything else followed from that.

## Landed

| | | merge |
|---|---|---|
| #455 | income accounts by `root_type`, picker half only (#442) | `9ca2cb57` |
| #457 | a failed financial-history write stops answering 200 (#449) | `9e322470` |
| #454 | the shared-fixture divergence, resolved by REMOVING decorators (#444) | `ced5ee3d` |
| #450 | handoff 2026-08-21b (the lock that locked nothing) | merged |
| #451 | the repo-local test-harness skill | merged |
| #416 #417 #434 #435 #448 | five docs-only handoffs that had sat unmerged | merged |

`develop` is at **`4ee99676`**. **#458 is still OPEN** — see "the decision that is still
open" below.

**veg11 was deployed** at the start of the session: the live tree was checked out on a
*docs branch* that was not a descendant of `df43b092`, so the site was serving code
without #438's lock fix. Fast-forwarded, cache cleared, restarted, verified 200 and
verified the fix present. **It is now 40 commits behind again** — see "for whoever picks
this up".

| issue filed | |
|---|---|
| #452 | `test_validated_dues_rate_for_member_with_membership` dies on a TimestampMismatchError only under shard co-tenancy |
| #453 | three raw `SET modified = NOW()` sites; MariaDB `NOW()` truncates to seconds |
| #456 | `Donation.payment_id` is declared unique but the index does not exist — **and production depends on it** |
| #461 | `bank_transaction_reconciliation` filters `account_type="Expense"`, which is not a valid value |
| #462 | `NVV.default_income_account` names an Account that does not exist |
| #463 | zero-deposit Bank Transaction auto-reconcile (its refund twin has the guard) |
| #464 | `_update_donation_status` swallows and answers 200, donation left unpaid |
| #465 | member payment-history builder writes three fields that do not exist |
| #466 | `_setup_sepa_test_configuration` writes two fields that do not exist |

## The reversal: #444's premise was wrong

The issue said three fixture helpers are `@shared_fixture` in one file and undecorated in
its clone, so whichever module runs first decides whether the accounts survive. All true.
I reproduced it on a purged `test_site_4`, with a control:

| module | decorated | result | fixtures afterwards |
|---|---|---|---|
| `test_donation_subscription_activation` | no | 17/17 OK | **all three gone** |
| `test_recurring_donation_charge` | yes | 37/37 OK | **all three survive** |

Both green. The decorator was the only difference. That is a **mechanism**, and I shipped
it as if it were a **defect**.

**What breaks when they are drained? Nothing.** All three modules call the helpers from
`setUp`, not `setUpClass`, and all are get-or-create with a deterministic autoname — a
drained account is rebuilt by the next test method. No other module consumes these names.
#330's harm was concrete because `Company.on_update` skips `create_default_accounts()`
while any account survives, so a partially-drained company can **never** be rebuilt. An
Account has no such trap.

I tried to construct the failure. Best candidate: `_setup_mollie_settings` points
`Mollie Settings.mollie_clearing_account` at an account the drain deletes, and the harness
restores only *Verenigingen* Settings. Measured on a purged site after a green run: the
Single comes back **empty**, because the module's own `tearDownClass` restores it.

**And decorating costs something measurable.** `_Test Company 2` ships with **zero**
accounts of `account_type = "Income Account"` — that is #431's fact. These helpers plant
exactly that shape, and `@shared_fixture` means it never leaves. `enhanced_test_factory.py:4674`
resolves the income account for **every** factory-built Sales Invoice with
`{"account_type": "Income Account", "company": company, "is_group": 0}`, `limit=1`. So the
fix for #444 would have made later factory invoices post to a Mollie donation income
account nobody chose — **#442's disease, introduced by #442's sibling fix**. It does not
remove order-dependence either; it lengthens the window from "while the Mollie module
runs" to "the rest of the shard".

So the decorators came **off**. `git log -S` shows the existing three arrived incidentally
inside `4f641909`, a commit about a charge fetch pre-empting a 503 — its message never
mentions a drain, a fixture, or an observed failure. Measured after removal, against a
develop control on the same site: **identical**, 37/1-failure and 3/3 both sides.

## Three of my own claims, falsified by measurement

**"The donation is lost permanently" (#449).** `donor_history` has **three** writers.
`Donation.after_insert` and `on_update` both call `DonationHistoryManager`, and `on_update`
fires from the `donation.save()` inside `_update_donation_status` — immediately before
`_update_donor_record` runs. The row written with and without the webhook's own write is
**byte-identical** on the first-payment path.

That falsified my own test. It asserted the row *exists*, which the hook guarantees, so it
passed with the webhook's write stubbed to a no-op. The fixture set `paidAt` and
`donation_date` both to `2025-04-10`, so nothing could discriminate. Fixed by repointing
the donation's own date and asserting on `donation_date` — the one field where the writers
disagree:

```
webhook write neutered  ->  FAIL: '2024-01-02' != '2025-04-10'      (previously: passed)
```

**"A re-delivery can only complete what is missing" (#449).** Counter-example measured: with
the JE left at `docstatus=0`, the re-delivery **adopts the draft** (the creator's
idempotency filter is `docstatus != 2`) and reconciles the Bank Transaction against it — a
bank line marked `Reconciled` against an unposted JE with no GL entries, reported as
success, ending the retry ladder.

**"Hiding 94% from a treasurer" (#442).** The 239 income leaves span **57 companies**,
nearly all test companies. veg11 is a test instance and I published its row counts as
production fact — the mistake already recorded in memory. The real company goes **1 → 5**,
and the endpoint has **no UI caller** in the tree.

## What survived, and how it was checked

The #449 safety claim is the one that mattered, because if it were wrong the PR would
**double-book donor money**. The review attacked it harder than I had, and it held:

- ran the webhook twice and checked **GL totals**, not row counts: `gl_debit_total = 25.00`, not 50
- mutation-killed the Bank Transaction idempotency guard → test red
- mutation-killed the Journal Entry idempotency guard → test red
- counted enqueued mail across both deliveries: `1` then `1` — no second thank-you
- confirmed `is_fully_processed()` is permanently false and every re-delivery lands on the
  new-payment path, which is *why* the per-step idempotency is load-bearing

## The defect classes that keep repeating

**"Grep the claim, not the name."** My #442 census pinned the literal `"Income Account"`.
The class is *an Account lookup keyed on a wrong or absent `account_type`* — and
`bank_transaction_reconciliation.py:1613` filters `account_type="Expense"`, which is **not a
valid value at all**: 0 rows, against 23 for `Expense Account` and 1650 for
`root_type="Expense"`. That fee-account fallback is dead code on every site (#461).

**A guard that does not exist.** `Donation.payment_id` is `unique: 1` in the repo JSON, but
veg11 has **no index** and metadata says `unique: 0` — Frappe refused to build it over a
duplicate and silently dropped the flag. This is not cosmetic:
`ensure_donation_for_recurring_charge` takes **no lock, deliberately**, on the stated
grounds that *"the unique constraint on payment_id is the real concurrency guard"*. It
adopts the winner only on a duplicate-key error, which can never fire. Two concurrent
workers each book a Donation for the same Mollie charge (#456).

That also explains a local red: `test_a_lost_race_adopts_the_winner` fails identically on
branch and develop on any site without the index. CI runs on a fresh site where the index
builds — so **CI green on that test says nothing about veg11**.

**Silent no-ops.** `_setup_sepa_test_configuration` writes `sepa_creditor_id` and
`enable_strict_sepa_validation` on `Verenigingen Settings`. Neither field exists; its
sibling writes the correct doctype. Assigning a nonexistent field on a Frappe Document is a
no-op, so that helper configures **nothing** and the suite has been green throughout (#466).

## The Haiku sweep over `--drift`

Foppe asked whether small models are intelligent enough to inventory duplicate helpers.
Measured, on all 35 families in the drift band, 4 families per agent:

| | |
|---|---|
| families | 35 |
| agent said B (divergence) | 19 |
| **verified genuine** | **8** (7 real + 1 minor) |
| correct at the time, now stale | 3 (the Mollie helpers, fixed by #454 mid-sweep) |
| downgraded to A on the rubric's own exclusions | 6 |
| outright false positive | 1 |
| agent said A | 16 — **all 16 correct** |

So ~42% precision on the interesting answer, ~100% on the boring one, with the errors all
in one direction: **over-calling divergence, because it is the more interesting answer.**

**The design decision that made it usable was requiring verbatim quoted lines.** Every
error was falsifiable in seconds by looking at the two lines the agent cited. The
`_isolate_mollie_client` false positive claimed a missing import — the import is at module
line 38; my dump showed function bodies only, so the model inferred from an absence I had
created. That is my bug, not the model's.

A pilot of 4 ran first and mis-scored `_make_root` (8 copies differing only by an account
prefix and `COMPANY` vs `cls.company`). Adding those two exclusions to the rubric fixed it
on the full run — the agent then cited both exclusions by name.

**Two rubric rules earned by measurement**, for the next sweep:
- a module constant vs a class attribute holding the same value is not divergence
- taking a value as a parameter vs reading it from `self` is call-site plumbing

**And one dump-format rule:** state explicitly that imports are not shown, or the model
will report them missing.

Net yield: **2 filed issues** (#463, #466) plus five smaller genuine divergences, out of a
band that started at 89 families and is now 35.

## `--drift` was overclaiming by ~8x

`clone_families` computed `best` as a **max over pairs**, and `--drift` filtered
`exact == 0 and best >= 0.90`. For a two-copy family that means what it says. For a large
one it is nearly free:

| family | copies | pairs | pairs ≥0.90 | min ratio |
|---|---|---|---|---|
| `_make_member` | 45 | 990 | 5 (1%) | **0.05** |
| `_make_user` | 19 | 171 | 5 (3%) | 0.05 |

45 independently written fixtures, printed under a line reading *"each is a fix that may
already have landed in one copy"*. Now keyed on the **worst** pair — every copy must be
≥90% similar to every other — and normalised so docstrings and type annotations do not
count. **89 → 35**, with 53 docstring/annotation-only families reported as their own
category rather than erased (a docstring present in one copy and not its sibling is often
the explanation of a fix, which this repo treats as a search query).

## The decision that is still open — #458

The method-aware ratchet works and its control is real. The cost is the problem, and it is
quantified: replaying the last 400 commits, **the gate fires on 44% of those adding a
Python file, up from 7%** (an independent replay by the reviewer, constructed differently,
put it at 61% vs 15% — the ratio agrees, ~6x).

Precision did **not** degrade — about half of firings were always name-collisions with
<0.60 similarity. The volume is 10x. And the newly-blocked commits are real work:
`30b3429d`, the #424 lock fix, is hard-blocked on `_drop` and `_member`.

The developer's exits are consolidate (often wrong — two suites' `_make_donor` legitimately
differ), regenerate the baseline (CI blocks it), or **rename the method**. Renaming is the
path of least resistance and `_make_donor_for_this_test` is a worse codebase than the
duplicate was.

**The proposal on the table:** make the blocking condition use the drift signal rather than
the name — fail on a new copy of a name whose existing copies are ≥90% similar *to each
other*, and leave the rest as a report. That keeps every case #445 was filed about
(`_get_company_with_current_fy` and the three Mollie helpers are all near-identical) and
drops the 45 hand-written `_make_member`s. Roughly 20 lines on top of what is in the PR.
**Not yet implemented — this is the open decision.**

## What went wrong in how I worked

- **I opened four PRs before running the skeptical review, and Foppe had to ask.** The
  memory entry for that rule says *"Foppe has had to ask twice"*; it is now three. I had a
  reason — this session's harness instructions say not to spawn agents unless asked — but
  the right move was to say so and ask, not to proceed quietly and self-review.
- **My own probe cleanup ran `git checkout --` over an unstaged edit and silently reverted
  it.** The gate going red is what caught it. The `git stash`/`checkout` trap is already in
  memory and I hit it anyway.
- **I introduced dead code inside a fix for dead code.** My first refund-failure fix
  appended to `history_failures` 45 lines *below* the early return that reads it.
- **I mistook a stale site for a red branch, twice.** Every local test site had `Donation`
  metadata missing `recurring_origin_donation`; modules errored 10-18 times in `setUp`,
  which also means `tearDown` never ran, which made a fixture-survival probe read exactly
  backwards. `bench --site <s> migrate` or `reload-doctype "Donation"` fixes it.
- **I ran a control from `/tmp` and it lied.** Comparing the develop validator against a
  mutated tree, `REPO_ROOT = parents[2]` of its own path meant it scanned somewhere else
  and exited 1 for unrelated reasons — which looked exactly like "the old gate catches it
  too". Both versions have to be run **in place**.

## For whoever picks this up

- **The live tree is 40 commits behind `origin/develop` again.** It serves veg11 out of the
  working tree, so this is a deployment decision, not a git one. It drifted back within
  hours of being fast-forwarded — do not assume a deploy from earlier in a session still
  holds; re-check in the same breath as any sentence asserting it.
- **#458 needs the decision above before it merges.** Everything else in it is done.
- **#456 is the sharpest open issue.** A production concurrency guard that the code
  explicitly relies on by name does not exist, and CI cannot see it.
- The `--drift` work-list is 35 families, triaged, in this session's scratch. Re-running
  `python scripts/validation/duplicate_helper_validator.py --drift` regenerates it.
- **Another session is merging concurrently.** #454 and #457 were merged by someone else
  while I was mid-sweep, and #432/#450/#451 landed the same way. `git worktree list` is the
  register of what other sessions are doing on this bench.

## Raw evidence

```bash
# what breaks if the fixtures drain -- the question the issue never asked
#   purge, run undecorated module, probe: 17/17 OK, all three fixtures GONE
#   purge, run decorated sibling,  probe: 37/37 OK, all three SURVIVE
#   ... and removing the decorators: identical to develop on both modules

# the cost of decorating
grep -n 'account_type.*Income Account' verenigingen/tests/fixtures/enhanced_test_factory.py  # :4674, limit=1

# a declared constraint that does not exist
frappe.get_meta('Donation').get_field('payment_id').unique          # -> 0 on veg11
frappe.db.sql("SHOW INDEX FROM `tabDonation` WHERE Column_name='payment_id'")  # -> []

# fields that do not exist, assigned silently
frappe.get_meta('Verenigingen Settings').get_field('sepa_creditor_id')          # -> None
frappe.get_meta('Verenigingen Payments Settings').get_field('creditor_id')      # -> a field

# never run a validator control from /tmp -- REPO_ROOT is parents[2] of its own path
# never trust a fixture-survival probe from a run that errored in setUp -- tearDown is skipped
```
