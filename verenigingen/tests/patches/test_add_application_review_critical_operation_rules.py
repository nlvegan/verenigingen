"""#1928: the patch brings existing sites the application review rules.

`add_missing_critical_operation_rules` commits what it creates; the commit is stubbed here so everything
the test writes (a deleted row, a stale one) rolls back with the class.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.add_application_review_critical_operation_rules import RULE, execute

STALE = {
    "security_level": "low",
    "rate_limit_calls": 180,
    "audit_level": "minimal",
    "alert_on_execution": 0,
    "required_roles": "System Manager",
}


class TestAddApplicationReviewRules(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # Mock justified: Infrastructure - the setup function commits what it creates; keep it in the rollback
        self.enterContext(patch("frappe.db.commit"))

    def _current_rule_row(self):
        return frappe.db.get_value(
            "Critical Operation Rule", RULE, ["rate_limit_calls", "security_level", "alert_on_execution"], as_dict=True
        )

    def test_a_missing_rule_is_created(self):
        frappe.db.delete("Critical Operation Rule", {"name": "request_more_info"})
        execute()
        self.assertEqual(frappe.db.get_value("Critical Operation Rule", "request_more_info", "rate_limit_calls"), 20)

    def test_the_stale_reject_row_is_brought_to_the_fixture(self):
        frappe.db.set_value("Critical Operation Rule", RULE, STALE)
        execute()
        row = self._current_rule_row()
        self.assertEqual((row.rate_limit_calls, row.security_level, int(row.alert_on_execution)), (20, "high", 1))

    def test_a_tuned_reject_row_is_left_alone(self):
        frappe.db.set_value("Critical Operation Rule", RULE, {**STALE, "rate_limit_calls": 7})
        execute()
        row = self._current_rule_row()
        self.assertEqual((row.rate_limit_calls, row.security_level), (7, "low"))
