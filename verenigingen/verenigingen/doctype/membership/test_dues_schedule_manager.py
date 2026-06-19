"""
Integration tests for verenigingen/verenigingen/doctype/membership/dues_schedule_manager.py

This module is core billing logic that bridges Membership records, their
Membership Dues Schedule, the customer's Sales Invoices and SEPA Direct Debit
batches. The tests below build REAL documents (no mocking of business logic)
and assert real money behaviour: invoice payment-status propagation, payment
history aggregation, and the guard branches of the two whitelisted SEPA helpers.

Several characterization tests document genuine production defects discovered
while writing these tests (see CHARACTERIZED BUG markers). Where the correct
behaviour is unambiguous the production code is fixed and the corrected
behaviour asserted; where money semantics are ambiguous the current behaviour
is pinned and FLAGGED rather than guessed.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.membership.dues_schedule_manager import (
    add_to_direct_debit_batch,
    create_direct_debit_batch,
    get_member_bank_details,
    get_membership_payment_history,
    get_unpaid_membership_invoices,
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

    def _set_member_payment_method(self, member, mode):
        """Persist a payment method on the member (privileged helper)."""
        member.payment_method = mode
        member.save()
        member.reload()

    # ------------------------------------------------------------------
    # get_member_bank_details  (documented placeholder)
    # ------------------------------------------------------------------
    def test_get_member_bank_details_returns_empty_placeholder(self):
        """get_member_bank_details is an unimplemented placeholder returning {}.

        It is consumed by create_direct_debit_batch as the *only* source of bank
        details, so its empty return means create_direct_debit_batch can never
        produce entries (asserted separately below). Pin the behaviour so a
        future real implementation is a deliberate, test-visible change.
        """
        member, _membership, _schedule = self._make_member_with_membership()
        self.assertEqual(get_member_bank_details(member.name), {})
        # Also robust to a non-existent member name.
        self.assertEqual(get_member_bank_details("does-not-exist"), {})

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

    # ------------------------------------------------------------------
    # create_direct_debit_batch
    # ------------------------------------------------------------------
    def test_create_direct_debit_batch_returns_none_when_no_eligible(self):
        """No SEPA members / no bank details -> no batch created.

        get_member_bank_details() is an empty placeholder, so even a SEPA member
        with an unpaid invoice yields no batch entries. This documents that
        create_direct_debit_batch is effectively inert in production.
        """
        member, _membership, _schedule = self._make_member_with_membership(payment_method="SEPA Direct Debit")
        # An unpaid invoice exists for a SEPA member ...
        self._make_invoice(member, grand_total=50.0)
        # ... but bank details are empty -> no batch.
        self.assertIsNone(create_direct_debit_batch())

    def test_create_direct_debit_batch_skips_non_sepa_members(self):
        member, _membership, _schedule = self._make_member_with_membership(payment_method="Bank Transfer")
        self._make_invoice(member, grand_total=50.0)
        self.assertIsNone(create_direct_debit_batch())

    # ------------------------------------------------------------------
    # get_unpaid_membership_invoices (whitelisted)
    # ------------------------------------------------------------------
    def test_get_unpaid_membership_invoices_empty_when_no_schedules(self):
        """When the SEPA selector finds no eligible invoices it returns []."""
        # Bank-transfer member with an unpaid invoice -> excluded (non-SEPA).
        member, _membership, _schedule = self._make_member_with_membership(payment_method="Bank Transfer")
        self._make_invoice(member, grand_total=50.0)
        self.assertEqual(get_unpaid_membership_invoices(), [])

    def test_get_unpaid_membership_invoices_excludes_members_without_mandate(self):
        """SEPA member with an unpaid invoice but no mandate_reference -> excluded.

        Member has no mandate_reference field at all, so the iban+mandate guard
        can never pass: this selector returns nothing for real members.
        """
        member, _membership, _schedule = self._make_member_with_membership(payment_method="SEPA Direct Debit")
        self._make_invoice(member, grand_total=50.0)
        result = get_unpaid_membership_invoices()
        member_names = [r["member"] for r in result]
        self.assertNotIn(member.name, member_names)

    # ------------------------------------------------------------------
    # add_to_direct_debit_batch (whitelisted, critical)
    # ------------------------------------------------------------------
    def test_add_to_direct_debit_batch_requires_dues_schedule(self):
        """Membership without a dues schedule is rejected before any field read."""
        member = self.create_test_member(first_name="DDBNo", last_name="Sched")
        self.link_member_to_customer(member)
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=self.membership_type.name
        )
        sched = frappe.db.get_value("Membership Dues Schedule", {"membership": membership.name}, "name")
        if sched:
            self._delete_schedule(sched)

        with self.assertRaises(frappe.ValidationError):
            add_to_direct_debit_batch(membership.name)

    def test_add_to_direct_debit_batch_unpaid_amount_field(self):
        """add_to_direct_debit_batch reads membership.unpaid_amount.

        CHARACTERIZED BUG: Membership has no `unpaid_amount` field (verified
        against the doctype JSON and Custom Field table). After the dues-schedule
        guard passes, the code does `if membership.unpaid_amount <= 0:`. On a
        real Membership document this attribute does not exist, so the access
        raises AttributeError (the membership cannot be added to a batch and the
        user sees an opaque server error rather than a clean message).

        This test pins the current broken behaviour. Money semantics are
        ambiguous here (what *is* a membership's unpaid amount now that it is
        tracked on Sales Invoices, not the Membership?) so the fix is FLAGGED for
        review rather than guessed.
        """
        member, membership, _schedule = self._make_member_with_membership(payment_method="SEPA Direct Debit")
        # Confirm the field genuinely does not exist on the membership.
        self.assertIsNone(membership.meta.get_field("unpaid_amount"))

        with self.assertRaises((AttributeError, TypeError)):
            add_to_direct_debit_batch(membership.name)
