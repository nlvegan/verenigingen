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
    def _insert_web_form(self, title, route):
        return frappe.get_doc(
            {
                "doctype": "Web Form",
                "title": title,
                "route": route,
                "doc_type": "Donation",
                "module": "Verenigingen",
                "published": 0,
            }
        ).insert()

    def _leftover(self):
        # A pre-existing real row would collide with the insert; the harness rollback undoes this delete.
        frappe.db.delete("Web Form", {"name": NAME})
        self._insert_web_form("Donation Form", "donate-813-test")
        self.assertEqual(frappe.db.exists("Web Form", NAME), NAME, "control: the row exists")

    def test_the_leftover_row_is_deleted_and_a_second_run_is_a_noop(self):
        self._leftover()
        execute = importlib.import_module(PATCH).execute
        execute()
        self.assertFalse(frappe.db.exists("Web Form", NAME))
        execute()  # idempotent
        self.assertFalse(frappe.db.exists("Web Form", NAME))

    def test_other_web_forms_are_untouched(self):
        self._leftover()
        other = self._insert_web_form("Other 813 Form", "other-813-test").name
        self.assertNotEqual(other, NAME, "control: a different row")
        importlib.import_module(PATCH).execute()
        self.assertFalse(frappe.db.exists("Web Form", NAME))
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
