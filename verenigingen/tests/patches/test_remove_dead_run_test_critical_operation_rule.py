"""#2099: deleting `tests/test_harness.py` removed the only `def run_test` in the app, which
orphaned the `run_test` Critical Operation Rule (it only ever matched `TestRunner.run_test`
in that dead test file). The patch must delete the row on sites that already imported it;
removing it from the fixture file alone prunes nothing, because COR is excluded from the
`fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_run_test_critical_operation_rule import DEAD_RULES, execute
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# A near-name rule for a live endpoint: a control the patch must not touch.
CONTROL = "run_production_scale_test"


class TestRemoveDeadRunTestRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_deleted_method(self):
        self.assertEqual(DEAD_RULES, ["run_test"])

    def test_execute_deletes_the_dead_rule_and_keeps_the_control(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "run_test"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "run_test"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "run_test"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
