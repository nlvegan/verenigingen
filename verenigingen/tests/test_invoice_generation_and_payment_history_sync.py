"""
Test suite for invoice generation and payment history synchronization
Tests designed to catch the issues that occurred with member Assoc-Member-2025-07-0025
"""

import frappe
from frappe import _
from frappe.utils import today, add_days, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestInvoiceGenerationAndPaymentHistorySync(VereningingenTestCase):
    """
    Test suite to prevent regression of invoice generation and payment history issues.
    
    This test suite specifically addresses:
    1. Payment history sync failures due to Draft status validation
    2. Incorrect due date calculation in invoice generation  
    3. End-to-end visibility of invoices in member payment history
    4. Auto-submit functionality with proper error handling
    """

    def setUp(self):
        """Set up test data"""
        super().setUp()
        
        # Create test member with customer record
        self.member = self.create_test_member(
            first_name="Test",
            last_name="PaymentHistory",
            email="test.paymenthistory@example.com"
        )
        
        # Ensure customer record exists
        if not self.member.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{self.member.first_name} {self.member.last_name}"
            customer.customer_type = "Individual"
            customer.save()
            self.member.customer = customer.name
            self.member.save()
            self.track_doc("Customer", customer.name)
        
        # Create membership
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type="Daglid"
        )
        
        # Create dues schedule
        self.dues_schedule = frappe.new_doc("Membership Dues Schedule")
        self.dues_schedule.schedule_name = f"Test Schedule {self.member.name}"
        self.dues_schedule.member = self.member.name
        self.dues_schedule.member_name = self.member.full_name
        self.dues_schedule.membership_type = "Daglid"
        self.dues_schedule.status = "Active"
        self.dues_schedule.billing_frequency = "Daily"
        self.dues_schedule.dues_rate = 2.0
        self.dues_schedule.next_invoice_date = today()
        self.dues_schedule.save()
        self.track_doc("Membership Dues Schedule", self.dues_schedule.name)

    def test_payment_status_field_allows_draft(self):
        """
        Test that the Member Payment History doctype allows 'Draft' as a valid payment status.
        
        This test prevents regression of the issue where 'Draft' was not in the allowed options,
        causing payment history sync to fail with validation error.
        """
        # Get the Member Payment History doctype
        doctype = frappe.get_meta("Member Payment History")
        payment_status_field = next(f for f in doctype.fields if f.fieldname == "payment_status")
        
        # Check that 'Draft' is in the options
        options = payment_status_field.options.split('\n')
        self.assertIn('Draft', options, 
                     "Payment Status field must include 'Draft' option to prevent payment history sync failures")
        
        # Verify the full expected set of options
        expected_options = ['Draft', 'Unpaid', 'Partially Paid', 'Paid', 'Overdue', 'Cancelled']
        for option in expected_options:
            self.assertIn(option, options, 
                         f"Payment Status field is missing required option: {option}")

    def test_invoice_due_date_calculation(self):
        """
        Test that invoices generated from dues schedules have proper due dates.
        
        This test prevents regression where due dates were set to next_invoice_date 
        (a past date) instead of a proper future due date.
        """
        # Generate invoice using the dues schedule
        invoice_name = self.dues_schedule.create_sales_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be created successfully")
        
        # Track the invoice for cleanup
        self.track_doc("Sales Invoice", invoice_name)
        
        # Get the created invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Verify due date is in the future
        posting_date = getdate(invoice.posting_date)
        due_date = getdate(invoice.due_date) if invoice.due_date else None
        
        self.assertIsNotNone(due_date, "Invoice must have a due date")
        self.assertGreaterEqual(due_date, posting_date, 
                               "Due date must be on or after posting date")
        
        # For invoices without payment terms, due date should be 30 days from posting
        if not invoice.payment_terms_template:
            expected_due_date = add_days(posting_date, 30)
            self.assertEqual(due_date, expected_due_date, 
                           "Due date should be 30 days from posting date when no payment terms specified")

    def test_payment_history_sync_with_draft_invoice(self):
        """
        Test that payment history sync works correctly with Draft invoices.
        
        This test ensures that creating and submitting invoices properly updates
        the member's payment history without validation errors.
        """
        # Create a draft invoice manually to simulate the issue
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.member.customer
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        # Add an item
        invoice.append("items", {
            "item_code": "Membership Dues - Daily",
            "qty": 1,
            "rate": 2.0,
            "description": "Test membership dues"
        })
        
        invoice.insert()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Get initial payment history count
        initial_count = len(self.member.payment_history) if hasattr(self.member, 'payment_history') else 0
        
        # Submit the invoice (this should trigger payment history sync)
        invoice.submit()
        
        # Refresh member to get updated payment history
        self.member.reload()
        
        # Verify payment history was updated without errors
        final_count = len(self.member.payment_history) if hasattr(self.member, 'payment_history') else 0
        self.assertGreater(final_count, initial_count, 
                          "Payment history should be updated when invoice is submitted")
        
        # Verify the specific invoice appears in payment history
        invoice_in_history = any(
            p.invoice == invoice.name 
            for p in self.member.payment_history 
            if hasattr(p, 'invoice')
        )
        self.assertTrue(invoice_in_history, 
                       "Submitted invoice should appear in member's payment history")

    def test_end_to_end_automatic_invoice_generation(self):
        """
        End-to-end test for automatic invoice generation from dues schedule.
        
        Tests the complete flow:
        1. Dues schedule generates invoice
        2. Invoice has proper due date
        3. Invoice auto-submits (if configured)
        4. Member payment history is updated
        5. Member can see invoice in their payment history
        """
        # Generate invoice from dues schedule
        invoice_name = self.dues_schedule.generate_invoice()
        self.assertIsNotNone(invoice_name, "Invoice should be generated from dues schedule")
        
        # Track for cleanup
        self.track_doc("Sales Invoice", invoice_name)
        
        # Get the invoice
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Verify invoice properties
        self.assertEqual(invoice.customer, self.member.customer, 
                        "Invoice should be for the correct customer")
        self.assertEqual(invoice.posting_date, getdate(today()), 
                        "Invoice should have today's posting date")
        self.assertGreaterEqual(getdate(invoice.due_date), getdate(today()), 
                               "Invoice due date should not be in the past")
        
        # If invoice was auto-submitted, verify payment history sync
        if invoice.docstatus == 1:
            # Refresh member payment history
            self.member.reload()
            
            # Check that invoice appears in payment history
            invoice_found = False
            for payment in self.member.payment_history:
                if hasattr(payment, 'invoice') and payment.invoice == invoice_name:
                    invoice_found = True
                    # Verify payment status is valid
                    valid_statuses = ['Draft', 'Unpaid', 'Partially Paid', 'Paid', 'Overdue', 'Cancelled']
                    self.assertIn(payment.payment_status, valid_statuses,
                                f"Payment status '{payment.payment_status}' must be valid")
                    break
            
            self.assertTrue(invoice_found, 
                           "Auto-submitted invoice should appear in member payment history")

    def test_payment_history_manual_refresh(self):
        """
        Test that manual payment history refresh works without validation errors.
        
        This tests the specific scenario that failed for Assoc-Member-2025-07-0025
        where payment history refresh failed due to Draft status validation.
        """
        # Create and submit an invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.member.customer
        invoice.posting_date = today()
        invoice.due_date = add_days(today(), 30)
        
        invoice.append("items", {
            "item_code": "Membership Dues - Daily", 
            "qty": 1,
            "rate": 2.0,
            "description": "Test dues"
        })
        
        invoice.insert()
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        
        # Now test manual payment history refresh
        try:
            self.member.load_payment_history()
            refresh_success = True
            error_message = None
        except Exception as e:
            refresh_success = False
            error_message = str(e)
        
        self.assertTrue(refresh_success, 
                       f"Payment history refresh should succeed without validation errors. Error: {error_message}")
        
        # Verify the invoice is now in payment history
        invoice_in_history = any(
            hasattr(p, 'invoice') and p.invoice == invoice.name 
            for p in self.member.payment_history
        )
        self.assertTrue(invoice_in_history, 
                       "Invoice should appear in payment history after manual refresh")

    def test_dues_schedule_invoice_generation_due_date_logic(self):
        """
        Test specific due date logic in dues schedule invoice generation.
        
        This test specifically addresses the bug where next_invoice_date was 
        incorrectly used as the due_date.
        """
        # Set next_invoice_date to a past date (simulating the original bug scenario)
        past_date = add_days(today(), -1)
        self.dues_schedule.next_invoice_date = past_date
        self.dues_schedule.save()
        
        # Generate invoice
        invoice_name = self.dues_schedule.create_sales_invoice()
        self.track_doc("Sales Invoice", invoice_name)
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Verify due date is NOT set to the past next_invoice_date
        self.assertNotEqual(getdate(invoice.due_date), getdate(past_date),
                           "Due date should NOT be set to next_invoice_date")
        
        # Verify due date is in the future
        self.assertGreaterEqual(getdate(invoice.due_date), getdate(today()),
                               "Due date should be in the future, not past")

    def test_auto_submit_error_handling(self):
        """
        Test that auto-submit errors are handled gracefully and logged properly.
        
        This test ensures that if auto-submit fails, the error is logged but doesn't
        break the invoice generation process.
        """
        # This test would require mocking the auto-submit failure, but demonstrates
        # the type of test needed to catch silent auto-submit failures
        
        # Generate invoice
        invoice_name = self.dues_schedule.create_sales_invoice()
        self.track_doc("Sales Invoice", invoice_name)
        
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        
        # Verify invoice was created successfully regardless of auto-submit outcome
        self.assertIsNotNone(invoice.name, "Invoice should be created even if auto-submit fails")
        
        # Check for any error logs related to this invoice
        error_logs = frappe.get_all("Error Log",
                                   filters={
                                       "error": ["like", f"%{invoice_name}%"],
                                       "creation": [">=", today()]
                                   })
        
        # If there are error logs, they should be related to auto-submit, not creation
        for error_log in error_logs:
            error_doc = frappe.get_doc("Error Log", error_log.name)
            # Auto-submit errors are acceptable, but creation errors are not
            if "Invoice Auto-Submit" not in error_doc.error:
                self.fail(f"Unexpected error during invoice generation: {error_doc.error}")

    def tearDown(self):
        """Clean up test data"""
        # The base test case handles cleanup of tracked documents
        super().tearDown()


class TestPaymentHistoryFieldValidation(VereningingenTestCase):
    """
    Additional tests for payment history field validation
    """
    
    def test_payment_status_field_validation_comprehensive(self):
        """
        Comprehensive test of payment status field validation
        """
        # Test that all expected payment statuses are valid
        test_statuses = ['Draft', 'Unpaid', 'Partially Paid', 'Paid', 'Overdue', 'Cancelled']
        
        member = self.create_test_member(
            first_name="Status",
            last_name="Test",
            email="status.test@example.com"
        )
        
        for status in test_statuses:
            # Create a payment history record with each status
            member.append("payment_history", {
                "invoice": None,
                "posting_date": today(),
                "amount": 10.0,
                "payment_status": status,
                "transaction_type": "Test Transaction"
            })
        
        # This should save without validation errors
        try:
            member.save()
            validation_success = True
            error_message = None
        except Exception as e:
            validation_success = False
            error_message = str(e)
        
        self.assertTrue(validation_success, 
                       f"All payment statuses should be valid. Error: {error_message}")


# Additional integration tests could be added here for:
# - Testing with different payment terms templates
# - Testing with different billing frequencies  
# - Testing SEPA mandate integration
# - Testing payment reconciliation workflows