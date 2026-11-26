"""#2234: the `membership_applications_overdue` Email Template had no sender (its only
intended sender, `send_overdue_notifications`, never sent anything; deleted under #1869).

Removing the row from the fixture file alone prunes nothing on existing sites, because
fixture sync inserts and updates but never deletes; the patch does.

Runs inside the test transaction: the patch does not commit, so nothing leaks.
Probe shortcut: the existing-site row is inserted directly, and ``execute`` is called
directly, not through the patch runner.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

import verenigingen
from verenigingen.patches.v2_2.remove_overdue_applications_email_template_2234 import (
    DEAD_TEMPLATE,
    execute,
)

APP_ROOT = Path(verenigingen.__file__).parent
# A live neighbour in the same fixture file: a near-name control the patch must not touch.
CONTROL = "membership_application_approved"


def _ensure_template(name):
    if not frappe.db.exists("Email Template", name):
        frappe.get_doc(
            {"doctype": "Email Template", "name": name, "subject": "s", "response": "<p>r</p>"}
        ).insert(ignore_permissions=True)


class TestRemoveOverdueApplicationsEmailTemplate(FrappeTestCase):
    def test_the_fixture_no_longer_ships_the_template(self):
        shipped = json.loads((APP_ROOT / "fixtures" / "email_template.json").read_text())
        names = {row["name"] for row in shipped}
        self.assertNotIn(DEAD_TEMPLATE, names)
        # control: the scan can see rows at all, including the live neighbour
        self.assertIn(CONTROL, names)

    def test_execute_deletes_the_row_and_keeps_the_neighbour(self):
        _ensure_template(DEAD_TEMPLATE)
        _ensure_template(CONTROL)

        execute()

        self.assertFalse(frappe.db.exists("Email Template", DEAD_TEMPLATE))
        self.assertTrue(frappe.db.exists("Email Template", CONTROL))

    def test_execute_is_idempotent_when_the_row_is_already_gone(self):
        frappe.db.delete("Email Template", {"name": DEAD_TEMPLATE})
        execute()
        execute()
        self.assertFalse(frappe.db.exists("Email Template", DEAD_TEMPLATE))

    def test_the_patch_is_registered(self):
        listed = (APP_ROOT / "patches.txt").read_text().splitlines()
        self.assertIn("verenigingen.patches.v2_2.remove_overdue_applications_email_template_2234", listed)
