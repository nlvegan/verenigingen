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
