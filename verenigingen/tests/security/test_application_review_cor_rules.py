"""#1928: the application review endpoints have their own Critical Operation Rule.

The rate-limit engine looks a rule up by FUNCTION name and falls back to `_generic_api_fallback`. The rows for
the member-keyed endpoints were removed with them in #1765, and the replacements had none, so approving,
rejecting and the dashboard quick approvals ran on the generic limit and without the approval alert.
Each row below carries the removed row's limits and alerting (approve 500/h with alert, reject 20/h,
quick approve 80/min; request_more_info like reject).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.rate_limit_engine import RateLimitEngine

ENDPOINTS = {
    "verenigingen.api.membership_application_review.approve_application": (500, 3600, 1),
    "verenigingen.api.membership_application_review.reject_application": (20, 3600, 1),
    "verenigingen.api.membership_application_review.request_more_info": (20, 3600, 1),
    "verenigingen.api.chapter_dashboard_api.quick_approve_application": (80, 60, 0),
    "verenigingen.api.chapter_dashboard_api.quick_approve_join_request": (80, 60, 0),
}


class TestApplicationReviewRules(EnhancedTestCase):
    def test_each_endpoint_resolves_to_its_own_rule_not_the_generic_fallback(self):
        generic = frappe.db.get_value(
            "Critical Operation Rule", {"operation_name": "_generic_api_fallback"}, "name"
        )
        self.assertTrue(generic, "control: the generic fallback row exists, so a miss would silently use it")
        engine = RateLimitEngine()
        for path, (calls, period, alert) in ENDPOINTS.items():
            with self.subTest(endpoint=path):
                function = frappe.get_attr(path)
                name = function.__name__  # the key the engine uses
                row = frappe.db.get_value(
                    "Critical Operation Rule",
                    {"operation_name": name, "enabled": 1},
                    ["name", "rate_limit_calls", "rate_limit_period_seconds", "rate_limit_scope", "alert_on_execution"],
                    as_dict=True,
                )
                self.assertTrue(row, f"{name} has no enabled rule, so the engine falls back to the generic one")
                self.assertNotEqual(row.name, generic)
                self.assertEqual((row.rate_limit_calls, row.rate_limit_period_seconds), (calls, period))
                self.assertEqual(row.rate_limit_scope, "per_user")
                self.assertEqual(int(row.alert_on_execution), alert)
                resolved = engine._get_cor_config(name)
                self.assertEqual(resolved.rate_limit_calls, calls, "the engine resolved another row")
