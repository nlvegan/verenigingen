"""#1588: the patch must delete the two Critical Operation Rules left behind on
sites that imported them before `setup_/reset_chapter_board_permissions` were
deleted. Removing the rows from the fixture file alone prunes nothing, because
COR is excluded from the `fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_chapter_board_permission_critical_operation_rules import (
    DEAD_RULES,
    execute,
)

CONTROL = "zz_1588_live_control_rule"


def _insert_rule(name):
    frappe.get_doc(
        {
            "doctype": "Critical Operation Rule",
            "operation_name": name,
            "operation_type": "admin",
            "enabled": 1,
            "security_level": "low",
            "required_roles": "System Manager",
            "rate_limit_calls": 180,
            "rate_limit_period_seconds": 3600,
            "rate_limit_scope": "per_user",
            "audit_level": "minimal",
        }
    ).insert(ignore_permissions=True)


class TestRemoveDeadChapterBoardPermissionRules(FrappeTestCase):
    def setUp(self):
        super().setUp()
        # FrappeTestCase rolls back per CLASS, not per test: start each test from
        # a known state, whatever a previous test or an imported site left behind.
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rules_names_are_the_two_deleted_functions(self):
        self.assertEqual(
            sorted(DEAD_RULES), ["reset_chapter_board_permissions", "setup_chapter_board_permissions"]
        )

    def test_execute_deletes_the_dead_rules_and_keeps_a_live_one(self):
        for name in DEAD_RULES:
            self.assertTrue(frappe.db.exists("Critical Operation Rule", name), f"fixture: {name}")

        execute()

        for name in DEAD_RULES:
            self.assertFalse(frappe.db.exists("Critical Operation Rule", name), name)
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
