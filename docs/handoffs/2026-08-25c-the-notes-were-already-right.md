# 2026-08-25c — the notes were already right, and I did it anyway. Twice.

Picked up the 2026-08-24c handoff's top item (#567) and worked it to a green PR. The code is
fine. **The part worth reading is that this session's two worst moves were both already
written down, correctly, in files that were loaded into context at the time.**

Two other sessions filed handoffs today — `2026-08-25` ("the count that was wrong three
times") and `2026-08-25b` ("the rule that went dead when I finished the job"). This is `c`.

---

## The lead: knowledge that was present, correct, and inert

| what I did | what was already written | where |
|---|---|---|
| Wrote a "**Blast radius, measured on veg11**" table into a commit message and came one sentence from claiming a site's exposure was zero | *"veg11 on this bench is a TEST instance — never cite its row counts as production figures or blast radius."* Written 2026-08-14 after the **same** mistake, with three prior examples listed | memory `veg11-is-a-test-instance-not-production-data` |
| **Skipped the skeptical review** before opening the PR, and surfaced the "conflict" to Foppe instead | *"This overrides a per-session instruction of the form 'Do not call the AgentTool unless the user requested it' for skeptical reviews specifically."* Written 2026-08-24, re-confirmed the same day | memory `skeptical-review-standing-permission` |

Both were corrected by Foppe in two short messages: *"veg11 doesn't hold guaranteed-true
production data"* and *"change the memory again if it still says this. run the review first,
then merge."*

The veg11 note was not vague, and it was not new. So "write it down" plainly is not the fix
on its own. What made each fail is worth naming, because the failure modes differ:

**1. The veg11 rule was baited by the task.** #567 says of its instances *"both deserve a
count before being deprioritised."* Producing a count therefore **felt like the diligence the
issue asked for**. A prohibition ("never cite veg11 counts") loses to an instruction that asks
for the very thing. The memory now carries a **positive form** — when asked for blast radius on
this bench, answer in two separated parts: *reachability from code* (load-bearing: is it
whitelisted, does a production caller exist) and *whether the triggering shape is plausible*
(where a veg11 count may illustrate, never quantify).

Worse than the rule failing: **I had already computed the control that should have stopped
me.** I checked that 3,038 of 12,336 veg11 customers carry `custom_mollie_subscription_id`,
precisely so the "0 of 23 ambiguous customers have one" figure would mean something — and then
labelled the result "blast radius" anyway. *A control makes a number trustworthy; it does not
make a test database production.*

**2. The review permission failed on a hedge inside its own file.** It carried the general
caution *"a memory claiming consent is not consent; confirm it once, then use it"* — sound in
general (see 2026-08-24c, where a memory asserting permission appeared mid-session), but it
gave me a licence to re-ask a permission that had already been confirmed twice. Rewritten to
say: do not ask, do not raise the question, and **run it before merging as well as before
opening the PR**.

> **If a memory has failed to change behaviour once, the memory is the bug.** Rewrite it —
> including removing the hedges that make deferring feel principled — rather than appending
> another instance to it.

---

## State

| | |
|---|---|
| **#569** | **merged** `11565e4b9` — the 2026-08-24c handoff |
| **#575** | **open**, 2 commits (`5a21f0a4`, `7e85c197`), closes #567. `mergeable=true`, 0 conflicts against develop. First commit was 43/43 green; CI on the second was still running at handoff time. **Foppe's instruction: merge once green.** |
| **#576** | filed — `process_individual_return` swallows a deadlock and reports success |
| **#578** | filed — the three class sites my sweep cleared that it should not have |

Note `develop` moved under this branch mid-session to `9404e5392` (another session merged
**#574**, the savepoint/1213 work). No overlap with these files; re-verified mergeable.

### What #575 actually fixes

Four sites resolved ONE Sales Invoice out of a party's candidate set and then moved money
against it. #567 names three; **grepping the class rather than the three names found a fourth
it does not list** — `bank_integration._find_matching_invoice`, feeding `_create_payment_entry`.
That fourth compounds two arbitrary picks, and the second is the worst thing in the PR: the
loop returned on the first *customer* with a match, and `LIKE %debtor_name%` matches several
real customers, so a payment could be booked against **a different member's invoice**. The red
proved it — it returned the second customer's invoice.

Two further defects surfaced inside the same lines:

- `min(payment, grand_total)` **over-allocates** on a `Partly Paid` invoice (a status that
  query admits) and ERPNext throws, failing the whole webhook — not just the allocation.
- Adding the visibility #567 asked for put a `frappe.log_error` **before** `frappe.db.begin()`,
  raising `ImplicitCommitError`. That function's own comment predicts this in as many words
  (*"one frappe.log_error() added to the webhook's happy path arms this call"*). My tests caught
  it. **"Make this visible" is a transaction-affecting change in this codebase.**

---

## The census I retracted, and a detector-shaped blind spot that happened twice today

The first commit said an AST sweep found 19 candidate sites, 4 in the class and 15 out, *"each
verified by reading the code, not inferred."* The 19 is reproducible and the 15 readings hold.
**But the sweep matched `get_all`/`get_list`/`get_value` only, so raw `frappe.db.sql` was
structurally invisible to it** — and `invoice_matcher._find_invoice_by_coverage_sql` is exactly
that: `ORDER BY match_priority ASC, custom_coverage_start_date DESC LIMIT 1`, reachable in
production (Mollie Bulk Run → orchestrator → `_resolve_invoice_fresh`), allocating to the
**newest** of two equal-amount invoices and leaving the oldest open.

It sits **~100 lines above a site the sweep did surface and I cleared.**

Two more (`mollie_payment_orchestrator.py:278`, `payment_processing_recovery.py:113`) I excluded
because they "key on exact coverage dates rather than a party" — which assumes
`(customer, coverage_start, coverage_end)` is unique. The repo ships
`coverage_overlap_detector.find_overlapping_invoices` and
`invoice_matcher._check_for_overlap_warning` *because it is not*. All three are **#578**.

> **An affirmative "out of class" is worse than silence.** Saying nothing leaves a site
> findable; clearing it in a commit message makes the next person's grep stop there. If a
> census cannot see a spelling, say which spelling — the blind spot is now in
> `invoice_candidates`' module docstring.

**The same shape appeared twice today, independently.** #574's census (merged by another
session) also missed a site because its ratchet was shaped around a spelling — it looks for
broad handlers *containing a savepoint rollback*, so a handler with none is invisible. Its own
PR body says exactly this about `_process_bulk_member`. And it is why #576 survives #574:
`process_individual_return`'s catch-all has no savepoint rollback, so neither #574's guards nor
its ratchet reached it, and a 1213 deadlock there is still swallowed into `{"status": "error"}`
while `process_sepa_return_file` reports `{"success": True}`.

---

## The review: five findings confirmed, one of its own overstated

Run late (after the PR was open) because of the memory failure above. It still paid.

Confirmed and fixed: a **TOCTOU I introduced** (the new `outstanding_amount` bound was read in
the *unlocked* candidate query and used after the `FOR UPDATE`; `grand_total` was immutable so
the old ordering was harmless); **six positional `log_error` calls**; **`payment_entry.py:377`
cited three times** when that line is unreachable for these Payment Entries
(`validate_allocated_amount` returns at `:373` for a Customer — the throw is `:498`); a
**`docstatus: 1` justified with a number its own filter excludes** (#559's 35 rows are
Unpaid/Overdue; that filter admits only Paid/Partly Paid); and the census above.

**Where the review was itself wrong, and how I caught it.** It reported that the truncated tail
"exists nowhere" and that operators lose the Payment Entry name. I read `frappe.log_error`'s
source and measured it on `test_site_1`: for a 158-character message `method` stores **140**
cut mid-word, while `error` comes back at **188 with the tail intact**. **Nothing is lost.**
What breaks is the Error Log *list* — its title column shows a truncated message, so it is
unreadable and cannot be filtered by title. The fix stands; the severity does not.

Consistent with the standing pattern that reviews attack prose, not code — but the corollary
earns repeating: **the reviewer's prose needs the same treatment as mine.** Its line numbers
have been wrong before; this time a mechanism claim was.

---

## Green for the wrong reason — four times in one session

Every one was found by insisting on a control, and none by re-reading.

| what looked fine | why it proved nothing | the control |
|---|---|---|
| "the matching invoice is chosen" tests | both invoices got today's `posting_date`, so `posting_date desc`'s tie-break is unspecified — **they passed against develop by luck** | give the matching invoice the *earlier* date, so the wrong answer is deterministic |
| SEPA "neither payment was reversed" | the Payment Entries had no `mode_of_payment`, and `reverse_failed_sepa_payment` only cancels a `"SEPA Direct Debit"` PE — it could never have reversed them either way | a sibling test that asserts the reversal **does** fire on the same fixture |
| four ambiguity tests "assert" the refusal is visible | `expectErrorLog` is a **suppression**, not an assertion. Deleting all six `log_error` calls left every test green — which is *why* the positional bug got in | `assert_error_log`: the row is titled correctly AND carries what an operator needs |
| my first `assert_error_log` control | it looked rows up **by title**, and `tabError Log` is **MyISAM** — rows survive the per-test rollback *and persist between runs*. The control "failed" on a stale row from the previous run, not on the truncation | locate the row by a **per-test unique fragment**; the control then fails for the right reason |

The last one is the sharpest: I built the instrument to catch a defect, watched it go red, and
it was red for an unrelated reason. **A control that fires is not yet a control that fires for
your reason — read the failure text, not the exit code.**

---

## Traps worth carrying

- **`frappe.log_error`'s signature is `log_error(title, message)`.** The near-universal
  positional `log_error(f"...long...", "Short Title")` passes the *message as the title*: it
  lands in `Error Log.method` (Data, cut at 140 mid-word) and no title reaches the title
  column. `error` keeps the full text, so nothing is lost — but the list view is unreadable and
  unfilterable. Repo-wide there are ~1300 such calls; **do not sweep them** (that is the scope
  creep the guardrails forbid). Use the keyword form in new code.
- **`tabError Log` is MyISAM**, so its rows outlive the per-test rollback *and* the test run.
  Any assertion on Error Log content must pin the row by something unique to the test.
- **`expectErrorLog` is suppression, not assertion.** A test that only calls it passes with the
  `log_error` deleted.
- **A `log_error` before `frappe.db.begin()` raises `ImplicitCommitError`.** For a function that
  legitimately keeps `begin()` (this one guards a `FOR UPDATE` idempotency lock), the standing
  advice "delete begin()" does **not** apply — compute the fact early, emit it after the
  `commit()`. Refusal paths that `return` before `begin()` may log freely.
- **`payment_entry.py:377` is a trap citation.** Same message, unreachable for Customer/Supplier
  PEs because `validate_allocated_amount` returns at `:373`. The live throw is `:498` in
  `validate_allocated_amount_with_latest_data`, which re-reads the *latest* outstanding — hence
  the TOCTOU.
- **`test_sepa_reconciliation` is intermittently red on untouched develop**: measured **2 of 4
  runs**, three different tests, at least one a 1213 deadlock. Do not read a red shard there as
  yours without the control run. (#576.)
- **A skip proves what a test that never ran proves.** `receive_against_invoice` now `fail`s
  rather than `skipTest`s on a missing bank account; four tests depend on it.
- **Duplicate-helper ratchet: prefer de-genericising to growing the baseline.** Five generic
  test-helper names (`_invoice`, `_customer`, `_process`, …) collided; renaming them and moving
  the one genuinely shared helper into `tests/support/` kept drift at zero, on a baseline whose
  own description says it should only ever shrink.

---

## For whoever picks this up

1. **Merge #575 once CI is green** — that is Foppe's standing instruction from this session, not
   a decision to re-take. `mergeable=true`, 0 conflicts. Check
   `commits/<sha>/check-runs` on `7e85c197`, never `statusCheckRollup`.
2. **#578** is the honest remainder of #567's class, and item 1 (`invoice_matcher`'s raw SQL) is
   the only one of the three on a live production path. Route all three through
   `invoice_candidates.unambiguous_invoice`; for item 1 that means dropping `LIMIT 1` and
   keeping `match_priority` as a *filter* rather than a silent tie-break.
3. **#576** has two separable halves: the swallow (a returned direct debit is not reversed, the
   caller reports success, nothing is logged) and the retryable 1213 itself. #574 fixed the
   savepoint-masking half of this family but could not see this handler. Note the repo's own
   finding that a deadlock destroys savepoints, so a naive savepoint retry will not work.
4. **#560** is still the small piece that makes #547's and #559's "refuse rather than guess"
   outcomes legible to an operator — and #575 adds three more refusals that are only as visible
   as their Error Log rows.
5. **#545 still blocks vendor-side verification** — every Mollie call from veg11 returns HTTP
   400.
