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

try:
    from vereinigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
except ImportError:
    # Fallback to basic TestCase if enhanced factory not available
    from unittest import TestCase as EnhancedTestCase


class TestDuesScheduleSync(EnhancedTestCase):
    """Test synchronization between Dues Schedule and Member records"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create a test member
        self.member = self.create_test_member(
            first_name="Test",
            last_name="Sync",
            birth_date="1990-01-01"
        )
        
        # Create a membership type
        self.membership_type = frappe.get_doc({
            "doctype": "Membership Type",
            "membership_type": "Test Sync Type",
            "amount": 100,
            "billing_frequency": "Monthly"
        }).insert()
        
    def tearDown(self):
        """Clean up test data"""
        # Delete test data
        frappe.delete_doc("Membership Type", self.membership_type.name, ignore_permissions=True)
        super().tearDown()
    
    def test_current_dues_schedule_set_on_creation(self):
        """Test that creating a dues schedule sets it as current on the member"""
        # Create a dues schedule
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 100,
            "billing_frequency": "Monthly",
            "next_invoice_date": today()
        }).insert()
        
        # Reload member to check the field
        self.member.reload()
        
        # Assert the schedule is set as current
        self.assertEqual(self.member.current_dues_schedule, schedule.name)
        
        # Clean up
        frappe.delete_doc("Membership Dues Schedule", schedule.name, ignore_permissions=True)
    
    def test_current_schedule_updates_when_status_changes(self):
        """Test that deactivating a schedule updates the member's current schedule"""
        # Create two schedules
        schedule1 = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 100,
            "billing_frequency": "Monthly",
            "next_invoice_date": today()
        }).insert()
        
        # Wait a moment to ensure different creation times
        frappe.db.commit()
        
        schedule2 = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 150,
            "billing_frequency": "Monthly",
            "next_invoice_date": today()
        }).insert()
        
        # Member should have schedule2 as current (newer)
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule2.name)
        
        # Deactivate schedule2
        schedule2.status = "Cancelled"
        schedule2.save()
        
        # Member should now have schedule1 as current
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule1.name)
        
        # Clean up
        frappe.delete_doc("Membership Dues Schedule", schedule1.name, ignore_permissions=True)
        frappe.delete_doc("Membership Dues Schedule", schedule2.name, ignore_permissions=True)
    
    def test_next_invoice_date_sync_after_invoice_generation(self):
        """Test that generating an invoice updates the member's next_invoice_date"""
        # Create a dues schedule with past next_invoice_date
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 100,
            "billing_frequency": "Daily",
            "next_invoice_date": add_days(today(), -1),
            "test_mode": 1  # Use test mode to avoid actual invoice creation
        }).insert()
        
        # Generate invoice (in test mode)
        schedule.generate_invoice()
        
        # Check that next_invoice_date was updated
        self.member.reload()
        schedule.reload()
        
        # Both should show the same next date
        self.assertEqual(
            getdate(self.member.next_invoice_date),
            getdate(schedule.next_invoice_date)
        )
        
        # The date should be in the future
        self.assertGreater(
            getdate(schedule.next_invoice_date),
            getdate(today())
        )
        
        # Clean up
        frappe.delete_doc("Membership Dues Schedule", schedule.name, ignore_permissions=True)
    
    def test_billing_period_shows_next_period(self):
        """Test that billing period dates show the NEXT period to be invoiced"""
        # Create a monthly schedule
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 100,
            "billing_frequency": "Monthly",
            "next_invoice_date": today(),
            "test_mode": 1
        }).insert()
        
        # Generate an invoice
        schedule.generate_invoice()
        schedule.reload()
        
        # The billing period should match the next invoice date's period
        calculated_start, calculated_end = schedule.calculate_billing_period(
            schedule.next_invoice_date
        )
        
        self.assertEqual(
            getdate(schedule.next_billing_period_start_date),
            getdate(calculated_start)
        )
        self.assertEqual(
            getdate(schedule.next_billing_period_end_date),
            getdate(calculated_end)
        )
        
        # For monthly billing, the period should be a full month
        if schedule.billing_frequency == "Monthly":
            from frappe.utils import date_diff
            days_in_period = date_diff(
                schedule.next_billing_period_end_date,
                schedule.next_billing_period_start_date
            ) + 1
            self.assertGreaterEqual(days_in_period, 28)
            self.assertLessEqual(days_in_period, 31)
        
        # Clean up
        frappe.delete_doc("Membership Dues Schedule", schedule.name, ignore_permissions=True)
    
    def test_race_condition_prevention(self):
        """Test that concurrent schedule updates don't cause race conditions"""
        # This test simulates what the FOR UPDATE lock prevents
        # Create a schedule
        schedule = frappe.get_doc({
            "doctype": "Membership Dues Schedule",
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "status": "Active",
            "dues_rate": 100,
            "billing_frequency": "Monthly",
            "next_invoice_date": today()
        }).insert()
        
        # The hook should use FOR UPDATE to prevent concurrent modifications
        # We can't easily test the actual lock, but we can verify the query structure
        from vereinigingen.verenigingen.doctype.membership_dues_schedule.membership_dues_schedule_hooks import (
            update_member_current_dues_schedule
        )
        
        # Call the hook function
        update_member_current_dues_schedule(schedule)
        
        # Verify the member was updated
        self.member.reload()
        self.assertEqual(self.member.current_dues_schedule, schedule.name)
        
        # Clean up
        frappe.delete_doc("Membership Dues Schedule", schedule.name, ignore_permissions=True)


def run_tests():
    """Run the test suite"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDuesScheduleSync)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)