"""#2306: the patch removes the nine dead critical rules and leaves their live bare-named twins.

Probe shortcut: the existing-site state is rows inserted by the test and the patch's
``execute`` is called directly, not through the patch runner.
"""

import importlib
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

DOCTYPE = "Critical Operation Rule"
PATCH = "verenigingen.patches.v2_2.remove_dead_critical_rules_matching_no_function_2306"
LIVE_TWIN = "nuclear_cleanup_all_members"
DEAD_TWIN = "admin_tools_nuclear_cleanup_all_members"
# An admin_tools_ row that is NOT in DEAD_RULES: the patch must not delete by prefix.
BYSTANDER = "admin_tools_preview_member_cleanup"


def _seed_critical_rule_2306(name):
    if frappe.db.exists(DOCTYPE, name):
        frappe.delete_doc(DOCTYPE, name, force=True)
    frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "operation_name": name,
            "operation_type": "admin",
            "security_level": "critical",
        }
    ).insert()


class TestRemoveDeadCriticalRules2306(FrappeTestCase):
    def test_removes_every_dead_rule_keeps_the_live_twin_and_is_idempotent(self):
        patch = importlib.import_module(PATCH)
        for name in patch.DEAD_RULES:
            _seed_critical_rule_2306(name)
        _seed_critical_rule_2306(LIVE_TWIN)
        _seed_critical_rule_2306(BYSTANDER)
        self.assertIn(DEAD_TWIN, patch.DEAD_RULES)

        patch.execute()
        for name in patch.DEAD_RULES:
            self.assertFalse(frappe.db.exists(DOCTYPE, name), name)
        self.assertTrue(frappe.db.exists(DOCTYPE, LIVE_TWIN), "the live bare-named rule must survive")
        self.assertTrue(frappe.db.exists(DOCTYPE, BYSTANDER), "a row outside DEAD_RULES must survive")

        patch.execute()
        self.assertTrue(frappe.db.exists(DOCTYPE, LIVE_TWIN))

    def test_the_dead_rules_are_gone_from_the_shipped_fixture(self):
        patch = importlib.import_module(PATCH)
        shipped = Path(frappe.get_app_path("verenigingen", "fixtures", "critical_operation_rule.json")).read_text()
        for name in patch.DEAD_RULES:
            self.assertNotIn(f'"operation_name": "{name}"', shipped)
        self.assertIn(f'"operation_name": "{LIVE_TWIN}"', shipped)

    def test_the_patch_is_registered(self):
        patches_txt = Path(frappe.get_app_path("verenigingen", "patches.txt")).read_text()
        self.assertIn(PATCH, patches_txt.splitlines())
