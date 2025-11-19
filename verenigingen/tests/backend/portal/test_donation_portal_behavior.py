"""
Tests for donation portal behavior - proper test class version

This tests the specific functions in manage_donations.py that interact with the donation portal:
- cancel_recurring_donation
- update_recurring_donation_amount

Converted from script-style test to proper unittest with Enhanced Test Factory.
"""

import frappe
# unittest.TestCase import removed - using EnhancedTestCase
from frappe.utils import today, now_datetime
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonationPortalBehavior(EnhancedTestCase):
    """Test donation portal behavior using Enhanced Test Factory"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test member and donation using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Portal User", 
            email=f"test-portal-{now_datetime().strftime('%H%M%S')}@example.com",
            birth_date="1990-01-01"
        )
        
        # Create test donation for portal testing
        # Note: Using direct frappe.get_doc as Enhanced Test Factory doesn't have create_donation yet
        self.test_donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": self.test_member.name,
            "donation_type": "Recurring", 
            "recurring_donation_amount": 25.0,
            "status": "Active",
            "payment_method": "Credit Card",
            "donation_date": today(),
            "recurring_start_date": today(),
        })
        
        # Use proper user context for donation creation
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            self.test_donation.insert()
        finally:
            frappe.set_user(current_user)

    def test_cancel_recurring_donation_behavior(self):
        """Test cancel_recurring_donation function behavior"""
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation
        
        # Get initial state
        initial_status = self.test_donation.status
        initial_cancelled_date = self.test_donation.recurring_cancelled_date
        
        self.assertEqual(initial_status, "Active")
        self.assertIsNone(initial_cancelled_date)
        
        # Call the function
        result = cancel_recurring_donation(self.test_donation.name)
        
        # Validate result
        self.assertIsNotNone(result)
        
        # Check post-operation state
        self.test_donation.reload()
        final_status = self.test_donation.status
        final_cancelled_date = self.test_donation.recurring_cancelled_date
        
        # Validate the operation worked
        self.assertEqual(final_status, "Cancelled")
        self.assertIsNotNone(final_cancelled_date)

    def test_update_donation_amount_behavior(self):
        """Test update_recurring_donation_amount function behavior"""
        from verenigingen.templates.pages.manage_donations import update_recurring_donation_amount
        
        # Get initial amount
        initial_amount = self.test_donation.recurring_donation_amount
        self.assertEqual(initial_amount, 25.0)
        
        new_amount = 35.0
        
        # Call the function
        result = update_recurring_donation_amount(self.test_donation.name, new_amount)
        
        # Validate result
        self.assertIsNotNone(result)
        
        # Check post-operation state
        self.test_donation.reload()
        final_amount = self.test_donation.recurring_donation_amount
        
        # Validate the operation worked
        self.assertEqual(final_amount, new_amount)

    def test_portal_behavior_transaction_safety(self):
        """Test that portal functions work without transaction warnings"""
        from verenigingen.templates.pages.manage_donations import (
            cancel_recurring_donation, 
            update_recurring_donation_amount
        )
        
        # Create a second donation for testing update
        test_donation_2 = frappe.get_doc({
            "doctype": "Donation", 
            "donor": self.test_member.name,
            "donation_type": "Recurring",
            "recurring_donation_amount": 30.0,
            "status": "Active",
            "payment_method": "Credit Card",
            "donation_date": today(),
            "recurring_start_date": today(),
        })
        
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            test_donation_2.insert()
        finally:
            frappe.set_user(current_user)
        
        # Test both functions work properly
        cancel_result = cancel_recurring_donation(self.test_donation.name)
        update_result = update_recurring_donation_amount(test_donation_2.name, 40.0)
        
        # Both should succeed
        self.assertIsNotNone(cancel_result)
        self.assertIsNotNone(update_result)
        
        # Verify final states
        self.test_donation.reload()
        test_donation_2.reload()
        
        self.assertEqual(self.test_donation.status, "Cancelled")
        self.assertEqual(test_donation_2.recurring_donation_amount, 40.0)