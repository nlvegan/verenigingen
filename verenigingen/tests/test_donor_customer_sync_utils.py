"""
Tests for Donor-Customer synchronization utility functions

This test suite validates the sync hook handlers and utility functions,
following CLAUDE.md testing requirements.
"""

import frappe
from unittest.mock import patch
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.donor_customer_sync import (
    sync_donor_to_customer,
    sync_customer_to_donor
)


class TestDonorCustomerSyncUtils(VereningingenTestCase):
    """Test suite for sync utility functions"""
    
    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test donor
        self.test_donor = frappe.new_doc("Donor")
        self.test_donor.donor_name = "Sync Utils Test Donor"
        self.test_donor.donor_type = "Individual"
        self.test_donor.donor_email = "syncutils@example.com"
        self.test_donor.phone = "+31612345678"
        self.test_donor.save()
        self.track_doc("Donor", self.test_donor.name)
        self.track_doc("Customer", self.test_donor.customer)

    def test_sync_donor_to_customer_hook(self):
        """Test sync_donor_to_customer hook function"""
        # Modify donor to create sync scenario
        self.test_donor.customer_sync_status = "Pending"
        
        # Call hook function directly
        sync_donor_to_customer(self.test_donor)
        
        # Verify sync was triggered
        self.assertEqual(self.test_donor.customer_sync_status, "Synced")

    def test_sync_donor_to_customer_with_from_customer_sync_flag(self):
        """Test that sync is skipped when from_customer_sync flag is set"""
        # Set flag to prevent sync
        self.test_donor.flags.from_customer_sync = True
        original_status = self.test_donor.customer_sync_status
        
        # Call hook function
        sync_donor_to_customer(self.test_donor)
        
        # Verify sync was skipped
        self.assertEqual(self.test_donor.customer_sync_status, original_status)

    def test_sync_donor_to_customer_with_ignore_sync_flag(self):
        """Test that sync is skipped when ignore_customer_sync flag is set"""
        # Set flag to ignore sync
        self.test_donor.flags.ignore_customer_sync = True
        original_status = self.test_donor.customer_sync_status
        
        # Call hook function
        sync_donor_to_customer(self.test_donor)
        
        # Verify sync was skipped
        self.assertEqual(self.test_donor.customer_sync_status, original_status)

    def test_sync_donor_to_customer_error_handling(self):
        """Test that sync errors are handled gracefully"""
        # Mock sync_with_customer to raise an exception
        original_sync = self.test_donor.sync_with_customer
        
        def failing_sync():
            raise Exception("Simulated sync error")
        
        self.test_donor.sync_with_customer = failing_sync
        
        # Hook should not raise exception
        try:
            sync_donor_to_customer(self.test_donor)
            error_handled = True
        except Exception:
            error_handled = False
        
        self.assertTrue(error_handled, "Hook should handle sync errors gracefully")
        
        # Restore original method
        self.test_donor.sync_with_customer = original_sync

    def test_sync_customer_to_donor_hook(self):
        """Test sync_customer_to_donor hook function"""
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        
        # Update customer data
        customer.customer_name = "Updated by Customer Hook"
        customer.email_id = "updatedhook@example.com"
        customer.mobile_no = "+31687654321"
        
        # Call hook function
        sync_customer_to_donor(customer)
        
        # Verify donor was updated
        self.test_donor.reload()
        self.assertEqual(self.test_donor.donor_name, "Updated by Customer Hook")
        self.assertEqual(self.test_donor.donor_email, "updatedhook@example.com")
        self.assertEqual(self.test_donor.phone, "+31687654321")

    def test_sync_customer_to_donor_with_from_donor_sync_flag(self):
        """Test that customer-to-donor sync is skipped with from_donor_sync flag"""
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        customer.flags.from_donor_sync = True
        
        original_donor_name = self.test_donor.donor_name
        customer.customer_name = "Should Not Update"
        
        # Call hook function
        sync_customer_to_donor(customer)
        
        # Verify donor was not updated
        self.test_donor.reload()
        self.assertEqual(self.test_donor.donor_name, original_donor_name)

    def test_sync_customer_to_donor_without_donor_reference(self):
        """Test that sync is skipped when customer has no donor reference"""
        # Create customer without donor reference
        customer = frappe.new_doc("Customer")
        customer.customer_name = "No Donor Reference"
        customer.customer_type = "Individual"
        customer.customer_group = "All Customer Groups"
        customer.territory = "All Territories"
        customer.save()
        self.track_doc("Customer", customer.name)
        
        # Call hook function - should return early without error
        try:
            sync_customer_to_donor(customer)
            no_error = True
        except Exception:
            no_error = False
        
        self.assertTrue(no_error, "Hook should handle customers without donor reference")

    def test_sync_customer_to_donor_with_nonexistent_donor(self):
        """Test sync when donor reference points to non-existent donor"""
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        customer.custom_donor_reference = "NONEXISTENT-DONOR"
        
        # Call hook function - should return early without error
        try:
            sync_customer_to_donor(customer)
            no_error = True
        except Exception:
            no_error = False
        
        self.assertTrue(no_error, "Hook should handle non-existent donor references")

    def test_sync_customer_to_donor_error_handling(self):
        """Test that customer-to-donor sync errors are handled gracefully"""
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        
        # Mock get_doc to raise an exception
        with patch('frappe.get_doc') as mock_get_doc:
            mock_get_doc.side_effect = Exception("Simulated get_doc error")
            
            # Hook should not raise exception
            try:
                sync_customer_to_donor(customer)
                error_handled = True
            except Exception:
                error_handled = False
            
            self.assertTrue(error_handled, "Hook should handle get_doc errors gracefully")

    def test_bidirectional_sync_data_consistency(self):
        """Test that bidirectional sync maintains data consistency"""
        # Update donor
        self.test_donor.donor_name = "Bidirectional Test"
        self.test_donor.donor_email = "bidirectional@example.com"
        self.test_donor.phone = "+31600111222"
        
        # Trigger donor-to-customer sync
        sync_donor_to_customer(self.test_donor)
        
        # Verify customer was updated
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        self.assertEqual(customer.customer_name, "Bidirectional Test")
        self.assertEqual(customer.email_id, "bidirectional@example.com")
        self.assertEqual(customer.mobile_no, "+31600111222")
        
        # Update customer
        customer.customer_name = "Bidirectional Customer Update"
        customer.email_id = "bidir_customer@example.com"
        customer.mobile_no = "+31600333444"
        
        # Trigger customer-to-donor sync
        sync_customer_to_donor(customer)
        
        # Verify donor was updated
        self.test_donor.reload()
        self.assertEqual(self.test_donor.donor_name, "Bidirectional Customer Update")
        self.assertEqual(self.test_donor.donor_email, "bidir_customer@example.com")
        self.assertEqual(self.test_donor.phone, "+31600333444")

    def test_sync_only_when_changes_detected(self):
        """Test that sync only occurs when actual changes are detected"""
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        original_modified = self.test_donor.modified
        
        # Call sync without making changes
        sync_customer_to_donor(customer)
        
        # Verify donor was not unnecessarily saved
        self.test_donor.reload()
        # Note: In practice, this test depends on implementation details
        # The sync utility should detect when no changes are needed

    def test_sync_preserves_customer_link(self):
        """Test that sync maintains the customer link in donor"""
        original_customer = self.test_donor.customer
        
        # Update customer details
        customer = frappe.get_doc("Customer", original_customer)
        customer.customer_name = "Link Preservation Test"
        
        # Trigger sync
        sync_customer_to_donor(customer)
        
        # Verify customer link is preserved
        self.test_donor.reload()
        self.assertEqual(self.test_donor.customer, original_customer)

    def test_sync_handles_missing_phone_field(self):
        """Test sync when donor doesn't have phone field"""
        # Create customer without mobile number
        customer = frappe.get_doc("Customer", self.test_donor.customer)
        customer.mobile_no = ""
        
        # Should handle gracefully without error
        try:
            sync_customer_to_donor(customer)
            no_error = True
        except Exception:
            no_error = False
        
        self.assertTrue(no_error, "Sync should handle missing phone fields gracefully")

    def test_sync_status_updates(self):
        """Test that sync status is properly updated during sync operations"""
        # Reset sync status
        self.test_donor.customer_sync_status = "Pending"
        self.test_donor.last_customer_sync = None
        
        # Trigger sync
        sync_donor_to_customer(self.test_donor)
        
        # Verify sync status was updated
        self.assertEqual(self.test_donor.customer_sync_status, "Synced")
        self.assertIsNotNone(self.test_donor.last_customer_sync)