import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.test_patches import apply_test_patches, remove_test_patches
from verenigingen.utils.payment_notifications import check_and_resolve_payment_retries, on_payment_submit
from verenigingen.verenigingen_payments.utils.sepa_notifications import SEPAMandateNotificationManager


class TestSEPANotifications(unittest.TestCase):
    """Test SEPA notification system"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Apply test patches to disable notifications
        apply_test_patches()

        cls.test_member = None
        cls.test_mandate = None
        cls.test_customer = None

        # Create test customer
        if not frappe.db.exists("Customer", "TEST-SEPA-CUSTOMER"):
            cls.test_customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "Test SEPA Customer",
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")}
            ).insert()
        else:
            cls.test_customer = frappe.get_doc("Customer", "TEST-SEPA-CUSTOMER")

        # Create test member
        if not frappe.db.exists("Member", {"email": "sepa-test@example.com"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_name": "Test SEPA Member",
                    "email": "sepa-test@example.com",
                    "customer": cls.test_customer.name}
            ).insert()
        else:
            cls.test_member = frappe.get_doc("Member", {"email": "sepa-test@example.com"})

    def setUp(self):
        """Set up for each test"""
        self.notification_manager = SEPAMandateNotificationManager()

        # Create a test mandate for each test
        self.test_mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.test_member.name,
                "mandate_id": f"TEST-MANDATE-{frappe.utils.random_string(6)}",
                "iban": "NL39RABO0300065264",
                "bic": "RABONL2U",
                "account_holder_name": "Test Account Holder",
                "sign_date": today(),
                "status": "Active",
                "is_active": 1,
                "used_for_memberships": 1}
        ).insert()

    def tearDown(self):
        """Clean up after each test"""
        # Delete test mandate
        if self.test_mandate and frappe.db.exists("SEPA Mandate", self.test_mandate.name):
            frappe.delete_doc("SEPA Mandate", self.test_mandate.name, force=True)

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        # Delete test communications
        frappe.db.sql(
            """
            DELETE FROM `tabCommunication`
            WHERE reference_doctype = 'SEPA Mandate'
            AND reference_name LIKE 'TEST-MANDATE-%'
        """
        )

        # Delete test member and customer
        if cls.test_member and frappe.db.exists("Member", cls.test_member.name):
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        if cls.test_customer and frappe.db.exists("Customer", cls.test_customer.name):
            frappe.delete_doc("Customer", cls.test_customer.name, force=True)

        # Remove test patches
        remove_test_patches()

        frappe.db.commit()

    @patch("frappe.core.doctype.communication.email.make")
    def test_mandate_created_notification(self, mock_email):
        """Test mandate creation notification"""
        # Send notification
        self.notification_manager.send_mandate_created_notification(self.test_mandate)

        # Verify email was called
        mock_email.assert_called_once()
        call_args = mock_email.call_args[1]

        # Check email parameters
        self.assertEqual(call_args["recipients"], [self.test_member.email])
        self.assertIn("SEPA Direct Debit Mandate Activated", call_args["subject"])
        self.assertIn("Test SEPA Member", call_args["content"])
        self.assertIn("NL39****5264", call_args["content"])  # Masked IBAN
        self.assertEqual(call_args["doctype"], "Member")
        self.assertEqual(call_args["name"], self.test_member.name)

    @patch("frappe.core.doctype.communication.email.make")
    def test_mandate_cancelled_notification(self, mock_email):
        """Test mandate cancellation notification"""
        # Send notification
        self.notification_manager.send_mandate_cancelled_notification(
            self.test_mandate, "Test cancellation reason"
        )

        # Verify email was called
        mock_email.assert_called_once()
        call_args = mock_email.call_args[1]

        # Check email parameters
        self.assertEqual(call_args["recipients"], [self.test_member.email])
        self.assertIn("SEPA Direct Debit Mandate Cancelled", call_args["subject"])
        self.assertIn("Test cancellation reason", call_args["content"])

    @patch("frappe.core.doctype.communication.email.make")
    def test_mandate_expiring_notification(self, mock_email):
        """Test mandate expiry notification"""
        # Set expiry date
        self.test_mandate.expiry_date = add_days(today(), 15)
        self.test_mandate.save()

        # Send notification
        self.notification_manager.send_mandate_expiring_notification(self.test_mandate, 15)

        # Verify email was called
        mock_email.assert_called_once()
        call_args = mock_email.call_args[1]

        # Check email parameters
        self.assertEqual(call_args["recipients"], [self.test_member.email])
        self.assertIn("SEPA Mandate Expiring Soon", call_args["subject"])
        self.assertIn("15", call_args["content"])  # Days until expiry

    @patch("frappe.core.doctype.communication.email.make")
    def test_payment_retry_notification(self, mock_email):
        """Test payment retry notification"""
        # Create test invoice
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.test_customer.name,
                "posting_date": today(),
                "due_date": add_days(today(), 30),
                "items": [
                    {
                        "item_code": frappe.db.get_value("Item", {"item_group": {"!=": ""}}, "name"),
                        "qty": 1,
                        "rate": 100}
                ]}
        ).insert()
        invoice.submit()

        # Create retry record
        retry_record = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "retry_count": 1,
                "next_retry_date": add_days(today(), 3),
                "status": "Scheduled",
                "last_failure_reason": "Insufficient funds"}
        ).insert()

        # Send notification
        self.notification_manager.send_payment_retry_notification(retry_record)

        # Verify email was called
        mock_email.assert_called_once()
        call_args = mock_email.call_args[1]

        # Check email parameters
        self.assertEqual(call_args["recipients"], [self.test_member.email])
        self.assertIn("Payment Retry Scheduled", call_args["subject"])
        self.assertIn("€100.00", call_args["content"])

        # Clean up
        retry_record.delete()
        invoice.cancel()
        invoice.delete()

    @patch("frappe.core.doctype.communication.email.make")
    def test_payment_success_notification(self, mock_email):
        """Test payment success notification"""
        # Create test payment entry
        payment = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": self.test_customer.name,
                "paid_amount": 150,
                "received_amount": 150,
                "posting_date": today(),
                "mode_of_payment": "Bank Transfer",
                "paid_to": frappe.db.get_value("Account", {"account_type": "Bank", "is_group": 0}, "name"),
                "paid_to_account_currency": "EUR"}
        )
        payment.insert()

        # Send notification
        self.notification_manager.send_payment_success_notification(payment)

        # Verify email was called
        mock_email.assert_called_once()
        call_args = mock_email.call_args[1]

        # Check email parameters
        self.assertEqual(call_args["recipients"], [self.test_member.email])
        self.assertIn("Payment Received", call_args["subject"])
        self.assertIn("€150.00", call_args["content"])

        # Clean up
        payment.delete()

    def test_iban_masking(self):
        """Test IBAN masking for security"""
        # Test various IBANs
        test_cases = [
            ("NL39RABO0300065264", "NL39****5264"),
            ("DE89370400440532013000", "DE89****3000"),
            ("BE68539007547034", "BE68****7034"),
            ("FR1420041010050500013M02606", "FR14****2606"),
            ("SHORT", "SHORT"),  # Too short to mask
            ("", ""),  # Empty
            (None, None),  # None
        ]

        for iban, expected in test_cases:
            masked = self.notification_manager._mask_iban(iban)
            self.assertEqual(masked, expected, f"Failed for IBAN: {iban}")

    def test_bank_name_derivation(self):
        """Test bank name derivation from IBAN"""
        # Test known Dutch banks
        test_cases = [
            ("NL39RABO0300065264", "Rabobank"),
            ("NL91ABNA0417164300", "ABN AMRO"),
            ("NL69INGB0123456789", "ING"),
            ("DE89370400440532013000", "Unknown Bank"),  # Non-Dutch
            ("INVALID", "Unknown Bank"),  # Invalid IBAN
        ]

        for iban, expected in test_cases:
            bank_name = self.notification_manager._get_bank_name(iban)
            if expected != "Unknown Bank":
                self.assertEqual(bank_name, expected)
            else:
                # For unknown banks, just check it returns something
                self.assertIsNotNone(bank_name)

    @patch("frappe.get_all")
    @patch("frappe.db.get_value")
    @patch("frappe.core.doctype.communication.email.make")
    def test_check_and_send_expiry_notifications(self, mock_email, mock_get_value, mock_get_all):
        """Test scheduled expiry notification check"""
        # Mock mandates expiring in 20 days
        mock_get_all.return_value = [
            {
                "name": self.test_mandate.name,
                "member": self.test_member.name,
                "expiry_date": add_days(today(), 20),
                "mandate_id": self.test_mandate.mandate_id,
                "iban": self.test_mandate.iban}
        ]

        # Mock no recent notifications sent
        mock_get_value.return_value = None

        # Run the check
        self.notification_manager.check_and_send_expiry_notifications()

        # Verify get_all was called with correct filters
        mock_get_all.assert_called_once()
        call_args = mock_get_all.call_args
        self.assertEqual(call_args[0][0], "SEPA Mandate")
        self.assertEqual(call_args[1]["filters"]["status"], "Active")

        # Verify email was sent
        mock_email.assert_called_once()

    def test_notification_error_handling(self):
        """Test that notification errors don't break the system"""
        # Create a member without email
        member_no_email = frappe.get_doc(
            {"doctype": "Member", "member_name": "No Email Member", "email": ""}  # No email
        ).insert()

        mandate_no_email = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": member_no_email.name,
                "mandate_id": "TEST-MANDATE-NOEMAIL",
                "iban": "NL39RABO0300065264",
                "bic": "RABONL2U",
                "account_holder_name": "Test Account Holder",
                "sign_date": today(),
                "status": "Active"}
        ).insert()

        # These should not raise exceptions
        try:
            self.notification_manager.send_mandate_created_notification(mandate_no_email)
            self.notification_manager.send_mandate_cancelled_notification(mandate_no_email)
            self.notification_manager.send_mandate_expiring_notification(mandate_no_email, 30)
        except Exception as e:
            self.fail(f"Notification without email raised exception: {e}")

        # Clean up
        mandate_no_email.delete()
        member_no_email.delete()


class TestPaymentNotifications(unittest.TestCase):
    """Test payment notification handlers"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test customer
        if not frappe.db.exists("Customer", "TEST-PAYMENT-CUSTOMER"):
            cls.test_customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": "Test Payment Customer",
                    "customer_type": "Individual",
                    "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name")}
            ).insert()
        else:
            cls.test_customer = frappe.get_doc("Customer", "TEST-PAYMENT-CUSTOMER")

        # Create test member
        if not frappe.db.exists("Member", {"email": "payment-test@example.com"}):
            cls.test_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "member_name": "Test Payment Member",
                    "email": "payment-test@example.com",
                    "customer": cls.test_customer.name}
            ).insert()
        else:
            cls.test_member = frappe.get_doc("Member", {"email": "payment-test@example.com"})

    @classmethod
    def tearDownClass(cls):
        """Clean up test data"""
        if cls.test_member and frappe.db.exists("Member", cls.test_member.name):
            frappe.delete_doc("Member", cls.test_member.name, force=True)

        if cls.test_customer and frappe.db.exists("Customer", cls.test_customer.name):
            frappe.delete_doc("Customer", cls.test_customer.name, force=True)

    @patch("verenigingen.utils.payment_notifications.check_and_resolve_payment_retries")
    @patch(
        "verenigingen.utils.sepa_notifications.SEPAMandateNotificationManager.send_payment_success_notification"
    )
    def test_on_payment_submit(self, mock_send_notification, mock_resolve_retries):
        """Test payment submission handler"""
        # Create mock payment entry
        payment = MagicMock()
        payment.party_type = "Customer"
        payment.party = self.test_customer.name
        payment.paid_amount = 100

        # Call handler
        on_payment_submit(payment, None)

        # Verify notifications were triggered
        mock_send_notification.assert_called_once_with(payment)
        mock_resolve_retries.assert_called_once_with(payment, self.test_member.name)

    def test_check_and_resolve_payment_retries(self):
        """Test payment retry resolution"""
        # Create test invoice
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": self.test_customer.name,
                "posting_date": today(),
                "items": [
                    {
                        "item_code": frappe.db.get_value("Item", {"item_group": {"!=": ""}}, "name"),
                        "qty": 1,
                        "rate": 100}
                ]}
        ).insert()
        invoice.submit()

        # Create retry record
        retry = frappe.get_doc(
            {
                "doctype": "SEPA Payment Retry",
                "invoice": invoice.name,
                "member": self.test_member.name,
                "original_amount": 100,
                "status": "Scheduled"}
        ).insert()

        # Create payment entry with reference
        payment = MagicMock()
        payment.posting_date = today()
        payment.mode_of_payment = "Bank Transfer"
        payment.name = "TEST-PAYMENT-001"

        # Mock payment reference
        ref = MagicMock()
        ref.reference_doctype = "Sales Invoice"
        ref.reference_name = invoice.name
        payment.references = [ref]

        # Resolve retries
        check_and_resolve_payment_retries(payment, self.test_member.name)

        # Check retry was resolved
        retry.reload()
        self.assertEqual(retry.status, "Resolved")
        self.assertEqual(retry.resolution_method, "Payment Received")
        self.assertEqual(retry.resolution_reference, payment.name)

        # Clean up
        retry.delete()
        invoice.cancel()
        invoice.delete()

    @patch("frappe.log_error")
    def test_payment_notification_error_handling(self, mock_log_error):
        """Test that errors in payment notifications don't block payment"""
        # Create payment that will cause an error (no party)
        payment = MagicMock()
        payment.party_type = "Customer"
        payment.party = None  # This will cause an error
        payment.paid_amount = 100

        # Should not raise exception
        try:
            on_payment_submit(payment, None)
        except Exception as e:
            self.fail(f"Payment notification error was not handled: {e}")

        # Verify error was logged
        mock_log_error.assert_called_once()


def run_tests():
    """Run all SEPA notification tests"""
    suite = unittest.TestSuite()

    # Add notification tests
    suite.addTest(unittest.makeSuite(TestSEPANotifications))
    suite.addTest(unittest.makeSuite(TestPaymentNotifications))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    run_tests()
