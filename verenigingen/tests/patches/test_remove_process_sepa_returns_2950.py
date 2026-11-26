"""#2950: `process_sepa_returns` (a whitelisted endpoint taking a SERVER FILESYSTEM PATH
and handing it to `open()`) is removed, together with its Critical Operation Rule.

The rule row is also pruned from existing sites by a patch, because COR is excluded from
the `fixtures` hook and removing the fixture row alone prunes nothing.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_process_sepa_returns_critical_operation_rule_2950 import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)
from verenigingen.verenigingen_payments.doctype.direct_debit_batch import sepa_processor

# A live endpoint in the same module with a fixture rule: the controls.
LIVE_ENDPOINT = "verify_invoice_coverage_status"
CONTROL_RULE = "validate_sepa_configuration"


class TestRemoveProcessSepaReturns(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL_RULE):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_endpoint_is_gone_and_not_whitelisted(self):
        self.assertFalse(hasattr(sepa_processor, "process_sepa_returns"))
        self.assertNotIn("process_sepa_returns", sepa_processor.__all__)
        whitelisted_names = {fn.__name__ for fn in frappe.whitelisted}
        self.assertNotIn("process_sepa_returns", whitelisted_names)
        # control: the sibling endpoints in the same module are still whitelisted
        self.assertIn(getattr(sepa_processor, LIVE_ENDPOINT), frappe.whitelisted)

    def test_the_dotted_path_does_not_resolve(self):
        with self.assertRaises(AttributeError):
            frappe.get_attr(
                "verenigingen.verenigingen_payments.doctype.direct_debit_batch."
                "sepa_processor.process_sepa_returns"
            )

    def test_the_fixture_no_longer_ships_the_row(self):
        fixture = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "critical_operation_rule.json"
        names = {row["name"] for row in json.loads(fixture.read_text())}
        self.assertNotIn("process_sepa_returns", names)
        self.assertIn(CONTROL_RULE, names)  # control: the scan reads real rows

    def test_execute_deletes_the_rule_and_keeps_the_control(self):
        self.assertEqual(DEAD_RULES, ["process_sepa_returns"])
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "process_sepa_returns"))

        execute()
        execute()  # idempotent

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "process_sepa_returns"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL_RULE))
