import frappe
from frappe.tests.utils import FrappeTestCase


class TestRenameMemberImport(FrappeTestCase):
    def test_member_import_doctype_exists(self):
        self.assertTrue(frappe.db.exists("DocType", "Member Import"))
        self.assertFalse(frappe.db.exists("DocType", "Procurios CSV Import"))

    def test_series_updated(self):
        naming = frappe.get_meta("Member Import").get_field("naming_series")
        self.assertIn("MEM-IMP-", naming.options)
