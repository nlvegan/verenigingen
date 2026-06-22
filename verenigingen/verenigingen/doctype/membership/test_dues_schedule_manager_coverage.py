"""
Additional coverage for membership/dues_schedule_manager.py.

test_dues_schedule_manager.py already covers the Paid path, the early-return
guards, the placeholder bank-details helper and the SEPA selector guards. These
tests target the *uncovered* status branches of sync_membership_with_dues_schedule
and the Payment-Entry aggregation loop in get_membership_payment_history:

- sync: Overdue invoice -> membership.unpaid_amount = outstanding_amount.
- sync: ordinary Unpaid invoice (else branch) -> unpaid_amount = outstanding.
- sync: Paid invoice -> unpaid_amount cleared to 0 and last_payment_date set.
- payment history: a linked, submitted Payment Entry shows up in the entry's
  `payments` list with the real paid amount.

All documents are real; no business logic is mocked.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
    get_membership_payment_history,
    sync_membership_with_dues_schedule,
)


class TestDuesScheduleManagerCoverage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="DSMCov Type",
            amount=50.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _member_with_membership(self):
        member, schedule = self.create_test_member_with_schedule(
            first_name="DsmCov",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=today(),
        )
        membership_name = frappe.db.get_value(
            "Membership", {"member": member.name, "status": "Active"}, "name"
        )
        membership = frappe.get_doc("Membership", membership_name)
        return member, membership, schedule

    def _force_invoice_status(self, invoice, status, outstanding):
        invoice.reload()
        invoice.db_set("outstanding_amount", outstanding)
        invoice.db_set("status", status)
        invoice.reload()

    def _pay_invoice(self, invoice):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = f"REF-{frappe.generate_hash(length=6)}"
        pe.reference_date = today()
        pe.insert()
        pe.submit()
        return pe

    # ------------------------------------------------------------------
    # sync_membership_with_dues_schedule status branches
    # ------------------------------------------------------------------
    def test_sync_overdue_sets_unpaid_amount(self):
        """An Overdue latest invoice sets membership.unpaid_amount to its outstanding."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        self._force_invoice_status(invoice, "Overdue", outstanding=50.0)

        result = sync_membership_with_dues_schedule(membership)

        self.assertIsNotNone(result)
        membership.reload()
        self.assertEqual(membership.unpaid_amount, 50.0)

    def test_sync_unpaid_else_branch_sets_outstanding(self):
        """A plain Unpaid invoice (else branch) sets unpaid_amount to its outstanding."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        # Freshly submitted invoices are already "Unpaid" with full outstanding.
        invoice.reload()
        self.assertEqual(invoice.status, "Unpaid")

        sync_membership_with_dues_schedule(membership)

        membership.reload()
        self.assertEqual(membership.unpaid_amount, invoice.outstanding_amount)
        self.assertGreater(membership.unpaid_amount, 0)

    def test_sync_paid_clears_unpaid_and_sets_payment_date(self):
        """A Paid latest invoice clears unpaid_amount and records last_payment_date."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        self._force_invoice_status(invoice, "Paid", outstanding=0)

        sync_membership_with_dues_schedule(membership)

        membership.reload()
        self.assertEqual(membership.unpaid_amount, 0)
        self.assertEqual(frappe.utils.getdate(membership.last_payment_date), frappe.utils.getdate(today()))

    # ------------------------------------------------------------------
    # get_membership_payment_history with a linked Payment Entry
    # ------------------------------------------------------------------
    def test_payment_history_includes_linked_payment_entry(self):
        """A submitted Payment Entry against the invoice surfaces in the payments list."""
        member, membership, _schedule = self._member_with_membership()
        invoice = self.create_test_sales_invoice(member.customer, grand_total=50.0)
        pe = self._pay_invoice(invoice)

        history = get_membership_payment_history(membership)

        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry["invoice"], invoice.name)
        # The Payment Entry loop populated the payments list with the real PE.
        self.assertEqual(len(entry["payments"]), 1)
        payment = entry["payments"][0]
        self.assertEqual(payment["payment_entry"], pe.name)
        self.assertEqual(payment["amount"], pe.paid_amount)
        self.assertEqual(payment["amount"], 50.0)
