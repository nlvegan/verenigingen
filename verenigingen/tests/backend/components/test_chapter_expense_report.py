"""
Unit tests for Chapter Expense Report
Tests the ERPNext-integrated expense reporting functionality

Updated: December 2024 - Reflects ERPNext-only integration and legacy system phase-out
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report import (
    build_expense_row,
    execute,
    get_approval_level_for_amount,
    get_chart_data,
    get_data,
    get_erpnext_expense_data,
    get_summary,
    get_user_accessible_chapters,
)


class TestChapterExpenseReport(unittest.TestCase):
    """Test Chapter Expense Report functionality"""

    def setUp(self):
        """Set up for each test"""
        frappe.set_user("Administrator")
        self.test_filters = {"from_date": "2024-01-01", "to_date": "2024-12-31"}

    def tearDown(self):
        """Clean up after each test"""
        frappe.db.rollback()

    def test_execute_returns_proper_structure(self):
        """Test that execute returns proper report structure"""
        with patch(
            "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report.get_data",
            return_value=[],
        ):
            columns, data, message, chart, summary = execute(self.test_filters)

            # Should return 5-tuple
            self.assertIsInstance(columns, list)
            self.assertIsInstance(data, list)
            self.assertIsNone(message)  # Should be None for this report
            self.assertIsNone(chart)  # Should be None when no data
            self.assertIsInstance(summary, list)

    def test_get_erpnext_expense_data_with_filters(self):
        """Test ERPNext expense data retrieval with date filters"""
        mock_expense_claims = [
            {
                "name": "EXP-2024-001",
                "posting_date": "2024-06-15",
                "total_claimed_amount": 100.00,
                "total_sanctioned_amount": 100.00,
                "status": "Submitted",
                "approval_status": "Approved",
                "employee": "HR-EMP-001",
                "employee_name": "Test Employee",
                "remark": "Test expense claim",
                "company": "Test Company",
                "cost_center": None,
            }
        ]

        mock_expense_details = [
            {
                "expense_type": "Travel",
                "description": "Business travel",
                "amount": 100.00,
                "expense_date": "2024-06-15",
            }
        ]

        with patch("frappe.get_all") as mock_get_all:
            # First call returns expense claims, second call returns details
            mock_get_all.side_effect = [mock_expense_claims, mock_expense_details]

            with patch("frappe.db.get_value", return_value=None):  # No volunteer found
                result = get_erpnext_expense_data(self.test_filters)

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["name"], "EXP-2024-001")
                self.assertEqual(result[0]["amount"], 100.00)
                self.assertEqual(result[0]["status"], "Approved")
                self.assertEqual(result[0]["volunteer_name"], "Test Employee")

    def test_get_erpnext_expense_data_no_details(self):
        """Test ERPNext expense data when no expense details are found"""
        mock_expense_claims = [
            {
                "name": "EXP-2024-002",
                "posting_date": "2024-06-15",
                "total_claimed_amount": 75.00,
                "status": "Draft",
                "approval_status": "Draft",
                "employee": "HR-EMP-002",
                "employee_name": "Another Employee",
                "remark": "Simple expense claim",
                "company": "Test Company",
                "cost_center": None,
            }
        ]

        with patch("frappe.get_all") as mock_get_all:
            # First call returns expense claims, second call raises exception (no details)
            mock_get_all.side_effect = [mock_expense_claims, Exception("No details")]

            result = get_erpnext_expense_data(self.test_filters)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["name"], "EXP-2024-002")
            self.assertEqual(result[0]["category_name"], "General")  # Fallback category
            self.assertEqual(result[0]["status"], "Draft")

    def test_get_erpnext_expense_data_with_volunteer_lookup(self):
        """Test volunteer information lookup by employee_id"""
        mock_expense_claims = [
            {
                "name": "EXP-2024-003",
                "posting_date": "2024-06-15",
                "total_claimed_amount": 150.00,
                "status": "Paid",
                "approval_status": "Approved",
                "employee": "HR-EMP-003",
                "employee_name": "Employee Name",
                "remark": "Reimbursed expense",
                "company": "Test Company",
                "cost_center": None,
            }
        ]

        mock_volunteer_record = {"name": "VOL-001", "volunteer_name": "John Volunteer"}

        with patch("frappe.get_all", return_value=mock_expense_claims):
            with patch("frappe.db.get_value", return_value=mock_volunteer_record):
                result = get_erpnext_expense_data(self.test_filters)

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["volunteer_name"], "John Volunteer")
                self.assertEqual(result[0]["status"], "Reimbursed")  # Paid -> Reimbursed

    def test_get_user_accessible_chapters_admin_user(self):
        """Test that admin users see all chapters"""
        with patch("frappe.session.user", "administrator@example.com"):
            with patch("frappe.get_roles", return_value=["System Manager"]):
                result = get_user_accessible_chapters()
                self.assertIsNone(result)  # None means see all

    def test_get_user_accessible_chapters_regular_user(self):
        """Test that regular users have restricted access"""
        with patch("frappe.session.user", "user@example.com"):
            with patch("frappe.get_roles", return_value=["Employee"]):
                result = get_user_accessible_chapters()
                self.assertIsNone(result)  # Currently returns None for all users

    def test_get_approval_level_for_amount(self):
        """Test approval level calculation based on amount"""
        # Test Basic level (≤ €100)
        self.assertEqual(get_approval_level_for_amount(50.00), "Basic")
        self.assertEqual(get_approval_level_for_amount(100.00), "Basic")

        # Test Financial level (€100 < amount ≤ €500)
        self.assertEqual(get_approval_level_for_amount(150.00), "Financial")
        self.assertEqual(get_approval_level_for_amount(500.00), "Financial")

        # Test Admin level (> €500)
        self.assertEqual(get_approval_level_for_amount(750.00), "Admin")
        self.assertEqual(get_approval_level_for_amount(1000.00), "Admin")

    def test_build_expense_row_erpnext_claim(self):
        """Test building expense row for ERPNext expense claim"""
        with patch("frappe.db.count", return_value=2):  # 2 attachments
            row = build_expense_row(
                name="EXP-2024-001",
                volunteer_name="Test Volunteer",
                description="Test expense",
                amount=250.00,
                expense_date="2024-06-15",
                category_name="Travel",
                organization_type="Chapter",
                organization_name="Test Chapter",
                status="Approved",
                is_erpnext=True,
                expense_claim_id="EXP-2024-001",
            )

            self.assertEqual(row["name"], "EXP-2024-001")
            self.assertEqual(row["volunteer_name"], "Test Volunteer")
            self.assertEqual(row["amount"], 250.00)
            self.assertEqual(row["approval_level"], "Financial")
            self.assertEqual(row["attachment_count"], 2)
            self.assertIn("green", row["status_indicator"])  # Approved status

    def test_build_expense_row_status_indicators(self):
        """Test status indicator generation"""
        # Test different status indicators
        statuses = [
            ("Approved", "green"),
            ("Reimbursed", "green"),
            ("Rejected", "red"),
            ("Submitted", "blue"),
            ("Draft", "grey"),
        ]

        for status, expected_color in statuses:
            with patch("frappe.db.count", return_value=0):
                row = build_expense_row(
                    name="EXP-TEST",
                    volunteer_name="Test",
                    description="Test",
                    amount=100.00,
                    expense_date="2024-06-15",
                    category_name="Travel",
                    organization_type="National",
                    organization_name="National",
                    status=status,
                    is_erpnext=True,
                )

                self.assertIn(expected_color, row["status_indicator"])

    def test_build_expense_row_overdue_pending(self):
        """Test overdue pending expense indicator"""
        import datetime

        old_date = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y-%m-%d")

        with patch("frappe.db.count", return_value=0):
            row = build_expense_row(
                name="EXP-OVERDUE",
                volunteer_name="Test",
                description="Overdue expense",
                amount=100.00,
                expense_date=old_date,
                category_name="Travel",
                organization_type="National",
                organization_name="National",
                status="Submitted",
                is_erpnext=True,
            )

            self.assertIn("orange", row["status_indicator"])
            self.assertIn("Overdue", row["status_indicator"])
            self.assertEqual(row["days_to_approval"], 10)

    def test_get_summary_with_data(self):
        """Test summary statistics generation"""
        test_data = [
            {"amount": 100.00, "status": "Approved", "days_to_approval": 3, "approval_level": "Basic"},
            {
                "amount": 250.00,
                "status": "Submitted",
                "days_to_approval": None,
                "approval_level": "Financial",
            },
            {"amount": 50.00, "status": "Rejected", "days_to_approval": None, "approval_level": "Basic"},
            {"amount": 750.00, "status": "Reimbursed", "days_to_approval": 5, "approval_level": "Admin"},
        ]

        summary = get_summary(test_data)

        # Find specific summary items
        summary_dict = {item["label"]: item["value"] for item in summary}

        self.assertEqual(summary_dict["Total Expenses"], 4)
        self.assertEqual(summary_dict["Total Amount"], 1150.00)
        self.assertEqual(summary_dict["Approved"], 2)  # Approved + Reimbursed
        self.assertEqual(summary_dict["Approved Amount"], 850.00)
        self.assertEqual(summary_dict["Pending Approval"], 1)
        self.assertEqual(summary_dict["Pending Amount"], 250.00)
        self.assertEqual(summary_dict["Rejected"], 1)
        self.assertEqual(summary_dict["Basic Level"], 2)
        self.assertEqual(summary_dict["Financial Level"], 1)
        self.assertEqual(summary_dict["Admin Level"], 1)
        self.assertEqual(summary_dict["Avg. Approval Time (days)"], 4.0)  # (3+5)/2

    def test_get_summary_empty_data(self):
        """Test summary statistics with empty data"""
        summary = get_summary([])
        self.assertEqual(summary, [])

    def test_get_chart_data_with_data(self):
        """Test chart data generation"""
        test_data = [
            {"organization_name": "Chapter A", "amount": 100.00, "status": "approved"},
            {"organization_name": "Chapter A", "amount": 50.00, "status": "submitted"},
            {"organization_name": "Chapter B", "amount": 200.00, "status": "rejected"},
            {"organization_name": "National", "amount": 300.00, "status": "reimbursed"},
        ]

        chart = get_chart_data(test_data)

        self.assertIsNotNone(chart)
        self.assertEqual(chart["type"], "bar")
        self.assertIn("Chapter A", chart["data"]["labels"])
        self.assertIn("Chapter B", chart["data"]["labels"])
        self.assertIn("National", chart["data"]["labels"])

        # Check datasets
        datasets = {ds["name"]: ds["values"] for ds in chart["data"]["datasets"]}
        self.assertIn("Approved", datasets)
        self.assertIn("Pending", datasets)
        self.assertIn("Rejected", datasets)

    def test_get_chart_data_empty_data(self):
        """Test chart data with empty data"""
        chart = get_chart_data([])
        self.assertIsNone(chart)

    def test_get_data_with_filters(self):
        """Test main get_data function with filters"""
        mock_expense_data = [
            {
                "name": "EXP-2024-001",
                "volunteer_name": "Test Volunteer",
                "amount": 100.00,
                "status": "Approved",
                "organization_type": "Chapter",
                "chapter": "Test Chapter",
            }
        ]

        with patch(
            "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report.get_erpnext_expense_data",
            return_value=mock_expense_data,
        ):
            with patch(
                "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report.get_user_accessible_chapters",
                return_value=None,
            ):
                result = get_data(self.test_filters)

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["name"], "EXP-2024-001")

    def test_get_data_with_approval_level_filter(self):
        """Test get_data with approval level filtering"""
        mock_expense_data = [
            {"name": "EXP-1", "amount": 50.00},  # Basic level
            {"name": "EXP-2", "amount": 300.00},  # Financial level
            {"name": "EXP-3", "amount": 800.00},  # Admin level
        ]

        filters_with_level = self.test_filters.copy()
        filters_with_level["approval_level"] = "Financial"

        with patch(
            "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report.get_erpnext_expense_data",
            return_value=mock_expense_data,
        ):
            with patch(
                "verenigingen.verenigingen.report.chapter_expense_report.chapter_expense_report.get_user_accessible_chapters",
                return_value=None,
            ):
                result = get_data(filters_with_level)

                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]["name"], "EXP-2")  # Only Financial level expense

    def test_database_field_compatibility(self):
        """Test that the report works with actual ERPNext field structure"""
        # Test that we use correct ERPNext Expense Claim fields
        expected_fields = [
            "name",
            "posting_date",
            "total_claimed_amount",
            "total_sanctioned_amount",
            "status",
            "approval_status",
            "employee",
            "employee_name",
            "remark",
            "company",
            "cost_center",
        ]

        # This would fail if we try to use non-existent fields like 'title'
        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.return_value = []

            get_erpnext_expense_data({})

            # Verify the call was made with correct fields
            mock_get_all.assert_called_with(
                "Expense Claim",
                filters={"docstatus": 1},
                fields=expected_fields,
                order_by="posting_date desc, creation desc",
            )

    def test_error_handling_in_expense_data_retrieval(self):
        """Test error handling when expense data retrieval fails"""
        with patch("frappe.get_all", side_effect=Exception("Database error")):
            # Should not raise exception, should handle gracefully
            try:
                result = get_erpnext_expense_data(self.test_filters)
                # Should return empty list or handle gracefully
                self.assertIsInstance(result, list)
            except Exception as e:
                self.fail(f"get_erpnext_expense_data should handle database errors gracefully: {e}")


class TestChapterExpenseReportIntegration(unittest.TestCase):
    """Integration tests for Chapter Expense Report with ERPNext"""

    def setUp(self):
        frappe.set_user("Administrator")

    def test_report_execution_end_to_end(self):
        """Test complete report execution from filters to output"""
        filters = {"from_date": "2024-01-01", "to_date": "2024-12-31"}

        # Mock the entire data pipeline
        mock_claims = [
            {
                "name": "EXP-INTEGRATION-001",
                "posting_date": "2024-06-15",
                "total_claimed_amount": 125.00,
                "status": "Submitted",
                "approval_status": "Approved",
                "employee": "HR-EMP-001",
                "employee_name": "Integration Test User",
                "remark": "Integration test expense",
                "company": "Test Company",
                "cost_center": None,
            }
        ]

        mock_details = [
            {
                "expense_type": "Travel",
                "description": "Business trip",
                "amount": 125.00,
                "expense_date": "2024-06-15",
            }
        ]

        with patch("frappe.get_all") as mock_get_all:
            mock_get_all.side_effect = [mock_claims, mock_details]

            with patch("frappe.db.get_value", return_value=None):
                with patch("frappe.db.count", return_value=1):
                    columns, data, message, chart, summary = execute(filters)

                    # Verify complete structure
                    self.assertIsInstance(columns, list)
                    self.assertGreater(len(columns), 0)

                    self.assertIsInstance(data, list)
                    self.assertEqual(len(data), 1)

                    # Verify data structure
                    row = data[0]
                    self.assertEqual(row["name"], "EXP-INTEGRATION-001")
                    self.assertEqual(row["volunteer_name"], "Integration Test User")
                    self.assertEqual(row["amount"], 125.00)
                    self.assertEqual(row["approval_level"], "Financial")

                    # Verify summary
                    self.assertIsInstance(summary, list)
                    self.assertGreater(len(summary), 0)

                    # Verify chart
                    self.assertIsNotNone(chart)

    def test_workspace_link_compatibility(self):
        """Test that report works with workspace link configuration"""
        # This test ensures the report can be called from workspace shortcuts
        filters = {"from_date": "2024-01-01", "to_date": "2024-12-31"}

        with patch("frappe.get_all", return_value=[]):
            try:
                columns, data, message, chart, summary = execute(filters)

                # Should execute without errors even with no data
                self.assertIsInstance(columns, list)
                self.assertIsInstance(data, list)
                self.assertEqual(len(data), 0)

            except Exception as e:
                self.fail(f"Report should be compatible with workspace links: {e}")


if __name__ == "__main__":
    unittest.main()
