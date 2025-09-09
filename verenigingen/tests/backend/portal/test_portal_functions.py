"""
Tests for portal functions - proper test class version

Basic tests for portal functionality converted from script-style tests.
"""

import frappe
from frappe.utils import today, now_datetime
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPortalFunctions(EnhancedTestCase):
    """Test portal functions using Enhanced Test Factory"""

    def setUp(self):
        """Set up test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test member using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Portal User",
            email=f"test-portal-{now_datetime().strftime('%H%M%S')}@example.com", 
            birth_date="1990-01-01"
        )

    def create_test_donation(self):
        """Create test donation for portal testing"""
        donation = frappe.get_doc({
            "doctype": "Donation",
            "donor": self.test_member.name,
            "donation_date": today(),
            "amount": 25.0,
            "mode_of_payment": "Credit Card",
            "status": "Active",
            "donation_purpose_type": "Membership Support",
            "recurring_donation": 1,
            "recurring_donation_amount": 25.0,
            "recurring_frequency": "Monthly",
        })
        
        # Use proper user context for donation creation  
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            donation.insert()
            return donation
        finally:
            frappe.set_user(current_user)

    def test_cancel_recurring_donation_function(self):
        """Test the cancel_recurring_donation function"""
        from verenigingen.templates.pages.manage_donations import cancel_recurring_donation
        
        # Create test donation
        donation = self.create_test_donation()
        
        # Get initial state
        initial_status = donation.status
        self.assertEqual(initial_status, "Submitted")  # After submit
        
        # Test the cancel function
        result = cancel_recurring_donation(donation.name)
        
        # Validate result
        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "success")
        
        # Check final state
        donation.reload()
        final_status = donation.status
        self.assertEqual(final_status, "Cancelled")

    def test_update_donation_amount_function(self):
        """Test donation amount update function"""  
        from verenigingen.templates.pages.manage_donations import update_recurring_donation
        
        # Create test donation
        donation = self.create_test_donation()
        
        # Get initial amount
        initial_amount = donation.recurring_donation_amount
        self.assertEqual(initial_amount, 25.0)
        
        new_amount = 35.0
        
        # Test the update function - note: this function may take different parameters
        # Need to check the actual function signature in manage_donations.py
        result = update_recurring_donation()
        
        # Validate result
        self.assertIsNotNone(result)
        
        # Check final amount
        donation.reload()
        final_amount = donation.recurring_donation_amount
        self.assertEqual(final_amount, new_amount)