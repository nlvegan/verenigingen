import unittest
from unittest.mock import MagicMock, patch

from frappe.utils import add_days, today


class TestPaymentReportIntegration(unittest.TestCase):
    """Integration tests for the complete payment reporting workflow"""

    def setUp(self):
        """Set up integration test environment"""
        self.test_data = self.create_mock_test_data()

    def create_mock_test_data(self):
        """Create comprehensive mock test data"""
        return {
            "members": [
                {
                    "name": "MEM-001",
                    "full_name": "John Doe",
                    "email": "john@example.com",
                    "primary_chapter": "Amsterdam",
                    "customer": "CUST-001",
                },
                {
                    "name": "MEM-002",
                    "full_name": "Jane Smith",
                    "email": "jane@example.com",
                    "primary_chapter": "Rotterdam",
                    "customer": "CUST-002",
                },
            ],
            "invoices": [
                {
                    "name": "SINV-001",
                    "customer": "CUST-001",
                    "status": "Overdue",
                    "due_date": add_days(today(), -45),
                    "posting_date": add_days(today(), -75),
                    "outstanding_amount": 150.00,
                    "subscription": "SUB-001",
                    "docstatus": 1,
                },
                {
                    "name": "SINV-002",
                    "customer": "CUST-002",
                    "status": "Overdue",
                    "due_date": add_days(today(), -70),
                    "posting_date": add_days(today(), -100),
                    "outstanding_amount": 75.00,
                    "subscription": "SUB-002",
                    "docstatus": 1,
                },
            ],
            "subscriptions": [
                {"name": "SUB-001", "reference_doctype": "Membership Type"},
                {"name": "SUB-002", "reference_doctype": "Membership Type"},
            ],
            "memberships": [
                {"member": "MEM-001", "membership_type": "Regular", "status": "Active"},
                {"member": "MEM-002", "membership_type": "Student", "status": "Active"},
            ],
        }

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_chapter_filter"
    )
    def test_complete_report_workflow_admin_user(self, mock_chapter_filter, mock_sql):
        """Test complete report workflow for admin user"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute

        # Mock admin user (no chapter filter)
        mock_chapter_filter.return_value = None

        # Mock SQL response
        mock_sql.return_value = [
            {
                "member_name": "MEM-001",
                "member_full_name": "John Doe",
                "member_email": "john@example.com",
                "chapter": "Amsterdam",
                "overdue_count": 2,
                "total_overdue": 150.00,
                "oldest_invoice_date": add_days(today(), -75),
                "days_overdue": 45,
                "membership_type": "Regular",
                "last_payment_date": add_days(today(), -60),
            },
            {
                "member_name": "MEM-002",
                "member_full_name": "Jane Smith",
                "member_email": "jane@example.com",
                "chapter": "Rotterdam",
                "overdue_count": 1,
                "total_overdue": 75.00,
                "oldest_invoice_date": add_days(today(), -100),
                "days_overdue": 70,
                "membership_type": "Student",
                "last_payment_date": add_days(today(), -90),
            },
        ]

        # Execute report
        columns, data, message, chart, summary = execute({})

        # Verify report structure
        self.assertIsInstance(columns, list)
        self.assertIsInstance(data, list)
        self.assertIsNone(message)
        self.assertIsInstance(chart, dict)
        self.assertIsInstance(summary, list)

        # Verify data content
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["member_name"], "MEM-001")
        self.assertEqual(data[1]["member_name"], "MEM-002")

        # Verify status indicators
        self.assertIn("Urgent", data[0]["status_indicator"])  # 45 days
        self.assertIn("Critical", data[1]["status_indicator"])  # 70 days

        # Verify summary calculations
        summary_dict = {item["label"]: item["value"] for item in summary}
        self.assertEqual(summary_dict["Members with Overdue Payments"], 2)
        self.assertEqual(summary_dict["Total Overdue Amount"], 225.00)
        self.assertEqual(summary_dict["Critical (>60 days)"], 1)

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_chapter_filter"
    )
    def test_complete_report_workflow_chapter_user(self, mock_chapter_filter, mock_sql):
        """Test complete report workflow for chapter board member"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute

        # Mock chapter-restricted user
        mock_chapter_filter.return_value = "(m.primary_chapter = 'Amsterdam')"

        # Mock SQL response (only Amsterdam members)
        mock_sql.return_value = [
            {
                "member_name": "MEM-001",
                "member_full_name": "John Doe",
                "member_email": "john@example.com",
                "chapter": "Amsterdam",
                "overdue_count": 2,
                "total_overdue": 150.00,
                "oldest_invoice_date": add_days(today(), -75),
                "days_overdue": 45,
                "membership_type": "Regular",
                "last_payment_date": add_days(today(), -60),
            }
        ]

        # Execute report
        columns, data, message, chart, summary = execute({})

        # Verify filtered results
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["chapter"], "Amsterdam")

        # Verify summary reflects filtered data
        summary_dict = {item["label"]: item["value"] for item in summary}
        self.assertEqual(summary_dict["Members with Overdue Payments"], 1)
        self.assertEqual(summary_dict["Total Overdue Amount"], 150.00)

    @patch("verenigingen.api.payment_processing.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    def test_complete_reminder_workflow(self, mock_send_email, mock_get_data):
        """Test complete payment reminder workflow"""
        from verenigingen.api.payment_processing import send_overdue_payment_reminders

        # Mock report data
        mock_get_data.return_value = [
            {
                "member_name": "MEM-001",
                "member_full_name": "John Doe",
                "member_email": "john@example.com",
                "chapter": "Amsterdam",
                "total_overdue": 150.00,
                "overdue_count": 2,
                "days_overdue": 45,
            }
        ]

        # Mock successful email sending
        mock_send_email.return_value = True

        # Execute reminder workflow
        result = send_overdue_payment_reminders(
            reminder_type="Urgent Notice", include_payment_link=True, custom_message="Please pay immediately."
        )

        # Verify workflow completion
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)

        # Verify email function was called correctly
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs["member_name"], "MEM-001")
        self.assertEqual(call_kwargs["reminder_type"], "Urgent Notice")
        self.assertTrue(call_kwargs["include_payment_link"])
        self.assertEqual(call_kwargs["custom_message"], "Please pay immediately.")

    @patch("verenigingen.api.payment_processing.get_data")
    def test_complete_export_workflow(self, mock_get_data):
        """Test complete export workflow"""
        from verenigingen.api.payment_processing import export_overdue_payments

        # Mock report data
        mock_get_data.return_value = [
            {
                "member_name": "MEM-001",
                "member_full_name": "John Doe",
                "member_email": "john@example.com",
                "chapter": "Amsterdam",
                "overdue_count": 2,
                "total_overdue": 150.00,
                "oldest_invoice_date": add_days(today(), -75),
                "days_overdue": 45,
                "membership_type": "Regular",
                "last_payment_date": add_days(today(), -60),
            }
        ]

        # Mock file operations
        with patch("builtins.open", create=True) as mock_open:
            with patch("csv.DictWriter") as mock_csv_writer:
                with patch("frappe.get_doc") as mock_get_doc:
                    # Mock file document
                    mock_file_doc = MagicMock()
                    mock_file_doc.file_url = "/files/export.csv"
                    mock_get_doc.return_value = mock_file_doc

                    # Execute export workflow
                    result = export_overdue_payments(filters={"chapter": "Amsterdam"}, format="CSV")

                    # Verify export completion
                    self.assertTrue(result["success"])
                    self.assertEqual(result["count"], 1)
                    self.assertIn("file_url", result)

                    # Verify CSV operations
                    mock_csv_writer.assert_called_once()

    @patch("verenigingen.api.payment_processing.get_data")
    @patch("verenigingen.api.payment_processing.send_payment_reminder_email")
    @patch("verenigingen.api.payment_processing.suspend_member_for_nonpayment")
    def test_complete_bulk_action_workflow(self, mock_suspend, mock_send_email, mock_get_data):
        """Test complete bulk action workflow"""
        from verenigingen.api.payment_processing import execute_bulk_payment_action

        # Mock report data
        mock_get_data.return_value = [
            {"member_name": "MEM-001", "days_overdue": 70, "total_overdue": 150.00},  # Critical
            {"member_name": "MEM-002", "days_overdue": 35, "total_overdue": 75.00},  # Urgent
        ]

        # Mock successful operations
        mock_send_email.return_value = True
        mock_suspend.return_value = True

        # Test bulk reminder action
        result = execute_bulk_payment_action(action="Send Payment Reminders", apply_to="All Visible Records")

        # Verify bulk action completion
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(mock_send_email.call_count, 2)

        # Reset mocks
        mock_send_email.reset_mock()
        mock_suspend.reset_mock()

        # Test bulk suspension action for critical only
        result = execute_bulk_payment_action(
            action="Suspend Memberships", apply_to="Critical Only (>60 days)"
        )

        # Verify critical filter was applied
        call_args = mock_get_data.call_args[0][0]
        self.assertTrue(call_args.get("critical_only"))

    def test_permission_integration_workflow(self):
        """Test permission integration workflow"""
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
            get_user_chapter_filter,
        )

        # Test admin access
        with patch("frappe.session.user", "admin@test.com"):
            with patch("frappe.get_roles", return_value=["System Manager"]):
                result = get_user_chapter_filter()
                self.assertIsNone(result)  # No restrictions

        # Test chapter board member access
        with patch("frappe.session.user", "board@test.com"):
            with patch("frappe.get_roles", return_value=["Chapter Board Member"]):
                with patch("frappe.db.get_value", return_value="MEM-BOARD"):
                    with patch("frappe.get_all") as mock_get_all:
                        with patch("frappe.get_doc") as mock_get_doc:
                            # Mock volunteer and board position
                            mock_get_all.side_effect = [
                                [{"name": "VOL-001"}],  # Volunteer records
                                [{"parent": "Amsterdam", "chapter_role": "ROLE-001"}],  # Board positions
                            ]

                            # Mock role with finance permissions
                            mock_role = MagicMock()
                            mock_role.permissions_level = "Finance"
                            mock_get_doc.return_value = mock_role

                            result = get_user_chapter_filter()

                            # Should have chapter-specific filter
                            self.assertIsInstance(result, str)
                            self.assertIn("Amsterdam", result)

        # Test unauthorized access
        with patch("frappe.session.user", "user@test.com"):
            with patch("frappe.get_roles", return_value=["Member"]):
                with patch("frappe.db.get_value", return_value=None):
                    result = get_user_chapter_filter()
                    self.assertEqual(result, "1=0")  # Deny access

    def test_error_handling_workflow(self):
        """Test error handling throughout the workflow"""
        from verenigingen.api.payment_processing import send_overdue_payment_reminders

        # Test with invalid data
        with patch("verenigingen.api.payment_processing.get_data", side_effect=Exception("Database error")):
            with self.assertRaises(Exception):
                send_overdue_payment_reminders()

        # Test with partial failures
        with patch("verenigingen.api.payment_processing.get_data") as mock_get_data:
            with patch("verenigingen.api.payment_processing.send_payment_reminder_email") as mock_send_email:
                mock_get_data.return_value = [{"member_name": "MEM-001"}, {"member_name": "MEM-002"}]

                # First succeeds, second fails
                mock_send_email.side_effect = [True, Exception("Email failed")]

                result = send_overdue_payment_reminders()

                # Should still report partial success
                self.assertTrue(result["success"])
                self.assertEqual(result["count"], 1)


if __name__ == "__main__":
    unittest.main()
