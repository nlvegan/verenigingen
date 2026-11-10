"""#2232: the patch must delete the Critical Operation Rule left behind on sites that
imported it before `process_member_post_creation` stopped being whitelisted. Removing the
row from the fixture file alone prunes nothing (COR is excluded from the `fixtures` hook).

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_process_member_post_creation_critical_operation_rule import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# The live caller's rule (create_member_optimized is still @high_security_api): must survive.
CONTROL = "create_member_optimized"


class TestRemoveDeadProcessMemberPostCreationRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)
        self.rows_before = frappe.db.count("Critical Operation Rule")

    def test_the_rule_name_is_the_unwhitelisted_function(self):
        self.assertEqual(DEAD_RULES, ["process_member_post_creation"])

    def test_execute_deletes_the_dead_rule_and_keeps_the_control(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "process_member_post_creation"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "process_member_post_creation"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
        self.assertEqual(frappe.db.count("Critical Operation Rule"), self.rows_before - 1)

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "process_member_post_creation"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
