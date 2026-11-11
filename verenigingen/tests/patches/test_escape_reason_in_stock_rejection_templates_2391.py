"""#2391: the patch adds |e to {{ reason }} in a stock rejection Email Template ONLY while the row still
holds the old stock text; an admin-edited row is left alone.

Probe shortcut: an existing site's row is built by writing the frozen old text over the template, and the
patch's ``execute`` is called directly, not through the patch runner.
"""

import importlib
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates

PATCH = "verenigingen.patches.v2_2.escape_reason_in_stock_rejection_templates_2391"
NAMES = [
    "membership_application_rejected",
    "membership_rejection_incomplete",
    "membership_rejection_ineligible",
    "membership_rejection_duplicate",
]


def _write(name, response):
    """Make the row exist with exactly this response (a row created from scratch if missing)."""
    if frappe.db.exists("Email Template", name):
        frappe.db.set_value("Email Template", name, "response", response, update_modified=False)
        return
    frappe.get_doc(
        {"doctype": "Email Template", "name": name, "subject": "s {{ member_name }}", "response": response}
    ).insert()


class TestEscapeReasonInStockRejectionTemplates(FrappeTestCase):
    def setUp(self):
        super().setUp()
        self.patch = importlib.import_module(PATCH)
        self.addCleanup(_cleanup_stock_email_templates, NAMES)

    def test_old_stock_rows_get_the_escape_and_nothing_else_changes(self):
        for name, old in self.patch.OLD_STOCK.items():
            _write(name, old)

        self.patch.execute()

        for name, old in self.patch.OLD_STOCK.items():
            response = frappe.db.get_value("Email Template", name, "response")
            self.assertEqual(response, old.replace("{{ reason }}", "{{ reason|e }}"), name)
            self.assertNotIn("{{ reason }}", response, name)
            self.assertEqual(response.count("{{ reason|e }}"), 1, name)

    def test_an_edited_row_is_left_alone(self):
        name = "membership_rejection_incomplete"
        edited = self.patch.OLD_STOCK[name] + "\n<p>Our own footer {{ reason }}</p>"
        _write(name, edited)

        self.patch.execute()

        self.assertEqual(frappe.db.get_value("Email Template", name, "response"), edited)

    def test_a_second_run_changes_nothing(self):
        for name, old in self.patch.OLD_STOCK.items():
            _write(name, old)
        self.patch.execute()
        after_first = {n: frappe.db.get_value("Email Template", n, "response") for n in NAMES}

        self.patch.execute()

        self.assertEqual(after_first, {n: frappe.db.get_value("Email Template", n, "response") for n in NAMES})

    def test_the_old_stock_text_is_what_the_seeder_used_to_write(self):
        """Control: the frozen text is the seeder's text minus the escape, so a site seeded before this
        fix really matches. Fails if the seeder body drifts from the frozen copy."""
        from verenigingen.api.membership_email_templates import create_default_email_templates

        for name in NAMES:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True)
        create_default_email_templates()

        for name, old in self.patch.OLD_STOCK.items():
            seeded = frappe.db.get_value("Email Template", name, "response")
            self.assertEqual(seeded.replace("{{ reason|e }}", "{{ reason }}"), old, name)

    def test_the_patch_is_registered(self):
        import verenigingen

        listed = (Path(verenigingen.__file__).parent / "patches.txt").read_text().splitlines()
        self.assertIn(PATCH, listed)
