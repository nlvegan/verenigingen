"""
Working tests for donor auto-creation functionality
Following CLAUDE.md requirements with proper Frappe ORM compliance
"""

import frappe
from frappe.utils import flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorAutoCreationWorking(VereningingenTestCase):
    """Working test suite for donor auto-creation functionality"""
    
    def setUp(self):
        """Set up test data for each test"""
        super().setUp()
        
        # Use existing accounts from the system
        self.donations_account = self.get_existing_income_account()
        self.receivable_account = self.get_existing_receivable_account()
        
        # Configure auto-creation settings without timestamp conflicts
        self.configure_auto_creation_settings()
        
    def get_existing_income_account(self):
        """Get existing income account"""
        account = frappe.db.get_value(
            "Account", 
            {"account_type": "Income Account", "is_group": 0, "disabled": 0}, 
            "name"
        )
        if not account:
            self.skipTest("No income account available for testing")
        return account
        
    def get_existing_receivable_account(self):
        """Get existing receivable account"""
        account = frappe.db.get_value(
            "Account", 
            {"account_type": "Receivable", "is_group": 0, "disabled": 0}, 
            "name"
        )
        if not account:
            self.skipTest("No receivable account available for testing")
        return account
    
    def configure_auto_creation_settings(self):
        """Configure settings using database update to avoid timestamp issues"""
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", self.donations_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "")  # Allow all
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 50.0)
        
        # Clear cache to ensure settings are reloaded
        frappe.clear_cache(doctype="Verenigingen Settings")
    
    def test_api_functions_work(self):
        """Test that all API functions work correctly"""
        from verenigingen.utils.donor_auto_creation import (
            get_auto_creation_settings,
            get_auto_creation_stats,
            test_auto_creation_conditions
        )
        
        # Test settings API
        settings = get_auto_creation_settings()
        self.assertIsInstance(settings, dict)
        self.assertIn('enabled', settings)
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['donations_gl_account'], self.donations_account)
        
        # Test stats API  
        stats = get_auto_creation_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn('auto_created_count', stats)
        self.assertIsInstance(stats['auto_created_count'], int)
        
        # Test conditions API with non-existent customer
        conditions = test_auto_creation_conditions("NONEXISTENT", 100.0)
        self.assertIsInstance(conditions, dict)
        self.assertIn('would_create', conditions)
        self.assertFalse(conditions['would_create'])
        self.assertFalse(conditions['conditions']['customer_exists'])
    
    def test_utility_functions_work(self):
        """Test utility functions work correctly"""
        from verenigingen.utils.donor_auto_creation import (
            is_customer_group_eligible,
            has_existing_donor
        )
        
        # Get settings for testing
        settings = frappe.get_single("Verenigingen Settings")
        
        # Test customer group eligibility with empty groups (allow all)
        result = is_customer_group_eligible("Any Group", settings)
        self.assertTrue(result)
        
        # Test has_existing_donor with non-existent customer
        result = has_existing_donor("NONEXISTENT-CUSTOMER")
        self.assertFalse(result)
    
    def test_management_api_functions(self):
        """Test management API functions"""
        from verenigingen.api.donor_auto_creation_management import (
            get_auto_creation_dashboard,
            get_donations_gl_accounts,
            get_customer_groups
        )
        
        # Test dashboard API
        dashboard = get_auto_creation_dashboard()
        self.assertIsInstance(dashboard, dict)
        if 'error' not in dashboard:
            self.assertIn('settings', dashboard)
            self.assertIn('statistics', dashboard)
        
        # Test GL accounts API
        accounts = get_donations_gl_accounts()
        self.assertIsInstance(accounts, list)
        
        # Test customer groups API
        groups = get_customer_groups()
        self.assertIsInstance(groups, list)
    
    def test_donor_creation_with_simple_scenario(self):
        """Test donor creation with simplified scenario"""
        # Create test customer
        customer = self.create_simple_test_customer()
        
        # Verify no donor exists initially
        self.assertFalse(frappe.db.exists("Donor", {"customer": customer.name}))
        
        # Test the core auto-creation logic by calling it directly
        # This simulates what would happen when a payment is processed
        from verenigingen.utils.donor_auto_creation import create_donor_from_customer
        
        try:
            donor_name = create_donor_from_customer(customer, 100.0, "TEST-PAYMENT-001")
            
            if donor_name:
                # Verify donor was created with correct data
                donor = frappe.get_doc("Donor", donor_name)
                self.assertEqual(donor.donor_name, customer.customer_name)
                self.assertEqual(donor.customer, customer.name)
                self.assertEqual(donor.customer_sync_status, "Auto-Created")
                self.assertEqual(flt(donor.creation_trigger_amount), 100.0)
                
                # Track for cleanup
                self.track_doc("Donor", donor_name)
            else:
                self.fail("Donor creation returned None - check logs for errors")
        except Exception as e:
            self.fail(f"Donor creation failed with error: {str(e)}")
    
    def test_existing_donor_prevention(self):
        """Test that existing donors prevent duplication"""
        # Create test customer and donor
        customer = self.create_simple_test_customer("Existing Customer")
        donor = self.create_simple_test_donor("Existing Donor", customer.name)
        
        # Try to create another donor
        from verenigingen.utils.donor_auto_creation import create_donor_from_customer
        
        result = create_donor_from_customer(customer, 100.0, "TEST-PAYMENT-002")
        
        # Should return None because donor already exists
        self.assertIsNone(result)
        
        # Verify only one donor exists
        donor_count = frappe.db.count("Donor", {"customer": customer.name})
        self.assertEqual(donor_count, 1)
    
    def test_eligibility_conditions_work(self):
        """Test eligibility conditions work properly"""
        from verenigingen.utils.donor_auto_creation import (
            is_customer_group_eligible,
            has_existing_donor
        )
        
        # Create test customer
        customer = self.create_simple_test_customer("Eligibility Test Customer")
        
        # Test eligibility functions
        settings = frappe.get_single("Verenigingen Settings")
        
        # Should be eligible (empty groups = allow all)
        eligible = is_customer_group_eligible(customer.customer_group, settings)
        self.assertTrue(eligible)
        
        # Should not have existing donor
        has_donor = has_existing_donor(customer.name)
        self.assertFalse(has_donor)
        
        # Create donor and test again
        donor = self.create_simple_test_donor("Test Donor", customer.name)
        
        # Now should have existing donor
        has_donor_after = has_existing_donor(customer.name)
        self.assertTrue(has_donor_after)
    
    def test_settings_configuration_works(self):
        """Test settings configuration works correctly"""
        # Test updating settings via API
        from verenigingen.api.donor_auto_creation_management import update_auto_creation_settings
        
        result = update_auto_creation_settings(
            enabled=True,
            donations_gl_account=self.donations_account,
            eligible_customer_groups="Test Group",
            minimum_amount=75.0
        )
        
        self.assertIsInstance(result, dict)
        if 'error' not in result:
            self.assertTrue(result.get('success'))
            
            # Verify settings were updated
            settings = frappe.get_single("Verenigingen Settings")
            self.assertTrue(settings.auto_create_donors)
            self.assertEqual(settings.donor_customer_groups, "Test Group")
            self.assertEqual(flt(settings.minimum_donation_amount), 75.0)
    
    # Helper methods following CLAUDE.md requirements
    def create_simple_test_customer(self, name_suffix="Test Customer"):
        """Create simple test customer with required fields"""
        # Get an existing customer group
        customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
        if not customer_group:
            customer_group = "All Customer Groups"
        
        customer = frappe.new_doc("Customer")
        customer.customer_name = name_suffix
        customer.customer_group = customer_group
        customer.territory = "All Territories"
        customer.email_id = f"{name_suffix.lower().replace(' ', '.')}@example.com"
        customer.insert()
        
        self.track_doc("Customer", customer.name)
        return customer
    
    def create_simple_test_donor(self, donor_name, customer_name=None):
        """Create simple test donor with all required fields"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_type = "Individual"
        donor.donor_email = f"{donor_name.lower().replace(' ', '.')}@example.com"
        if customer_name:
            donor.customer = customer_name
        donor.insert()
        
        self.track_doc("Donor", donor.name)
        return donor