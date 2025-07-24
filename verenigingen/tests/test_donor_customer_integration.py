"""
Comprehensive tests for Donor-Customer integration

This test suite validates the bi-directional synchronization between
Donor and Customer records, following CLAUDE.md testing requirements.
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorCustomerIntegration(VereningingenTestCase):
    """Test suite for Donor-Customer integration functionality"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Ensure Donors customer group exists for tests
        if not frappe.db.exists("Customer Group", "Donors"):
            donor_group = frappe.new_doc("Customer Group")
            donor_group.customer_group_name = "Donors"
            donor_group.parent_customer_group = "All Customer Groups"
            donor_group.is_group = 0
            donor_group.flags.ignore_permissions = True
            donor_group.insert()
            self.track_doc("Customer Group", donor_group.name)

    def test_donor_creation_creates_customer(self):
        """Test that creating a donor automatically creates a customer"""
        # Create donor with all required fields from JSON
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Test Donor Individual"
        donor.donor_type = "Individual"  # From JSON options
        donor.donor_email = "testdonor@example.com"  # Required field
        donor.phone = "+31612345678"
        
        # Save donor - should automatically create customer
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify customer was created
        self.assertTrue(donor.customer, "Customer should be automatically created")
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertIsNotNone(donor.last_customer_sync)
        
        # Verify customer details
        customer = frappe.get_doc("Customer", donor.customer)
        self.track_doc("Customer", customer.name)
        
        self.assertEqual(customer.customer_name, donor.donor_name)
        self.assertEqual(customer.customer_type, "Individual")
        self.assertEqual(customer.email_id, donor.donor_email)
        self.assertEqual(customer.mobile_no, donor.phone)
        self.assertEqual(customer.customer_group, "Donors")
        self.assertEqual(customer.custom_donor_reference, donor.name)

    def test_organization_donor_creates_company_customer(self):
        """Test that organization donors create company-type customers"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Test Organization Corp"
        donor.donor_type = "Organization"  # From JSON options
        donor.donor_email = "org@example.com"
        donor.contact_person = "John Manager"
        
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify customer type is Company for organizations
        customer = frappe.get_doc("Customer", donor.customer)
        self.track_doc("Customer", customer.name)
        
        self.assertEqual(customer.customer_type, "Company")
        self.assertEqual(customer.customer_name, donor.donor_name)

    def test_donor_update_syncs_to_customer(self):
        """Test that updating donor syncs changes to customer"""
        # Create initial donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Original Name"
        donor.donor_type = "Individual"
        donor.donor_email = "original@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        
        original_customer = donor.customer
        self.track_doc("Customer", original_customer)
        
        # Update donor information
        donor.donor_name = "Updated Name"
        donor.donor_email = "updated@example.com"
        donor.phone = "+31687654321"
        donor.save()
        
        # Verify customer was updated
        customer = frappe.get_doc("Customer", original_customer)
        self.assertEqual(customer.customer_name, "Updated Name")
        self.assertEqual(customer.email_id, "updated@example.com")
        self.assertEqual(customer.mobile_no, "+31687654321")

    def test_customer_update_syncs_to_donor(self):
        """Test that updating customer syncs changes back to donor"""
        # Create donor with customer
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Test Sync Back"
        donor.donor_type = "Individual"
        donor.donor_email = "syncback@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        
        customer_name = donor.customer
        self.track_doc("Customer", customer_name)
        
        # Update customer directly
        customer = frappe.get_doc("Customer", customer_name)
        customer.customer_name = "Customer Updated Name"
        customer.email_id = "customerupdated@example.com"
        customer.mobile_no = "+31600000000"
        customer.save()
        
        # Reload donor and verify sync
        donor.reload()
        self.assertEqual(donor.donor_name, "Customer Updated Name")
        self.assertEqual(donor.donor_email, "customerupdated@example.com")
        self.assertEqual(donor.phone, "+31600000000")

    def test_existing_customer_linking_by_email(self):
        """Test that existing customers are linked by email instead of creating duplicates"""
        # Create customer first
        customer = frappe.new_doc("Customer")
        customer.customer_name = "Existing Customer"
        customer.customer_type = "Individual"
        customer.email_id = "existing@example.com"
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.save()
        self.track_doc("Customer", customer.name)
        
        # Create donor with same email
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Existing Customer"
        donor.donor_type = "Individual"
        donor.donor_email = "existing@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify existing customer was linked, not new one created
        self.assertEqual(donor.customer, customer.name)
        
        # Verify donor reference was added to customer
        customer.reload()
        self.assertEqual(customer.custom_donor_reference, donor.name)

    def test_donor_without_customer_sync_disabled(self):
        """Test that donor sync can be disabled via flags"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = "No Sync Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "nosync@example.com"
        
        # Disable customer sync
        donor.flags.ignore_customer_sync = True
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify no customer was created
        self.assertFalse(donor.customer)
        self.assertFalse(donor.customer_sync_status)

    def test_sync_status_error_handling(self):
        """Test that sync errors are properly handled and logged"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Error Test Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "errortest@example.com"
        
        # Mock a scenario where customer creation fails
        # We'll patch the ensure_donor_customer_group method to raise an exception
        original_method = donor.ensure_donor_customer_group
        
        def failing_method():
            raise Exception("Simulated customer group creation failure")
        
        donor.ensure_donor_customer_group = failing_method
        
        # Save should handle the error gracefully
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify error status was set
        self.assertEqual(donor.customer_sync_status, "Error")
        
        # Restore original method for cleanup
        donor.ensure_donor_customer_group = original_method

    def test_manual_sync_refresh(self):
        """Test manual sync refresh functionality"""
        # Create donor with sync disabled initially
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Manual Sync Test"
        donor.donor_type = "Individual"  
        donor.donor_email = "manualsync@example.com"
        donor.flags.ignore_customer_sync = True
        donor.save()
        self.track_doc("donor", donor.name)
        
        # Verify no customer initially
        self.assertFalse(donor.customer)
        
        # Trigger manual sync
        result = donor.refresh_customer_sync()
        
        # Verify customer was created
        self.assertTrue(donor.customer)
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertEqual(result["message"], "Customer synchronization refreshed successfully")
        
        if donor.customer:
            self.track_doc("Customer", donor.customer)

    def test_get_customer_info(self):
        """Test getting customer information from donor"""
        # Create donor with customer
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Info Test Donor"
        donor.donor_type = "Individual"
        donor.donor_email = "info@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        self.track_doc("Customer", donor.customer)
        
        # Get customer info
        customer_info = donor.get_customer_info()
        
        # Verify customer info is returned correctly
        self.assertIsInstance(customer_info, dict)
        self.assertEqual(customer_info["customer_name"], donor.donor_name)
        self.assertEqual(customer_info["email_id"], donor.donor_email)
        self.assertEqual(customer_info["customer_group"], "Donors")
        self.assertIn("outstanding_amount", customer_info)

    def test_donor_customer_loop_prevention(self):
        """Test that sync loops are prevented between donor and customer"""
        # Create donor
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Loop Prevention Test"
        donor.donor_type = "Individual"
        donor.donor_email = "looptest@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        
        customer_name = donor.customer
        self.track_doc("Customer", customer_name)
        
        # Manually trigger sync hooks to ensure no infinite loops
        from verenigingen.utils.donor_customer_sync import sync_donor_to_customer, sync_customer_to_donor
        
        # These should not cause infinite recursion
        sync_donor_to_customer(donor)
        
        customer = frappe.get_doc("Customer", customer_name)
        sync_customer_to_donor(customer)
        
        # If we reach here without stack overflow, loop prevention works
        self.assertTrue(True, "Loop prevention successful")

    def test_donor_with_special_characters_in_name(self):
        """Test donor names with special characters sync correctly"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = "José María O'Connor-Smith & Co."
        donor.donor_type = "Organization"
        donor.donor_email = "jose@example.com"
        donor.save()
        self.track_doc("Donor", donor.name)
        
        # Verify customer was created with special characters
        customer = frappe.get_doc("Customer", donor.customer)
        self.track_doc("Customer", customer.name)
        
        self.assertEqual(customer.customer_name, "José María O'Connor-Smith & Co.")

    def test_donor_field_validation_adherence(self):
        """Test that required fields from JSON are properly validated"""
        # Test missing required field (donor_name)
        donor = frappe.new_doc("Donor")
        donor.donor_type = "Individual"
        donor.donor_email = "validation@example.com"
        # Missing donor_name (required field)
        
        with self.assertRaises(frappe.ValidationError):
            donor.save()
        
        # Test missing required field (donor_type)
        donor2 = frappe.new_doc("Donor")
        donor2.donor_name = "Validation Test"
        donor2.donor_email = "validation2@example.com"
        # Missing donor_type (required field)
        
        with self.assertRaises(frappe.ValidationError):
            donor2.save()
        
        # Test missing required field (donor_email)
        donor3 = frappe.new_doc("Donor")
        donor3.donor_name = "Validation Test 3"
        donor3.donor_type = "Individual"
        # Missing donor_email (required field)
        
        with self.assertRaises(frappe.ValidationError):
            donor3.save()

    def test_sync_status_tracking(self):
        """Test that sync status is properly tracked throughout lifecycle"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = "Status Tracking Test"
        donor.donor_type = "Individual"
        donor.donor_email = "status@example.com"
        
        # Initially no sync status
        self.assertFalse(hasattr(donor, 'customer_sync_status') and donor.customer_sync_status)
        
        donor.save()
        self.track_doc("Donor", donor.name)
        self.track_doc("Customer", donor.customer)
        
        # After save should be synced
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertIsNotNone(donor.last_customer_sync)
        
        # Update donor to trigger resync
        original_sync_time = donor.last_customer_sync
        frappe.utils.time.sleep(1)  # Ensure time difference
        
        donor.donor_name = "Updated Status Test"
        donor.save()
        
        # Sync time should be updated
        self.assertNotEqual(donor.last_customer_sync, original_sync_time)
        self.assertEqual(donor.customer_sync_status, "Synced")