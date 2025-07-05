import unittest
from unittest.mock import MagicMock, patch

from frappe.utils import add_days, today

from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
    execute,
    get_chart_data,
    get_data,
    get_summary,
    get_user_accessible_chapters,
)


class TestOverduePaymentsReport(unittest.TestCase):
    """Test suite for Overdue Member Payments report"""

    def setUp(self):
        """Set up test data"""
        self.maxDiff = None

        # Mock data for testing
        self.sample_overdue_data = [
            {
                "member_name": "MEM-001",
                "member_full_name": "John Doe",
                "member_email": "john@example.com",
                "chapter": "Amsterdam",
                "overdue_count": 2,
                "total_overdue": 150.00,
                "oldest_invoice_date": add_days(today(), -45),
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
                "oldest_invoice_date": add_days(today(), -70),
                "days_overdue": 70,
                "membership_type": "Student",
                "last_payment_date": add_days(today(), -90),
            },
            {
                "member_name": "MEM-003",
                "member_full_name": "Bob Wilson",
                "member_email": "bob@example.com",
                "chapter": "Amsterdam",
                "overdue_count": 3,
                "total_overdue": 225.00,
                "oldest_invoice_date": add_days(today(), -20),
                "days_overdue": 20,
                "membership_type": "Regular",
                "last_payment_date": add_days(today(), -30),
            },
        ]

    def test_execute_function_structure(self):
        """Test that execute function returns correct structure"""
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
        ) as mock_get_data:
            mock_get_data.return_value = self.sample_overdue_data

            columns, data, message, chart, summary = execute({})

            # Test return structure
            self.assertIsInstance(columns, list)
            self.assertIsInstance(data, list)
            self.assertIsNone(message)
            self.assertIsInstance(chart, dict)
            self.assertIsInstance(summary, list)

            # Test columns structure
            self.assertGreater(len(columns), 0)
            for column in columns:
                self.assertIn("label", column)
                self.assertIn("fieldname", column)
                self.assertIn("fieldtype", column)

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
    )
    def test_get_data_basic_query(self, mock_chapter_filter, mock_sql):
        """Test basic data retrieval and query construction"""
        mock_chapter_filter.return_value = None  # Admin user
        mock_sql.return_value = self.sample_overdue_data

        filters = {"chapter": "Amsterdam"}
        get_data(filters)

        # Verify SQL was called
        mock_sql.assert_called_once()

        # Check query structure
        sql_call = mock_sql.call_args[0][0]
        self.assertIn("sales invoice", sql_call.lower())
        self.assertIn("member", sql_call.lower())
        self.assertIn("subscription", sql_call.lower())
        self.assertIn("overdue", sql_call.lower())

        # Verify filters were applied
        self.assertIn("m.primary_chapter = %(chapter)s", sql_call)

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
    )
    def test_get_data_with_filters(self, mock_chapter_filter, mock_sql):
        """Test data retrieval with various filters"""
        mock_chapter_filter.return_value = None
        mock_sql.return_value = self.sample_overdue_data

        # Test with multiple filters
        filters = {
            "chapter": "Amsterdam",
            "membership_type": "Regular",
            "days_overdue": 30,
            "critical_only": True,
            "urgent_only": False,
        }

        get_data(filters)

        # Verify SQL query includes all filter conditions
        sql_call = mock_sql.call_args[0][0]
        self.assertIn("m.primary_chapter = %(chapter)s", sql_call)
        self.assertIn("ms.membership_type = %(membership_type)s", sql_call)

        # Check critical_only filter (60+ days)
        self.assertIn("si.due_date < '", sql_call)

    def test_status_indicator_logic(self):
        """Test status indicator assignment based on days overdue"""
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql"
        ) as mock_sql:
            with patch(
                "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
            ) as mock_filter:
                mock_filter.return_value = None
                mock_sql.return_value = [
                    {"days_overdue": 70, "total_overdue": 100},  # Critical
                    {"days_overdue": 45, "total_overdue": 50},  # Urgent
                    {"days_overdue": 20, "total_overdue": 25},  # Overdue
                    {"days_overdue": 5, "total_overdue": 75},  # Due
                ]

                result = get_data({})

                # Check status indicators
                self.assertIn("Critical", result[0]["status_indicator"])
                self.assertIn("Urgent", result[1]["status_indicator"])
                self.assertIn("Overdue", result[2]["status_indicator"])
                self.assertIn("Due", result[3]["status_indicator"])

    @patch("frappe.session.user", "admin@example.com")
    @patch("frappe.get_roles")
    def test_get_user_accessible_chapters_admin_access(self, mock_get_roles):
        """Test chapter filtering for admin users"""
        mock_get_roles.return_value = ["System Manager"]

        result = get_user_accessible_chapters()

        # Admin should have no filter (see all)
        self.assertIsNone(result)

    @patch("frappe.session.user", "board@example.com")
    @patch("frappe.get_roles")
    @patch("frappe.db.get_value")
    @patch("frappe.get_all")
    @patch("frappe.get_doc")
    def test_get_user_accessible_chapters_board_member_access(
        self, mock_get_doc, mock_get_all, mock_get_value, mock_get_roles
    ):
        """Test chapter filtering for board members"""
        mock_get_roles.return_value = ["Chapter Board Member"]
        mock_get_value.return_value = "MEM-BOARD-001"

        # Mock volunteer records
        mock_get_all.side_effect = [
            [{"name": "VOL-001"}],  # Volunteer records
            [{"parent": "Amsterdam", "chapter_role": "ROLE-001"}],  # Board positions
        ]

        # Mock chapter role with membership permissions
        mock_role = MagicMock()
        mock_role.permissions_level = "Membership"
        mock_get_doc.return_value = mock_role

        result = get_user_accessible_chapters()

        # Should return chapter filter
        self.assertIsInstance(result, str)
        self.assertIn("Amsterdam", result)
        self.assertIn("primary_chapter", result)

    @patch("frappe.session.user", "user@example.com")
    @patch("frappe.get_roles")
    @patch("frappe.db.get_value")
    def test_get_user_accessible_chapters_no_access(self, mock_get_value, mock_get_roles):
        """Test chapter filtering for users without access"""
        mock_get_roles.return_value = ["Member"]
        mock_get_value.return_value = None  # No member record

        result = get_user_accessible_chapters()

        # Should deny access
        self.assertEqual(result, "1=0")

    def test_get_summary_calculations(self):
        """Test summary statistics calculations"""
        summary = get_summary(self.sample_overdue_data)

        # Verify summary structure
        self.assertIsInstance(summary, list)
        self.assertGreater(len(summary), 0)

        # Find specific summary items
        summary_dict = {item["label"]: item["value"] for item in summary}

        # Test calculations
        self.assertEqual(summary_dict["Members with Overdue Payments"], 3)
        self.assertEqual(summary_dict["Total Overdue Invoices"], 6)  # 2+1+3
        self.assertEqual(summary_dict["Total Overdue Amount"], 450.00)  # 150+75+225
        self.assertEqual(summary_dict["Critical (>60 days)"], 1)  # Jane with 70 days
        self.assertEqual(summary_dict["Urgent (>30 days)"], 2)  # John (45) + Jane (70)

    def test_get_summary_empty_data(self):
        """Test summary with no data"""
        summary = get_summary([])

        self.assertEqual(summary, [])

    def test_get_chart_data_structure(self):
        """Test chart data generation"""
        chart = get_chart_data(self.sample_overdue_data)

        # Verify chart structure
        self.assertIsInstance(chart, dict)
        self.assertIn("data", chart)
        self.assertIn("type", chart)
        self.assertIn("colors", chart)

        # Test data structure
        chart_data = chart["data"]
        self.assertIn("labels", chart_data)
        self.assertIn("datasets", chart_data)

        # Test aggregation by chapter
        labels = chart_data["labels"]
        values = chart_data["datasets"][0]["values"]

        # Amsterdam: 150 + 225 = 375, Rotterdam: 75
        amsterdam_index = labels.index("Amsterdam")
        rotterdam_index = labels.index("Rotterdam")

        self.assertEqual(values[amsterdam_index], 375.00)
        self.assertEqual(values[rotterdam_index], 75.00)

    def test_get_chart_data_empty(self):
        """Test chart data with no data"""
        chart = get_chart_data([])

        self.assertIsNone(chart)

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
    )
    def test_filter_combinations(self, mock_chapter_filter, mock_sql):
        """Test various filter combinations"""
        mock_chapter_filter.return_value = None
        mock_sql.return_value = []

        # Test critical_only and urgent_only mutual exclusivity
        filters_critical = {"critical_only": True}
        get_data(filters_critical)

        sql_call = mock_sql.call_args[0][0]
        self.assertIn("60", sql_call)  # Critical = 60+ days

        # Reset mock
        mock_sql.reset_mock()

        filters_urgent = {"urgent_only": True}
        get_data(filters_urgent)

        sql_call = mock_sql.call_args[0][0]
        self.assertIn("30", sql_call)  # Urgent = 30+ days

    def test_data_type_validation(self):
        """Test that returned data has correct types"""
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql"
        ) as mock_sql:
            with patch(
                "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
            ) as mock_filter:
                mock_filter.return_value = None
                mock_sql.return_value = self.sample_overdue_data

                result = get_data({})

                for row in result:
                    # Test required fields exist
                    self.assertIn("member_name", row)
                    self.assertIn("total_overdue", row)
                    self.assertIn("overdue_count", row)
                    self.assertIn("days_overdue", row)

                    # Test data types
                    self.assertIsInstance(row.get("total_overdue"), (int, float))
                    self.assertIsInstance(row.get("overdue_count"), int)
                    self.assertIsInstance(row.get("days_overdue"), int)

    def test_edge_cases(self):
        """Test edge cases and error conditions"""

        # Test with None filters
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql"
        ) as mock_sql:
            with patch(
                "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
            ) as mock_filter:
                mock_filter.return_value = None
                mock_sql.return_value = []

                result = get_data(None)
                self.assertEqual(result, [])

        # Test with empty string chapter filter
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql"
        ) as mock_sql:
            with patch(
                "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
            ) as mock_filter:
                mock_filter.return_value = ""
                mock_sql.return_value = []

                result = get_data({"chapter": ""})
                self.assertEqual(result, [])

    @patch("verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql")
    @patch(
        "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
    )
    def test_subscription_filtering(self, mock_chapter_filter, mock_sql):
        """Test that only subscription-based invoices are included"""
        mock_chapter_filter.return_value = None
        mock_sql.return_value = []

        get_data({})

        sql_call = mock_sql.call_args[0][0]

        # Verify subscription filtering
        self.assertIn("si.subscription IS NOT NULL", sql_call)
        self.assertIn("EXISTS", sql_call)
        self.assertIn("tabSubscription", sql_call)
        self.assertIn("reference_doctype = 'Membership Type'", sql_call)

    def test_performance_considerations(self):
        """Test query performance considerations"""
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.frappe.db.sql"
        ) as mock_sql:
            with patch(
                "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_user_accessible_chapters"
            ) as mock_filter:
                mock_filter.return_value = None
                mock_sql.return_value = []

                # Test that query uses appropriate indexes
                get_data({"chapter": "Amsterdam"})

                sql_call = mock_sql.call_args[0][0]

                # Check for indexed fields in WHERE clause
                self.assertIn("si.status", sql_call)
                self.assertIn("si.due_date", sql_call)
                self.assertIn("si.docstatus", sql_call)
                self.assertIn("m.primary_chapter", sql_call)


class TestOverduePaymentsReportIntegration(unittest.TestCase):
    """Integration tests for the overdue payments report"""

    def setUp(self):
        """Set up integration test environment"""
        # These would be more comprehensive in a real test environment
        # with actual test data creation

    def test_full_report_execution(self):
        """Test full report execution with mocked dependencies"""
        with patch(
            "verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments.get_data"
        ) as mock_get_data:
            mock_get_data.return_value = [
                {
                    "member_name": "TEST-001",
                    "member_full_name": "Test User",
                    "member_email": "test@example.com",
                    "chapter": "Test Chapter",
                    "overdue_count": 1,
                    "total_overdue": 100.00,
                    "days_overdue": 35,
                    "membership_type": "Test",
                }
            ]

            columns, data, message, chart, summary = execute({"chapter": "Test Chapter"})

            # Verify complete execution
            self.assertIsInstance(columns, list)
            self.assertIsInstance(data, list)
            self.assertIsInstance(chart, dict)
            self.assertIsInstance(summary, list)

            # Verify data integrity
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["member_name"], "TEST-001")


if __name__ == "__main__":
    unittest.main()
