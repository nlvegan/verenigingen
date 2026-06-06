"""
Tests for Donor-Customer API endpoints

This test suite validates the API endpoints for managing donor-customer
relationships and synchronization, following CLAUDE.md testing requirements.
"""

import frappe
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.api.donor_customer_management import (
    get_donor_customer_info,
    force_donor_customer_sync,
    unlink_donor_customer,
    get_donor_sync_dashboard
)
from verenigingen.utils.donor_customer_sync import (
    bulk_sync_donors_to_customers,
    get_sync_status_summary
)


class TestDonorCustomerAPI(VereningingenTestCase):
    """Test suite for Donor-Customer API functionality"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # run-tests --module skips before_tests, so seed the ERPNext base
        # masters (Company, "All Territories") + Verenigingen creation_user
        # that donor->customer sync depends on.
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()

    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test donor with customer for API tests.
        # Donor->Customer sync is gated behind this flag during tests so that
        # unrelated donor fixtures don't create customers; enable it here so the
        # API tests actually have a linked customer to exercise.
        self.test_donor = frappe.new_doc("Donor")
        self.test_donor.donor_name = "API Test Donor"
        self.test_donor.donor_type = "Individual"
        self.test_donor.donor_email = "apitest@example.com"
        self.test_donor.phone = "+31612345678"
        self.test_donor.flags.enable_customer_sync_in_test = True
        self.test_donor.save()
        self.test_donor.reload()
        self.track_doc("Donor", self.test_donor.name)
        if self.test_donor.customer:
            self.track_doc("Customer", self.test_donor.customer)

    def test_get_donor_customer_info_success(self):
        """Test getting donor-customer info successfully"""
        result = get_donor_customer_info(self.test_donor.name)
        
        # Verify structure and content (OperationResult nested envelope)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("donor", data)
        self.assertIn("customer", data)
        self.assertIn("donations", data)
        self.assertIn("integration_status", data)

        # Verify donor information
        donor_info = data["donor"]
        self.assertEqual(donor_info["name"], self.test_donor.name)
        self.assertEqual(donor_info["donor_name"], self.test_donor.donor_name)
        self.assertEqual(donor_info["email"], self.test_donor.donor_email)
        self.assertEqual(donor_info["customer_sync_status"], "Synced")
        
        # Verify integration status
        integration_status = data["integration_status"]
        self.assertTrue(integration_status["has_customer"])
        self.assertEqual(integration_status["sync_status"], "Synced")
        self.assertFalse(integration_status["can_create_customer"])
        self.assertFalse(integration_status["needs_sync"])

    def test_get_donor_customer_info_nonexistent_donor(self):
        """Test getting info for non-existent donor"""
        result = get_donor_customer_info("NONEXISTENT-DONOR")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["message"], "Donor not found")
        self.assertEqual(result["error"]["code"], "DONOR_NOT_FOUND")

    def test_force_donor_customer_sync_success(self):
        """Test forcing donor-customer sync"""
        # Get fresh donor document to avoid timestamp issues
        fresh_donor = self.reload_doc_with_retries(self.test_donor)
        self.assertIsNotNone(fresh_donor, "Could not reload test donor")
        
        # First unlink customer to test recreation
        fresh_donor.customer = ""
        fresh_donor.customer_sync_status = "Pending"
        success = self.save_doc_with_retry(fresh_donor)
        self.assertTrue(success, "Failed to update donor for sync test")
        
        # Force sync - CSRF handled by base class mocks. The API re-fetches the
        # donor internally, so enable the test-sync gate globally for this call.
        frappe.flags.enable_customer_sync_in_test = True
        try:
            result = force_donor_customer_sync(fresh_donor.name)
        finally:
            frappe.flags.enable_customer_sync_in_test = False

        # Verify success response (OperationResult nested envelope)
        self.assertTrue(result["success"])
        self.assertIn("message", result["meta"])
        data = result["data"]
        self.assertIn("customer", data)
        self.assertEqual(data["sync_status"], "Synced")

        # Track the new customer for cleanup
        if data["customer"]:
            self.track_doc("Customer", data["customer"])

    def test_force_donor_customer_sync_nonexistent_donor(self):
        """Test forcing sync for non-existent donor"""
        result = force_donor_customer_sync("NONEXISTENT-DONOR")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["message"], "Donor not found")
        self.assertEqual(result["error"]["code"], "DONOR_NOT_FOUND")

    def test_unlink_donor_customer_success(self):
        """Test unlinking donor from customer"""
        customer_name = self.test_donor.customer
        
        result = unlink_donor_customer(self.test_donor.name, remove_customer=False)

        # Verify success response (OperationResult nested envelope)
        self.assertTrue(result["success"])
        self.assertIn("message", result["meta"])

        # Verify donor was unlinked
        self.test_donor.reload()
        self.assertFalse(self.test_donor.customer)
        self.assertFalse(self.test_donor.customer_sync_status)
        
        # Verify customer still exists but donor reference removed
        if frappe.db.exists("Customer", customer_name):
            customer = frappe.get_doc("Customer", customer_name)
            self.assertFalse(customer.donor)

    def test_unlink_donor_customer_with_removal(self):
        """Test unlinking and removing customer (when no transactions)"""
        customer_name = self.test_donor.customer
        
        result = unlink_donor_customer(self.test_donor.name, remove_customer=True)

        # Verify success response (OperationResult nested envelope)
        self.assertTrue(result["success"])

        # Verify customer was deleted (since no transactions)
        self.assertFalse(frappe.db.exists("Customer", customer_name))
        
        # Verify donor was unlinked
        self.test_donor.reload()
        self.assertFalse(self.test_donor.customer)

    def test_unlink_donor_customer_nonexistent_donor(self):
        """Test unlinking non-existent donor"""
        result = unlink_donor_customer("NONEXISTENT-DONOR")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["message"], "Donor not found")
        self.assertEqual(result["error"]["code"], "DONOR_NOT_FOUND")

    def test_unlink_donor_customer_no_customer_linked(self):
        """Test unlinking donor that has no customer"""
        # Create donor without customer
        donor_no_customer = frappe.new_doc("Donor")
        donor_no_customer.donor_name = "No Customer Donor"
        donor_no_customer.donor_type = "Individual"
        donor_no_customer.donor_email = "nocustomer@example.com"
        donor_no_customer.flags.ignore_customer_sync = True
        donor_no_customer.save()
        self.track_doc("Donor", donor_no_customer.name)
        
        result = unlink_donor_customer(donor_no_customer.name)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"]["message"], "No customer linked to this donor")
        self.assertEqual(result["error"]["code"], "NO_CUSTOMER_LINKED")

    def test_get_donor_sync_dashboard(self):
        """Test getting donor sync dashboard data"""
        result = get_donor_sync_dashboard()
        
        # Verify structure (OperationResult nested envelope)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("summary", data)
        self.assertIn("recent_syncs", data)
        self.assertIn("needs_sync", data)
        self.assertIn("no_customers", data)
        self.assertIn("dashboard_updated", data)

        # Verify summary structure
        summary = data["summary"]
        self.assertIn("sync_status", summary)
        self.assertIn("customer_links", summary)

    def test_bulk_sync_donors_to_customers(self):
        """Test bulk synchronization of donors to customers"""
        # Create additional test donors
        donor2 = frappe.new_doc("Donor")
        donor2.donor_name = "Bulk Test Donor 2"
        donor2.donor_type = "Organization"
        donor2.donor_email = "bulk2@example.com"
        donor2.flags.ignore_customer_sync = True  # Disable initial sync
        donor2.save()
        self.track_doc("Donor", donor2.name)
        
        donor3 = frappe.new_doc("Donor")
        donor3.donor_name = "Bulk Test Donor 3"
        donor3.donor_type = "Individual"
        donor3.donor_email = "bulk3@example.com"
        donor3.flags.ignore_customer_sync = True  # Disable initial sync
        donor3.save()
        self.track_doc("Donor", donor3.name)
        
        # Run bulk sync
        result = bulk_sync_donors_to_customers()
        
        # Verify results structure
        self.assertIsInstance(result, dict)
        self.assertIn("total_processed", result)
        self.assertIn("created_customers", result)
        self.assertIn("updated_customers", result)
        self.assertIn("errors", result)
        self.assertIn("error_details", result)
        
        # Verify some processing occurred
        self.assertGreaterEqual(result["total_processed"], 2)
        
        # Track created customers for cleanup
        donor2.reload()
        donor3.reload()
        if donor2.customer:
            self.track_doc("Customer", donor2.customer)
        if donor3.customer:
            self.track_doc("Customer", donor3.customer)

    def test_bulk_sync_with_filters(self):
        """Test bulk sync with specific filters"""
        # Run bulk sync with filters for individual donors only
        result = bulk_sync_donors_to_customers(filters={"donor_type": "Individual"})
        
        # Verify results structure
        self.assertIsInstance(result, dict)
        self.assertIn("total_processed", result)

    def test_get_sync_status_summary(self):
        """Test getting sync status summary"""
        result = get_sync_status_summary()
        
        # Verify structure
        self.assertIsInstance(result, dict)
        self.assertIn("sync_status", result)
        self.assertIn("customer_links", result)
        
        # Verify data types
        self.assertIsInstance(result["sync_status"], dict)
        self.assertIsInstance(result["customer_links"], dict)

    def test_api_error_handling(self):
        """Test that API methods handle errors gracefully"""
        # Test with invalid donor name format to trigger potential errors
        result = get_donor_customer_info("")
        
        # Should return error dict, not raise exception
        self.assertIsInstance(result, dict)
        # May contain error or just empty data, both acceptable

    def test_donor_with_donations(self):
        """Test API behavior with donor that has donations"""
        # Create a donation for our test donor.
        # mode_of_payment is mandatory; status is the valid field ("One-time"
        # is a valid value of the `status` select field).
        donation = frappe.new_doc("Donation")
        donation.donor = self.test_donor.name
        donation.amount = 100.0
        donation.donation_date = frappe.utils.today()
        donation.status = "One-time"
        donation.mode_of_payment = "Bank Transfer"
        donation.paid = 1
        donation.save()
        self.track_doc("Donation", donation.name)

        # Get donor info with donations (OperationResult nested envelope)
        result = get_donor_customer_info(self.test_donor.name)

        # Verify donations are included
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("donations", data)
        donations = data["donations"]
        self.assertIn("statistics", donations)
        self.assertIn("recent_donations", donations)

        # The created donation must actually be reflected in the summary.
        # (Donation is not submittable, so the summary query must count
        # docstatus < 2, not docstatus = 1.)
        stats = donations["statistics"]
        self.assertGreaterEqual(stats["total_donations"], 1)
        self.assertGreaterEqual(float(stats["total_amount"]), 100.0)
        self.assertTrue(
            any(d["name"] == donation.name for d in donations["recent_donations"]),
            "Created donation should appear in recent_donations",
        )