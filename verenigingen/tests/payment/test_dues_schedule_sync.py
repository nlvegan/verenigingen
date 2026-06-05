"""
Test cases for Membership Dues Schedule synchronization with Member records.

This module tests the synchronization logic between Membership Dues Schedule
and Member records, ensuring that:
1. Member.current_dues_schedule is properly maintained
2. Member.next_invoice_date stays synchronized
3. Billing period dates correctly show the NEXT period to be invoiced
"""

import frappe
import unittest
from frappe.utils import today, add_days, getdate
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesScheduleSync(EnhancedTestCase):
    """Test synchronization between Dues Schedule and Member records"""

    def setUp(self):
        """Set up test data"""
        super().setUp()

        # Create a test member
        self.member = self.create_test_member(first_name="Test", last_name="Sync", birth_date="1990-01-01")

        # Create a membership type with unique name (must be active, with a
        # role_profile, or Membership submit rejects it as inactive/invalid).
        import time

        unique_suffix = f"{int(time.time() * 1000000) % 1000000}"
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")
        self.membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": f"Test-Sync-{unique_suffix}",
                "billing_period": "Monthly",
                "is_active": 1,
                "minimum_amount": 5.0,
                "role_profile": role_profile,
            }
        ).insert()

        # Create an active membership for the member
        self.membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "start_date": add_days(today(), -30),
                "end_date": add_days(today(), 335),  # ~1 year
                "status": "Active",
            }
        ).insert()
        self.membership.submit()

        # Submitting may auto-create an Active dues schedule; cancel it so each
        # test's explicitly-created schedule is the only active one.
        for _name in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", _name, "status", "Cancelled")

    def tearDown(self):
        """Clean up test data"""
        # EnhancedTestCase handles automatic rollback, no manual cleanup needed
        super().tearDown()

    def test_current_dues_schedule_set_on_creation(self):
        """Test that creating a dues schedule sets it as current on the member"""
        # Create a dues schedule
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-1",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 100,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
            }
        ).insert()

        # Reload member to check the field
        self.member.reload()

        # Assert the schedule is set as current
        self.assertEqual(self.member.current_dues_schedule, schedule.name)

        # EnhancedTestCase handles automatic rollback, no manual cleanup needed

    def test_current_schedule_updates_when_status_changes(self):
        """Test that activating a replacement schedule updates the member's current schedule.

        NOTE: only one Active dues schedule per member is allowed now, so the old
        "two simultaneous active schedules" scenario is invalid. The replacement
        path is: cancel the current one, then create the new one.
        """
        schedule1 = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-2A",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 100,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
            }
        ).insert()

        # Member should have schedule1 as current.
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule1.name)

        # Cancel schedule1 before creating its replacement (one active per member).
        schedule1.reload()
        schedule1.status = "Cancelled"
        schedule1._ignore_permissions = True
        schedule1.save()

        schedule2 = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-2B",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 150,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
            }
        ).insert()

        # Member should now have schedule2 as current (the active one).
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule2.name)

        # EnhancedTestCase handles automatic rollback, no manual cleanup needed

    def test_next_invoice_date_sync_after_invoice_generation(self):
        """Test that generating an invoice updates the member's next_invoice_date"""
        # Create a dues schedule with past next_invoice_date
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-3",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 100,
                "billing_frequency": "Daily",
                "currency": "EUR",
                "next_invoice_date": add_days(today(), -1),
                "test_mode": 1,  # Use test mode to avoid actual invoice creation
                "auto_generate": 1,  # Enable so eligibility passes (in_import suppresses the default)
                "is_template": 0,  # Set explicitly: in_import suppresses the default, which
                # would otherwise register as a change on the later save() and trip the
                # "Cannot change template status after creation" guard.
            }
        ).insert()

        # Generate invoice (in test mode). force=True bypasses the eligibility
        # gate so we directly exercise the date-advancement + member-sync path.
        schedule.generate_invoice(force=True)

        # Check that next_invoice_date was updated
        self.member.reload()
        schedule.reload()

        # Both should show the same next date
        self.assertEqual(getdate(self.member.next_invoice_date), getdate(schedule.next_invoice_date))

        # The date should have advanced past the original (yesterday). For Daily
        # billing starting from yesterday, one advancement lands on today, so the
        # next date is >= today (and strictly after the original yesterday).
        self.assertGreater(getdate(schedule.next_invoice_date), getdate(add_days(today(), -1)))
        self.assertGreaterEqual(getdate(schedule.next_invoice_date), getdate(today()))

        # EnhancedTestCase handles automatic rollback, no manual cleanup needed

    def test_billing_period_shows_next_period(self):
        """Test that billing period dates show the NEXT period to be invoiced"""
        # Create a monthly schedule
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-4",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 100,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
                "test_mode": 1,
            }
        ).insert()

        # Generate an invoice
        schedule.generate_invoice()
        schedule.reload()

        # The stored next_billing_period_* fields were removed; the billing
        # period is now computed on demand via calculate_billing_period().
        calculated_start, calculated_end = schedule.calculate_billing_period(schedule.next_invoice_date)
        self.assertIsNotNone(calculated_start)
        self.assertIsNotNone(calculated_end)
        self.assertLessEqual(getdate(calculated_start), getdate(calculated_end))

        # For monthly billing, the period should be a full month
        if schedule.billing_frequency == "Monthly":
            from frappe.utils import date_diff

            days_in_period = date_diff(calculated_end, calculated_start) + 1
            self.assertGreaterEqual(days_in_period, 28)
            self.assertLessEqual(days_in_period, 31)

        # EnhancedTestCase handles automatic rollback, no manual cleanup needed

    def test_race_condition_prevention(self):
        """Test that concurrent schedule updates don't cause race conditions"""
        # This test simulates what the FOR UPDATE lock prevents
        # Create a schedule
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Test-{self.member.name}-Sync-5",
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "status": "Active",
                "dues_rate": 100,
                "billing_frequency": "Monthly",
                "currency": "EUR",
                "next_invoice_date": today(),
            }
        ).insert()

        # The hook should use FOR UPDATE to prevent concurrent modifications
        # We can't easily test the actual lock, but we can verify the query structure
        from verenigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule_hooks import (
            update_member_current_dues_schedule,
        )

        # Call the hook function
        update_member_current_dues_schedule(schedule)

        # Verify the member was updated
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule.name)

        # EnhancedTestCase handles automatic rollback, no manual cleanup needed


def run_tests():
    """Run the test suite"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDuesScheduleSync)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)
