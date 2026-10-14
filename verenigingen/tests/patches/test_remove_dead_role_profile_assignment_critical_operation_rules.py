"""#1659: the patch must delete the two Critical Operation Rules left behind on
sites that imported them before `assign_chapter_board_role_profile` / `assign_team_role_profile`
were deleted. Removing the rows from the fixture file alone prunes nothing, because
COR is excluded from the `fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_role_profile_assignment_critical_operation_rules import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

CONTROL = "zz_1659_live_control_rule"


class TestRemoveDeadRoleProfileAssignmentRules(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # FrappeTestCase rolls back per CLASS, not per test: start each test from
        # a known state, whatever a previous test or an imported site left behind.
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rules_names_are_the_two_deleted_functions(self):
        self.assertEqual(
            sorted(DEAD_RULES), ["assign_chapter_board_role_profile", "assign_team_role_profile"]
        )

    def test_execute_deletes_the_dead_rules_and_keeps_a_live_one(self):
        for name in DEAD_RULES:
            self.assertTrue(frappe.db.exists("Critical Operation Rule", name), f"fixture: {name}")

        execute()

        for name in DEAD_RULES:
            self.assertFalse(frappe.db.exists("Critical Operation Rule", name), name)
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        """Run on a site that is already clean: no raise, dead rules stay absent, live rule stays."""
        for name in DEAD_RULES:
            frappe.delete_doc("Critical Operation Rule", name, ignore_permissions=True, force=True)

        execute()
        execute()

        for name in DEAD_RULES:
            self.assertFalse(frappe.db.exists("Critical Operation Rule", name), name)
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
