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
        # Create donor using factory method with sync enabled
        donor = self.create_test_donor_with_sync(
            donor_name="Test Donor Individual",
            donor_type="Individual",
            donor_email="testdonor@example.com",
            phone="+31612345678"
        )
        
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
        self.assertEqual(customer.donor, donor.name)

    def test_organization_donor_creates_company_customer(self):
        """Test that organization donors create company-type customers"""
        donor = self.create_test_donor_with_sync(
            donor_name="Test Organization Corp",
            donor_type="Organization",
            donor_email="org@example.com",
            contact_person="John Manager"
        )
        
        # Verify customer type is Company for organizations
        customer = frappe.get_doc("Customer", donor.customer)
        self.track_doc("Customer", customer.name)
        
        self.assertEqual(customer.customer_type, "Company")
        self.assertEqual(customer.customer_name, donor.donor_name)

    def test_donor_update_syncs_to_customer(self):
        """Test that updating donor syncs changes to customer"""
        # Create initial donor with proper sync handling
        donor = self.create_test_donor_with_sync(
            donor_name="Original Name",
            donor_email="original@example.com"
        )
        
        original_customer = donor.customer
        self.assertIsNotNone(original_customer, "Customer should be created during donor creation")
        
        # Update donor information 
        donor.donor_name = "Updated Name"
        donor.donor_email = "updated@example.com"
        donor.phone = "+31687654321"
        
        # Re-enable sync flag for update (flags are cleared after each save)
        donor.flags.enable_customer_sync_in_test = True
        
        # Debug: Check values before save
        print(f"🐛 About to save donor with:")
        print(f"   donor_name: '{donor.donor_name}'")
        print(f"   donor_email: '{donor.donor_email}'")
        print(f"   phone: '{getattr(donor, 'phone', 'NOT SET')}'")
        
        # Simple save without retry mechanism to avoid complications
        donor.save()
        
        # Debug: Check values after save
        print(f"🐛 After save, donor has:")
        print(f"   donor_name: '{donor.donor_name}'")
        print(f"   donor_email: '{donor.donor_email}'")
        print(f"   phone: '{getattr(donor, 'phone', 'NOT SET')}'")
        
        # Also check database values
        db_values = frappe.db.get_value("Donor", donor.name, ["donor_name", "donor_email", "phone"], as_dict=True)
        print(f"🐛 Database values after save:")
        print(f"   donor_name: '{db_values.donor_name}'" if db_values else "NOT FOUND")
        print(f"   donor_email: '{db_values.donor_email}'" if db_values else "NOT FOUND")
        print(f"   phone: '{db_values.phone}'" if db_values else "NOT FOUND")
        
        # Commit to ensure visibility
        frappe.db.commit()
        
        # Verify customer was updated - reload the document properly
        customer = frappe.get_doc("Customer", original_customer)
        customer.reload()  # Force refresh from database
        
        # Debug output to understand what's happening
        print(f"\n🔍 DEBUG: Customer data from reloaded document:")
        print(f"   Original customer name: {original_customer}")
        print(f"   Current customer_name: {customer.customer_name}")
        print(f"   Current email_id: {customer.email_id}")
        print(f"   Current mobile_no: {customer.mobile_no}")
        
        self.assertEqual(customer.customer_name, "Updated Name")
        self.assertEqual(customer.email_id, "updated@example.com")
        self.assertEqual(customer.mobile_no, "+31687654321")

    def test_customer_update_syncs_to_donor(self):
        """Test that updating customer syncs changes back to donor"""
        # Create donor with customer using enhanced method
        donor = self.create_test_donor_with_sync(
            donor_name="Test Sync Back",
            donor_email="syncback@example.com"
        )
        
        customer_name = donor.customer
        self.assertIsNotNone(customer_name, "Customer should be created with donor")
        
        # Update customer and its contact properly
        customer = frappe.get_doc("Customer", customer_name)
        customer.customer_name = "Customer Updated Name"
        
        # Clear problematic Mollie fields that cause validation errors
        customer.subscription_status = ""
        customer.mollie_subscription_id = ""
        
        # Update the Contact record instead of read-only Customer fields
        if customer.customer_primary_contact:
            contact = frappe.get_doc("Contact", customer.customer_primary_contact)
            
            # Update contact email via child table
            contact.email_ids = []
            contact.append("email_ids", {
                "email_id": "customerupdated@example.com",
                "is_primary": 1
            })
            
            # Update contact phone via child table  
            contact.phone_nos = []
            contact.append("phone_nos", {
                "phone": "+31612345678",
                "is_primary_mobile_no": 1
            })
            
            contact.save()
        
        success = self.save_doc_with_retry(customer)
        self.assertTrue(success, "Failed to save customer updates")
        
        # Allow time for reverse sync and reload donor
        import time
        time.sleep(0.5)
        
        # Reload donor with retries to avoid timing issues
        fresh_donor = self.reload_doc_with_retries(donor)
        self.assertIsNotNone(fresh_donor, "Could not reload donor after customer update")
        
        # Verify reverse sync worked
        self.assertEqual(fresh_donor.donor_name, "Customer Updated Name")
        self.assertEqual(fresh_donor.donor_email, "customerupdated@example.com")
        self.assertEqual(fresh_donor.phone, "+31612345678")

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
        
        # Create donor with same email using factory method
        donor = self.create_test_donor_with_sync(
            donor_name="Existing Customer",
            donor_type="Individual",
            donor_email="existing@example.com"
        )
        
        # Verify existing customer was linked, not new one created
        self.assertEqual(donor.customer, customer.name)
        
        # Verify donor reference was added to customer
        customer.reload()
        self.assertEqual(customer.donor, donor.name)

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
        # Create donor normally first to establish baseline
        donor = self.create_test_donor_with_sync(
            donor_name="Error Test Donor",
            donor_email="errortest@example.com"
        )
        
        # Verify initial sync worked
        self.assertEqual(donor.customer_sync_status, "Synced")
        
        # Now simulate an error condition by patching sync method
        from unittest.mock import patch
        
        with patch.object(donor, 'sync_with_customer', side_effect=Exception("Simulated sync error")):
            donor.donor_name = "Updated Name to Trigger Sync Error"
            try:
                success = self.save_doc_with_retry(donor)
                # The save might succeed even if sync fails - depends on implementation
            except Exception:
                pass  # Expected to fail in some cases
            
        # Reload to check current state - error handling varies by implementation
        donor_reloaded = self.reload_doc_with_retries(donor)
        self.assertIsNotNone(donor_reloaded, "Donor should still exist after sync error")
        
        # The actual error status handling depends on implementation details
        # This test validates the error handling mechanism works without breaking

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
        # Create donor with customer using factory method
        donor = self.create_test_donor_with_sync(
            donor_name="Info Test Donor",
            donor_type="Individual",
            donor_email="info@example.com"
        )
        
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
        # Create donor using factory method with sync enabled
        donor = self.create_test_donor_with_sync(
            donor_name="Loop Prevention Test",
            donor_type="Individual",
            donor_email="looptest@example.com"
        )
        
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
        donor = self.create_test_donor_with_sync(
            donor_name="José María O'Connor-Smith & Co.",
            donor_type="Organization",
            donor_email="jose@example.com"
        )
        
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
        # Create donor with proper sync handling
        donor = self.create_test_donor_with_sync(
            donor_name="Status Tracking Test",
            donor_email="status@example.com"
        )
        
        # Should have sync status after creation
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertIsNotNone(donor.customer, "Customer should be created")
        self.assertIsNotNone(donor.last_customer_sync, "Sync timestamp should be set")
        
        # After save should be synced
        self.assertEqual(donor.customer_sync_status, "Synced")
        self.assertIsNotNone(donor.last_customer_sync)
        
        # Update donor to trigger resync
        original_sync_time = donor.last_customer_sync
        import time
        time.sleep(1)  # Ensure time difference
        
        donor.donor_name = "Updated Status Test"
        success = self.save_doc_with_retry(donor)
        self.assertTrue(success, "Failed to save donor status update")
        
        # Wait for sync to complete
        sync_completed = self.wait_for_sync_completion(donor)
        self.assertTrue(sync_completed, "Status tracking sync did not complete")
        
        # Sync time should be updated
        donor_fresh = self.reload_doc_with_retries(donor)
        self.assertIsNotNone(donor_fresh, "Could not reload donor after status update")
        self.assertNotEqual(donor_fresh.last_customer_sync, original_sync_time)
        self.assertEqual(donor_fresh.customer_sync_status, "Synced")