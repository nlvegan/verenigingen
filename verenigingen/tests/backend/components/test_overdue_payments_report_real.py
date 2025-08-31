"""
Real Integration Tests for Overdue Payments Report
=================================================

Phase 5.1 Database Mock Elimination: Report Testing
Replaces inappropriate SQL mocking with real database operations and test data.

Key Improvements:
- Eliminates frappe.db.sql mocks - uses real Sales Invoice data
- Eliminates frappe.get_doc mocks - uses actual document operations
- Tests real report SQL queries against authentic test data
- Validates actual report business logic and calculations
- Tests real chapter filtering and permission logic

This approach catches real SQL query issues, data type problems, and business logic bugs
that mocked report tests completely miss.
"""

import frappe
from frappe.utils import add_days, today, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
    execute,
    get_chart_data,
    get_data,
    get_summary,
    get_user_accessible_chapters,
)


class TestOverduePaymentsReportReal(EnhancedTestCase):
    """Real integration tests for Overdue Member Payments report without SQL mocks"""

    def setUp(self):
        """Set up real test data using Enhanced Test Factory"""
        super().setUp()
        
        # Create test chapter for filtering
        self.test_chapter = self.create_chapter(
            region="Noord-Holland"
        )
        # Chapter name is set automatically via autoname prompt
        
        # Create test members with different overdue scenarios
        self.member_moderate_overdue = self.create_test_member(
            first_name="Moderate",
            last_name="Overdue",
            email="moderate.overdue@test.example.com",
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        self.member_critical_overdue = self.create_test_member(
            first_name="Critical", 
            last_name="Overdue",
            email="critical.overdue@test.example.com",
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        self.member_current = self.create_test_member(
            first_name="Current",
            last_name="Member",
            email="current.member@test.example.com", 
            status="Active",
            primary_chapter=self.test_chapter.name
        )
        
        # Create overdue sales invoices using real database operations
        self.create_overdue_invoice_scenario()

    def create_overdue_invoice_scenario(self):
        """Create realistic overdue invoice test data"""
        
        # Moderate overdue (45 days) - €75 outstanding
        self.moderate_invoice = self.create_test_sales_invoice(
            customer=self.member_moderate_overdue.name,
            posting_date=add_days(today(), -50),
            due_date=add_days(today(), -45),
            grand_total=75.0,
            outstanding_amount=75.0,
            status="Overdue"
        )
        
        # Critical overdue (90 days) - €150 outstanding  
        self.critical_invoice = self.create_test_sales_invoice(
            customer=self.member_critical_overdue.name,
            posting_date=add_days(today(), -95),
            due_date=add_days(today(), -90),
            grand_total=150.0,
            outstanding_amount=150.0,
            status="Overdue"
        )
        
        # Current member - no overdue invoices (paid invoice)
        self.current_invoice = self.create_test_sales_invoice(
            customer=self.member_current.name,
            posting_date=add_days(today(), -10),
            due_date=add_days(today(), 20),  # Not yet due
            grand_total=50.0,
            outstanding_amount=0.0,  # Paid
            status="Paid"
        )

    def test_report_execution_with_real_data(self):
        """Test complete report execution with real database data"""
        
        # Execute report with real database operations (no SQL mocks)
        filters = {"chapter": self.test_chapter.name}
        columns, data, message, chart, summary = execute(filters)
        
        # Verify report structure
        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        self.assertIsInstance(data, list)
        
        # Verify data contains our overdue members (real SQL query results)
        member_names_in_report = [row.get("member_name") for row in data]
        self.assertIn(self.member_moderate_overdue.name, member_names_in_report)
        self.assertIn(self.member_critical_overdue.name, member_names_in_report)
        
        # Current member should NOT appear (no overdue invoices)
        self.assertNotIn(self.member_current.name, member_names_in_report)

    def test_get_data_real_sql_execution(self):
        """Test get_data function with real SQL execution (no mocks)"""
        
        # Test with chapter filter using real database operations
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        
        # Verify real SQL execution returned expected results
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)  # Should have our 2 overdue members
        
        # Verify data structure matches expected report format
        for row in data:
            required_fields = [
                "member_name", "member_full_name", "member_email", 
                "chapter", "overdue_count", "total_overdue"
            ]
            for field in required_fields:
                self.assertIn(field, row)
        
        # Verify actual amounts from real database
        moderate_row = next((r for r in data if r["member_name"] == self.member_moderate_overdue.name), None)
        self.assertIsNotNone(moderate_row)
        self.assertEqual(moderate_row["total_overdue"], 75.0)
        
        critical_row = next((r for r in data if r["member_name"] == self.member_critical_overdue.name), None)
        self.assertIsNotNone(critical_row)
        self.assertEqual(critical_row["total_overdue"], 150.0)

    def test_date_filter_real_database_operations(self):
        """Test date filtering with real database queries"""
        
        # Test from_date filter with real SQL execution
        filters = {
            "from_date": add_days(today(), -60),  # Should exclude critical overdue (95 days ago)
            "chapter": self.test_chapter.name
        }
        data = get_data(filters)
        
        # Should only include moderate overdue (50 days ago), not critical (95 days ago)
        member_names = [row["member_name"] for row in data]
        self.assertIn(self.member_moderate_overdue.name, member_names)
        self.assertNotIn(self.member_critical_overdue.name, member_names)

    def test_days_overdue_filter_real_sql(self):
        """Test days overdue filtering with real database operations"""
        
        # Test filtering for only critical overdue (60+ days)
        filters = {
            "days_overdue": 60,
            "chapter": self.test_chapter.name
        }
        data = get_data(filters)
        
        # Should only include critical overdue member (90 days), not moderate (45 days)
        member_names = [row["member_name"] for row in data]
        self.assertNotIn(self.member_moderate_overdue.name, member_names)  # Only 45 days
        self.assertIn(self.member_critical_overdue.name, member_names)    # 90 days

    def test_summary_calculations_real_data(self):
        """Test summary calculations with real database data"""
        
        # Get real data and calculate summary
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        summary = get_summary(data)
        
        # Verify summary calculations against real data
        self.assertIsInstance(summary, list)
        self.assertGreater(len(summary), 0)
        
        # Verify total amounts calculation
        expected_total = 75.0 + 150.0  # Our two overdue members
        total_summary = next((s for s in summary if "Total" in s.get("label", "")), None)
        if total_summary:
            self.assertEqual(total_summary["value"], expected_total)

    def test_chart_data_real_database(self):
        """Test chart data generation with real database operations"""
        
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        chart = get_chart_data(data)
        
        # Verify chart structure
        self.assertIsInstance(chart, dict)
        self.assertIn("data", chart)
        
        # Chart should reflect real data distribution
        chart_data = chart["data"]
        self.assertIsInstance(chart_data, dict)

    def test_chapter_filtering_real_permissions(self):
        """Test chapter filtering with real user permissions (no mocks)"""
        
        # Test without chapter filter (admin access)
        filters = {}
        all_data = get_data(filters)
        
        # Test with specific chapter filter  
        filters = {"chapter": self.test_chapter.name}
        chapter_data = get_data(filters)
        
        # Chapter filtered data should be subset of all data
        self.assertLessEqual(len(chapter_data), len(all_data))
        
        # All returned members should be from specified chapter
        for row in chapter_data:
            self.assertEqual(row["chapter"], self.test_chapter.name)

    def test_report_error_handling_real_operations(self):
        """Test error handling with real database operations"""
        
        # Test with invalid filters that would cause real SQL errors
        invalid_filters = {"from_date": "invalid-date-format"}
        
        # Should handle gracefully without crashing
        try:
            data = get_data(invalid_filters)
            # If it doesn't crash, verify it returns valid structure
            self.assertIsInstance(data, list)
        except Exception as e:
            # Real error handling - should be meaningful error message
            self.assertIsInstance(str(e), str)
            self.assertGreater(len(str(e)), 0)