# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Unit tests for Membership controller methods
Tests the Python controller methods including minimum period enforcement
"""


import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.test_membership_utilities import MembershipTestUtilities
from verenigingen.tests.utils.base import VereningingenUnitTestCase
from verenigingen.tests.utils.factories import TestDataBuilder


class TestMembershipController(VereningingenUnitTestCase):
    """Test Membership controller methods"""

    @classmethod
    def setUpClass(cls):
        """Set up test environment"""
        super().setUpClass()
        cls.test_env = {}

        # Create test membership types
        membership_types = []

        # Annual membership type
        if not frappe.db.exists("Membership Type", "Test Annual"):
            annual_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Annual",
                    "amount": 100,
                    "currency": "EUR",
                    "payment_interval": "Yearly"}
            )
            annual_type.insert(ignore_permissions=True)
            membership_types.append(annual_type)
        else:
            membership_types.append(frappe.get_doc("Membership Type", "Test Annual"))

        # Quarterly membership type
        if not frappe.db.exists("Membership Type", "Test Quarterly"):
            quarterly_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Quarterly",
                    "amount": 30,
                    "currency": "EUR",
                    "payment_interval": "Quarterly"}
            )
            quarterly_type.insert(ignore_permissions=True)
            membership_types.append(quarterly_type)
        else:
            membership_types.append(frappe.get_doc("Membership Type", "Test Quarterly"))

        # Monthly membership type
        if not frappe.db.exists("Membership Type", "Test Monthly"):
            monthly_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Monthly",
                    "amount": 10,
                    "currency": "EUR",
                    "payment_interval": "Monthly"}
            )
            monthly_type.insert(ignore_permissions=True)
            membership_types.append(monthly_type)
        else:
            membership_types.append(frappe.get_doc("Membership Type", "Test Monthly"))

        # Daily membership type
        if not frappe.db.exists("Membership Type", "Test Daily"):
            daily_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Daily",
                    "amount": 1,
                    "currency": "EUR",
                    "payment_interval": "Daily"}
            )
            daily_type.insert(ignore_permissions=True)
            membership_types.append(daily_type)
        else:
            membership_types.append(frappe.get_doc("Membership Type", "Test Daily"))

        cls.test_env["membership_types"] = membership_types

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        self.builder = TestDataBuilder()

    def tearDown(self):
        """Clean up after each test"""
        self.builder.cleanup()
        super().tearDown()

    def test_validate_dates_method(self):
        """Test the validate_dates method"""
        # Create member and membership type
        test_data = self.builder.with_member().build()
        member = test_data["member"]
        membership_type = self.test_env["membership_types"][0]  # Annual type

        # Test valid dates
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today(),
                "renewal_date": add_days(today(), 365)}
        )

        # Should not raise error
        membership.validate_dates()

        # Test renewal date before start date
        membership.renewal_date = add_days(today(), -1)
        with self.assert_validation_error("Renewal date"):
            membership.validate_dates()

    def test_set_renewal_date_with_minimum_period_enabled(self):
        """Test renewal date calculation with minimum period enforced"""
        # Create membership type with minimum period enabled
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Enforced Annual",
                "amount": 100,
                "currency": "EUR",  # Monthly but enforced to 1 year
                "enforce_minimum_period": 1}
        )
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)

        # Create member and membership
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today()}
        )

        # Set renewal date should enforce minimum 1 year
        membership.set_renewal_date()

        expected_renewal_date = add_months(today(), 12)
        self.assertEqual(getdate(membership.renewal_date), getdate(expected_renewal_date))

    def test_set_renewal_date_with_minimum_period_disabled(self):
        """Test renewal date calculation with minimum period disabled"""
        # Create membership type with minimum period disabled
        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": "Test Monthly No Minimum",
                "amount": 10,
                "currency": "EUR",
                "enforce_minimum_period": 0}
        )
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)

        # Create member and membership
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today()}
        )

        # Set renewal date should follow billing frequency (1 month)
        membership.set_renewal_date()

        expected_renewal_date = add_months(today(), 1)
        self.assertEqual(getdate(membership.renewal_date), getdate(expected_renewal_date))

    def test_set_renewal_date_daily_period(self):
        """Test renewal date calculation for daily period"""
        # Use context manager to temporarily disable minimum period
        membership_type = self.test_env["membership_types"][3]  # Daily type
        with MembershipTestUtilities.with_minimum_period_disabled([membership_type.name]):
            test_data = self.builder.with_member().build()
            member = test_data["member"]

            membership = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member.name,
                    "membership_type": membership_type.name,
                    "start_date": today()}
            )

            # Set renewal date for daily period
            membership.set_renewal_date()

            expected_renewal_date = add_days(today(), 1)
            self.assertEqual(getdate(membership.renewal_date), getdate(expected_renewal_date))

    def test_create_dues_schedule_method(self):
        """Test dues schedule creation from membership"""
        # Create member with membership
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        test_data["member"]
        test_data["membership"]

        # Test dues schedule creation
        # This would test the actual dues schedule creation logic
        # Implementation uses the new dues schedule system

    def test_sync_payment_details_from_dues_schedule(self):
        """Test payment details sync from dues schedule"""
        # Create member with membership and dues schedule
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        test_data["membership"]

        # Test payment sync
        # This would test syncing payment status from dues schedule

    def test_cancel_dues_schedule_method(self):
        """Test dues schedule cancellation"""
        # Create member with active membership
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name, status="Active")
            .build()
        )

        test_data["membership"]

        # Test cancellation
        # This would test the dues schedule cancellation logic

    def test_on_cancel_with_minimum_period(self):
        """Test membership cancellation respects minimum period"""
        # Create membership with minimum period enforced
        membership_type = self.test_env["membership_types"][0]  # Annual with minimum

        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=membership_type.name, start_date=add_days(today(), -30)  # Started 30 days ago
            )
            .build()
        )

        membership = test_data["membership"]

        try:
            membership.submit()  # Submit to enable cancellation

            # Try to cancel before minimum period as non-admin user
            # Create a test user with limited permissions
            test_user = self.create_test_user("test.cancel@example.com", ["Verenigingen Manager"])

            with self.as_user(test_user.name):
                # Try to cancel before minimum period
                with self.assert_validation_error("cannot be cancelled before 1 year"):
                    # Get the membership document as this user
                    user_membership = frappe.get_doc("Membership", membership.name)
                    user_membership.cancel()
        finally:
            # Clean up submitted membership
            frappe.set_user("Administrator")
            # Reload to get current status
            membership.reload()
            if membership.docstatus == 1:
                # Cancel as admin to clean up
                membership.cancel()

    def test_membership_lifecycle_hooks(self):
        """Test membership lifecycle event hooks"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]
        membership_type = self.test_env["membership_types"][0]

        # Test before_insert
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today()}
        )

        # Insert should trigger hooks
        membership.insert()
        self.track_doc("Membership", membership.name)

        # Should have renewal date set
        self.assertIsNotNone(membership.renewal_date)

        # Test on_update
        membership.status = "Suspended"
        membership.save()

        # Member status should be updated
        member.reload()
        # Implementation depends on status sync logic

    def test_get_membership_details(self):
        """Test getting membership details for display"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        membership = test_data["membership"]

        # Test getting formatted details
        details = membership.get_membership_details()

        self.assertIn("type", details)
        self.assertIn("status", details)
        self.assertIn("start_date", details)
        self.assertIn("renewal_date", details)

    def test_renewal_notification_scheduling(self):
        """Test scheduling of renewal notifications"""
        # Create membership near expiry
        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=self.test_env["membership_types"][0].name,
                start_date=add_days(today(), -335),  # Expires in 30 days
                renewal_date=add_days(today(), 30),
            )
            .build()
        )

        test_data["membership"]

        # Test notification scheduling
        # This would test the notification scheduling logic

    def test_payment_status_sync(self):
        """Test payment status synchronization"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        test_data["membership"]

        # Test various payment status scenarios
        payment_statuses = ["Paid", "Overdue", "Failed", "Pending"]

        for status in payment_statuses:
            # This would test payment status sync logic
            pass

    def test_membership_type_change(self):
        """Test changing membership type"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        membership = test_data["membership"]

        # Try to change to different type
        new_type = self.test_env["membership_types"][1]  # Student type
        membership.membership_type = new_type.name

        # This would test the membership type change logic
        # Including pro-rating, fee adjustments, etc.

    def test_concurrent_membership_validation(self):
        """Test validation of concurrent memberships"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Create first active membership
        membership1 = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": self.test_env["membership_types"][0].name,
                "start_date": today(),
                "status": "Active"}
        )
        # Insert first, then submit
        membership1.insert()
        # Track membership before member for proper cleanup order
        self.track_doc("Membership", membership1.name)

        try:
            # Submit to make it active
            membership1.submit()

            # Try to create overlapping membership
            membership2 = frappe.get_doc(
                {
                    "doctype": "Membership",
                    "member": member.name,
                    "membership_type": self.test_env["membership_types"][1].name,
                    "start_date": add_days(today(), 30),
                    "status": "Active"}
            )

            # Validate will set the renewal_date
            membership2.validate()

            # Should raise validation error for overlap
            with self.assert_validation_error("overlaps"):
                membership2.insert()
        finally:
            # Ensure membership is cancelled before cleanup
            if membership1.docstatus == 1:
                membership1.reload()
                if membership1.docstatus == 1:
                    membership1.cancel()

    def test_renew_membership_method(self):
        """Test the renew_membership method"""
        # Create expired membership
        test_data = (
            self.builder.with_member()
            .with_membership(
                membership_type=self.test_env["membership_types"][0].name,
                start_date=add_days(today(), -400),
                renewal_date=add_days(today(), -35),
                status="Expired",
            )
            .build()
        )

        membership = test_data["membership"]

        # Renew membership
        new_membership_name = membership.renew_membership()

        # Verify new membership created
        self.assertIsNotNone(new_membership_name)

        # Get the new membership document
        new_membership = frappe.get_doc("Membership", new_membership_name)
        self.track_doc("Membership", new_membership_name)

        self.assertEqual(new_membership.member, membership.member)
        self.assertEqual(new_membership.membership_type, membership.membership_type)
        self.assertEqual(new_membership.status, "Draft")  # New memberships start as Draft
        # New membership starts from the expired membership's renewal date
        self.assertEqual(getdate(new_membership.start_date), getdate(membership.renewal_date))

    def test_calculate_effective_amount(self):
        """Test membership fee calculation with discounts"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Ensure we have a membership type
        if self.test_env.get("membership_types") and len(self.test_env["membership_types"]) > 0:
            membership_type = self.test_env["membership_types"][0]
        else:
            # Create a test membership type
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership Type",
                    "amount": 100,
                    "currency": "EUR"}
            )
            membership_type.insert(ignore_permissions=True)
            self.track_doc("Membership Type", membership_type.name)

        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "start_date": today()}
        )

        # Test normal amount
        amount = membership.calculate_effective_amount()
        self.assertEqual(amount, membership_type.amount)

        # Test with discount
        membership.discount_percentage = 25
        amount = membership.calculate_effective_amount()
        expected = membership_type.amount * 0.75
        self.assertEqual(amount, expected)

        # Test with fee override on member
        member.dues_rate = 50
        member.save(ignore_permissions=True)
        # Re-set member reference to trigger calculation with override
        membership.member = member.name
        amount = membership.calculate_effective_amount()
        self.assertEqual(amount, 50)

    def test_update_member_status_method(self):
        """Test member status updates from membership changes"""
        test_data = (
            self.builder.with_member(status="Active")
            .with_membership(membership_type=self.test_env["membership_types"][0].name, status="Active")
            .build()
        )

        member = test_data["member"]
        membership = test_data["membership"]

        # Submit the membership first
        membership.submit()

        # Change membership to expired by setting renewal_date to past
        membership.renewal_date = add_days(today(), -1)  # Set to yesterday
        membership.status = "Expired"
        membership.db_set("renewal_date", membership.renewal_date)
        membership.db_set("status", membership.status)

        # Call update_member_status to sync the status
        membership.update_member_status()

        # Member status should reflect membership
        member.reload()
        self.assertEqual(member.membership_status, "Expired")

    def test_get_billing_amount(self):
        """Test billing amount calculation"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][2].name)  # Monthly
            .build()
        )

        membership = test_data["membership"]

        # Test billing amount
        billing_amount = membership.get_billing_amount()
        self.assertGreater(billing_amount, 0)

    def test_validate_membership_type(self):
        """Test membership type validation"""
        test_data = self.builder.with_member().build()
        member = test_data["member"]

        # Test with invalid membership type
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": "Invalid Type",
                "start_date": today()}
        )

        with self.assert_validation_error("Membership Type"):
            membership.validate_membership_type()

    def test_on_submit_hooks(self):
        """Test on_submit lifecycle hooks"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        membership = test_data["membership"]
        member = test_data["member"]

        try:
            # Submit membership
            membership.submit()

            # Check member fields updated
            member.reload()

            # The member fields should be updated by the membership submission
            # Check if membership_status field is set
            if hasattr(member, "membership_status"):
                self.assertEqual(member.membership_status, "Active")

            # Check if current_membership_type field is set
            if hasattr(member, "current_membership_type"):
                self.assertIsNotNone(member.current_membership_type)
        finally:
            # Ensure cleanup by cancelling the submitted document
            if membership.docstatus == 1:
                membership.cancel()
                self.track_doc("Membership", membership.name)

    def test_regenerate_pending_invoices(self):
        """Test regeneration of pending invoices"""
        test_data = (
            self.builder.with_member()
            .with_membership(membership_type=self.test_env["membership_types"][0].name)
            .build()
        )

        test_data["membership"]

        # This would test invoice regeneration logic
        # Implementation depends on ERPNext integration
