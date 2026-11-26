"""#1869: the patch must delete the Critical Operation Rule left behind on sites
that imported it before `send_overdue_notifications` was deleted. Removing the row from
the fixture file alone prunes nothing, because COR is excluded from the `fixtures` hook.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_send_overdue_notifications_critical_operation_rule import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# A live near-name rule (payment reminders): a control the patch must not touch.
CONTROL = "send_overdue_payment_reminders"


class TestRemoveDeadSendOverdueNotificationsRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_deleted_function(self):
        self.assertEqual(DEAD_RULES, ["send_overdue_notifications"])

    def test_execute_deletes_the_dead_rule_and_keeps_the_safe_one(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "send_overdue_notifications"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "send_overdue_notifications"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "send_overdue_notifications"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))
