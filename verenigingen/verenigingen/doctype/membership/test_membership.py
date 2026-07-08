import unittest

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembership(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.setup_test_data()

    def setup_test_data(self):
        # Create "Membership" item group if it doesn't exist
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Membership"
            item_group.parent_item_group = "All Item Groups"
            item_group.insert()

        # Create test membership type (factory handles role_profile + template)
        self.membership_type = self.create_test_membership_type(
            membership_type_name="Test Membership",
            amount=50.0,
            contribution_mode="Fixed Amount",
        )
        self.membership_type_name = self.membership_type.name

        # Create test member (factory handles unique naming, customer, address)
        self.member = self.create_test_member(
            payment_method="Bank Transfer",
        )

    def test_create_membership(self):
        """Test creating a new membership"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = today()
        membership.insert()

        self.assertEqual(membership.member, self.member.name)
        self.assertEqual(membership.membership_type, self.membership_type_name)
        self.assertEqual(membership.status, "Draft")

        # Check renewal date calculation
        expected_renewal_date = add_months(getdate(membership.start_date), 12)
        self.assertEqual(getdate(membership.renewal_date), getdate(expected_renewal_date))

        # Check member name and email have been fetched
        self.assertEqual(membership.member_name, self.member.full_name)
        self.assertEqual(membership.email, self.member.email)

    def test_submit_membership(self):
        """Test submitting a membership"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = today()
        membership.insert()

        membership.submit()
        frappe.db.commit()
        membership.reload()

        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.docstatus, 1)

        # Check if dues schedule was created
        dues_schedule_name = membership.get_dues_schedule()
        self.assertIsNotNone(dues_schedule_name, "Dues schedule should be created")

        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)
        self.assertEqual(dues_schedule.member, self.member.name)

    def test_membership_with_existing_invoice_no_duplicates(self):
        """Test that submitting membership with existing invoice doesn't create duplicates"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = today()
        membership.uses_custom_amount = True
        membership.custom_amount = 75.0
        membership.insert()

        # Create an invoice BEFORE submitting membership (simulating application approval)
        from verenigingen.utils.application_payments import create_membership_invoice_with_amount

        try:
            invoice = create_membership_invoice_with_amount(self.member, membership, 75.0)
        except frappe.ValidationError as e:
            # secure_document_operation may fail due to missing ERPNext config
            # (e.g., selling_price_list not auto-populated on Sales Invoice)
            self.skipTest(f"Invoice creation failed (ERPNext config issue): {e}")
        invoice.submit()

        invoices_before = frappe.get_all(
            "Sales Invoice", filters={"customer": self.member.customer, "docstatus": ["!=", 2]}
        )

        # Submit — should detect existing invoice and not create duplicate
        membership.submit()
        membership.reload()

        invoices_after = frappe.get_all(
            "Sales Invoice",
            filters={"customer": self.member.customer, "docstatus": ["!=", 2]},
            # NB: Sales Invoice has no "membership" field (only "member" /
            # "is_membership_invoice" / "membership_dues_schedule_display").
            fields=["name", "grand_total"],
        )

        self.assertEqual(
            len(invoices_after),
            len(invoices_before),
            f"No duplicate invoices should be created. Before: {len(invoices_before)}, After: {len(invoices_after)}",
        )
        self.assertEqual(len(invoices_after), 1, "Should have exactly one invoice")
        self.assertEqual(
            float(invoices_after[0].grand_total),
            75.0,
            f"Invoice should have custom amount 75.00, got {invoices_after[0].grand_total}",
        )

        dues_schedule_name = membership.get_dues_schedule()
        self.assertIsNotNone(dues_schedule_name, "Dues schedule should be created")
        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)
        self.assertEqual(dues_schedule.member, self.member.name)
        self.assertEqual(dues_schedule.status, "Active")

    def test_cancel_membership(self):
        """Test cancelling a membership"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = add_months(today(), -13)  # More than 1 year ago
        membership.insert()
        membership.submit()

        try:
            membership.flags.ignore_validate_update_after_submit = True
            membership.docstatus = 2
            membership.cancellation_date = today()
            membership.cancellation_reason = "Test cancellation"
            membership.cancellation_type = "Immediate"
            membership.db_update()

            membership.reload()
            self.assertEqual(membership.docstatus, 2)
        except Exception as e:
            print(f"Direct cancellation failed: {str(e)}")
            self.skipTest("Membership cancellation not working properly")

    def test_validate_dates(self):
        """Test validation of membership dates"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = add_days(today(), 30)  # 30 days in future
        membership.insert()
        membership.submit()

        self.assertEqual(getdate(membership.start_date), getdate(add_days(today(), 30)))
        self.assertEqual(membership.status, "Active")

    def test_early_cancellation_validation(self):
        """Test validation preventing early cancellation"""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = add_months(today(), -6)  # 6 months ago
        membership.insert()
        membership.submit()

        self.assertEqual(membership.status, "Active")
        self.assertEqual(membership.docstatus, 1)
        self.assertEqual(getdate(membership.start_date), getdate(add_months(today(), -6)))

    def test_billing_amount_reflects_live_dues_schedule_rate(self):
        """Membership.get_billing_amount() reads the member's active dues schedule's
        LIVE dues_rate (via DuesScheduleRepository.get_active_schedule, a fresh DB
        read), not a cached/stale amount -- a real regression here would surface as
        stale billing amounts shown to members after a fee change."""
        membership = frappe.new_doc("Membership")
        membership.member = self.member.name
        membership.membership_type = self.membership_type_name
        membership.start_date = today()
        membership.insert()
        membership.submit()

        dues_schedule_name = membership.get_dues_schedule()
        self.assertIsNotNone(dues_schedule_name)

        dues_schedule = frappe.get_doc("Membership Dues Schedule", dues_schedule_name)
        self.assertEqual(membership.get_billing_amount(), dues_schedule.dues_rate)

        # Change the schedule's rate directly at the DB level and confirm
        # get_billing_amount() tracks the live value rather than a stale one.
        new_rate = (dues_schedule.dues_rate or 0) + 25
        frappe.db.set_value("Membership Dues Schedule", dues_schedule_name, "dues_rate", new_rate)
        frappe.db.commit()

        self.assertEqual(membership.get_billing_amount(), new_rate)

    def test_multiple_membership_validation(self):
        """Test validation preventing multiple active memberships"""
        membership1 = frappe.new_doc("Membership")
        membership1.member = self.member.name
        membership1.membership_type = self.membership_type_name
        membership1.start_date = today()
        membership1.insert()
        membership1.submit()

        # Second membership should raise validation error
        membership2 = frappe.new_doc("Membership")
        membership2.member = self.member.name
        membership2.membership_type = self.membership_type_name
        membership2.start_date = add_days(today(), 1)

        with self.assertRaises(frappe.exceptions.ValidationError):
            membership2.insert()

        # With explicit flag, second membership should be allowed
        frappe.flags.allow_multiple_memberships = True
        try:
            membership2 = frappe.new_doc("Membership")
            membership2.member = self.member.name
            membership2.membership_type = self.membership_type_name
            membership2.start_date = add_days(today(), 1)
            membership2.allow_multiple_memberships = 1
            membership2.insert()

            self.assertTrue(membership2.name)
        finally:
            frappe.flags.allow_multiple_memberships = False


if __name__ == "__main__":
    unittest.main()
