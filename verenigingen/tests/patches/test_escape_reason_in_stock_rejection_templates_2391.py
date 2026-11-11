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
# Written out here, not imported from the patch, so the test states the on-disk shapes independently.
MINIFIED_STYLE = "background:#fff3cd;border:1px solid #ffeaa7;padding:15px;border-radius:5px;margin:15px 0"
SPACED_STYLE = (
    "background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0;"
)


def _write(name, response):
    """Make the row exist with exactly this response. insert() would run the sanitiser (and minify an inline
    style), so the row is created first and the response is then written with set_value, verbatim."""
    if not frappe.db.exists("Email Template", name):
        frappe.get_doc(
            {"doctype": "Email Template", "name": name, "subject": "s {{ member_name }}", "response": "x"}
        ).insert()
    frappe.db.set_value("Email Template", name, "response", response, update_modified=False)


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

    def test_an_install_seeded_row_with_the_spaced_style_gets_the_escape(self):
        """Rows seeded under frappe.flags.in_install skip the sanitiser and keep the spaced inline style.
        Built the way a real site gets one: seed with the flag set, then undo the escape (test_site_11 has
        developer_mode=1, which does not affect this path)."""
        for name in NAMES:
            if frappe.db.exists("Email Template", name):
                frappe.delete_doc("Email Template", name, force=True)
        from verenigingen.api.membership_email_templates import create_default_email_templates

        previous = frappe.flags.in_install
        frappe.flags.in_install = True
        try:
            create_default_email_templates()
        finally:
            frappe.flags.in_install = previous
        for name in NAMES:
            seeded = frappe.db.get_value("Email Template", name, "response")
            # control: this really is the spaced, unsanitised shape (not the minified one)
            self.assertIn(SPACED_STYLE, seeded, name)
            _write(name, seeded.replace("{{ reason|e }}", "{{ reason }}"))

        self.patch.execute()

        for name in NAMES:
            response = frappe.db.get_value("Email Template", name, "response")
            self.assertIn("{{ reason|e }}", response, name)
            self.assertNotIn("{{ reason }}", response, name)
            self.assertIn(SPACED_STYLE, response, name)

    def test_an_edited_spaced_row_is_left_alone(self):
        name = "membership_rejection_ineligible"
        edited = self.patch.OLD_STOCK[name].replace(
            MINIFIED_STYLE, SPACED_STYLE
        ) + "\n<p>Our own footer</p>"
        _write(name, edited)

        self.patch.execute()

        self.assertEqual(frappe.db.get_value("Email Template", name, "response"), edited)

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
