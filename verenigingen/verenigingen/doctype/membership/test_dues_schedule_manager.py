"""
Integration tests for verenigingen/verenigingen/doctype/membership/dues_schedule_manager.py

This module bridges Membership records, their Membership Dues Schedule and the
customer's Sales Invoices. The tests below build REAL documents (no mocking of
business logic) and assert real money behaviour: invoice payment-status
propagation (sync_membership_with_dues_schedule) and payment history
aggregation (get_membership_payment_history).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
    get_membership_payment_history,
    sync_membership_with_dues_schedule,
)


class TestDuesScheduleManager(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="DSM Test Type",
            amount=50.0,
            contribution_mode="Fixed Amount",
        )

    # ------------------------------------------------------------------
    # Helpers (privileged data creation lives here, NOT in test bodies)
    # ------------------------------------------------------------------
    def _make_member_with_membership(self, payment_method="Bank Transfer", start_date=None):
        """Create a member (+customer) with a submitted membership and its schedule.

        Returns (member_doc, membership_doc, schedule_doc).
        """
        start_date = start_date or today()
        member, schedule = self.create_test_member_with_schedule(
            first_name="Dsm",
            last_name="Member",
            membership_type_name=self.membership_type.name,
            start_date=start_date,
            payment_method=payment_method,
        )
        membership_name = frappe.db.get_value(
            "Membership", {"member": member.name, "status": "Active"}, "name"
        )
        membership = frappe.get_doc("Membership", membership_name)
        return member, membership, schedule

    def _make_invoice(self, member, status=None, grand_total=50.0, outstanding=None, posting_date=None):
        """Create a submitted Sales Invoice for the member's customer."""
        kwargs = {
            "grand_total": grand_total,
            "posting_date": posting_date or today(),
        }
        if status is not None:
            kwargs["status"] = status
        if outstanding is not None:
            kwargs["outstanding_amount"] = outstanding
        return self.create_test_sales_invoice(member.customer, **kwargs)

    # ------------------------------------------------------------------
    # sync_membership_with_dues_schedule
    # ------------------------------------------------------------------
    def test_sync_returns_none_without_dues_schedule(self):
        """No dues schedule -> early return None, no side effects."""
        member = self.create_test_member(first_name="NoSched", last_name="Member")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type.name
        )
        # Remove the auto-created dues schedule so the lookup misses.
        sched = frappe.db.get_value("Membership Dues Schedule", {"membership": membership.name}, "name")
        if sched:
            self._delete_schedule(sched)

        self.assertIsNone(sync_membership_with_dues_schedule(membership))

    def _delete_schedule(self, schedule_name):
        frappe.delete_doc("Membership Dues Schedule", schedule_name, force=True, ignore_permissions=True)

    def test_sync_returns_none_without_invoices(self):
        """Has schedule + customer but no invoices -> returns None."""
        _member, membership, _schedule = self._make_member_with_membership()
        self.assertIsNone(sync_membership_with_dues_schedule(membership))

    def test_sync_with_paid_invoice_reports_invoice(self):
        """A submitted (Paid) invoice is reported back by the sync helper.

        Asserts the returned invoice list carries the real invoice, status and
        posting date - i.e. the money path actually finds the invoice rather
        than silently returning None.
        """
        member, membership, _schedule = self._make_member_with_membership()
        invoice = self._make_invoice(member, grand_total=50.0)
        # A freshly-submitted, fully-outstanding invoice is "Unpaid"; force a
        # Paid invoice by paying it down to zero outstanding.
        self._mark_invoice_paid(invoice)

        result = sync_membership_with_dues_schedule(membership)

        self.assertIsNotNone(result)
        names = [r["name"] for r in result]
        self.assertIn(invoice.name, names)
        latest = result[0]
        self.assertEqual(latest["status"], "Paid")

    def _mark_invoice_paid(self, invoice):
        """Drive a submitted invoice to Paid by clearing its outstanding amount."""
        invoice.reload()
        invoice.db_set("outstanding_amount", 0)
        invoice.db_set("status", "Paid")
        invoice.reload()

    def test_sync_uses_latest_invoice_by_posting_date(self):
        """sync orders invoices posting_date desc and acts on the newest one."""
        member, membership, _schedule = self._make_member_with_membership(start_date=add_days(today(), -40))
        old = self._make_invoice(member, grand_total=10.0, posting_date=add_days(today(), -30))
        new = self._make_invoice(member, grand_total=20.0, posting_date=today())
        self._mark_invoice_paid(old)
        self._mark_invoice_paid(new)

        result = sync_membership_with_dues_schedule(membership)
        self.assertEqual(result[0]["name"], new.name)

    def test_sync_only_counts_invoices_on_or_after_start_date(self):
        """Invoices posted before membership.start_date are excluded."""
        member, membership, _schedule = self._make_member_with_membership(start_date=today())
        before = self._make_invoice(member, grand_total=10.0, posting_date=add_days(today(), -10))
        self._mark_invoice_paid(before)

        # Only the pre-start invoice exists -> filtered out -> None.
        self.assertIsNone(sync_membership_with_dues_schedule(membership))

    # ------------------------------------------------------------------
    # get_membership_payment_history
    # ------------------------------------------------------------------
    def test_payment_history_empty_without_schedule(self):
        member = self.create_test_member(first_name="HistNo", last_name="Sched")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type.name
        )
        sched = frappe.db.get_value("Membership Dues Schedule", {"membership": membership.name}, "name")
        if sched:
            self._delete_schedule(sched)
        self.assertEqual(get_membership_payment_history(membership), [])

    def test_payment_history_empty_without_invoices(self):
        _member, membership, _schedule = self._make_member_with_membership()
        self.assertEqual(get_membership_payment_history(membership), [])

    def test_payment_history_reports_invoice_amount_and_status(self):
        """Payment history carries the invoice grand_total + status + empty payments."""
        member, membership, _schedule = self._make_member_with_membership()
        invoice = self._make_invoice(member, grand_total=50.0)

        history = get_membership_payment_history(membership)

        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry["invoice"], invoice.name)
        self.assertEqual(entry["amount"], invoice.grand_total)
        self.assertEqual(entry["status"], invoice.status)
        # No payment entries linked yet.
        self.assertEqual(entry["payments"], [])
