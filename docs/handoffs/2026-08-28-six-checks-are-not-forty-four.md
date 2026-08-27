# Handoff — 2026-08-28: six checks are not forty-four

**PR #621** (issue #606) merged. It had been sitting green, and it had never once run the
test suite.

Its base was `fix/597-purpose-filtered-mandate-resolution`, not `develop`. Both
`server-tests.yml` and `ci.yml` declare:

```yaml
on:
  pull_request:
    branches: [main, develop]
```

That filter is on the **base branch**. With the base set to a feature branch, neither
workflow ever *queued* — so there were no shards to be red. What remained was one
unfiltered build workflow, and its output was six green ticks:

```
success  build (3.10)   success  build (3.11)   success  build (3.12)
success  build (3.10)   success  build (3.11)   success  build (3.12)
```

`mergeable_state: clean`. `reviewDecision: ""`. Nothing failing anywhere. A guard on a
direct-debit money path, ready to merge, with zero tests behind it.

## The tell is the count, not the colour

CLAUDE.md already carries "green checks on a stacked PR are pylint/build ONLY" — recorded
from PR #347. What was missing is the cheap probe. On this repo, for a PR based on
`develop`:

| target | checks | test shards |
|---|---|---|
| a docs-only PR (#611) | 28 | 0 (path filters) |
| a code PR (#604, merged) | 43 | 12 |
| #621, base = a feature branch | **6** | **0** |
| #621, after retargeting | **44** | **12** |
| `develop` after the merge | 37 | 12 |

**Read `.base.ref` and count the checks before believing a PR is green.** Six is not
forty-four, and the difference is not visible in the colour.

Two mechanics worth keeping:

- Retarget with `gh api -X PATCH repos/<o>/<r>/pulls/<n> -f base=develop`. `gh pr edit`
  fails here with the Projects-classic GraphQL error *and does not apply* — already in
  MEMORY.md, still true.
- **Retargeting does not re-run CI.** A base change fires `pull_request: edited`, which is
  not in the default trigger types. It took a push (merging `develop` in) to make the suite
  queue. A retarget that looks like it changed nothing has changed nothing.

The PR body had *predicted this exactly* — "until then CI here runs the build/lint checks
only, not the suite" — written when the branch was stacked. #604 merged at 11:14:43Z and
nobody came back to retarget. The note was correct and inert. **A comment that describes a
future action is not the action**; if the follow-up matters, it belongs somewhere that
fails, not somewhere that reads.

And the suite justified itself immediately. With base=develop it found that the branch
reddened `test_membership_coverage.py`'s
`test_get_member_sepa_mandates_excludes_non_membership_mandate`: it builds an Active SEPA
mandate with `used_for_memberships=0`, and both sibling purpose flags carry docfield default
`0`, so the branch's new "an Active mandate must have a purpose" guard rejected it.
Reproduced with a control before touching it — red under `PYTHONPATH=<worktree>`, green
against the installed checkout.

That was nine days of a guard nobody had tested, one shard away from merge.

## My own probes lied three times in one session

Investigating a leftover donation on veg11, three separate probes returned a confident,
clean, **empty** answer that was wrong. Same failure shape each time: an absence I could not
distinguish from an error.

**1. `bench console < script.py` does not halt on an exception.** IPython executes the file
line by line, so a raising statement simply leaves its key missing from the result dict —
and I read the gap as "no such row". The real error was
`(1054, "Unknown column 'amount' in 'SELECT'")`, invisible in the console, explicit the
moment the same file ran as `cd <bench>/sites && ../env/bin/python probe.py` with
`frappe.init()` + `frappe.connect()`. **Use the interpreter, not the console, for any probe
whose output you intend to trust.**

**2. A discovery sweep must not blanket-suppress a query-error class.** My inbound-link
walker selected `parent`/`parenttype` unconditionally, so every **non-child** table raised
`Unknown column 'parent'` — and I was filtering exactly that string out as noise. It
reported **0 inbound references** to a SEPA Mandate that a Donation referenced, and 0 for a
Donor that two Donations pointed at. `SHOW COLUMNS` first, select only what exists, and
**print the error count as part of the result**: `errors: 0` is a claim the sweep has to
make out loud.

**3. A control drawn from a reference value can itself be dangling.** My "must exist"
control was `Donor DN-26-00068`, taken from `tabDonation.donor` — not from `tabDonor`. It
returned `exists=False`, so the control proved nothing and nearly discredited a correct
delete. **Draw controls from the authoritative table.** It did surface a real pre-existing
fact: veg11 has 3 missing donors referenced by 4 donation rows.

Also re-confirmed in the reading direction: `getattr(doc, "date", None)` returned `None` for
a field that does not exist (`Donation` has `donation_date`), and I briefly recorded that
`None` as data. The read-side twin of the known "assigning a nonexistent field is a silent
no-op".

## A stale branch needs a control tree, not a re-run

**PR #379** (Mollie reversals, issue #370) was 8 days old, `dirty`, **441 commits** behind
develop, and showing 7 red checks. Its body claimed "no failing tests".

Re-running that CI would have proved nothing: shards re-pack, and the run had executed
against a develop that no longer exists. So: merge develop in (2 conflicts, both genuinely
additive — kept all three `@shared_fixture` gates), then classify every named failure by
running it against the branch **and** against `origin/develop` in a detached control
worktree.

| failure | branch | develop | verdict |
|---|---|---|---|
| `..._reversed_by_a_payment_entry` | FAIL | branch-only test | **branch** |
| `test_the_sweep_also_reverses_in_kind...` | FAIL | branch-only test | **branch**, same bug |
| `test_refund_bank_transaction_is_withdrawal` | FAIL | **OK** | **branch** |
| `test_clearing_account_company_mismatch_falls_back` | OK | OK | co-tenancy |
| `test_the_bank_account_is_owned_not_borrowed` | OK | OK | co-tenancy |
| `test_gl_entry_validation_comprehensive` | OK | OK | co-tenancy |

Half the redness was not the branch's. Without the control worktree there is no way to say
which half, and the temptation is to "fix" tests that were never broken.

**The classification held.** After the merge and the three real fixes, CI on `633fd86af`
came back **43/43, 12/12 shards, 0 failing**. The three failures I declined to touch went
green on their own, and so did shard 9 — which named no test at all, and which I had guessed
was the leak ratchet. That guess is now unfalsifiable and should be read as a guess: the
shard passed, so nothing confirms what it was. What *is* confirmed is the method — a control
tree distinguishes "this branch broke it" from "this shard was unlucky", and three of six
failures needed no code change.

**The real bug was an ambient fixture the drain deletes.**
`create_unified_payment_entry` resolves its bank account as
`Mollie Settings.mollie_bank_account` → an Account named exactly `"Mollie"` →
`Company.default_bank_account`. Measured on test_site_1 for `_Test Company 2`: `""`, null,
null. So it returned `None` from its account-validation branch and two tests failed on
`assertIsNotNone(forward, "fixture problem, not the defect")` — the message was right. The
sibling class in the same file *creates* that `"Mollie"` Account in setUp; the failing class
relied on it already existing. It cannot: the Account is inserted inside a test, so the
captured-insert drain claims it and deletes it at that test's teardown. This is the
documented shared-fixture hazard reached from a new direction — **an ambient get-or-create
in one class is not a fixture for another.**

**And a wrong-target test.** `test_refund_bank_transaction_is_withdrawal` did
`inspect.getsource(_process_pending_refunds)` and asserted the literal
`-float(refund_amount)`. This branch's whole point is that both reversal routes now book
through one implementation, so that logic moved four levels down:

```
_process_pending_refunds
  -> _book_donation_reversal                     (dispatch on forward artefact)
    -> _book_donation_reversal_as_journal_entry  (JE branch)
      -> _create_reversal_bank_transaction_and_journal_entry   <- writes the BT
```

Retargeted to the leaf with every link pinned, so neither dropping the negative amount nor
short-circuiting the delegation passes. I got it wrong once on the way: I first retargeted to
`_book_donation_reversal` and it still failed — that method is only a dispatcher, and an
`awk` range that had spilled into the next method is what made it look like the owner.
**An `awk`/`sed` range is not a scope; use AST when you need to know which function owns a
line.**

## The duplicate-helper ratchet earned its keep twice

Both PRs reddened it, both times for a real name collision, and both times the right fix was
a **rename, not a baseline bump**:

| PR | entry | the two builders |
|---|---|---|
| #621 | `_mandate::4 → ::5` | five different mandate builders sharing a name |
| #379 | `_make_submitted_journal_entry::2` | develop's forces `docstatus` via `frappe.db.set_value` to skip JE validation and only needs a link-valid *name*; the newcomer must post a real balanced entry because the ambiguity lookup reads its GL rows |

Neither entry carried a `# clone family` annotation, which is exactly the signal: not
near-identical code, just a shared name. Because they are not interchangeable, merging them
would break a test — so the honest fix is a name that says which one it is, with the reason
recorded on the def. After each rename, `--update-baseline` produced **no diff**, which is
the check to run before assuming the gate is being obtuse.

#379's gate was green on 08-19 and red now on unchanged code: the merge brought develop's
newer baseline. **A ratchet failure on code you didn't touch usually means the baseline
moved, not the tree.**

## Mutation, not green

Every guard and rewritten test in both PRs was checked by breaking it:

| mutation | result |
|---|---|
| remove `validate_no_duplicate_invoices()` from `validate()` | 3 of 10 fail |
| remove `validate_active_mandate_has_a_purpose()` from `validate()` | 4 of 11 fail |
| `-float(amount)` → `float(amount)` at the BT leaf | 19 → 1 failure |

One test in #621 survived its mutation and correctly so:
`test_three_rows_for_one_invoice_name_the_row_numbers` calls the guard method directly,
because it asserts the message text — and it documents why it asserts the rendered
`"rows 1, 2, 3"` rather than the digits (an invoice name like `ACC-SINV-2026-00123` contains
`1`, `2` and `3` on its own). Three *other* tests cover the wiring. A surviving mutant is
worth reading before it is worth fixing.

## Two false docstring claims, found by review

The skeptical review on #621 falsified two specific, checkable assertions. Both were
verified false before being rewritten:

- **"the scheduler retries daily."** The scheduled task is daily, but
  `_daily_batch_optimization_impl` returns unless `is_batch_creation_day()`, which reads
  `Verenigingen Payments Settings.batch_creation_days` — default `"1"`. The real default
  retry is **the 1st of next month**. This was the entire justification for a
  throw-vs-record tradeoff.
- **"no production code writes a child row without going through its parent."**
  `dd_batch_api.apply_conflict_resolutions` loads child rows standalone and `save()`s and
  `delete_doc()`s them. Narrowed to **inserts**, which is true and is what the guard
  depends on.

The review also caught that the 0/0 supersession shape is a class of **two** deprecated
helpers, not one. A docstring that asserts a class is clean is a claim, and this repo keeps
paying for the ones nobody re-ran.

## Filed, not fixed

- **#626** — `dd_batch_api`'s `consolidate_entries` groups child rows by `mandate_reference`
  with no invoice check, so two *distinct* invoices for one member collapse into one debit
  carrying the SUM. `mark_batch_invoices_as_paid` then iterates the surviving rows and builds
  its Payment Entry from the **Sales Invoice doc**, so the second invoice gets no Payment
  Entry and stays Unpaid while its money was collected. An existing passing test
  (`test_dd_batch_api.py`) enshrines 25+30→55 for two different invoices, which is why the
  behaviour looks deliberate — whichever way it is resolved, that test has to be revisited.
- **#627** — the reachable duplicate *producer* is an ungrouped SQL fan-out
  (`dd_batch_optimizer.py:148-165`, `sepa_mandate_service.py:235-238`, no `GROUP BY si.name`),
  and when the new guard fires in the optimizer pipeline the run is swallowed by a blanket
  `except Exception`, reported as **"No batches created - no eligible invoices"** through
  `frappe.logger().info` (which reaches nothing anyone reads), with the next attempt
  defaulting to the 1st of next month. One bad row turns "one member debited twice" into
  "nobody was collected this month", silently.

## Also done

- **veg11 cleanup.** The long-outstanding "orphan donation" was not an orphan but a closed
  6-row test cluster: donor `TEST-PDA-Donor-001`, two draft €100 donations, mandate
  `TEST-PDA-SEPA-001`, two `Donation History` rows. Every inbound reference came from inside
  the cluster, two of its links were **already** dangling to `Periodic Donation Agreement`
  records that do not exist, and it had zero GL/journal/invoice/batch footprint. Deleted
  child rows → donations → mandate → donor (the closure is circular, so the child rows must
  go first or Frappe throws `LinkExistsError`). Verified with working controls: 0 references
  across 3299 link columns, and a control proving `db.exists` can return `True`.
- **MEMORY.md** brought from 25096 to **24575 bytes**, under its own <24KB target, 141
  pointers, 0 broken. Each compression was verified by comparing the set of link targets
  before and after, so no memory file was orphaned. **The budget is now saturated** at ~173
  bytes per pointer — the next addition breaches it, and the structural options are dropping
  superseded pointers or raising the target. Separately: **197 of 337 topic files were
  already unreferenced** before this prune.

## Open threads

- **PR #379** — `[WIP]`, still open, and now **green: 43/43, 12/12 shards, `clean`** at
  `633fd86af`. 4 of the 7 original red checks were fixed here (2 fixture, 1 wrong-target
  test, 1 ratchet); the other 3 were shard co-tenancy and needed nothing.
  **A green suite is not a reviewed fix.** The substance — 16 commits of GL-posting logic
  for donation refunds and chargebacks — has NOT been reviewed by this session: it was only
  merged with develop and de-flaked. A skeptical review was dispatched at the end of the
  session; its findings are not in this document. Do not merge on the strength of the green
  alone.

  The specific gap to hand that review, or to check by hand: develop made **10+ commits** to
  `webhook_wrapper_service_unified.py` — including the #449/#464 "stops answering 200" fixes
  and "a Bank Transaction with no Journal Entry is not a success" — and git **auto-merged**
  them against this branch's rewrite of the same file. I verified that structurally only (29
  defs, 0 duplicated, both sides' markers present). Nobody has verified those behaviours
  still function.
- **PR #620** — green at 44/44, `clean`, ready. Fixed by `4526f5ba6` ("the sign-date sentinel
  was on the wrong clock"), not by this session.
- **#626 / #627** — filed above, unowned.
