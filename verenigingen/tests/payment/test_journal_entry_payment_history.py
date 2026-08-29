"""A Journal Entry that moves a member invoice's outstanding must refresh history (#645).

Payment Entry and Sales Invoice each have a route to `Member.payment_history`;
Journal Entry had neither, and the Sales Invoice route does not cover it. ERPNext
writes the restored figure with `frappe.db.set_value` + `set_status(update=True)`
(`gl_entry.py`), and neither dispatches `on_update_after_submit` -- so after a
reversing entry the ledger is right and the member's history still says Paid.

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
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import (
    build_eur_membership_invoice,
    member_with_customer,
    receive_against_invoice,
)
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company


class _MemberFixture(EnhancedTestCase):
    """A member with a Customer. No ledger -- see `_PaidInvoiceFixture` for that."""

    def setUp(self):
        super().setUp()
        self.member = member_with_customer(self, "JEHistory")


class _PaidInvoiceFixture(_MemberFixture):
    """`_MemberFixture` plus a fully paid EUR invoice and the accounts to reverse it."""

    INVOICE_AMOUNT = 42.0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # `receive_against_invoice` READS `Company.default_bank_account`; this is
        # what provisions it. Doing it here rather than in the test body keeps the
        # helper's own commit out of a test's in-flight fixtures.
        get_eur_bank_account(get_eur_test_company())

    def setUp(self):
        super().setUp()
        self.company = get_eur_test_company()
        self.invoice = build_eur_membership_invoice(self, self.member.customer, rate=self.INVOICE_AMOUNT)
        # The Payment Entry handle is kept because `receive_against_invoice` says to:
        # a caller whose code-under-test commits has it committed too and must be
        # able to force-clean it, and the drain fails on a stranded one.
        _, self.forward_payment = receive_against_invoice(self, self.invoice.name, self.INVOICE_AMOUNT)
        self.track_test_record("Payment Entry", self.forward_payment.name)

        self.receivable = self.invoice.debit_to
        self.bank_gl_account = frappe.db.get_value("Company", self.company, "default_bank_account")

    def _reversing_entry(self, amount, submit=True):
        """Debit the receivable against the invoice, credit the bank -- a refund.

        This is the shape `dues_reversal_journal_entry_creator` writes: the party
        sits on the receivable ROW, not on the document, which is the whole reason
        the Payment Entry handler cannot be reused as-is.
        """
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = self.company
        je.posting_date = today()
        je.append(
            "accounts",
            {
                "account": self.receivable,
                "party_type": "Customer",
                "party": self.member.customer,
                "debit_in_account_currency": amount,
                "credit_in_account_currency": 0,
                "reference_type": "Sales Invoice",
                "reference_name": self.invoice.name,
            },
        )
        je.append(
            "accounts",
            {
                "account": self.bank_gl_account,
                "debit_in_account_currency": 0,
                "credit_in_account_currency": amount,
            },
        )
        je.insert()
        self.track_test_record("Journal Entry", je.name)
        if submit:
            je.submit()
        return je

    def _history_row(self):
        member = frappe.get_doc("Member", self.member.name)
        rows = [e for e in member.payment_history if e.invoice == self.invoice.name]
        self.assertEqual(len(rows), 1, f"expected exactly one history row for {self.invoice.name}")
        return rows[0]

    def _drain(self):
        from verenigingen.utils.background_jobs import drain_member_payment_history

        drain_member_payment_history(self.member.name, self.member.customer)

    def _drains_for_this_member(self, enqueue):
        """The (member, customer) pairs the handler asked to drain."""
        return {
            (c.kwargs.get("member"), c.kwargs.get("customer"))
            for c in enqueue.call_args_list
            if c.kwargs.get("member") == self.member.name
        }

    @property
    def _expected_drain(self):
        return {(self.member.name, self.member.customer)}


class TestJournalEntryRefreshesPaymentHistory(_PaidInvoiceFixture):
    def test_the_drain_replaces_a_stale_row_rather_than_skipping_it(self):
        """The payload half: the refresh has to OVERWRITE, not backfill.

        Without this, wiring the hook would be inert -- the row already exists, so
        an add-if-missing refresh would walk straight past the stale figure.
        """
        self._drain()
        row = self._history_row()
        self.assertEqual(flt(row.outstanding_amount), 0.0)
        self.assertEqual(row.payment_status, "Paid")

        self._reversing_entry(20.0)
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", self.invoice.name, "outstanding_amount")),
            20.0,
            "the reversing entry must restore outstanding",
        )

        self._drain()

        row = self._history_row()
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
            self._reversing_entry(20.0)

        self.assertEqual(
            self._drains_for_this_member(enqueue),
            self._expected_drain,
            "submitting a Journal Entry against a member's receivable must queue a "
            "payment-history drain for that member AND that member's customer",
        )

    def test_cancelling_the_entry_asks_for_a_refresh(self):
        """Cancel takes the restored outstanding away again, so it is the same defect."""
        je = self._reversing_entry(20.0)

        with patch("verenigingen.utils.background_jobs.frappe.enqueue") as enqueue:
            je.cancel()

        self.assertEqual(self._drains_for_this_member(enqueue), self._expected_drain)

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
                self._reversing_entry(20.0)

        drains = [c.kwargs for c in enqueue.call_args_list if c.kwargs.get("member") == self.member.name]
        self.assertTrue(drains)
        self.assertEqual(drains[0]["customer"], self.member.customer)
        self.assertTrue(drains[0]["enqueue_after_commit"])
        self.assertTrue(drains[0]["deduplicate"])
        self.assertEqual(drains[0]["job_id"], f"fin_history_payment_{self.member.name}")
        proc.assert_not_called()


class TestJournalEntryHandlerCoversEveryParty(_MemberFixture):
    """The handler is called with the doc directly, so a multi-party entry can be
    exercised without hand-building a balanced multi-member ledger.

    Deliberately built on `_MemberFixture`, not `_PaidInvoiceFixture`: none of these
    needs an invoice or a payment, and inheriting them would tie four fast tests to
    the bank-account provisioning in that class's setUpClass.
    """

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
