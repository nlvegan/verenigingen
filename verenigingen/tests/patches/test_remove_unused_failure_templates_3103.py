"""#3103: the Email Templates `payment_failure_first`, `payment_failure_second` and
`payment_failure_generic` had no sender (maintainer ruling 2026-11-25: members get the
per-failure "Payment Retry Scheduled" mail and a retry-exhaustion mail; these three are deleted).

Fixture sync never deletes, so the patch must remove them from existing sites, and must clear
any Email Notification Type row still linking one (a dangling Link fails the next save of that row).

Runs inside the test transaction (the patch does not commit).
Probe shortcut: existing-site rows are inserted directly and ``execute`` is called directly,
not through the patch runner.
"""

import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

import verenigingen
from verenigingen.patches.v2_2.remove_unused_failure_templates_3103 import DEAD_TEMPLATES, execute

APP_ROOT = Path(verenigingen.__file__).parent
# payment_failure_final is wired by a sender (PR #3244): a near-name control the patch must keep.
CONTROL = "payment_failure_final"
KEY = "zz_probe_3103"


def _ensure_probe_template_3103(name):
    if not frappe.db.exists("Email Template", name):
        frappe.get_doc(
            {"doctype": "Email Template", "name": name, "subject": "s", "response": "<p>r</p>"}
        ).insert(ignore_permissions=True)


class TestRemoveUnusedFailureTemplates(FrappeTestCase):
    def test_the_fixture_no_longer_ships_the_templates(self):
        names = {row["name"] for row in json.loads((APP_ROOT / "fixtures" / "email_template.json").read_text())}
        self.assertEqual(set(DEAD_TEMPLATES), {"payment_failure_first", "payment_failure_second", "payment_failure_generic"})
        for dead in DEAD_TEMPLATES:
            self.assertNotIn(dead, names)
        self.assertIn(CONTROL, names)  # control: the scan sees rows, including the live neighbour

    def test_execute_deletes_the_rows_and_keeps_the_neighbour(self):
        for name in (*DEAD_TEMPLATES, CONTROL):
            _ensure_probe_template_3103(name)
        execute()
        for dead in DEAD_TEMPLATES:
            self.assertFalse(frappe.db.exists("Email Template", dead), dead)
        self.assertTrue(frappe.db.exists("Email Template", CONTROL))

    def test_execute_clears_a_notification_type_link_to_a_deleted_template(self):
        _ensure_probe_template_3103(DEAD_TEMPLATES[0])
        _ensure_probe_template_3103(CONTROL)
        frappe.db.delete("Email Notification Type", {"notification_key": ["like", f"{KEY}%"]})
        for suffix, template in (("a", DEAD_TEMPLATES[0]), ("b", CONTROL)):
            row = frappe.new_doc("Email Notification Type")
            row.update({"notification_key": f"{KEY}_{suffix}", "label": "probe", "email_template": template,
                        "parent": "Verenigingen Email Configuration", "parenttype": "Verenigingen Email Configuration",
                        "parentfield": "notification_types"})
            row.db_insert()
        execute()
        get = lambda s: frappe.db.get_value("Email Notification Type", {"notification_key": f"{KEY}_{s}"}, "email_template")
        self.assertFalse(get("a"))
        self.assertEqual(get("b"), CONTROL)

    def test_execute_is_idempotent_when_the_rows_are_already_gone(self):
        for dead in DEAD_TEMPLATES:
            frappe.db.delete("Email Template", {"name": dead})
        execute()
        execute()

    def test_the_patch_is_registered(self):
        fragments = (APP_ROOT / "patches.d" / "post_model_sync").glob("*.txt")
        lines = {l.strip() for f in fragments for l in f.read_text().splitlines()}
        self.assertIn("verenigingen.patches.v2_2.remove_unused_failure_templates_3103", lines)
