# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

import frappe
import unittest
import json
from datetime import datetime, timedelta
from frappe.utils import getdate, add_months, now_datetime, add_days, flt
from verenigingen.tests.test_utils import BaseTestCase


class TestMembershipAnalyticsFunctionality(BaseTestCase):
    """Test core functionality of membership analytics"""
    
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        
    def setUp(self):
        super().setUp()
        self.create_test_data()
    
    def create_test_data(self):
        """Create comprehensive test data for analytics"""
        # Create membership types
        self.create_membership_types()
        
        # Create members with various statuses and dates
        self.create_test_members()
        
        # Create memberships
        self.create_test_memberships()
        
        # Create some terminations
        self.create_test_terminations()
        
        # Create test invoices
        self.create_test_invoices()
        
        frappe.db.commit()
    
    def create_membership_types(self):
        """Create test membership types"""
        types = [
            {"name": "TEST_Standard", "amount": 100},
            {"name": "TEST_Premium", "amount": 200},
            {"name": "TEST_Student", "amount": 50}
        ]
        
        for type_data in types:
            if not frappe.db.exists("Membership Type", type_data["name"]):
                doc = frappe.get_doc({
                    "doctype": "Membership Type",
                    "membership_type": type_data["name"],
                    "amount": type_data["amount"],
                    "is_active": 1
                })
                doc.insert(ignore_permissions=True)
    
    def create_test_members(self):
        """Create test members with various characteristics"""
        self.test_members = []
        
        # Active members joined at different times
        for i in range(20):
            # Spread joining dates over past 3 years
            months_ago = i * 2  # 0, 2, 4, 6... months ago
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"Active",
                "last_name": f"Member{i}",
                "email": f"active{i}@test.com",
                "status": "Active",
                "member_since": add_months(getdate(), -months_ago),
                "birth_date": add_months(getdate(), -(20 + i) * 12),  # Various ages
                "payment_method": ["Bank Transfer", "Direct Debit", "Credit Card"][i % 3],
                "membership_fee_override": 120 if i % 5 == 0 else None  # Some with overrides
            })
            member.insert(ignore_permissions=True)
            self.test_members.append(member.name)
        
        # Members who will be terminated
        for i in range(5):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"ToTerminate",
                "last_name": f"Member{i}",
                "email": f"terminate{i}@test.com",
                "status": "Active",
                "member_since": add_months(getdate(), -12)
            })
            member.insert(ignore_permissions=True)
            self.test_members.append(member.name)
        
        # Recently joined members (for growth metrics)
        for i in range(10):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": f"New",
                "last_name": f"Member{i}",
                "email": f"new{i}@test.com",
                "status": "Active",
                "member_since": add_days(getdate(), -i)  # Joined in last 10 days
            })
            member.insert(ignore_permissions=True)
            self.test_members.append(member.name)
    
    def create_test_memberships(self):
        """Create active memberships for test members"""
        membership_types = ["TEST_Standard", "TEST_Premium", "TEST_Student"]
        
        for i, member_name in enumerate(self.test_members):
            if "ToTerminate" not in member_name:  # Don't create for members to be terminated
                membership = frappe.get_doc({
                    "doctype": "Membership",
                    "member": member_name,
                    "membership_type": membership_types[i % 3],
                    "from_date": add_months(getdate(), -12),
                    "to_date": add_months(getdate(), 12),
                    "status": "Active"
                })
                membership.insert(ignore_permissions=True)
    
    def create_test_terminations(self):
        """Create termination requests for some members"""
        # Get members to terminate
        members_to_terminate = frappe.get_all("Member", 
            filters={"first_name": "ToTerminate"},
            fields=["name"])
        
        for i, member in enumerate(members_to_terminate[:3]):  # Terminate 3 members
            termination = frappe.get_doc({
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_date": add_days(getdate(), -(i + 1)),
                "reason": "Test termination",
                "status": "Completed"
            })
            termination.insert(ignore_permissions=True)
            
            # Update member status
            frappe.db.set_value("Member", member.name, "status", "Terminated")
    
    def create_test_invoices(self):
        """Create test invoices for revenue calculations"""
        active_members = frappe.get_all("Member",
            filters={"status": "Active", "first_name": ["in", ["Active", "New"]]},
            fields=["name"],
            limit=10)
        
        for i, member in enumerate(active_members):
            # Create some paid invoices
            invoice = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": f"Test Customer {i}",
                "member": member.name,
                "posting_date": add_days(getdate(), -30),
                "due_date": add_days(getdate(), -15),
                "grand_total": 100 + (i * 10),
                "outstanding_amount": 0,
                "status": "Paid"
            })
            invoice.insert(ignore_permissions=True)
            invoice.submit()
            
            # Create some overdue invoices for payment failure testing
            if i < 3:
                overdue_invoice = frappe.get_doc({
                    "doctype": "Sales Invoice",
                    "customer": f"Test Customer {i}",
                    "member": member.name,
                    "posting_date": add_days(getdate(), -60),
                    "due_date": add_days(getdate(), -30),
                    "grand_total": 100,
                    "outstanding_amount": 100,
                    "status": "Overdue"
                })
                overdue_invoice.insert(ignore_permissions=True)
                overdue_invoice.submit()
    
    def test_summary_metrics_calculation(self):
        """Test calculation of summary metrics"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_summary_metrics
        
        current_year = datetime.now().year
        metrics = get_summary_metrics(current_year, "year")
        
        # Verify metrics structure
        self.assertIn("total_members", metrics)
        self.assertIn("new_members", metrics)
        self.assertIn("lost_members", metrics)
        self.assertIn("net_growth", metrics)
        self.assertIn("growth_rate", metrics)
        self.assertIn("projected_revenue", metrics)
        
        # Verify calculations
        self.assertGreater(metrics["total_members"], 0)
        self.assertEqual(metrics["net_growth"], metrics["new_members"] - metrics["lost_members"])
        
        # Test different periods
        quarterly_metrics = get_summary_metrics(current_year, "quarter")
        self.assertIn("period", quarterly_metrics)
        
        monthly_metrics = get_summary_metrics(current_year, "month")
        self.assertIn("period", monthly_metrics)
    
    def test_growth_trend_calculation(self):
        """Test growth trend data calculation"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_growth_trend
        
        current_year = datetime.now().year
        trend_data = get_growth_trend(current_year, "year")
        
        # Should have 12 months of data
        self.assertEqual(len(trend_data), 12)
        
        # Each month should have required fields
        for month_data in trend_data:
            self.assertIn("period", month_data)
            self.assertIn("new_members", month_data)
            self.assertIn("lost_members", month_data)
            self.assertIn("net_growth", month_data)
            
            # Verify net growth calculation
            self.assertEqual(
                month_data["net_growth"],
                month_data["new_members"] - month_data["lost_members"]
            )
    
    def test_revenue_projection(self):
        """Test revenue projection calculations"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_revenue_projection
        
        current_year = datetime.now().year
        revenue_data = get_revenue_projection(current_year)
        
        # Should have data for each membership type
        self.assertGreater(len(revenue_data), 0)
        
        # Verify structure
        for type_data in revenue_data:
            self.assertIn("membership_type", type_data)
            self.assertIn("member_count", type_data)
            self.assertIn("revenue", type_data)
            self.assertIn("average_fee", type_data)
            
            # Revenue should be member_count * average_fee (approximately)
            if type_data["member_count"] > 0:
                self.assertGreater(type_data["revenue"], 0)
    
    def test_membership_breakdown(self):
        """Test membership type breakdown"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_membership_breakdown
        
        current_year = datetime.now().year
        breakdown = get_membership_breakdown(current_year)
        
        # Should have data
        self.assertGreater(len(breakdown), 0)
        
        # Verify each type has count and revenue
        total_count = 0
        for item in breakdown:
            self.assertIn("membership_type", item)
            self.assertIn("count", item)
            self.assertIn("revenue", item)
            total_count += item["count"]
        
        # Total should match active memberships
        active_memberships = frappe.db.count("Membership", {"status": "Active"})
        self.assertEqual(total_count, active_memberships)
    
    def test_goal_functionality(self):
        """Test membership goal creation and tracking"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import create_goal, get_goals_progress
        
        # Create a test goal
        goal_data = {
            "goal_name": "Test Member Growth Goal",
            "goal_type": "Member Count Growth",
            "goal_year": datetime.now().year,
            "target_value": 50,
            "start_date": frappe.utils.year_start(),
            "end_date": frappe.utils.year_end(),
            "description": "Test goal for unit testing"
        }
        
        goal_name = create_goal(json.dumps(goal_data))
        self.assertTrue(frappe.db.exists("Membership Goal", goal_name))
        
        # Test goal progress calculation
        goals = get_goals_progress(datetime.now().year)
        
        # Find our test goal
        test_goal = next((g for g in goals if g["name"] == goal_name), None)
        self.assertIsNotNone(test_goal)
        
        # Verify goal fields
        self.assertIn("current_value", test_goal)
        self.assertIn("achievement_percentage", test_goal)
        self.assertIn("status", test_goal)
        
        # Clean up
        frappe.delete_doc("Membership Goal", goal_name)
    
    def test_insights_generation(self):
        """Test generation of insights"""
        from vereiningen.verenigingen.page.membership_analytics.membership_analytics import get_top_insights
        
        current_year = datetime.now().year
        insights = get_top_insights(current_year)
        
        # Should return a list of insights
        self.assertIsInstance(insights, list)
        
        # Each insight should have type and message
        for insight in insights:
            self.assertIn("type", insight)
            self.assertIn("message", insight)
            self.assertIn(insight["type"], ["success", "warning", "danger", "info"])
    
    def test_segmentation_data(self):
        """Test segmentation calculations"""
        from verenigingen.vereiningen.page.membership_analytics.membership_analytics import get_segmentation_data
        
        current_year = datetime.now().year
        segmentation = get_segmentation_data(current_year)
        
        # Verify all segmentation types are present
        self.assertIn("by_chapter", segmentation)
        self.assertIn("by_region", segmentation)
        self.assertIn("by_age", segmentation)
        self.assertIn("by_payment_method", segmentation)
        self.assertIn("by_join_year", segmentation)
        
        # Test payment method segmentation (we know we created members with different methods)
        payment_methods = segmentation["by_payment_method"]
        self.assertGreater(len(payment_methods), 0)
        
        method_names = [pm["name"] for pm in payment_methods]
        self.assertIn("Bank Transfer", method_names)
        self.assertIn("Direct Debit", method_names)
        
        # Test age segmentation
        age_groups = segmentation["by_age"]
        self.assertGreater(len(age_groups), 0)
        
        # Verify total members across all age groups
        total_in_age_groups = sum(ag["total_members"] for ag in age_groups)
        active_with_birthdate = frappe.db.count("Member", {
            "status": "Active",
            "birth_date": ["is", "set"]
        })
        self.assertEqual(total_in_age_groups, active_with_birthdate)
    
    def test_cohort_analysis(self):
        """Test cohort retention analysis"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import get_cohort_analysis
        
        current_year = datetime.now().year
        cohorts = get_cohort_analysis(current_year)
        
        # Should have cohort data
        self.assertIsInstance(cohorts, list)
        
        if cohorts:  # If we have cohort data
            for cohort in cohorts:
                self.assertIn("cohort", cohort)
                self.assertIn("initial", cohort)
                self.assertIn("retention", cohort)
                
                # Initial count should be positive
                self.assertGreater(cohort["initial"], 0)
                
                # Retention should be a list
                self.assertIsInstance(cohort["retention"], list)
                
                # First month retention should be 100% or close
                if cohort["retention"]:
                    first_retention = cohort["retention"][0]
                    self.assertGreaterEqual(first_retention["rate"], 90)
    
    def test_export_functionality(self):
        """Test data export functions"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import (
            export_dashboard_data, prepare_summary_sheet, prepare_growth_sheet
        )
        
        # Get dashboard data
        current_year = datetime.now().year
        data = {
            "summary": {
                "total_members": 100,
                "new_members": 10,
                "lost_members": 2,
                "net_growth": 8,
                "growth_rate": 8.5,
                "projected_revenue": 50000
            },
            "growth_trend": [
                {"period": "January", "new_members": 5, "lost_members": 1, "net_growth": 4},
                {"period": "February", "new_members": 5, "lost_members": 1, "net_growth": 4}
            ]
        }
        
        # Test summary sheet preparation
        summary_sheet = prepare_summary_sheet(data)
        self.assertEqual(summary_sheet[0], ["Metric", "Value"])
        self.assertEqual(len(summary_sheet), 7)  # Header + 6 metrics
        
        # Test growth sheet preparation
        growth_sheet = prepare_growth_sheet(data)
        self.assertEqual(growth_sheet[0], ["Period", "New Members", "Lost Members", "Net Growth"])
        self.assertEqual(len(growth_sheet), 3)  # Header + 2 months
    
    def test_snapshot_creation_and_retrieval(self):
        """Test analytics snapshot functionality"""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            create_snapshot, calculate_period
        )
        
        # Test period calculation
        test_date = getdate("2025-01-15")
        
        daily_period = calculate_period("Daily", test_date)
        self.assertEqual(daily_period["start_date"], test_date)
        self.assertEqual(daily_period["end_date"], test_date)
        
        weekly_period = calculate_period("Weekly", test_date)
        self.assertEqual(weekly_period["start_date"].weekday(), 0)  # Monday
        
        monthly_period = calculate_period("Monthly", test_date)
        self.assertEqual(monthly_period["start_date"].day, 1)
        
        # Create a test snapshot
        snapshot_name = create_snapshot("Daily", test_date)
        self.assertTrue(frappe.db.exists("Membership Analytics Snapshot", snapshot_name))
        
        # Verify snapshot data
        snapshot = frappe.get_doc("Membership Analytics Snapshot", snapshot_name)
        self.assertEqual(snapshot.snapshot_type, "Daily")
        self.assertIsNotNone(snapshot.total_members)
        self.assertIsNotNone(snapshot.active_members)
        self.assertIsNotNone(snapshot.by_membership_type)  # JSON field
        
        # Test duplicate prevention
        with self.assertRaises(frappe.ValidationError):
            create_snapshot("Daily", test_date)
        
        # Clean up
        frappe.delete_doc("Membership Analytics Snapshot", snapshot_name)
    
    def test_filter_functionality(self):
        """Test filtering in analytics functions"""
        from verenigingen.verenigingen.page.membership_analytics.membership_analytics import (
            get_dashboard_data, build_filter_conditions
        )
        
        # Test filter condition building
        filters = {
            "membership_type": "TEST_Standard",
            "age_group": "25-34",
            "payment_method": "Bank Transfer"
        }
        
        conditions = build_filter_conditions(filters)
        self.assertIn("membership_type", conditions)
        self.assertIn("25 AND 34", conditions)  # Age range condition
        
        # Test dashboard data with filters
        current_year = datetime.now().year
        filtered_data = get_dashboard_data(
            year=current_year,
            filters=json.dumps({"membership_type": "TEST_Standard"})
        )
        
        self.assertIsNotNone(filtered_data)
        self.assertIn("summary", filtered_data)
    
    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")
        
        # Delete in order of dependencies
        frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE customer LIKE 'Test Customer%'")
        frappe.db.sql("DELETE FROM `tabMembership Termination Request` WHERE reason = 'Test termination'")
        frappe.db.sql("DELETE FROM `tabMembership` WHERE member IN (SELECT name FROM `tabMember` WHERE email LIKE '%@test.com')")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE '%@test.com'")
        frappe.db.sql("DELETE FROM `tabMembership Type` WHERE name LIKE 'TEST_%'")
        frappe.db.sql("DELETE FROM `tabMembership Goal` WHERE goal_name LIKE 'Test%'")
        
        frappe.db.commit()
        super().tearDown()


class TestPredictiveAnalytics(BaseTestCase):
    """Test predictive analytics functionality"""
    
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.create_historical_data()
    
    def create_historical_data(self):
        """Create 3 years of historical data for predictions"""
        # Create members over 3 years with realistic growth pattern
        base_members = 100
        growth_rate = 0.05  # 5% monthly growth
        
        for months_ago in range(36, 0, -1):
            # Calculate how many members to create for this month
            month_members = int(base_members * ((1 + growth_rate) ** (36 - months_ago)))
            join_date = add_months(getdate(), -months_ago)
            
            # Create members for this month
            for i in range(max(1, month_members // 20)):  # Scale down for testing
                member = frappe.get_doc({
                    "doctype": "Member",
                    "first_name": f"Historical",
                    "last_name": f"M{months_ago}_{i}",
                    "email": f"hist_{months_ago}_{i}@test.com",
                    "status": "Active",
                    "member_since": join_date
                })
                member.insert(ignore_permissions=True)
                
                # Create membership
                membership = frappe.get_doc({
                    "doctype": "Membership",
                    "member": member.name,
                    "membership_type": "TEST_Standard",
                    "from_date": join_date,
                    "to_date": add_months(join_date, 12),
                    "status": "Active"
                })
                membership.insert(ignore_permissions=True)
        
        # Create membership type if not exists
        if not frappe.db.exists("Membership Type", "TEST_Standard"):
            mt = frappe.get_doc({
                "doctype": "Membership Type",
                "membership_type": "TEST_Standard",
                "amount": 100,
                "is_active": 1
            })
            mt.insert(ignore_permissions=True)
        
        frappe.db.commit()
    
    def test_member_growth_forecast(self):
        """Test member growth forecasting"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import forecast_member_growth
        
        forecast = forecast_member_growth(months_ahead=12)
        
        # Should not have error
        self.assertNotIn("error", forecast)
        
        # Verify structure
        self.assertIn("historical_trend", forecast)
        self.assertIn("forecast", forecast)
        self.assertIn("metrics", forecast)
        
        # Historical trend should have data
        self.assertGreater(len(forecast["historical_trend"]["months"]), 0)
        self.assertGreater(len(forecast["historical_trend"]["values"]), 0)
        
        # Forecast should have 12 months
        self.assertEqual(len(forecast["forecast"]["months"]), 12)
        self.assertEqual(len(forecast["forecast"]["values"]), 12)
        self.assertEqual(len(forecast["forecast"]["confidence_intervals"]), 12)
        
        # Metrics should be calculated
        self.assertGreater(forecast["metrics"]["current_members"], 0)
        self.assertGreater(forecast["metrics"]["forecast_members"], 0)
        
        # Forecast should show growth (based on historical trend)
        self.assertGreaterEqual(
            forecast["metrics"]["forecast_members"],
            forecast["metrics"]["current_members"]
        )
    
    def test_revenue_forecast(self):
        """Test revenue forecasting"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import forecast_revenue
        
        revenue_forecast = forecast_revenue(months_ahead=12)
        
        # Should not have error
        self.assertNotIn("error", revenue_forecast)
        
        # Verify structure
        self.assertIn("monthly_forecast", revenue_forecast)
        self.assertIn("cumulative_revenue", revenue_forecast)
        self.assertIn("annual_projection", revenue_forecast)
        self.assertIn("avg_member_value", revenue_forecast)
        
        # Monthly forecast should have 12 months
        self.assertEqual(len(revenue_forecast["monthly_forecast"]), 12)
        
        # Each month should have required fields
        for month in revenue_forecast["monthly_forecast"]:
            self.assertIn("month", month)
            self.assertIn("revenue", month)
            self.assertIn("member_count", month)
            self.assertIn("avg_member_value", month)
            self.assertGreater(month["revenue"], 0)
        
        # Cumulative revenue should increase
        cumulative = revenue_forecast["cumulative_revenue"]
        for i in range(1, len(cumulative)):
            self.assertGreaterEqual(cumulative[i], cumulative[i-1])
    
    def test_churn_risk_analysis(self):
        """Test churn risk analysis"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import analyze_churn_risk
        
        # Create some at-risk members
        self.create_at_risk_members()
        
        churn_analysis = analyze_churn_risk()
        
        # Verify structure
        self.assertIn("high_risk_members", churn_analysis)
        self.assertIn("statistics", churn_analysis)
        self.assertIn("risk_distribution", churn_analysis)
        
        # Statistics should have all risk levels
        stats = churn_analysis["statistics"]
        self.assertIn("total_at_risk", stats)
        self.assertIn("high_risk", stats)
        self.assertIn("medium_risk", stats)
        self.assertIn("low_risk", stats)
        self.assertIn("risk_percentage", stats)
        
        # Risk distribution
        self.assertIn("payment_issues", churn_analysis["risk_distribution"])
        self.assertIn("inactive", churn_analysis["risk_distribution"])
        
        # High risk members should have required fields
        for member in churn_analysis["high_risk_members"]:
            self.assertIn("member", member)
            self.assertIn("member_name", member)
            self.assertIn("risk_score", member)
            self.assertIn("risk_factors", member)
            self.assertIn("recommended_action", member)
            self.assertIsInstance(member["risk_factors"], list)
            self.assertTrue(0 <= member["risk_score"] <= 1)
    
    def create_at_risk_members(self):
        """Create members with risk factors"""
        # Create members with overdue invoices
        for i in range(3):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": "AtRisk",
                "last_name": f"Payment{i}",
                "email": f"atrisk_payment{i}@test.com",
                "status": "Active",
                "member_since": add_months(getdate(), -6)
            })
            member.insert(ignore_permissions=True)
            
            # Create overdue invoice
            invoice = frappe.get_doc({
                "doctype": "Sales Invoice",
                "customer": f"AtRisk Customer {i}",
                "member": member.name,
                "posting_date": add_days(getdate(), -60),
                "due_date": add_days(getdate(), -30),
                "grand_total": 100,
                "outstanding_amount": 100,
                "status": "Overdue"
            })
            invoice.insert(ignore_permissions=True)
            invoice.submit()
    
    def test_seasonal_patterns(self):
        """Test seasonal pattern detection"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import detect_seasonal_patterns
        
        patterns = detect_seasonal_patterns()
        
        # Verify structure
        self.assertIn("seasonal_indices", patterns)
        self.assertIn("peak_seasons", patterns)
        self.assertIn("low_seasons", patterns)
        self.assertIn("insights", patterns)
        
        # Should have 12 months of indices
        self.assertEqual(len(patterns["seasonal_indices"]), 12)
        
        # Peak and low seasons should have at most 3 entries each
        self.assertLessEqual(len(patterns["peak_seasons"]), 3)
        self.assertLessEqual(len(patterns["low_seasons"]), 3)
        
        # Each season entry should have month and index
        for season in patterns["peak_seasons"]:
            self.assertIn("month", season)
            self.assertIn("index", season)
            self.assertGreater(season["index"], 1.0)  # Peak should be above average
        
        for season in patterns["low_seasons"]:
            self.assertIn("month", season)
            self.assertIn("index", season)
            self.assertLess(season["index"], 1.0)  # Low should be below average
    
    def test_growth_scenarios(self):
        """Test growth scenario calculations"""
        from vereiningen.verenigingen.page.membership_analytics.predictive_analytics import calculate_growth_scenarios
        
        scenarios = calculate_growth_scenarios()
        
        # Verify structure
        self.assertIn("current_state", scenarios)
        self.assertIn("scenarios", scenarios)
        
        # Current state
        current = scenarios["current_state"]
        self.assertIn("members", current)
        self.assertIn("annual_revenue", current)
        self.assertIn("growth_rate", current)
        
        # Should have 4 scenarios
        self.assertEqual(len(scenarios["scenarios"]), 4)
        self.assertIn("conservative", scenarios["scenarios"])
        self.assertIn("moderate", scenarios["scenarios"])
        self.assertIn("optimistic", scenarios["scenarios"])
        self.assertIn("aggressive", scenarios["scenarios"])
        
        # Each scenario should have required fields
        for key, scenario in scenarios["scenarios"].items():
            self.assertIn("name", scenario)
            self.assertIn("growth_rate", scenario)
            self.assertIn("description", scenario)
            self.assertIn("projections", scenario)
            self.assertIn("requirements", scenario)
            
            # Projections
            self.assertIn("year_1", scenario["projections"])
            self.assertIn("year_3", scenario["projections"])
            
            # Growth rates should be in order
            if key == "conservative":
                self.assertLess(scenario["growth_rate"], scenarios["scenarios"]["moderate"]["growth_rate"])
            elif key == "optimistic":
                self.assertGreater(scenario["growth_rate"], scenarios["scenarios"]["moderate"]["growth_rate"])
            elif key == "aggressive":
                self.assertGreater(scenario["growth_rate"], scenarios["scenarios"]["optimistic"]["growth_rate"])
    
    def test_recommendations_generation(self):
        """Test recommendation generation"""
        from vereiningen.verenigingen.page.membership_analytics.predictive_analytics import generate_recommendations
        
        recommendations = generate_recommendations()
        
        # Should return a list
        self.assertIsInstance(recommendations, list)
        
        # Each recommendation should have required fields
        for rec in recommendations:
            self.assertIn("category", rec)
            self.assertIn("priority", rec)
            self.assertIn("recommendation", rec)
            self.assertIn("impact", rec)
            self.assertIn("actions", rec)
            
            # Category should be valid
            self.assertIn(rec["category"], ["Growth", "Retention", "Revenue", "Operations", "Seasonal"])
            
            # Priority should be valid
            self.assertIn(rec["priority"], ["Critical", "High", "Medium", "Low"])
            
            # Actions should be a list
            self.assertIsInstance(rec["actions"], list)
            self.assertGreater(len(rec["actions"]), 0)
        
        # Should be sorted by priority
        priority_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        for i in range(1, len(recommendations)):
            self.assertLessEqual(
                priority_order.get(recommendations[i-1]["priority"], 4),
                priority_order.get(recommendations[i]["priority"], 4)
            )
    
    def test_predictive_analytics_integration(self):
        """Test full predictive analytics integration"""
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import get_predictive_analytics
        
        predictions = get_predictive_analytics(months_ahead=6)
        
        # Should have all components
        self.assertIn("member_growth_forecast", predictions)
        self.assertIn("revenue_forecast", predictions)
        self.assertIn("churn_risk_analysis", predictions)
        self.assertIn("seasonal_patterns", predictions)
        self.assertIn("growth_scenarios", predictions)
        self.assertIn("recommendations", predictions)
        
        # Each component should have data
        self.assertNotIn("error", predictions["member_growth_forecast"])
        self.assertNotIn("error", predictions["revenue_forecast"])
        self.assertIsInstance(predictions["recommendations"], list)
    
    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")
        
        # Delete test data
        frappe.db.sql("DELETE FROM `tabSales Invoice` WHERE customer LIKE 'AtRisk Customer%'")
        frappe.db.sql("DELETE FROM `tabMembership` WHERE member IN (SELECT name FROM `tabMember` WHERE email LIKE '%@test.com')")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE '%@test.com'")
        
        frappe.db.commit()
        super().tearDown()


class TestAnalyticsAlertSystem(BaseTestCase):
    """Test analytics alert rule functionality"""
    
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.create_test_data()
    
    def create_test_data(self):
        """Create test data for alerts"""
        # Create test members
        for i in range(10):
            member = frappe.get_doc({
                "doctype": "Member",
                "first_name": "Alert",
                "last_name": f"Test{i}",
                "email": f"alert_test{i}@test.com",
                "status": "Active",
                "member_since": add_days(getdate(), -i)
            })
            member.insert(ignore_permissions=True)
    
    def test_alert_rule_creation(self):
        """Test creating and configuring alert rules"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Member Count Alert",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 5,
            "check_frequency": "Daily",
            "send_email": 0,
            "send_system_notification": 1,
            "alert_message_template": "Member count is {value} (threshold: {threshold})"
        })
        
        # Add recipients
        alert_rule.append("alert_recipients", {
            "recipient_type": "User",
            "recipient": "Administrator"
        })
        
        alert_rule.insert()
        
        # Verify creation
        self.assertTrue(frappe.db.exists("Analytics Alert Rule", alert_rule.name))
        
        # Test validation
        alert_rule.metric = "Churn Rate"
        alert_rule.threshold_value = 150  # Invalid percentage
        with self.assertRaises(frappe.ValidationError):
            alert_rule.save()
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
    
    def test_alert_metric_calculations(self):
        """Test metric calculations for alerts"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Metrics",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 0,
            "check_frequency": "Daily"
        })
        alert_rule.insert()
        
        # Test different metrics
        metrics_to_test = [
            ("Total Members", lambda x: x > 0),
            ("New Members", lambda x: x >= 0),
            ("Churn Rate", lambda x: 0 <= x <= 100),
            ("Growth Rate", lambda x: isinstance(x, (int, float))),
            ("Payment Failure Rate", lambda x: 0 <= x <= 100)
        ]
        
        for metric, validator in metrics_to_test:
            alert_rule.metric = metric
            value = alert_rule.get_metric_value()
            self.assertTrue(validator(value), f"Invalid value for {metric}: {value}")
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
    
    def test_alert_condition_evaluation(self):
        """Test alert condition evaluation logic"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Conditions",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 5,
            "check_frequency": "Daily"
        })
        alert_rule.insert()
        
        # Test different conditions
        test_cases = [
            (10, "Greater Than", 5, True),
            (3, "Greater Than", 5, False),
            (3, "Less Than", 5, True),
            (7, "Less Than", 5, False),
            (5, "Equals", 5, True),
            (5.01, "Equals", 5, False),
        ]
        
        for current_value, condition, threshold, expected in test_cases:
            alert_rule.condition = condition
            alert_rule.threshold_value = threshold
            result = alert_rule.evaluate_condition(current_value)
            self.assertEqual(result, expected, 
                f"Condition {condition} with value {current_value} and threshold {threshold} failed")
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
    
    def test_alert_triggering(self):
        """Test alert triggering and logging"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Trigger Alert",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 1,  # Low threshold to ensure trigger
            "check_frequency": "Daily",
            "send_email": 0,
            "send_system_notification": 0
        })
        alert_rule.insert()
        
        # Check and trigger
        alert_rule.check_and_trigger()
        
        # Verify alert was triggered (check last_triggered)
        alert_rule.reload()
        self.assertIsNotNone(alert_rule.last_triggered)
        
        # Check alert log was created
        alert_logs = frappe.get_all("Analytics Alert Log",
            filters={"alert_rule": alert_rule.name},
            fields=["name", "metric_value", "threshold_value"])
        
        self.assertGreater(len(alert_logs), 0)
        
        # Verify log details
        log = frappe.get_doc("Analytics Alert Log", alert_logs[0].name)
        self.assertEqual(log.alert_rule, alert_rule.name)
        self.assertGreater(log.metric_value, log.threshold_value)
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
        for log in alert_logs:
            frappe.delete_doc("Analytics Alert Log", log.name)
    
    def test_alert_frequency_control(self):
        """Test that alerts respect check frequency"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Frequency",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 0,
            "check_frequency": "Daily",
            "send_email": 0,
            "send_system_notification": 0
        })
        alert_rule.insert()
        
        # First check should run
        alert_rule.check_and_trigger()
        first_check = alert_rule.last_checked
        
        # Immediate second check should not run (within frequency window)
        alert_rule.check_and_trigger()
        alert_rule.reload()
        
        # For daily frequency, should not check again immediately
        should_check = alert_rule.should_check()
        self.assertFalse(should_check)
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
    
    def test_alert_actions(self):
        """Test automated actions when alerts trigger"""
        alert_rule = frappe.get_doc({
            "doctype": "Analytics Alert Rule",
            "rule_name": "Test Actions",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Total Members",
            "condition": "Greater Than",
            "threshold_value": 0,
            "check_frequency": "Daily",
            "send_email": 0,
            "send_system_notification": 0
        })
        
        # Add automated action
        alert_rule.append("automated_actions", {
            "action_type": "Create Task",
            "task_subject": "Review member growth",
            "task_priority": "High"
        })
        
        alert_rule.insert()
        
        # Trigger alert
        initial_task_count = frappe.db.count("Task")
        alert_rule.check_and_trigger()
        
        # Verify task was created
        new_task_count = frappe.db.count("Task")
        self.assertEqual(new_task_count, initial_task_count + 1)
        
        # Find and verify the created task
        tasks = frappe.get_all("Task",
            filters={"subject": "Review member growth"},
            fields=["name", "priority"])
        
        self.assertGreater(len(tasks), 0)
        self.assertEqual(tasks[0].priority, "High")
        
        # Clean up
        frappe.delete_doc("Analytics Alert Rule", alert_rule.name)
        for task in tasks:
            frappe.delete_doc("Task", task.name)
    
    def tearDown(self):
        """Clean up test data"""
        frappe.set_user("Administrator")
        
        # Delete test data
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Log`")
        frappe.db.sql("DELETE FROM `tabAnalytics Alert Rule` WHERE rule_name LIKE 'Test%'")
        frappe.db.sql("DELETE FROM `tabTask` WHERE subject = 'Review member growth'")
        frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE 'alert_test%@test.com'")
        
        frappe.db.commit()
        super().tearDown()


if __name__ == "__main__":
    unittest.main()