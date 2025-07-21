from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.utils.payment_retry import PaymentRetryManager
from verenigingen.tests.utils.base import VereningingenTestCase


class TestPaymentRetryManager(VereningingenTestCase):
    """Test automated payment retry functionality"""

    def setUp(self):
        """Set up test data using factory methods"""
        super().setUp()
        
        # Create test member with customer using factory method
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Retry Member",
            email=f"retry-test.{frappe.generate_hash(length=6)}@example.com"
        )
        
        # Get the customer that was automatically created
        self.test_customer = frappe.get_doc("Customer", self.test_member.customer)
        
        # Create test membership using factory method (draft to avoid deletion issues)
        self.test_membership = self.create_test_membership(
            member=self.test_member.name,
            from_date=today(),
            to_date=add_days(today(), 365),
            paid=0,
            docstatus=0  # Keep as draft for easier cleanup
        )

    def create_test_invoice(self):
        """Create a test invoice for retry testing"""
        self.retry_manager = PaymentRetryManager()

        # Create a test invoice using proper factory approach
        invoice_data = {
            "doctype": "Sales Invoice",
            "customer": self.test_customer.name,
            "posting_date": today(),
            "due_date": add_days(today(), -5),  # Already overdue
            "items": [
                {
                    "item_code": self.get_or_create_test_item(),
                    "qty": 1,
                    "rate": 100
                }
            ]
        }
        
        self.test_invoice = frappe.get_doc(invoice_data)
        # Mock the membership attribute for testing since it's a custom field
        self.test_invoice.membership = self.test_membership.name
        self.test_invoice.insert()
        self.test_invoice.submit()
        self.track_doc("Sales Invoice", self.test_invoice.name)
    
    def get_or_create_test_item(self):
        """Get or create a test item for invoices"""
        item_name = "TEST-RETRY-ITEM"
        if not frappe.db.exists("Item", item_name):
            item = frappe.get_doc({
                "doctype": "Item",
                "item_code": item_name,
                "item_name": "Test Retry Item",
                "item_group": "Services",
                "stock_uom": "Nos",
                "is_stock_item": 0,
                "is_sales_item": 1,
                "is_purchase_item": 0
            })
            item.insert()
            self.track_doc("Item", item_name)
        return item_name

    def test_get_retry_config(self):
        """Test retry configuration retrieval"""
        self.create_test_invoice()
        config = self.retry_manager.get_retry_config()

        # Check default values
        self.assertEqual(config["max_retries"], 3)
        self.assertEqual(config["retry_intervals"], [3, 7, 14])
        self.assertTrue(config["skip_weekends"])
        self.assertTrue(config["skip_holidays"])
        self.assertEqual(config["retry_time"], "10:00:00")
        self.assertEqual(config["escalate_after"], 2)

    @patch(
        "verenigingen.utils.sepa_notifications.SEPAMandateNotificationManager.send_payment_retry_notification"
    )
    def test_schedule_retry_first_attempt(self, mock_notification):
        """Test scheduling first retry attempt"""
        self.create_test_invoice()
        result = self.retry_manager.schedule_retry(
            self.test_invoice.name, "INSUFFICIENT_FUNDS", "Not enough balance"
        )

        # Check result
        self.assertTrue(result["scheduled"])
        self.assertEqual(result["attempt_number"], 1)
        self.assertIn("Payment retry scheduled", result["message"])

        # Check retry record was created
        retry_record = frappe.get_doc("SEPA Payment Retry", {"invoice": self.test_invoice.name})
        self.track_doc("SEPA Payment Retry", retry_record.name)
        self.assertEqual(retry_record.status, "Scheduled")
        self.assertEqual(retry_record.retry_count, 1)
        self.assertEqual(retry_record.member, self.test_member.name)
        self.assertEqual(retry_record.original_amount, 100)

        # Check notification was sent
        mock_notification.assert_called_once()

    def test_calculate_next_retry_date(self):
        """Test retry date calculation"""
        self.create_test_invoice()
        
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 0,
                "status": "Pending"}
        )
        retry_record.insert()
        self.track_doc("SEPA Payment Retry", retry_record.name)

        # Test first retry (3 days)
        next_date = self.retry_manager.calculate_next_retry_date(retry_record)
        expected = add_days(today(), 3)

        # Skip weekends if needed
        if getdate(expected).weekday() >= 5:  # Saturday or Sunday
            while getdate(expected).weekday() >= 5:
                expected = add_days(expected, 1)

        # Compare as dates (both should be date objects)
        self.assertEqual(next_date, getdate(expected))

        # Test second retry (7 days)
        retry_record.retry_count = 1
        next_date = self.retry_manager.calculate_next_retry_date(retry_record)
        expected = add_days(today(), 7)

        # Skip weekends if needed
        if getdate(expected).weekday() >= 5:
            while getdate(expected).weekday() >= 5:
                expected = add_days(expected, 1)

        # Compare as dates (both should be date objects)
        self.assertEqual(next_date, getdate(expected))

        # Cleanup handled by base class

    def test_get_next_business_day(self):
        """Test business day calculation"""
        self.create_test_invoice()
        
        # Test weekday
        wednesday = datetime(2024, 1, 3).date()  # Wednesday
        result = self.retry_manager.get_next_business_day(wednesday)
        self.assertEqual(result, wednesday)

        # Test Saturday -> Monday
        saturday = datetime(2024, 1, 6).date()  # Saturday
        result = self.retry_manager.get_next_business_day(saturday)
        monday = datetime(2024, 1, 8).date()  # Monday
        self.assertEqual(result, monday)

        # Test Sunday -> Monday
        sunday = datetime(2024, 1, 7).date()  # Sunday
        result = self.retry_manager.get_next_business_day(sunday)
        self.assertEqual(result, monday)

    @patch(
        "verenigingen.utils.sepa_notifications.SEPAMandateNotificationManager.send_payment_retry_notification"
    )
    def test_max_retries_escalation(self, mock_notification):
        """Test escalation after max retries"""
        self.create_test_invoice()
        
        # Create retry record at max attempts
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 3,  # Already at max
                "status": "Failed"}
        )
        retry_record.insert()
        self.track_doc("SEPA Payment Retry", retry_record.name)

        # Try to schedule another retry
        result = self.retry_manager.schedule_retry(
            self.test_invoice.name, "INSUFFICIENT_FUNDS", "Still no funds"
        )

        # Should not be scheduled
        self.assertFalse(result["scheduled"])
        self.assertIn("Maximum retry attempts reached", result["message"])

        # Check record was escalated
        retry_record.reload()
        self.assertEqual(retry_record.status, "Escalated")

        # Cleanup handled by base class

    def test_retry_log_creation(self):
        """Test retry log entries"""
        self.create_test_invoice()
        
        # Schedule a retry
        self.retry_manager.schedule_retry(self.test_invoice.name, "AC04", "Closed account")

        # Get retry record
        retry_record = frappe.get_doc("SEPA Payment Retry", {"invoice": self.test_invoice.name})
        self.track_doc("SEPA Payment Retry", retry_record.name)

        # Check retry log
        self.assertEqual(len(retry_record.retry_log), 1)
        log_entry = retry_record.retry_log[0]
        self.assertEqual(log_entry.reason_code, "AC04")
        self.assertEqual(log_entry.reason_message, "Closed account")
        self.assertIsNotNone(log_entry.scheduled_retry)

        # Schedule another retry
        retry_record.status = "Failed"
        retry_record.save()

        self.retry_manager.schedule_retry(self.test_invoice.name, "MD07", "Mandate cancelled")

        # Check second log entry
        retry_record.reload()
        self.assertEqual(len(retry_record.retry_log), 2)
        self.assertEqual(retry_record.retry_log[1].reason_code, "MD07")

    @patch("frappe.enqueue")
    def test_create_retry_job(self, mock_enqueue):
        """Test scheduled job creation"""
        self.create_test_invoice()
        
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "next_retry_date": add_days(today(), 3),
                "status": "Scheduled"}
        )
        retry_record.insert()
        self.track_doc("SEPA Payment Retry", retry_record.name)

        # Create job
        self.retry_manager.create_retry_job(retry_record)

        # Check enqueue was called
        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args

        # Verify job parameters
        self.assertEqual(call_args[1]["method"], "verenigingen.utils.payment_retry.execute_single_retry")
        self.assertEqual(call_args[1]["retry_record"], retry_record.name)
        self.assertIn("queue", call_args[1])

        # Cleanup handled by base class

    def test_escalate_payment_failure(self):
        """Test payment failure escalation"""
        self.create_test_invoice()
        
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "membership": self.test_membership.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 2,
                "status": "Failed"}
        )
        retry_record.insert()
        self.track_doc("SEPA Payment Retry", retry_record.name)

        # Escalate
        self.retry_manager.escalate_payment_failure(retry_record)

        # Check status
        retry_record.reload()
        self.assertEqual(retry_record.status, "Escalated")
        self.assertIsNotNone(retry_record.escalation_date)

        # Check comment was added
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": self.test_invoice.name,
                "comment_type": "Comment"},
            fields=["content"],
        )

        self.assertTrue(any("escalated" in c.content.lower() for c in comments))

        # Cleanup handled by base class

    def test_skip_holidays(self):
        """Test holiday skipping"""
        self.create_test_invoice()
        
        # This test would require setting up a holiday list
        # For now, just test the method exists and handles no holiday list
        test_date = today()
        result = self.retry_manager.skip_holidays(test_date)

        # Should return same date if no holiday list configured
        # Compare as date objects
        self.assertEqual(getdate(result), getdate(test_date))

    def test_execute_payment_retry(self):
        """Test payment retry execution"""
        self.create_test_invoice()
        
        # This would test the actual payment retry execution
        # which involves creating SEPA batches
        pass  # Placeholder for complex integration test
