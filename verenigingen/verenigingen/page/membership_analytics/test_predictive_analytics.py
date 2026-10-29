# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""
Regression coverage for calculate_current_churn_rate() (#1532).

The function filtered Membership Termination Request on status="Completed",
which is not a valid Select option
(Draft/Pending/Approved/Rejected/Executed/Cancelled) -- the real terminal
value TerminationExecutionService.execute() writes is "Executed" -- so
terminated_last_year was always 0 and the churn-rate KPI on the predictive
analytics dashboard always read 0%, silently.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.termination_request import (
    create_draft_termination_request,
    execute_real_termination,
)
from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import (
    calculate_current_churn_rate,
)


class TestPredictiveAnalyticsChurnRate(EnhancedTestCase):
    def test_churn_rate_increases_after_real_termination(self):
        """Compares BEFORE vs AFTER a REAL termination (via
        TerminationExecutionService, not a hand-set status -- #1530 was found
        precisely because an earlier fix trusted a status string) rather than
        an absolute value: churn_rate is a GLOBAL count over the last 12
        months, so an absolute expected value would be fragile against
        whatever else exists on the site. One real Executed termination dated
        today both increases the numerator (terminated_last_year) and
        decreases the denominator (active_members, since the terminated
        member's status is no longer "Active"), so the rate strictly
        increases.

        Control: a Membership Termination Request left at status="Draft"
        (never executed) must NOT count -- this is what distinguishes the
        "Executed"-only fix from the plausible wrong fix of dropping the
        status filter entirely (any termination request, regardless of
        status, would then count as churn)."""
        # keeps active_members >= 1 after the termination below removes one.
        self._make_churn_member()
        terminated_member = self._make_churn_member()
        draft_member = self._make_churn_member()

        before = calculate_current_churn_rate()

        create_draft_termination_request(self, draft_member.name)
        mid = calculate_current_churn_rate()
        self.assertEqual(mid, before, "a Draft (never executed) request must not count as churn")

        execute_real_termination(self, terminated_member.name, termination_date=today())
        after = calculate_current_churn_rate()

        self.assertGreater(after, mid)

    # ------------------------------------------------------------- internals
    def _make_churn_member(self):
        return self.create_test_member(
            first_name="PredChurn",
            last_name="Member",
            email=f"pred.churn.{frappe.generate_hash(length=8)}@example.com",
        )


class TestPredictiveAnalyticsEmptyHistory(EnhancedTestCase):
    """#1503: detect_seasonal_patterns() divided by an empty aggregate when no
    Member had member_since in the last 3 years, failing the whole whitelisted
    get_predictive_analytics() endpoint with ZeroDivisionError.

    Emptiness is derived, not assumed: the site carries other tests' Members,
    so every non-Rejected Member's member_since is pushed outside the 3-year
    window (a direct UPDATE standing in for "a young
    association" -- the query only reads member_since/status) and restored
    afterwards."""

    def setUp(self):
        super().setUp()
        # A real row that would be counted if the window were not emptied below.
        self.create_test_member(
            first_name="SeasonalEmpty",
            last_name="Member",
            email=f"seasonal.empty.{frappe.generate_hash(length=8)}@example.com",
        )
        original = frappe.db.sql("SELECT name, member_since FROM `tabMember`")
        self.addCleanup(self._restore_member_since, original)
        frappe.db.sql("UPDATE `tabMember` SET member_since = DATE_SUB(CURDATE(), INTERVAL 10 YEAR)")

    @staticmethod
    def _restore_member_since(original):
        # Explicit restore: the harness teardown can already have ended the
        # transaction, so a savepoint rollback is not reliable here.
        for name, member_since in original:
            frappe.db.sql("UPDATE `tabMember` SET member_since = %s WHERE name = %s", (member_since, name))

    def test_precondition_window_is_empty(self):
        count = frappe.db.sql(
            "SELECT COUNT(*) FROM `tabMember` WHERE member_since >= DATE_SUB(CURDATE(), INTERVAL 3 YEAR)"
            " AND status != 'Rejected'"
        )[0][0]
        self.assertEqual(count, 0)

    def test_detect_seasonal_patterns_reports_insufficient_data(self):
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import (
            detect_seasonal_patterns,
        )

        result = detect_seasonal_patterns()
        self.assertIn("error", result)
        self.assertNotIn("seasonal_indices", result)

    def test_whitelisted_endpoint_survives_empty_history(self):
        from verenigingen.verenigingen.page.membership_analytics.predictive_analytics import (
            get_predictive_analytics,
        )

        with self.set_user("Administrator"):
            result = get_predictive_analytics()

        self.assertIn("error", result["seasonal_patterns"])
        self.assertIn("error", result["member_growth_forecast"])
        # the other sections still render
        self.assertIn("scenarios", result["growth_scenarios"])
        self.assertIsInstance(result["recommendations"], list)
