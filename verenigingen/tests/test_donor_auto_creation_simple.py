"""
Simplified tests for automatic donor creation
"""

import frappe
from frappe.utils import flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorAutoCreationSimple(VereningingenTestCase):
    """Test automatic donor creation with existing accounts"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Store original settings
        self.settings = frappe.get_single("Verenigingen Settings")
        self.original_auto_create = self.settings.auto_create_donors
        self.original_donations_account = self.settings.donations_gl_account
        self.original_customer_groups = self.settings.donor_customer_groups
        self.original_minimum_amount = self.settings.minimum_donation_amount
        
        # Find an existing income account
        self.donations_account = frappe.db.get_value(
            "Account", 
            {"account_type": "Income", "is_group": 0}, 
            "name"
        )
        
        # Enable auto-creation with minimal config
        if self.donations_account:
            self.settings.auto_create_donors = 1
            self.settings.donations_gl_account = self.donations_account
            self.settings.donor_customer_groups = ""  # Allow all
            self.settings.minimum_donation_amount = 0  # No minimum
            self.settings.save()
        
    def tearDown(self):
        """Restore original settings"""
        self.settings.auto_create_donors = self.original_auto_create
        self.settings.donations_gl_account = self.original_donations_account
        self.settings.donor_customer_groups = self.original_customer_groups
        self.settings.minimum_donation_amount = self.original_minimum_amount
        self.settings.save()
        
        super().tearDown()
        
    def test_auto_creation_settings_api(self):
        """Test the settings API without complex account setup"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_settings
        
        # Skip if no income account available
        if not self.donations_account:
            self.skipTest("No income account available for testing")
            
        settings = get_auto_creation_settings()
        
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['donations_gl_account'], self.donations_account)
        self.assertEqual(settings['eligible_customer_groups'], "")
        self.assertEqual(settings['minimum_amount'], 0)
        
    def test_auto_creation_stats_api(self):
        """Test the stats API"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_stats
        
        stats = get_auto_creation_stats()
        
        # Should return valid stats structure
        self.assertIsInstance(stats['auto_created_count'], int)
        self.assertIsInstance(stats['total_trigger_amount'], (int, float))
        self.assertIsInstance(stats['recent_creations'], list)
        
    def test_conditions_api_with_nonexistent_customer(self):
        """Test conditions API with nonexistent customer"""
        from verenigingen.utils.donor_auto_creation import test_auto_creation_conditions
        
        # Skip if no income account available
        if not self.donations_account:
            self.skipTest("No income account available for testing")
        
        result = test_auto_creation_conditions("NONEXISTENT-CUSTOMER", 100.0)
        
        self.assertFalse(result['would_create'])
        self.assertFalse(result['conditions']['customer_exists'])
        self.assertEqual(result['conditions']['failure_reason'], "Customer NONEXISTENT-CUSTOMER does not exist")
        
    def test_customer_group_eligibility_function(self):
        """Test customer group eligibility check"""
        from verenigingen.utils.donor_auto_creation import is_customer_group_eligible
        
        # Test with empty groups (should allow all)
        self.settings.donor_customer_groups = ""
        self.settings.save()
        
        result = is_customer_group_eligible("Any Group", self.settings)
        self.assertTrue(result)
        
        # Test with specific groups
        self.settings.donor_customer_groups = "Donors,General"
        self.settings.save()
        
        result_allowed = is_customer_group_eligible("Donors", self.settings) 
        self.assertTrue(result_allowed)
        
        result_denied = is_customer_group_eligible("Corporate", self.settings)
        self.assertFalse(result_denied)
        
    def test_existing_donor_check_function(self):
        """Test existing donor check function"""
        from verenigingen.utils.donor_auto_creation import has_existing_donor
        
        # Create test customer and donor
        customer = self.create_test_customer("Test Customer", "General")
        donor = self.create_test_donor("Test Donor", customer=customer.name)
        
        # Should detect existing donor
        result = has_existing_donor(customer.name)
        self.assertTrue(result)
        
        # Test with non-existent customer
        result_none = has_existing_donor("NONEXISTENT-CUSTOMER")
        self.assertFalse(result_none)
        
    def test_auto_creation_disabled_handling(self):
        """Test behavior when auto-creation is disabled"""
        from verenigingen.utils.donor_auto_creation import process_payment_for_donor_creation
        
        # Disable auto-creation
        self.settings.auto_create_donors = 0
        self.settings.save()
        
        # Create mock payment entry (won't actually process without proper setup)
        mock_payment = frappe._dict({
            'doctype': 'Payment Entry',
            'name': 'TEST-PE-001',
            'payment_type': 'Receive'
        })
        
        # Should return early and not raise errors
        try:
            process_payment_for_donor_creation(mock_payment)
            # If we get here, function returned early as expected
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"Function should return early when disabled, but raised: {e}")
            
    # Helper methods
    def create_test_customer(self, customer_name, customer_group):
        """Create a simple test customer"""
        # Get an existing customer group
        existing_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        if not existing_group:
            existing_group = "All Customer Groups"
            
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_group = existing_group
        customer.territory = "All Territories"
        customer.insert()
        
        self.track_doc("Customer", customer.name)
        return customer
        
    def create_test_donor(self, donor_name, customer=None):
        """Create a simple test donor"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_type = "Individual"
        donor.donor_email = f"{donor_name.lower().replace(' ', '.')}@example.com"
        if customer:
            donor.customer = customer
        donor.insert()
        
        self.track_doc("Donor", donor.name)
        return donor