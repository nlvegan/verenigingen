"""#813: the patch removes the donation-form Web Form row left on existing sites, and is idempotent.

Probe shortcut: the leftover row is inserted directly (a plain Web Form with the old name) to stand in
for the row a pre-deletion migrate synced from the removed files; ``execute`` is called directly.
"""

import importlib
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

PATCH = "verenigingen.patches.v2_2.delete_dead_donation_form_web_form_813"
NAME = "donation-form"


class TestDeleteDeadDonationFormWebForm(FrappeTestCase):
    def _leftover(self):
        frappe.get_doc(
            {
                "doctype": "Web Form",
                "title": "Donation Form",
                "route": "donate-813-test",
                "doc_type": "Donation",
                "module": "Verenigingen",
                "published": 0,
            }
        ).insert()
        self.assertEqual(frappe.db.exists("Web Form", NAME), NAME, "control: the row exists")
        self.addCleanup(self._remove_leftover)

    @staticmethod
    def _remove_leftover():
        # Web Form insert commits, so the class rollback cannot remove the row: delete it for real,
        # or a failing run leaves it behind and the next run skips instead of testing.
        frappe.db.delete("Web Form", {"name": NAME})
        frappe.db.commit()

    def test_the_leftover_row_is_deleted_and_a_second_run_is_a_noop(self):
        if frappe.db.exists("Web Form", NAME):
            self.skipTest("a real donation-form row already exists on this site")
        self._leftover()
        execute = importlib.import_module(PATCH).execute
        execute()
        self.assertFalse(frappe.db.exists("Web Form", NAME))
        execute()  # idempotent
        self.assertFalse(frappe.db.exists("Web Form", NAME))

    def test_other_web_forms_are_untouched(self):
        other = frappe.db.get_value("Web Form", {"name": ["!=", NAME]}, "name")
        if not other:
            self.skipTest("no other Web Form on this site")
        importlib.import_module(PATCH).execute()
        self.assertTrue(frappe.db.exists("Web Form", other))

    def test_the_patch_is_registered(self):
        import verenigingen

        listed = (Path(verenigingen.__file__).parent / "patches.txt").read_text().splitlines()
        self.assertIn(PATCH, listed)

    def test_the_form_files_are_gone(self):
        import verenigingen

        root = Path(verenigingen.__file__).parent / "verenigingen" / "web_form"
        self.assertFalse((root / "donation_form").exists())
        self.assertTrue((root / "periodic_donation_agreement_form").exists(), "control: sibling form kept")
