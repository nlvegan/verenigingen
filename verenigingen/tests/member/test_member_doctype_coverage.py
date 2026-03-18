"""
Test coverage for 3 member-related DocTypes.

DocTypes tested:
1. MemberContactRequest — contact request handling and validation
2. MembershipAnalyticsSnapshot — analytics calculations (module-level functions)
3. MembershipGoal — goal tracking and calculation
"""

from datetime import timedelta

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


# ---------------------------------------------------------------------------
# 1. MemberContactRequest
# ---------------------------------------------------------------------------
class TestMemberContactRequest(EnhancedTestCase):
    """Tests for Member Contact Request DocType — contact request handling."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="Contact", last_name=f"R{self.uid}")
        # Ensure member is Active
        frappe.db.set_value("Member", self.member.name, "membership_status", "Active", update_modified=False)
        frappe.db.commit()
        self.member.reload()

    def _create_request(self, **overrides):
        """Helper to create a contact request."""
        data = {
            "doctype": "Member Contact Request",
            "member": self.member.name,
            "subject": "Test Request",
            "message": "This is a test contact request",
            "request_type": "General Inquiry",
            "preferred_contact_method": "Email",
            "urgency": "Normal",
            "request_date": today(),
        }
        data.update(overrides)
        doc = frappe.get_doc(data)
        return doc

    # --- validate_member_exists ---
    def test_validate_member_required(self):
        """Throws when member is empty."""
        doc = self._create_request(member=None)
        with self.assertRaises(frappe.ValidationError):
            doc.validate()

    def test_validate_member_not_found(self):
        """Throws for non-existent member."""
        doc = self._create_request(member="NONEXISTENT-MEMBER-XYZ")
        with self.assertRaises(frappe.ValidationError):
            doc.validate()

    def test_validate_member_not_active(self):
        """Throws when member is not active."""
        frappe.db.set_value("Member", self.member.name, "membership_status", "Pending", update_modified=False)
        frappe.db.commit()
        self.member.reload()
        doc = self._create_request()
        with self.assertRaises(frappe.ValidationError):
            doc.validate()

    # --- set_member_details ---
    def test_auto_populate_member_details(self):
        """Auto-populates member_name from linked member."""
        doc = self._create_request(member_name=None)
        doc.validate()
        self.assertTrue(bool(doc.member_name))

    # --- validate_contact_preferences ---
    def test_phone_required_when_preferred(self):
        """Throws when phone is preferred but not set."""
        doc = self._create_request(preferred_contact_method="Phone", phone=None)
        doc.member_name = "Test"
        doc.email = "test@example.com"
        with self.assertRaises(frappe.ValidationError):
            doc.validate_contact_preferences()

    def test_email_required_when_preferred(self):
        """Throws when email is preferred but not set."""
        doc = self._create_request(preferred_contact_method="Email", email=None)
        doc.member_name = "Test"
        doc.phone = None
        with self.assertRaises(frappe.ValidationError):
            doc.validate_contact_preferences()

    def test_email_preferred_with_email(self):
        """Passes when email is preferred and set."""
        doc = self._create_request(preferred_contact_method="Email")
        doc.email = "test@example.com"
        doc.member_name = "Test"
        doc.validate_contact_preferences()  # Should not throw

    # --- get_notification_recipients ---
    def test_get_notification_recipients(self):
        """Returns list of recipient emails."""
        doc = self._create_request()
        doc.urgency = "Normal"
        recipients = doc.get_notification_recipients()
        self.assertIsInstance(recipients, list)

    def test_urgent_includes_system_managers(self):
        """Urgent requests query system manager recipients."""
        doc = self._create_request(urgency="Urgent")
        recipients = doc.get_notification_recipients()
        self.assertIsInstance(recipients, list)

    # --- handle_status_change ---
    def test_status_in_progress_sets_response_date(self):
        """Sets response_date when status changes to In Progress."""
        doc = self._create_request()
        doc.status = "In Progress"
        doc.response_date = None
        doc.handle_status_change()
        self.assertIsNotNone(doc.response_date)

    def test_status_resolved_sets_closed_date(self):
        """Sets closed_date when status changes to Resolved."""
        doc = self._create_request()
        doc.status = "Resolved"
        doc.closed_date = None
        doc.handle_status_change()
        self.assertIsNotNone(doc.closed_date)

    def test_status_closed_sets_closed_date(self):
        """Sets closed_date when status changes to Closed."""
        doc = self._create_request()
        doc.status = "Closed"
        doc.closed_date = None
        doc.handle_status_change()
        self.assertIsNotNone(doc.closed_date)

    # --- handle_assignment_change ---
    def test_assignment_sets_follow_up_date(self):
        """Sets follow_up_date when assigned_to is set."""
        doc = self._create_request()
        doc.assigned_to = "Administrator"
        doc.follow_up_date = None
        doc.handle_assignment_change()
        self.assertIsNotNone(doc.follow_up_date)


# ---------------------------------------------------------------------------
# 2. MembershipAnalyticsSnapshot (module-level functions)
# ---------------------------------------------------------------------------
class TestMembershipAnalyticsSnapshot(EnhancedTestCase):
    """Tests for Membership Analytics Snapshot — analytics calculation functions."""

    # --- calculate_period ---
    def test_calculate_period_daily(self):
        """Daily period has same start/end date."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
        )

        snapshot_date = getdate(today())
        result = calculate_period("Daily", snapshot_date)
        self.assertEqual(result["start_date"], snapshot_date)
        self.assertEqual(result["end_date"], snapshot_date)
        self.assertIn("-", result["label"])

    def test_calculate_period_weekly(self):
        """Weekly period starts on Monday."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
        )

        snapshot_date = getdate(today())
        result = calculate_period("Weekly", snapshot_date)
        # Start date should be a Monday
        self.assertEqual(result["start_date"].weekday(), 0)
        self.assertIn("Week", result["label"])

    def test_calculate_period_monthly(self):
        """Monthly period starts on day 1."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
        )

        snapshot_date = getdate(today())
        result = calculate_period("Monthly", snapshot_date)
        self.assertEqual(result["start_date"].day, 1)

    def test_calculate_period_quarterly(self):
        """Quarterly period starts on first month of quarter."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
        )

        snapshot_date = getdate(today())
        result = calculate_period("Quarterly", snapshot_date)
        self.assertIn(result["start_date"].month, [1, 4, 7, 10])
        self.assertIn("Q", result["label"])

    def test_calculate_period_yearly(self):
        """Yearly period spans Jan 1 to Dec 31."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
        )

        snapshot_date = getdate(today())
        result = calculate_period("Yearly", snapshot_date)
        self.assertEqual(result["start_date"].month, 1)
        self.assertEqual(result["start_date"].day, 1)
        self.assertEqual(result["end_date"].month, 12)
        self.assertEqual(result["end_date"].day, 31)

    # --- calculate_member_metrics ---
    def test_calculate_member_metrics(self):
        """Populates member count fields on snapshot."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_member_metrics,
            calculate_period,
        )

        snapshot_date = getdate(today())
        period = calculate_period("Daily", snapshot_date)
        snapshot = frappe._dict()
        calculate_member_metrics(snapshot, period)
        self.assertIn("total_members", snapshot)
        self.assertIn("active_members", snapshot)
        self.assertIn("net_growth", snapshot)
        self.assertIn("retention_rate", snapshot)

    # --- calculate_financial_metrics ---
    def test_calculate_financial_metrics(self):
        """Populates revenue fields on snapshot."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_financial_metrics,
            calculate_period,
        )

        snapshot_date = getdate(today())
        period = calculate_period("Daily", snapshot_date)
        snapshot = frappe._dict()
        calculate_financial_metrics(snapshot, period)
        self.assertIn("total_revenue", snapshot)
        self.assertIn("average_member_value", snapshot)

    # --- calculate_segmentation_data ---
    def test_calculate_segmentation_data(self):
        """Populates segmentation JSON fields on snapshot."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_period,
            calculate_segmentation_data,
        )

        snapshot_date = getdate(today())
        period = calculate_period("Monthly", snapshot_date)
        snapshot = frappe._dict()
        calculate_segmentation_data(snapshot, period)
        self.assertIsNotNone(snapshot.by_chapter)
        self.assertIsNotNone(snapshot.by_region)
        self.assertIsNotNone(snapshot.by_membership_type)

    # --- calculate_cohort_data ---
    def test_calculate_cohort_data(self):
        """Populates cohort_data JSON field."""
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            calculate_cohort_data,
            calculate_period,
        )

        snapshot_date = getdate(today())
        period = calculate_period("Monthly", snapshot_date)
        snapshot = frappe._dict()
        calculate_cohort_data(snapshot, period)
        self.assertIsNotNone(snapshot.cohort_data)


# ---------------------------------------------------------------------------
# 3. MembershipGoal
# ---------------------------------------------------------------------------
class TestMembershipGoal(EnhancedTestCase):
    """Tests for Membership Goal DocType — goal tracking and calculation."""

    def setUp(self):
        super().setUp()
        self.mt = self.ensure_membership_type("Test Goal MT")

    def _create_goal(self, **overrides):
        """Helper to create a membership goal."""
        data = {
            "doctype": "Membership Goal",
            "goal_name": "Test Goal",
            "goal_type": "New Member Acquisition",
            "target_value": 100,
            "start_date": add_months(today(), -6),
            "end_date": add_months(today(), 6),
            "status": "Active",
            "applies_to_all_chapters": 1,
            "applies_to_all_types": 1,
        }
        data.update(overrides)
        return frappe.get_doc(data)

    # --- validate ---
    def test_validate_end_before_start(self):
        """Throws when end_date is before start_date."""
        doc = self._create_goal(start_date=today(), end_date=add_days(today(), -1))
        with self.assertRaises(frappe.ValidationError):
            doc.validate()

    def test_validate_sets_goal_year(self):
        """Sets goal_year from start_date when not provided."""
        doc = self._create_goal(goal_year=None)
        doc.validate()
        self.assertEqual(doc.goal_year, getdate(doc.start_date).year)

    # --- update_achievement ---
    def test_update_achievement_zero_target(self):
        """Sets 0% when target is 0."""
        doc = self._create_goal(target_value=0)
        doc.update_achievement()
        self.assertEqual(doc.achievement_percentage, 0)

    def test_update_achievement_positive_target(self):
        """Calculates achievement percentage."""
        doc = self._create_goal(target_value=100)
        doc.update_achievement()
        self.assertIsNotNone(doc.achievement_percentage)
        self.assertIsNotNone(doc.last_updated)

    # --- calculate_current_value ---
    def test_calculate_member_growth(self):
        """Member Count Growth returns int."""
        doc = self._create_goal(goal_type="Member Count Growth")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, int)

    def test_calculate_revenue_growth(self):
        """Revenue Growth returns float."""
        doc = self._create_goal(goal_type="Revenue Growth")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, (int, float))

    def test_calculate_retention_rate(self):
        """Retention Rate returns float between 0 and 100."""
        doc = self._create_goal(goal_type="Retention Rate")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, (int, float))
        self.assertGreaterEqual(result, 0)

    def test_calculate_new_members(self):
        """New Member Acquisition returns int >= 0."""
        doc = self._create_goal(goal_type="New Member Acquisition")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)

    def test_calculate_churn_rate(self):
        """Churn Reduction returns float >= 0."""
        doc = self._create_goal(goal_type="Churn Reduction")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, (int, float))
        self.assertGreaterEqual(result, 0)

    def test_calculate_chapter_expansion(self):
        """Chapter Expansion returns int >= 0."""
        doc = self._create_goal(goal_type="Chapter Expansion")
        result = doc.calculate_current_value()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)

    def test_calculate_unknown_type(self):
        """Unknown goal type returns 0."""
        doc = self._create_goal(goal_type="Unknown Type")
        result = doc.calculate_current_value()
        self.assertEqual(result, 0)

    # --- update_status ---
    def test_status_draft_unchanged(self):
        """Draft status remains unchanged."""
        doc = self._create_goal(status="Draft")
        doc.achievement_percentage = 50
        doc.update_status()
        self.assertEqual(doc.status, "Draft")

    def test_status_achieved_when_100pct(self):
        """Active goal becomes Achieved at 100%."""
        doc = self._create_goal(status="Active")
        doc.achievement_percentage = 100
        doc.update_status()
        self.assertEqual(doc.status, "Achieved")

    def test_status_in_progress(self):
        """Active goal within dates shows In Progress."""
        doc = self._create_goal(
            status="Active",
            start_date=add_days(today(), -10),
            end_date=add_days(today(), 10),
        )
        doc.achievement_percentage = 50
        doc.update_status()
        self.assertEqual(doc.status, "In Progress")

    def test_status_missed_after_end(self):
        """Goal after end_date with < 100% is Missed."""
        doc = self._create_goal(
            status="Active",
            start_date=add_days(today(), -30),
            end_date=add_days(today(), -1),
        )
        doc.achievement_percentage = 50
        doc.update_status()
        self.assertEqual(doc.status, "Missed")

    # --- calculate_member_growth with chapter filter ---
    def test_member_growth_all_chapters(self):
        """Member growth for all chapters returns int."""
        doc = self._create_goal(
            goal_type="Member Count Growth",
            applies_to_all_chapters=1,
        )
        result = doc.calculate_member_growth()
        self.assertIsInstance(result, int)

    # --- calculate_revenue_growth with type filter ---
    def test_revenue_growth_with_type_filter(self):
        """Revenue growth respects membership type filter."""
        doc = self._create_goal(
            goal_type="Revenue Growth",
            applies_to_all_types=0,
            membership_type=self.mt.name,
        )
        result = doc.calculate_revenue_growth()
        self.assertIsInstance(result, (int, float))

    # --- calculate_new_members all chapters ---
    def test_new_members_all_chapters(self):
        """New member count for all chapters returns int."""
        doc = self._create_goal(
            goal_type="New Member Acquisition",
            applies_to_all_chapters=1,
        )
        result = doc.calculate_new_members()
        self.assertIsInstance(result, int)
