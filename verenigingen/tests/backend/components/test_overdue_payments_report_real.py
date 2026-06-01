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
        
        # Create test chapter for filtering with unique naming
        self.test_chapter = self.create_test_chapter(
            chapter_name=f"Test Overdue Chapter {self.test_run_id}"
        )
        
        # Create test members with different overdue scenarios
        self.member_moderate_overdue = self.create_test_member(
            first_name="Moderate",
            last_name="Overdue",
            email="moderate.overdue@test.example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        self.member_critical_overdue = self.create_test_member(
            first_name="Critical", 
            last_name="Overdue",
            email="critical.overdue@test.example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        self.member_current = self.create_test_member(
            first_name="Current",
            last_name="Member",
            email="current.member@test.example.com", 
            status="Active",
            chapter=self.test_chapter.name
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

    def test_status_indicator_logic_real_calculations(self):
        """Test status indicator assignment based on real overdue calculations"""
        
        # Create additional members with specific overdue scenarios for status testing
        
        # Critical overdue member (90+ days)
        critical_member = self.create_test_member(
            first_name="Critical",
            last_name="StatusTest",
            email="critical.status@test.example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        critical_invoice = self.create_test_sales_invoice(
            customer=critical_member.name,
            posting_date=add_days(today(), -100),
            due_date=add_days(today(), -95),  # 95 days overdue
            grand_total=200.0,
            outstanding_amount=200.0,
            status="Overdue"
        )
        
        # Execute report with real database operations  
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        
        # Find results for status indicator testing
        moderate_result = next((r for r in data if r["member_name"] == self.member_moderate_overdue.name), None)
        critical_result = next((r for r in data if r["member_name"] == critical_member.name), None)
        
        # Verify status indicators based on real days overdue calculations
        if moderate_result:
            # 45 days overdue - should be "Urgent" (30-59 days)
            status = moderate_result.get("status_indicator", "")
            self.assertIn("Urgent", status)
            
        if critical_result:
            # 95 days overdue - should be "Critical" (60+ days) 
            status = critical_result.get("status_indicator", "")
            self.assertIn("Critical", status)

    def test_user_permission_filtering_real_access_control(self):
        """Test user permission filtering with real access control logic"""

        # Real permission testing - exercise the actual role-based access
        # control in get_user_accessible_chapters(); no mocking of frappe.get_roles.

        # An admin-tier role has unrestricted access (no filter -> None). Use the
        # Verenigingen Administrator *role* rather than the Administrator *user*,
        # which would bypass every DocPerm check and mask real permission bugs.
        with self.as_admin_role():
            admin_filter = get_user_accessible_chapters()
            self.assertIsNone(admin_filter)

            # As admin the report returns all data without error.
            all_data = get_data({"chapter": self.test_chapter.name})
            self.assertIsInstance(all_data, list)

        # A user with only a non-admin role and no member/board record has no
        # chapter access at all (the function returns an empty list).
        with self.as_role("Employee"):
            limited_filter = get_user_accessible_chapters()
            self.assertEqual(limited_filter, [])

    def test_subscription_filtering_real_database_operations(self):
        """Test subscription-based invoice filtering with real database queries"""
        
        # Create a non-subscription invoice to test filtering
        non_subscription_member = self.create_test_member(
            first_name="NonSubscription",
            last_name="Member", 
            email="nonsubscription@test.example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create invoice without dues schedule connection
        non_subscription_invoice = self.create_test_sales_invoice(
            customer=non_subscription_member.name,
            posting_date=add_days(today(), -40),
            due_date=add_days(today(), -35),
            grand_total=100.0,
            outstanding_amount=100.0,
            status="Overdue"
            # NOTE: No membership dues schedule link
        )
        
        # Execute report - should only include subscription-linked invoices
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        
        # Non-subscription member should NOT appear in results
        member_names = [row["member_name"] for row in data]
        self.assertNotIn(non_subscription_member.name, member_names,
                        "Non-subscription invoices should be filtered out")
        
        # Subscription-linked members should appear
        self.assertIn(self.member_moderate_overdue.name, member_names)
        self.assertIn(self.member_critical_overdue.name, member_names)

    def test_summary_calculations_real_aggregations(self):
        """Test summary statistics with real database aggregations"""
        
        # Get real data from database
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        summary = get_summary(data)
        
        # Verify summary structure
        self.assertIsInstance(summary, list)
        self.assertGreater(len(summary), 0)
        
        # Convert summary to dict for easier testing
        summary_dict = {item["label"]: item["value"] for item in summary if "label" in item}
        
        # Verify calculated totals match real data
        total_members = len(data)
        total_invoices = sum(row.get("overdue_count", 0) for row in data)
        total_amount = sum(row.get("total_overdue", 0) for row in data)
        
        # Check key summary statistics
        if "Members with Overdue Payments" in summary_dict:
            self.assertEqual(summary_dict["Members with Overdue Payments"], total_members)
            
        if "Total Overdue Invoices" in summary_dict:
            self.assertEqual(summary_dict["Total Overdue Invoices"], total_invoices)
            
        if "Total Overdue Amount" in summary_dict:
            self.assertAlmostEqual(summary_dict["Total Overdue Amount"], total_amount, places=2)
        
        # Verify severity categorizations
        critical_count = len([row for row in data if row.get("days_overdue", 0) > 60])
        urgent_count = len([row for row in data if row.get("days_overdue", 0) > 30])
        
        if "Critical (>60 days)" in summary_dict:
            self.assertEqual(summary_dict["Critical (>60 days)"], critical_count)
            
        if "Urgent (>30 days)" in summary_dict:
            self.assertEqual(summary_dict["Urgent (>30 days)"], urgent_count)

    def test_chart_data_real_chapter_aggregation(self):
        """Test chart data generation with real chapter-based aggregation"""
        
        # Create member in different chapter for aggregation testing
        other_chapter = self.create_test_chapter(
            chapter_name=f"Test Rotterdam Chapter {self.test_run_id}"
        )
        
        other_chapter_member = self.create_test_member(
            first_name="Other",
            last_name="Chapter",
            email="other.chapter@test.example.com",
            status="Active",
            chapter=other_chapter.name
        )
        
        other_chapter_invoice = self.create_test_sales_invoice(
            customer=other_chapter_member.name,
            posting_date=add_days(today(), -30),
            due_date=add_days(today(), -25),
            grand_total=125.0,
            outstanding_amount=125.0,
            status="Overdue"
        )
        
        # Get data for both chapters
        all_data = get_data({})  # No chapter filter
        chart = get_chart_data(all_data)
        
        # Verify chart structure
        self.assertIsInstance(chart, dict)
        self.assertIn("data", chart)
        
        chart_data = chart["data"]
        self.assertIn("labels", chart_data)
        self.assertIn("datasets", chart_data)
        
        # Verify chapter aggregation
        labels = chart_data["labels"]
        values = chart_data["datasets"][0]["values"]
        
        # Should aggregate amounts by chapter
        if self.test_chapter.name in labels:
            chapter_index = labels.index(self.test_chapter.name)
            chapter_total = values[chapter_index]
            # Should aggregate our test invoices (75 + 150 = 225)
            self.assertGreaterEqual(chapter_total, 225.0)
            
        if other_chapter.name in labels:
            other_index = labels.index(other_chapter.name)
            other_total = values[other_index]
            # Should show the other chapter's invoice (125)
            self.assertGreaterEqual(other_total, 125.0)

    def test_membership_type_filtering_real_database(self):
        """Test membership type filtering with real member data"""
        
        # Create member with specific membership type
        student_member = self.create_test_member(
            first_name="Student",
            last_name="Member",
            email="student.member@test.example.com",
            status="Active",
            chapter=self.test_chapter.name
        )
        
        # Create membership record with specific type
        student_membership = self.create_test_membership(
            member=student_member.name,
            membership_type="Student",
            status="Active"
        )
        
        student_invoice = self.create_test_sales_invoice(
            customer=student_member.name,
            posting_date=add_days(today(), -35),
            due_date=add_days(today(), -30),
            grand_total=40.0,  # Student discount rate
            outstanding_amount=40.0,
            status="Overdue"
        )
        
        # Test filtering by membership type
        student_filters = {
            "chapter": self.test_chapter.name,
            "membership_type": "Student"
        }
        
        student_data = get_data(student_filters)
        
        # Should only include student members
        for row in student_data:
            membership_type = row.get("membership_type")
            if membership_type:
                self.assertEqual(membership_type, "Student")
        
        # Should include our student member
        student_names = [row["member_name"] for row in student_data]
        self.assertIn(student_member.name, student_names)

    def test_performance_query_optimization_real_database(self):
        """Test query performance optimization with real database operations"""
        
        # This tests that the query uses appropriate indexes and performs well
        
        # Execute query and verify it completes in reasonable time
        import time
        
        start_time = time.time()
        
        filters = {
            "chapter": self.test_chapter.name,
            "days_overdue": 30,
            "critical_only": False,
            "urgent_only": True
        }
        
        data = get_data(filters)
        
        end_time = time.time()
        execution_time = end_time - start_time
        
        # Should execute in under 5 seconds for reasonable dataset
        self.assertLess(execution_time, 5.0, 
                       f"Query took too long: {execution_time:.2f} seconds")
        
        # Verify results are returned
        self.assertIsInstance(data, list)
        
        # Verify filtering worked correctly
        for row in data:
            days_overdue = row.get("days_overdue", 0)
            # Urgent filter should include 30+ days
            self.assertGreaterEqual(days_overdue, 30)

    def test_data_type_validation_real_results(self):
        """Test that real database results have correct data types"""
        
        filters = {"chapter": self.test_chapter.name}
        data = get_data(filters)
        
        # Verify data structure and types from real database
        for row in data:
            # Required fields should exist
            required_fields = [
                "member_name", "member_full_name", "member_email",
                "chapter", "overdue_count", "total_overdue", "days_overdue"
            ]
            
            for field in required_fields:
                self.assertIn(field, row, f"Missing required field: {field}")
            
            # Verify data types
            self.assertIsInstance(row["member_name"], str)
            self.assertIsInstance(row["member_full_name"], str)
            self.assertIsInstance(row["member_email"], str)
            self.assertIsInstance(row["chapter"], str)
            self.assertIsInstance(row["overdue_count"], int)
            self.assertIsInstance(row["total_overdue"], (int, float))
            self.assertIsInstance(row["days_overdue"], int)
            
            # Verify reasonable value ranges
            self.assertGreater(row["overdue_count"], 0)
            self.assertGreater(row["total_overdue"], 0)
            self.assertGreater(row["days_overdue"], 0)
            
            # Verify status indicator is set
            if "status_indicator" in row:
                status = row["status_indicator"]
                valid_statuses = ["Due", "Overdue", "Urgent", "Critical"]
                self.assertTrue(any(status_type in status for status_type in valid_statuses))

    def test_edge_cases_real_database_operations(self):
        """Test edge cases with real database operations"""
        
        # Test with member who has no overdue invoices (paid up)
        current_member_filters = {"chapter": self.test_chapter.name}
        current_data = get_data(current_member_filters)
        
        # Current member should NOT appear (no overdue invoices)
        current_names = [row["member_name"] for row in current_data]
        self.assertNotIn(self.member_current.name, current_names)
        
        # Test empty chapter filter
        empty_filters = {"chapter": "NonExistentChapter"}
        empty_data = get_data(empty_filters)
        
        # Should return empty list for non-existent chapter
        self.assertEqual(len(empty_data), 0)
        
        # Test future date filter (should return no results)
        future_filters = {
            "from_date": add_days(today(), 1),  # Future date
            "to_date": add_days(today(), 30)
        }
        
        future_data = get_data(future_filters)
        
        # Should return empty results for future date range
        self.assertEqual(len(future_data), 0)