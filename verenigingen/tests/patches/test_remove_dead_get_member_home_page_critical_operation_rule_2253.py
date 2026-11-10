"""#2253: the patch must delete the Critical Operation Rule left behind on sites
that imported it before its fixture row was removed. Removing the row from
the fixture file alone prunes nothing, because COR is excluded from the `fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_get_member_home_page_critical_operation_rule_2253 import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# A live, unrelated rule: a control the patch must not touch.
CONTROL = "get_member_age_distribution"


class TestRemoveDeadGetMemberHomePageRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_endpoint(self):
        self.assertEqual(DEAD_RULES, ["get_member_home_page"])

    def test_the_fixture_no_longer_ships_the_row_and_the_endpoint_survives(self):
        fixture = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "critical_operation_rule.json"
        names = {row["name"] for row in json.loads(fixture.read_text())}
        self.assertNotIn("get_member_home_page", names)
        self.assertIn(CONTROL, names)  # control: the scan reads real rows
        from verenigingen import auth_hooks

        self.assertTrue(callable(auth_hooks.get_member_home_page))

    def test_execute_deletes_the_dead_rule_and_keeps_the_safe_one(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "get_member_home_page"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "get_member_home_page"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "get_member_home_page"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
