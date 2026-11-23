"""#2637: deleting `scripts/member_performance_analyzer.py` removed the only
`analyze_member_performance` endpoint, orphaning its Critical Operation Rule. The patch must
delete the row on sites that already imported it; removing it from the fixture file alone
prunes nothing, because COR is excluded from the `fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_analyze_member_performance_critical_operation_rule import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# A near-name rule: a control the patch must not touch.
CONTROL = "analyze_member_doctype_performance"


class TestRemoveDeadAnalyzeMemberPerformanceRule2637(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_deleted_endpoint(self):
        self.assertEqual(DEAD_RULES, ["analyze_member_performance"])

    def test_execute_deletes_the_dead_rule_and_keeps_the_control(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "analyze_member_performance"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "analyze_member_performance"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "analyze_member_performance"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
