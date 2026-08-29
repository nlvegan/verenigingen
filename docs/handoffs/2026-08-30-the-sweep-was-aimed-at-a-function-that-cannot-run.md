# 2026-08-30 — the sweep was aimed at a function that cannot run

**Merged:** #654 (`aebdae707`) closing **#649**, then #655 (`3cb03a890`) closing **#653**.
**Filed:** #653.

Two fixes in the same bug class #645 named: *a voucher that moves a member invoice's
`outstanding_amount` without dispatching an event on that invoice*. #649 said there were
two more producers. There were three, and the reason I could not have found the third is
the most useful thing in this session.

| what I did | what it was worth |
|---|---|
| swept erpnext for GL Entry `against_voucher` producers | **structurally unable** to find the missing one — it posts no GL row |
| concluded "no fourth producer", in a commit message | wrong, and stated as a finding rather than as a scope |
| ran a skeptical review, acted on it, merged | the review ran on the commit BEFORE the one I merged |
| eight mutation controls | three of them survived; each was a real missing test |

---

## 1. The sweep was aimed at a function that cannot run

`gl_entry.update_outstanding_amt` is what #645's docstring cites for "how ERPNext restores
an invoice's outstanding". So when #649 asked for the wider class, I grepped erpnext for
GL Entry `against_voucher` producers and reasoned from that function.

**It cannot run for a Sales Invoice at all.** `GLEntry.on_update`
(`gl_entry.py:111-115`) gates the call on

```python
if frappe.get_cached_value("Account", self.account, "account_type") not in ["Receivable", "Payable"]:
```

and an invoice's `against_voucher` row always sits on `debit_to`, which ERPNext validates as
Receivable. Measured with a positive control (both symbols patched with `wraps=`, so a zero
is not a broken instrument): **0** calls to `update_outstanding_amt`, **1** to
`update_voucher_outstanding` (`erpnext/accounts/utils.py:2141`), driven by
`PaymentLedgerEntry.on_update` plus four direct callers.

One of those four is `unreconcile_payment.py:67`. **`Unreconcile Payment` posts no GL row
at all** — it calls the recompute directly, once per allocation row, and unlinks references
with raw query-builder updates. No GL Entry, no Payment Entry save, no Journal Entry save.
A GL-shaped grep cannot reach it, and neither can #649's own scoping query on veg11
(`SELECT DISTINCT voucher_type FROM tabGL Entry WHERE against_voucher_type='Sales Invoice'
…`), which is why "returns Payment Entry only" was weaker evidence than it read.

**The lesson is not "grep harder".** It is that a class sweep inherits the mechanism you
believe in, and a wrong mechanism makes part of the class unreachable *by construction* —
no amount of care within the sweep recovers it. Before sweeping for "what does X", verify
that the thing you think does X is what actually does it. One `wraps=` probe with a control
would have caught this at the start instead of at review.

The wrong citation was itself a class. I corrected it in `background_jobs.py` and wrote in
the commit message that it was "corrected in place". Grepping the explanation
(`gl_entry\.py|update_outstanding_amt`) found **three** occurrences, one fixed — the other
two being the #645 test module and, worse, the docstring of
`dues_reversal_journal_entry_creator`, the production service that *writes* these Journal
Entries and is what the next person will reason from. **If the fix deserved an explanation,
that explanation is a search query** — including when the fix is to an explanation.

## 2. I reviewed the round before the one I merged

The skeptical review ran on `73f3c1093` and produced the refutation above. Acting on it
turned that commit into `c62ac891c`: **+238 lines**, a new production handler, a new
`doc_events` registration on a doctype the app had never touched, a new shared helper, two
new test classes, a reworked fixture and a wholesale-rewritten commit message.

Foppe's condition for merging was "if it's been skeptically reviewed itself". Technically
it had. **The artifact that had been reviewed no longer existed.** I dispatched a second
review of the delta before merging; it came back merge-safe on correctness and found
finding 1's incompleteness above.

This repo already records this as `review-the-round-that-answers-the-review`. It recurred
anyway, because "was it reviewed?" is a question about the branch and the honest question is
about the **commit**. Ask: *does the SHA I am about to merge differ from the SHA that was
reviewed, and by how much?*

## 3. Three mutations survived, and each was a real missing test

Sixteen mutation controls across the two PRs. Thirteen reddened exactly the named tests.
The three that survived were the whole value of running them:

| mutation | survived because | now caught by |
|---|---|---|
| drop `is_return` from the **batch** writer | every parity test used an ordinary invoice; every credit-note test drove only the incremental writer | a credit-note case in the writer-parity suite |
| put the literal `"Draft"` back in the fallback | once validation accepts credit notes the fallback is no longer REACHED by one | two tests driving it with the builder stubbed at the seam |
| mislabel the **non-membership** credit note (`else "Credit Note"` → `else "Regular Invoice"`) | **63 tests across 5 suites** all used `is_membership_invoice = 1`, and the validator tests passed the transaction type as a LITERAL | one integration test with `is_membership_invoice = 0` |

The third is the sharpest. A credit note against a member's donation or merchandise invoice
would have failed the new sign rule and degraded to the minimal fallback — *the exact defect
the change exists to fix* — with everything green. A test suite that only ever builds the
common fixture cannot see the branch it never builds, and no amount of test COUNT reveals
that. A surviving mutation does.

## 4. The same decision, made the other way, one layer out

#653 taught `determine_payment_status` that a credited invoice is not "Paid". The review
found `PaymentStatus.PAID_STATUSES` — a named constant containing `"Credit Note Issued"` —
feeding the **member-facing** dashboard, which mapped the whole set to `"Paid"`. Shipping
only the first fix would have left the desk grid saying `Credited` and the member's own page
saying `Paid` for the same invoice.

The constant is deliberately unchanged. Its other consumer, `dues_schedule_manager`, asks
*"should we still chase this?"* and must keep answering **no** for a credited invoice — a
waived member must not become collectable again. **Two questions sharing one constant**, and
the bug was that nothing recorded which question it answered.

Generalisable: when you change what a value MEANS, the class to grep is not other copies of
the code, it is other places that answer the same QUESTION. They will not share a name.

## 5. `update_outstanding_for_self` defaults to 1

#649 states the condition (`is_return and return_against and not
update_outstanding_for_self`) as fact. The DocType field **defaults to 1**, so a credit note
built the obvious way books against ITSELF and the original never moves. My premise test —
written first precisely so the dispatch tests could not be vacuous — came back with the flag
at 1 and the outstanding unmoved. A dispatch-only suite would have gone green testing
nothing.

`validate_against_voucher_outstanding` also **flips it back to 1** when the note exceeds the
original's outstanding, which rules out the obvious "reuse the fully-paid fixture" choice.

**When an issue states a condition as fact, check the condition's DEFAULT before building a
fixture on it, and assert the premise separately from the behaviour.**

## 6. Claims of mine that were wrong

Recorded because the pattern matters more than any one of them — every one was prose I was
confident about, and every one was found by review or by a probe, never by re-reading:

* *"the credit note's row is dropped"* — it is written, stamped `"Draft"` on a submitted
  document. A probe showed it; I had inferred it from the `return None`.
* *"no fourth producer"* — finding 1.
* *"corrected in place"* — 1 of 3.
* *"`Credit Note Issued` = fully credited"* — ERPNext sets it for ANY credit note once
  outstanding ≤ 0, so an invoice with a €10 credit whose €32 remainder the member PAYS lands
  there too. This became a real feature: Foppe asked for the distinction, and
  `Partially Credited` now splits it.
* *"it cannot itself raise on a Sales Invoice"* — `frappe.new_doc("Sales Invoice")
  .outstanding_amount` is **None**, and only a `docstatus == 0` early return kept the
  fallback alive. A fallback that can raise is worse than the lie it replaced.
* *"a sign RULE, not an exemption"* — half true; `outstanding_amount` IS an exemption.
* *"byte-identical"* of the writer-parity suite — it compares 18 named fields, and
  `due_date`, the discriminator another test relies on, is not among them.
* *"17 tests green with the Select option removed proves it is unenforced"* —
  non-discriminating: BOTH `update_child_table` skipping `_validate()` AND `in_import`
  short-circuiting `_validate_selects` explain it. And the production consequence is worse
  than "renders blank" — `member_history_update_service` refreshes via a real
  `member_doc.save()`, which DOES validate selects.

## 7. Two environment facts worth keeping

* **`bench reload-doctype` without `PYTHONPATH` reads the INSTALLED app**, not your
  worktree. A DocType JSON change in a worktree is invisible until you reload *with* it. A
  sweep went red on a schema test for exactly this reason and it looked like a defect.
* **Two suites on one test site produce failures that never reproduce.** A background sweep
  on `test_site_3` turned a 15-second module into a 72-second one and reddened it. The skill
  file says this; I did it anyway.

---

## Left open

* **#648** — `deduplicate=True` is inert under `enqueue_after_commit=True`. Now confirmed
  twice more: a Journal Entry reconciliation dispatches the drain **N+1 times for N rows**
  (`reconcile_against_document` passes `do_not_save=True` for a Payment Entry and saves once,
  but lets `update_reference_in_journal_entry` save AND saves again). Redundant, not wrong.
  The warning in that issue about the migration-flag guard still stands.
* **Two adjacent defects, named but not filed.** `determine_payment_status`'s `Cancelled`
  branch sits after the `outstanding_amount <= 0` short-circuit and is unreachable for a real
  cancelled invoice; and four Mollie writers append `Member Payment History` rows bypassing
  the builder entirely, writing fields that are not on the DocType.
* **`Repost Payment Ledger`** recreates PLEs with `update_outstanding` defaulting to `"Yes"`
  and is registered nowhere — a lower-confidence fifth producer candidate, untested.
* **The shard replayer** still needs fixing before it is parked under `scripts/testing/`
  (carried over from 2026-08-29b).
* **Six handoff PRs are open and unmerged**: #629, #632, #644, #647, #652, and this one.
