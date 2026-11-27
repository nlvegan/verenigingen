"""#638: `handle_refund_webhook` is removed together with its Critical Operation Rule.

The rule row is also pruned from existing sites by a patch, because COR is excluded from
the `fixtures` hook and removing the fixture row alone prunes nothing.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_refund_webhook_critical_operation_rule_638 import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# The live payment webhook keeps its fixture rule: the control.
CONTROL_RULE = "handle_payment_webhook"


class TestRemoveRefundWebhookRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL_RULE):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_fixture_no_longer_ships_the_row(self):
        fixture = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "critical_operation_rule.json"
        names = {row["name"] for row in json.loads(fixture.read_text())}
        self.assertNotIn("handle_refund_webhook", names)
        self.assertIn(CONTROL_RULE, names)  # control: the scan reads real rows

    def test_execute_deletes_the_rule_and_keeps_the_control(self):
        self.assertEqual(DEAD_RULES, ["handle_refund_webhook"])
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "handle_refund_webhook"))

        execute()
        execute()  # idempotent

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "handle_refund_webhook"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL_RULE))
