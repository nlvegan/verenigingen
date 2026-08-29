"""Shared fixtures for the "a voucher moved a member invoice's outstanding" suites.

#645 (Journal Entry) and #649 (credit note, Payment Reconciliation) are the same
defect with different producers, and each suite makes the same two assertions: that
the handler asked for a drain naming the right (member, customer) PAIR, and that the
drain then OVERWROTE the stale history row rather than backfilling a missing one.

Shared rather than copied per suite. The duplicate-helper census keys on NAMES, so
two private copies of `_drains_for_this_member` would have been a clone family -- and
more to the point, the reason those assertions are shaped the way they are (a pair,
not a member; a pinned status, not `assertNotEqual`) is a finding that should live in
one place, not be re-derived by whoever adds the next producer.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.invoice_payments import (
    build_eur_membership_invoice,
    member_with_customer,
    receive_against_invoice,
)
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company


class MemberPaymentHistoryFixture(EnhancedTestCase):
    """A member with a Customer, plus the drain assertions every producer shares.

    Deliberately carries NO company, no invoice, no ledger and no bank account: a suite
    that only calls a handler with a hand-built doc should not pay for provisioning any
    of them. `self.company` in particular is NOT set here -- resolving it builds a
    94-account EUR test company, and putting it in the shared base coupled five
    handler-only tests to that build.

    Stated as a CONTRACT, not a measured saving: those five currently share a module
    with a `PaidInvoiceFixture` suite whose setUpClass builds the company anyway, so the
    runtime saving in the tree as it stands is zero. The point is that the base does not
    REQUIRE it, so a future handler-only module can live without one. See
    `PaidInvoiceFixture` for the rest.
    """

    MEMBER_FIRST_NAME = "PaymentHistory"

    def setUp(self):
        super().setUp()
        self.member = member_with_customer(self, self.MEMBER_FIRST_NAME)

    def history_row(self, invoice_name):
        """The member's single payment-history row for `invoice_name`."""
        member = frappe.get_doc("Member", self.member.name)
        rows = [e for e in member.payment_history if e.invoice == invoice_name]
        self.assertEqual(len(rows), 1, f"expected exactly one history row for {invoice_name}")
        return rows[0]

    def drain(self):
        from verenigingen.utils.background_jobs import drain_member_payment_history

        drain_member_payment_history(self.member.name, self.member.customer)

    def drains_for_this_member(self, enqueue):
        """The (member, customer) PAIRS the handler asked to drain.

        Pairs, not members: `drain_member_payment_history(member, customer)` queues
        only invoices matching that `customer`, so a handler passing the wrong one
        enqueues a job that reads zero invoices and changes nothing. Asserting the
        member alone leaves that mutation alive -- measured on #645, where it
        survived all 39 tests.
        """
        return {
            (c.kwargs.get("member"), c.kwargs.get("customer"))
            for c in enqueue.call_args_list
            if c.kwargs.get("member") == self.member.name
        }

    @property
    def expected_drain(self):
        return {(self.member.name, self.member.customer)}


class PaidInvoiceFixture(MemberPaymentHistoryFixture):
    """`MemberPaymentHistoryFixture` plus a fully paid EUR invoice and a way to reverse it."""

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

    def reversing_entry(self, amount, submit=True):
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
