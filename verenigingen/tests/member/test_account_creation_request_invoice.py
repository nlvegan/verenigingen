"""
Real-integration tests for
``AccountCreationRequest.get_application_invoice``.

The method previously searched Member Payment History rows for an
``invoice_type == "Application"`` or an ``"application"`` substring in a
``description`` field. Member Payment History has neither field, so the lookup
always returned ``None`` and the gated approval email
(``send_member_approval_email`` -> ``if invoice:``) was never sent.

The fix matches ``transaction_type == "Membership Invoice"`` (the value the
payment-history builder assigns to invoices linked to a Membership) and returns
the earliest such invoice by ``posting_date`` -- i.e. the original application /
onboarding invoice.

These tests create real Members, append real Member Payment History child rows,
and point them at real Sales Invoices. No business logic is mocked.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestAccountCreationRequestInvoice(VereningingenTestCase):
    """Exercise get_application_invoice end to end with real child rows."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="ACRInvoice",
            last_name="Lookup",
            email=f"acr.invoice.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        # An unsaved Account Creation Request is enough: get_application_invoice
        # is a pure read over the passed-in member's payment_history.
        self.acr = frappe.new_doc("Account Creation Request")

    def _append_history_row(self, invoice_name, transaction_type, posting_date=None):
        """Append a real Member Payment History child row to the member doc."""
        self.member.append(
            "payment_history",
            {
                "invoice": invoice_name,
                "transaction_type": transaction_type,
                "posting_date": posting_date or today(),
                "amount": 25.0,
                "outstanding_amount": 0.0,
                "payment_status": "Paid",
            },
        )

    # --------------------------------------------------------------------- positive path

    def test_returns_membership_invoice(self):
        """A Membership Invoice row yields the linked Sales Invoice (was None)."""
        invoice = self.create_test_sales_invoice(member=self.member.name)
        self._append_history_row(invoice.name, "Membership Invoice")

        result = self.acr.get_application_invoice(self.member)

        self.assertIsNotNone(result, "get_application_invoice must find the membership invoice")
        self.assertEqual(result.doctype, "Sales Invoice")
        self.assertEqual(result.name, invoice.name)

    # --------------------------------------------------------------------- negative path

    def test_regular_invoice_only_returns_none(self):
        """Only Regular Invoice rows -> no application invoice."""
        invoice = self.create_test_sales_invoice(member=self.member.name)
        self._append_history_row(invoice.name, "Regular Invoice")

        result = self.acr.get_application_invoice(self.member)

        self.assertIsNone(result)

    def test_empty_history_returns_none(self):
        """A member with no payment history returns None (no crash)."""
        result = self.acr.get_application_invoice(self.member)
        self.assertIsNone(result)

    # --------------------------------------------------------------------- earliest selection

    def test_returns_earliest_membership_invoice(self):
        """With several Membership Invoices, the earliest posting_date wins."""
        earliest_inv = self.create_test_sales_invoice(member=self.member.name)
        middle_inv = self.create_test_sales_invoice(member=self.member.name)
        latest_inv = self.create_test_sales_invoice(member=self.member.name)

        # Append out of chronological order to ensure selection is by date, not order.
        self._append_history_row(middle_inv.name, "Membership Invoice", posting_date=add_days(today(), -30))
        self._append_history_row(latest_inv.name, "Membership Invoice", posting_date=today())
        self._append_history_row(earliest_inv.name, "Membership Invoice", posting_date=add_days(today(), -60))

        result = self.acr.get_application_invoice(self.member)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, earliest_inv.name)

    def test_mixed_rows_picks_membership_invoice(self):
        """Membership Invoice is selected even when Regular Invoice rows precede it."""
        regular_inv = self.create_test_sales_invoice(member=self.member.name)
        membership_inv = self.create_test_sales_invoice(member=self.member.name)

        self._append_history_row(regular_inv.name, "Regular Invoice", posting_date=add_days(today(), -90))
        self._append_history_row(membership_inv.name, "Membership Invoice", posting_date=today())

        result = self.acr.get_application_invoice(self.member)

        self.assertIsNotNone(result)
        self.assertEqual(result.name, membership_inv.name)
