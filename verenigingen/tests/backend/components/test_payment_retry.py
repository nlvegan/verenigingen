import unittest
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.utils.payment_retry import PaymentRetryManager


class TestPaymentRetryManager(unittest.TestCase):
    """Test automated payment retry functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test customer
        if not frappe.db.exists("Customer", "TEST-RETRY-CUSTOMER"):
            cls.test_customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "Test Retry Customer",
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")}
            ).insert()
        else:
            cls.test_customer = frappe.get_doc("Customer", "TEST-RETRY-CUSTOMER")

        # Create test member
        if not frappe.db.exists("Member", {"email": "retry-test@example.com"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_name": "Test Retry Member",
                    "email": "retry-test@example.com",
                    "customer": cls.test_customer.name}
            ).insert()
        else:
            cls.test_member = frappe.get_doc("Member", {"email": "retry-test@example.com"})

        # Create test membership (required for invoice)
        cls.test_membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": cls.test_member.name,
                "membership_type": frappe.db.get_value("Membership Type", {"name": ["!=", ""]}, "name"),
                "from_date": today(),
                "to_date": add_days(today(), 365),
                "paid": 0}
        ).insert()

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Delete test data
        if hasattr(cls, "test_membership") and frappe.db.exists("Membership", cls.test_membership.name):
            frappe.delete_doc("Membership", cls.test_membership.name, force=True)

        if cls.test_member and frappe.db.exists("Member", cls.test_member.name):
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        if cls.test_customer and frappe.db.exists("Customer", cls.test_customer.name):
            frappe.delete_doc("Customer", cls.test_customer.name, force=True)

        frappe.db.commit()

    def setUp(self):
        """Set up for each test"""
        self.retry_manager = PaymentRetryManager()

        # Create a test invoice
        self.test_invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.test_customer.name,
                "posting_date": today(),
                "due_date": add_days(today(), -5),  # Already overdue
                "membership": self.test_membership.name,
                "items": [
                    {
                        "item_code": frappe.db.get_value("Item", {"item_group": {"!=": ""}}, "name"),
                        "qty": 1,
                        "rate": 100}
                ]}
        ).insert()
        self.test_invoice.submit()

    def tearDown(self):
        """Clean up after each test"""
        # Delete test retry records
        frappe.db.sql(
            """
            DELETE FROM `tabSEPA Payment Retry`
            WHERE invoice = %s
        """,
            self.test_invoice.name,
        )

        # Cancel and delete test invoice
        if frappe.db.exists("Sales Invoice", self.test_invoice.name):
            self.test_invoice.reload()
            if self.test_invoice.docstatus == 1:
                self.test_invoice.cancel()
            frappe.delete_doc("Sales Invoice", self.test_invoice.name, force=True)

        frappe.db.commit()

    def test_get_retry_config(self):
        """Test retry configuration retrieval"""
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
        result = self.retry_manager.schedule_retry(
            self.test_invoice.name, "INSUFFICIENT_FUNDS", "Not enough balance"
        )

        # Check result
        self.assertTrue(result["scheduled"])
        self.assertEqual(result["attempt_number"], 1)
        self.assertIn("Payment retry scheduled", result["message"])

        # Check retry record was created
        retry_record = frappe.get_doc("SEPA Payment Retry", {"invoice": self.test_invoice.name})
        self.assertEqual(retry_record.status, "Scheduled")
        self.assertEqual(retry_record.retry_count, 1)
        self.assertEqual(retry_record.member, self.test_member.name)
        self.assertEqual(retry_record.original_amount, 100)

        # Check notification was sent
        mock_notification.assert_called_once()

    def test_calculate_next_retry_date(self):
        """Test retry date calculation"""
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 0,
                "status": "Pending"}
        ).insert()

        # Test first retry (3 days)
        next_date = self.retry_manager.calculate_next_retry_date(retry_record)
        expected = add_days(today(), 3)

        # Skip weekends if needed
        if getdate(expected).weekday() >= 5:  # Saturday or Sunday
            while getdate(expected).weekday() >= 5:
                expected = add_days(expected, 1)

        self.assertEqual(next_date, expected)

        # Test second retry (7 days)
        retry_record.retry_count = 1
        next_date = self.retry_manager.calculate_next_retry_date(retry_record)
        expected = add_days(today(), 7)

        # Skip weekends if needed
        if getdate(expected).weekday() >= 5:
            while getdate(expected).weekday() >= 5:
                expected = add_days(expected, 1)

        self.assertEqual(next_date, expected)

        # Clean up
        retry_record.delete()

    def test_get_next_business_day(self):
        """Test business day calculation"""
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
        # Create retry record at max attempts
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 3,  # Already at max
                "status": "Failed"}
        ).insert()

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

        # Clean up
        retry_record.delete()

    def test_retry_log_creation(self):
        """Test retry log entries"""
        # Schedule a retry
        self.retry_manager.schedule_retry(self.test_invoice.name, "AC04", "Closed account")

        # Get retry record
        retry_record = frappe.get_doc("SEPA Payment Retry", {"invoice": self.test_invoice.name})

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
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "next_retry_date": add_days(today(), 3),
                "status": "Scheduled"}
        ).insert()

        # Create job
        self.retry_manager.create_retry_job(retry_record)

        # Check enqueue was called
        mock_enqueue.assert_called_once()
        call_args = mock_enqueue.call_args

        # Verify job parameters
        self.assertEqual(call_args[1]["method"], "verenigingen.utils.payment_retry.execute_single_retry")
        self.assertEqual(call_args[1]["retry_record"], retry_record.name)
        self.assertIn("queue", call_args[1])

        # Clean up
        retry_record.delete()

    def test_escalate_payment_failure(self):
        """Test payment failure escalation"""
        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": self.test_invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 2,
                "status": "Failed"}
        ).insert()

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

        # Clean up
        retry_record.delete()

    def test_skip_holidays(self):
        """Test holiday skipping"""
        # This test would require setting up a holiday list
        # For now, just test the method exists and handles no holiday list
        test_date = today()
        result = self.retry_manager.skip_holidays(test_date)

        # Should return same date if no holiday list configured
        self.assertEqual(result, getdate(test_date))

    def test_execute_payment_retry(self):
        """Test payment retry execution"""
        # This would test the actual payment retry execution
        # which involves creating SEPA batches
        pass  # Placeholder for complex integration test


def run_tests():
    """Run all payment retry tests"""
    suite = unittest.TestLoader().loadTestsFromTestCase(TestPaymentRetryManager)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    unittest.main()
