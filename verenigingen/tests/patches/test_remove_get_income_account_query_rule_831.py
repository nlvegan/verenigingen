"""#831/#2288: the patch removes the dead `get_income_account_query` Critical Operation Rule row.

Probe shortcut: the existing-site state is a row inserted by the test, and the patch's ``execute``
is called directly, not through the patch runner. A real row on the site is deleted inside the
test first; the harness rollback undoes that.
"""

import importlib
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

DOCTYPE = "Critical Operation Rule"
PATCH = "verenigingen.patches.v2_2.remove_get_income_account_query_critical_operation_rule"
DEAD = "get_income_account_query"
OTHER = "Test831KeepRule"


def _make_rule(name):
    if frappe.db.exists(DOCTYPE, name):
        frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
    frappe.get_doc(
        {
            "doctype": DOCTYPE,
            "operation_name": name,
            "operation_type": "reporting",
            "security_level": "low",
        }
    ).insert(ignore_permissions=True)


class TestRemoveGetIncomeAccountQueryRule(FrappeTestCase):
    def test_removes_only_the_dead_rule_and_is_idempotent(self):
        _make_rule(DEAD)
        _make_rule(OTHER)
        patch = importlib.import_module(PATCH)

        patch.execute()
        self.assertFalse(frappe.db.exists(DOCTYPE, DEAD))
        self.assertTrue(frappe.db.exists(DOCTYPE, OTHER), "an unrelated rule must survive")

        patch.execute()  # second run: row already gone, must be a no-op
        self.assertFalse(frappe.db.exists(DOCTYPE, DEAD))
        self.assertTrue(frappe.db.exists(DOCTYPE, OTHER))

    def test_the_patch_is_registered(self):
        patches_txt = Path(frappe.get_app_path("verenigingen", "patches.txt")).read_text()
        self.assertIn(PATCH, patches_txt.splitlines())
