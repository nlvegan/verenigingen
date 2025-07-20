import json
import unittest
from unittest.mock import MagicMock, patch

from verenigingen.api.payment_processing import (
    create_application_invoice,
    execute_bulk_payment_action,
    export_overdue_payments,
    generate_payment_reminder_html,
    get_or_create_customer,
    send_overdue_payment_reminders,
    send_payment_reminder_email,
)


class TestPaymentProcessingAPI(unittest.TestCase):
    """Test suite for payment processing API endpoints"""

    def setUp(self):
        """Set up test data"""
        self.sample_payment_info = {
            "member_name": "MEM-001",
            "member_full_name": "John Doe",
            "member_email": "john@example.com",
            "chapter": "Amsterdam",
            "overdue_count": 2,
            "total_overdue": 150.00,
            "days_overdue": 45,
            "membership_type": "Regular"}

        self.sample_overdue_data = [self.sample_payment_info]

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    def test_send_overdue_payment_reminders_success(self, mock_send_email, mock_get_data):
        """Test successful payment reminder sending"""
        mock_get_data.return_value = self.sample_overdue_data
        mock_send_email.return_value = True

        result = send_overdue_payment_reminders(
            reminder_type="Friendly Reminder",
            include_payment_link=True,
            filters=json.dumps({"chapter": "Amsterdam"}),
        )

        # Verify successful response
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertIn("successfully", result["message"])

        # Verify email sending was called
        mock_send_email.assert_called_once()
        call_args = mock_send_email.call_args[1]
        self.assertEqual(call_args["member_name"], "MEM-001")
        self.assertEqual(call_args["reminder_type"], "Friendly Reminder")
        self.assertTrue(call_args["include_payment_link"])

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    def test_send_overdue_payment_reminders_no_data(self, mock_get_data):
        """Test payment reminders with no overdue data"""
        mock_get_data.return_value = []

        result = send_overdue_payment_reminders()

        # Verify no data response
        self.assertFalse(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertIn("No overdue payments found", result["message"])

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    def test_send_overdue_payment_reminders_with_chapter_notification(self, mock_send_email, mock_get_data):
        """Test payment reminders with chapter notifications"""
        mock_get_data.return_value = self.sample_overdue_data
        mock_send_email.return_value = True

        with patch("verenigingen.api.payment_processing.send_chapter_notification") as mock_chapter_notify:
            mock_chapter_notify.return_value = True

            result = send_overdue_payment_reminders(send_to_chapters=True, filters=json.dumps({}))

            # Verify chapter notification was called
            mock_chapter_notify.assert_called_once()
            call_args = mock_chapter_notify.call_args[1]
            self.assertEqual(call_args["chapter"], "Amsterdam")
            self.assertEqual(call_args["member_name"], "MEM-001")

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    def test_send_overdue_payment_reminders_partial_failure(self, mock_send_email, mock_get_data):
        """Test payment reminders with some failures"""
        # Multiple members, one fails
        multiple_data = [
            self.sample_payment_info,
            {
                "member_name": "MEM-002",
                "member_full_name": "Jane Smith",
                "member_email": "jane@example.com",
                "chapter": "Rotterdam",
                "overdue_count": 1,
                "total_overdue": 75.00,
                "days_overdue": 30,
                "membership_type": "Student"},
        ]

        mock_get_data.return_value = multiple_data
        # First call succeeds, second fails
        mock_send_email.side_effect = [True, Exception("Email failed")]

        result = send_overdue_payment_reminders()

        # Should still report success for the one that worked
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    def test_export_overdue_payments_success(self, mock_get_data):
        """Test successful payment data export"""
        mock_get_data.return_value = self.sample_overdue_data

        with patch("builtins.open", create=True) as mock_open:
            with patch("csv.DictWriter") as mock_csv_writer:
                with patch("frappe.get_doc") as mock_get_doc:
                    # Mock file document creation
                    mock_file_doc = MagicMock()
                    mock_file_doc.file_url = "/files/test.csv"
                    mock_get_doc.return_value = mock_file_doc

                    result = export_overdue_payments(filters=json.dumps({"chapter": "Amsterdam"}))

                    # Verify successful export
                    self.assertTrue(result["success"])
                    self.assertEqual(result["count"], 1)
                    self.assertIn("Export completed", result["message"])
                    self.assertIn("file_url", result)

                    # Verify CSV writer was used
                    mock_csv_writer.assert_called_once()

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    def test_export_overdue_payments_no_data(self, mock_get_data):
        """Test export with no data"""
        mock_get_data.return_value = []

        result = export_overdue_payments()

        # Verify no data response
        self.assertFalse(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertIn("No data to export", result["message"])

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    def test_export_overdue_payments_file_error(self, mock_get_data):
        """Test export with file creation error"""
        mock_get_data.return_value = self.sample_overdue_data

        with patch("builtins.open", side_effect=Exception("File error")):
            with patch("frappe.logger") as mock_logger:
                result = export_overdue_payments()

                # Verify error response
                self.assertFalse(result["success"])
                self.assertIn("Export failed", result["message"])

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    def test_execute_bulk_payment_action_send_reminders(self, mock_send_email, mock_get_data):
        """Test bulk action: send reminders"""
        mock_get_data.return_value = self.sample_overdue_data
        mock_send_email.return_value = True

        result = execute_bulk_payment_action(
            action="Send Payment Reminders", apply_to="All Visible Records", filters=json.dumps({})
        )

        # Verify successful bulk action
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)

        # Verify reminder was sent
        mock_send_email.assert_called_once()

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    @patch("verenigingen.api.payment_processing.suspend_member_for_nonpayment")
    def test_execute_bulk_payment_action_suspend_memberships(self, mock_suspend, mock_get_data):
        """Test bulk action: suspend memberships"""
        mock_get_data.return_value = self.sample_overdue_data
        mock_suspend.return_value = True

        result = execute_bulk_payment_action(
            action="Suspend Memberships", apply_to="Critical Only (>60 days)", filters=json.dumps({})
        )

        # Verify successful bulk action
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)

        # Verify suspension was called
        mock_suspend.assert_called_once_with("MEM-001")

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data")
    def test_execute_bulk_payment_action_filters(self, mock_get_data):
        """Test bulk action filter application"""
        mock_get_data.return_value = []

        # Test critical filter application
        execute_bulk_payment_action(
            action="Send Payment Reminders",
            apply_to="Critical Only (>60 days)",
            filters=json.dumps({"chapter": "Amsterdam"}),
        )

        # Verify get_data was called with critical filter
        call_args = mock_get_data.call_args[0][0]
        self.assertTrue(call_args.get("critical_only"))

        # Reset mock
        mock_get_data.reset_mock()

        # Test urgent filter application
        execute_bulk_payment_action(
            action="Send Payment Reminders", apply_to="Urgent Only (>30 days)", filters=json.dumps({})
        )

        # Verify get_data was called with urgent filter
        call_args = mock_get_data.call_args[0][0]
        self.assertTrue(call_args.get("urgent_only"))

    @patch("frappe.get_doc")
    @patch("frappe.sendmail")
    def test_send_payment_reminder_email_with_template(self, mock_sendmail, mock_get_doc):
        """Test sending payment reminder with email template"""
        # Mock member document
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.first_name = "John"
        mock_get_doc.return_value = mock_member

        # Mock template existence
        with patch("frappe.db.exists", return_value=True):
            result = send_payment_reminder_email(
                member_name="MEM-001",
                reminder_type="Friendly Reminder",
                payment_info=self.sample_payment_info,
            )

            # Verify email was sent
            self.assertTrue(result)
            mock_sendmail.assert_called_once()

            # Verify template was used
            call_args = mock_sendmail.call_args[1]
            self.assertEqual(call_args["template"], "payment_reminder_friendly")

    @patch("frappe.get_doc")
    @patch("frappe.sendmail")
    def test_send_payment_reminder_email_fallback_html(self, mock_sendmail, mock_get_doc):
        """Test sending payment reminder with HTML fallback"""
        # Mock member document
        mock_member = MagicMock()
        mock_member.email = "test@example.com"
        mock_member.first_name = "John"
        mock_get_doc.return_value = mock_member

        # Mock no template exists
        with patch("frappe.db.exists", return_value=False):
            result = send_payment_reminder_email(
                member_name="MEM-001", reminder_type="Urgent Notice", payment_info=self.sample_payment_info
            )

            # Verify email was sent with HTML message
            self.assertTrue(result)
            mock_sendmail.assert_called_once()

            # Verify HTML message was used (no template)
            call_args = mock_sendmail.call_args[1]
            self.assertIn("message", call_args)
            self.assertNotIn("template", call_args)

    @patch("frappe.get_doc")
    def test_send_payment_reminder_email_no_email_address(self, mock_get_doc):
        """Test sending payment reminder to member without email"""
        # Mock member document without email
        mock_member = MagicMock()
        mock_member.email = None
        mock_get_doc.return_value = mock_member

        result = send_payment_reminder_email(member_name="MEM-001", payment_info=self.sample_payment_info)

        # Should return False (failed)
        self.assertFalse(result)

    def test_generate_payment_reminder_html(self):
        """Test HTML email generation"""
        # Mock member object
        member = MagicMock()
        member.first_name = "John"

        html = generate_payment_reminder_html(
            member=member,
            payment_info=self.sample_payment_info,
            reminder_type="Final Notice",
            custom_message="Please contact us immediately.",
        )

        # Verify HTML content
        self.assertIn("John", html)
        self.assertIn("final notice", html.lower())
        self.assertIn("150", html)  # Amount
        self.assertIn("2", html)  # Invoice count
        self.assertIn("45", html)  # Days overdue
        self.assertIn("Please contact us immediately", html)

    @patch("verenigingen.utils.termination_integration.suspend_member_safe")
    def test_suspend_member_for_nonpayment(self, mock_suspend):
        """Test member suspension for non-payment"""
        from verenigingen.api.payment_processing import suspend_member_for_nonpayment

        mock_suspend.return_value = True

        result = suspend_member_for_nonpayment("MEM-001")

        # Verify suspension was called correctly
        self.assertTrue(result)
        mock_suspend.assert_called_once_with(
            member_name="MEM-001",
            suspension_reason="Non-payment of membership fees",
            suspend_user=False,
            suspend_teams=True,
        )

    def test_filter_json_parsing(self):
        """Test JSON filter parsing in API endpoints"""
        filters_dict = {"chapter": "Amsterdam", "days_overdue": 30}
        filters_json = json.dumps(filters_dict)

        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
        ) as mock_get_data:
            mock_get_data.return_value = []

            # Test with JSON string
            send_overdue_payment_reminders(filters=filters_json)

            # Verify filters were parsed correctly
            call_args = mock_get_data.call_args[0][0]
            self.assertEqual(call_args["chapter"], "Amsterdam")
            self.assertEqual(call_args["days_overdue"], 30)

            # Reset mock
            mock_get_data.reset_mock()

            # Test with dict (should work the same)
            send_overdue_payment_reminders(filters=filters_dict)

            # Verify filters were passed correctly
            call_args = mock_get_data.call_args[0][0]
            self.assertEqual(call_args["chapter"], "Amsterdam")


class TestPaymentProcessingEmailTemplates(unittest.TestCase):
    """Test email template functionality"""

    def test_reminder_subject_generation(self):
        """Test email subject generation"""
        from verenigingen.api.payment_processing import get_reminder_subject

        payment_info = {"total_overdue": 100, "days_overdue": 30}

        subjects = {
            "Friendly Reminder": get_reminder_subject("Friendly Reminder", payment_info),
            "Urgent Notice": get_reminder_subject("Urgent Notice", payment_info),
            "Final Notice": get_reminder_subject("Final Notice", payment_info),
            "Unknown": get_reminder_subject("Unknown Type", payment_info)}

        # Verify different subjects
        self.assertIn("Payment Reminder", subjects["Friendly Reminder"])
        self.assertIn("URGENT", subjects["Urgent Notice"])
        self.assertIn("FINAL NOTICE", subjects["Final Notice"])
        self.assertIn("Payment Reminder", subjects["Unknown"])  # Fallback

    def test_create_application_invoice_function_exists(self):
        """Test that create_application_invoice function is importable and callable"""
        # This test verifies the import error fix

        # Function should be callable
        self.assertTrue(callable(create_application_invoice))

        # Function should have proper docstring
        self.assertIn("application", create_application_invoice.__doc__.lower())

        print("✅ create_application_invoice function imported successfully")

    def test_get_or_create_customer_function_exists(self):
        """Test that get_or_create_customer function is importable and callable"""
        # This test verifies the import error fix

        # Function should be callable
        self.assertTrue(callable(get_or_create_customer))

        # Function should have proper docstring
        self.assertIn("customer", get_or_create_customer.__doc__.lower())

        print("✅ get_or_create_customer function imported successfully")

    @patch("verenigingen.utils.application_payments.create_membership_invoice_with_amount")
    def test_create_application_invoice_delegates_correctly(self, mock_create_invoice):
        """Test that create_application_invoice properly delegates to application_payments module"""
        from unittest.mock import MagicMock

        # Mock return value
        mock_invoice = MagicMock()
        mock_create_invoice.return_value = mock_invoice

        # Mock inputs
        mock_member = MagicMock()
        mock_membership = MagicMock()
        mock_membership.membership_type = "Test Type"
        mock_membership.uses_custom_amount = True
        mock_membership.custom_amount = 75.0

        # Mock membership type
        with patch("frappe.get_doc") as mock_get_doc:
            mock_membership_type = MagicMock()
            mock_membership_type.amount = 50.0
            mock_get_doc.return_value = mock_membership_type

            # Call function
            result = create_application_invoice(mock_member, mock_membership)

            # Verify delegation
            mock_create_invoice.assert_called_once_with(mock_member, mock_membership, 75.0)
            self.assertEqual(result, mock_invoice)

        print("✅ create_application_invoice delegates correctly to application_payments module")

    @patch("verenigingen.utils.application_payments.create_customer_for_member")
    def test_get_or_create_customer_delegates_correctly(self, mock_create_customer):
        """Test that get_or_create_customer properly delegates to application_payments module"""
        from unittest.mock import MagicMock

        # Test case 1: Member already has customer
        mock_member = MagicMock()
        mock_member.customer = "CUST-001"

        with patch("frappe.get_doc") as mock_get_doc:
            mock_customer = MagicMock()
            mock_get_doc.return_value = mock_customer

            result = get_or_create_customer(mock_member)

            # Should return existing customer
            mock_get_doc.assert_called_once_with("Customer", "CUST-001")
            self.assertEqual(result, mock_customer)
            mock_create_customer.assert_not_called()

        # Test case 2: Member doesn't have customer
        mock_member.customer = None
        mock_new_customer = MagicMock()
        mock_new_customer.name = "CUST-002"
        mock_create_customer.return_value = mock_new_customer

        result = get_or_create_customer(mock_member)

        # Should create new customer and update member
        mock_create_customer.assert_called_once_with(mock_member)
        mock_member.db_set.assert_called_once_with("customer", "CUST-002")
        self.assertEqual(result, mock_new_customer)

        print("✅ get_or_create_customer delegates correctly to application_payments module")


if __name__ == "__main__":
    unittest.main()
