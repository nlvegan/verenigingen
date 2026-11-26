"""#2897: the patch must delete the Critical Operation Rule left behind on sites
that imported it before its fixture row was removed (COR is excluded from the
`fixtures` hook, so the fixture edit alone prunes nothing).

Runs inside the test transaction: the patch does not commit, so nothing leaks.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v2_2.remove_dead_generate_enhanced_sepa_xml_critical_operation_rule_2897 import (
    DEAD_RULES,
    execute,
)
from verenigingen.tests.patches.test_remove_dead_chapter_board_permission_critical_operation_rules import (
    _insert_rule,
)

# A live, unrelated rule: a control the patch must not touch.
CONTROL = "validate_sepa_xml_compliance"


class TestRemoveDeadGenerateEnhancedSepaXmlRule(FrappeTestCase):
    def setUp(self):
        super().setUp()
        for name in (*DEAD_RULES, CONTROL):
            frappe.db.delete("Critical Operation Rule", {"name": name})
            _insert_rule(name)

    def test_the_rule_name_is_the_function(self):
        self.assertEqual(DEAD_RULES, ["generate_enhanced_sepa_xml"])

    def test_the_fixture_no_longer_ships_the_row(self):
        fixture = Path(frappe.get_app_path("verenigingen")) / "fixtures" / "critical_operation_rule.json"
        names = {row["name"] for row in json.loads(fixture.read_text())}
        self.assertNotIn("generate_enhanced_sepa_xml", names)
        self.assertIn(CONTROL, names)  # control: the scan reads real rows

    def test_execute_deletes_the_dead_rule_and_keeps_the_other(self):
        self.assertTrue(frappe.db.exists("Critical Operation Rule", "generate_enhanced_sepa_xml"))

        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "generate_enhanced_sepa_xml"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_execute_is_idempotent(self):
        execute()
        execute()

        self.assertFalse(frappe.db.exists("Critical Operation Rule", "generate_enhanced_sepa_xml"))
        self.assertTrue(frappe.db.exists("Critical Operation Rule", CONTROL))

    def test_the_patch_is_registered_as_a_fragment(self):
        from frappe.modules import patch_handler

        from verenigingen.setup import patch_fragments

        patch_fragments.install()
        self.assertIn(
            "verenigingen.patches.v2_2.remove_dead_generate_enhanced_sepa_xml_critical_operation_rule_2897",
            patch_handler.get_patches_from_app("verenigingen"),
        )
