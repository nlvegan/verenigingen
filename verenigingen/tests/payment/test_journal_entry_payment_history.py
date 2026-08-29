"""A Journal Entry that moves a member invoice's outstanding must refresh history (#645).

Payment Entry and Sales Invoice each have a route to `Member.payment_history`;
Journal Entry had neither, and the Sales Invoice route does not cover it. ERPNext
writes the restored figure with `frappe.db.set_value` + `set_status(update=True)`,
and neither dispatches `on_update_after_submit` -- so after a reversing entry the
ledger is right and the member's history still says Paid.

That write is `update_voucher_outstanding` (`erpnext/accounts/utils.py:2141`), not
`gl_entry.update_outstanding_amt`, which this docstring cited until #649 and which
cannot run for a Sales Invoice at all -- see
`background_jobs.queue_journal_entry_payment_history_update_handler`.

Three properties are proved separately, because they fail for different reasons:

* **the dispatch** -- submitting or cancelling a real Journal Entry reaches the
  handler, once per distinct member the entry names. Driven through `doc.submit()`
  rather than by reading `doc_events`, so a registration that exists but is never
  dispatched still fails.
* **the argument** -- what is dispatched, not merely that something was. The drain
  is `drain_member_payment_history(member, customer)` and it queues only invoices
  matching that `customer`, so a handler passing the wrong one enqueues a job that
  reads zero invoices and changes nothing. Asserting the member alone leaves that
  mutation alive, which is why every enqueue assertion below pins the PAIR.
* **the payload** -- running that drain actually replaces the stale figure. Not
  implied by the dispatch: the payment-history validator that might have covered
  this backfills only rows that are *missing*, and a row that is present but stale
  is invisible to it. If the drain behaved the same way, wiring the hook would
  change nothing.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt

from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.payment_history_fixtures import (
    MemberPaymentHistoryFixture,
    PaidInvoiceFixture,
)


class TestJournalEntryRefreshesPaymentHistory(PaidInvoiceFixture):
    MEMBER_FIRST_NAME = "JEHistory"

    def test_the_drain_replaces_a_stale_row_rather_than_skipping_it(self):
        """The payload half: the refresh has to OVERWRITE, not backfill.

        Without this, wiring the hook would be inert -- the row already exists, so
        an add-if-missing refresh would walk straight past the stale figure.
        """
        self.drain()
        row = self.history_row(self.invoice.name)
        self.assertEqual(flt(row.outstanding_amount), 0.0)
        self.assertEqual(row.payment_status, "Paid")

        self.reversing_entry(20.0)
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")),
            20.0,
            "the reversing entry must restore outstanding",
        )

        self.drain()

        row = self.history_row(self.invoice.name)
        self.assertEqual(
            flt(row.outstanding_amount),
            20.0,
            "the member's payment history still carries the pre-reversal figure",
        )
        # Pinned, not `assertNotEqual(..., "Paid")`: the loose form passes for
        # "Unpaid" too, which is what this row actually said until
        # `determine_payment_status` learned ERPNext's "Partly Paid" -- a label
        # contradicting the paid_amount and outstanding_amount beside it.
        self.assertEqual(row.payment_status, "Partially Paid")
        self.assertEqual(flt(row.paid_amount), self.INVOICE_AMOUNT)

    def test_submitting_the_entry_asks_for_a_refresh(self):
        """The dispatch half, driven through a real submit."""
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            self.reversing_entry(20.0)

        self.assertEqual(
            self.drains_for_this_member(enqueue),
            self.expected_drain,
            "submitting a Journal Entry against a member's receivable must queue a "
            "payment-history drain for that member AND that member's customer",
        )

    def test_cancelling_the_entry_asks_for_a_refresh(self):
        """Cancel takes the restored outstanding away again, so it is the same defect."""
        je = self.reversing_entry(20.0)

        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            je.cancel()

        self.assertEqual(self.drains_for_this_member(enqueue), self.expected_drain)

    def test_the_drain_is_deferred_and_asks_for_dedupe(self):
        """Same contract as the Payment Entry handler: nothing runs inline.

        `deduplicate=True` is asserted as REQUESTED, not as achieved -- frappe
        checks for a duplicate eagerly at enqueue() time while
        enqueue_after_commit defers the actual push, so two enqueues in one
        transaction both land. That gap is the shared helper's, not this hook's.
        """
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            with patch(
                "verenigingen.utils.financial_history_batch_processor."
                "FinancialHistoryBatchProcessor._process_member_payment_batch"
            ) as proc:
                self.reversing_entry(20.0)

        drains = [c.kwargs for c in enqueue.call_args_list if c.kwargs.get("member") == self.member.name]
        self.assertTrue(drains)
        self.assertEqual(drains[0]["customer"], self.member.customer)
        self.assertTrue(drains[0]["enqueue_after_commit"])
        self.assertTrue(drains[0]["deduplicate"])
        self.assertEqual(drains[0]["job_id"], f"fin_history_payment_{self.member.name}")
        proc.assert_not_called()


class TestJournalEntryHandlerCoversEveryParty(MemberPaymentHistoryFixture):
    """The handler is called with the doc directly, so a multi-party entry can be
    exercised without hand-building a balanced multi-member ledger.

    Deliberately built on `MemberPaymentHistoryFixture`, not `PaidInvoiceFixture`:
    none of these five needs an invoice or a payment, and inheriting them would tie
    them to the bank-account provisioning in that class's setUpClass -- and to the
    94-account EUR company build behind `self.company`, which is why neither is in
    the shared base.
    """

    MEMBER_FIRST_NAME = "JEHistory"

    def _handler_calls(self, accounts, name="JE-TEST"):
        from verenigingen.utils import background_jobs

        doc = frappe._dict(doctype="Journal Entry", name=name, accounts=[frappe._dict(a) for a in accounts])
        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            background_jobs.queue_journal_entry_payment_history_update_handler(doc)
        return [c.kwargs for c in enqueue.call_args_list]

    def test_every_member_named_by_the_entry_is_refreshed_not_just_the_first(self):
        """The reason a Journal Entry cannot reuse the Payment Entry handler: its
        party is per ROW, and one entry can settle several members at once."""
        other = member_with_customer(self, "JEHistorySecond")

        calls = self._handler_calls(
            [
                {"party_type": "Customer", "party": self.member.customer, "debit_in_account_currency": 10},
                {"party_type": "Customer", "party": other.customer, "debit_in_account_currency": 10},
                {"party_type": None, "party": None, "credit_in_account_currency": 20},
            ]
        )

        # Pairs, not members: a handler that refreshed both members but passed one
        # customer for both would enqueue a job that reads zero invoices.
        self.assertEqual(
            {(c["member"], c["customer"]) for c in calls},
            {(self.member.name, self.member.customer), (other.name, other.customer)},
            "both members named by the entry must be refreshed, each against its own customer",
        )

    def test_one_member_on_two_rows_is_refreshed_once(self):
        calls = self._handler_calls(
            [
                {"party_type": "Customer", "party": self.member.customer, "debit_in_account_currency": 10},
                {"party_type": "Customer", "party": self.member.customer, "debit_in_account_currency": 5},
                {"party_type": None, "party": None, "credit_in_account_currency": 15},
            ]
        )
        self.assertEqual(
            [(c["member"], c["customer"]) for c in calls], [(self.member.name, self.member.customer)]
        )

    def test_a_non_customer_party_is_ignored(self):
        """A Supplier row carries a `party` too; it is not a member's receivable."""
        calls = self._handler_calls(
            [
                {"party_type": "Supplier", "party": self.member.customer, "debit_in_account_currency": 10},
                {"party_type": None, "party": None, "credit_in_account_currency": 10},
            ]
        )
        self.assertEqual(calls, [])

    def test_a_customer_with_no_member_is_ignored(self):
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"JE History Non-Member {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.insert(ignore_permissions=True)
        self.track_test_record("Customer", customer.name)

        calls = self._handler_calls(
            [
                {"party_type": "Customer", "party": customer.name, "debit_in_account_currency": 10},
                {"party_type": None, "party": None, "credit_in_account_currency": 10},
            ]
        )
        self.assertEqual(calls, [])

    def test_an_entry_with_no_account_rows_is_a_no_op(self):
        self.assertEqual(self._handler_calls([]), [])
