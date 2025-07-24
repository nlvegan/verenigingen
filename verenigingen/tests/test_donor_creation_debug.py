"""
Debug test for donor creation
"""

import frappe
from frappe.utils import flt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorCreationDebug(VereningingenTestCase):
    """Debug donor creation issues"""
    
    def test_create_donor_directly(self):
        """Test creating a donor directly to see what fails"""
        # Create simple customer
        customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name") or "Donors"
        
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Debug Test Customer"
        customer.customer_group = customer_group
        customer.territory = "All Territories"
        customer.email_id = "debug.test@example.com"
        customer.insert()
        
        self.track_doc("Customer", customer.name)
        
        # Try to create donor manually with all required fields
        try:
            donor = frappe.new_doc("Donor")
            donor.donor_name = customer.customer_name
            donor.donor_type = "Individual"
            donor.donor_email = customer.email_id
            donor.customer = customer.name
            donor.creation_trigger_amount = 100.0
            donor.created_from_payment = "TEST-PAYMENT-001"
            donor.customer_sync_status = "Auto-Created"
            donor.last_customer_sync = frappe.utils.now()
            
            print(f"About to insert donor with fields: {donor.as_dict()}")
            donor.insert()
            
            print(f"Successfully created donor: {donor.name}")
            self.track_doc("Donor", donor.name)
            
            # Verify creation
            self.assertTrue(frappe.db.exists("Donor", donor.name))
            
        except Exception as e:
            print(f"Direct donor creation failed: {str(e)}")
            import traceback
            traceback.print_exc()
            self.fail(f"Direct donor creation failed: {str(e)}")
    
    def test_create_customer_group(self):
        """Test creating Donors customer group if it doesn't exist"""
        if not frappe.db.exists("Customer Group", "Donors"):
            donor_group = frappe.new_doc("Customer Group")
            donor_group.customer_group_name = "Donors"
            donor_group.parent_customer_group = "All Customer Groups"
            donor_group.is_group = 0
            donor_group.insert()
            self.track_doc("Customer Group", donor_group.name)
            print(f"Created Donors customer group: {donor_group.name}")
        else:
            print("Donors customer group already exists")
    
    def test_auto_creation_function_with_debug(self):
        """Test the auto-creation function with debugging"""
        # Ensure customer group exists
        self.test_create_customer_group()
        
        # Create customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Auto Debug Customer"
        customer.customer_group = "Donors"
        customer.territory = "All Territories" 
        customer.email_id = "auto.debug@example.com"
        customer.insert()
        
        self.track_doc("Customer", customer.name)
        
        # Try auto-creation function
        from verenigingen.utils.donor_auto_creation import create_donor_from_customer
        
        print(f"Calling create_donor_from_customer with customer: {customer.name}")
        result = create_donor_from_customer(customer, 100.0, "TEST-PAYMENT-DEBUG")
        
        print(f"Auto-creation result: {result}")
        
        if result:
            self.track_doc("Donor", result)
            self.assertTrue(frappe.db.exists("Donor", result))
        else:
            # Check recent error logs
            recent_errors = frappe.db.get_all(
                "Error Log",
                filters={"creation": [">", frappe.utils.add_days(frappe.utils.now(), -1)]},
                fields=["name", "error", "creation"],
                order_by="creation desc",
                limit=5
            )
            
            print("Recent error logs:")
            for error in recent_errors:
                print(f"  - {error.creation}: {error.error[:200]}...")
            
            self.fail("Auto-creation returned None, check error logs above")