import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.patches.v15_0.rename_procurios_csv_import_to_member_import import (
    _drop_stale_naming_series_property_setters,
)


class TestRenameMemberImport(FrappeTestCase):
    def test_member_import_doctype_exists(self):
        self.assertTrue(frappe.db.exists("DocType", "Member Import"))
        self.assertFalse(frappe.db.exists("DocType", "Procurios CSV Import"))

    def test_series_updated(self):
        naming = frappe.get_meta("Member Import").get_field("naming_series")
        self.assertIn("MEM-IMP-", naming.options)

    def _make_stale_naming_series_property_setters(self):
        """Factory: create the PROC-IMP- naming_series Property Setters that
        the original doctype carried and rename_doc leaves behind."""
        created = []
        for prop in ("options", "default"):
            ps = frappe.get_doc(
                {
                    "doctype": "Property Setter",
                    "doctype_or_field": "DocField",
                    "doc_type": "Member Import",
                    "field_name": "naming_series",
                    "property": prop,
                    "property_type": "Text" if prop == "options" else "Data",
                    "value": "PROC-IMP-.YYYY.-.####.",
                }
            ).insert(ignore_permissions=True)
            created.append(ps.name)
        return created

    def test_patch_clears_stale_proc_imp_property_setters(self):
        """Reproduces the veg11 case: the original doctype carried
        naming_series Property Setters pinning PROC-IMP-, which rename_doc
        re-points at 'Member Import' with the stale value and which then
        override the JSON's MEM-IMP-. The patch must delete them so MEM-IMP-
        takes effect. See _drop_stale_naming_series_property_setters."""
        created = self._make_stale_naming_series_property_setters()

        # Sanity: the stale setter is now in effect
        frappe.clear_cache(doctype="Member Import")
        self.assertEqual(
            frappe.get_meta("Member Import").get_field("naming_series").options,
            "PROC-IMP-.YYYY.-.####.",
        )

        _drop_stale_naming_series_property_setters()

        for name in created:
            self.assertFalse(
                frappe.db.exists("Property Setter", name),
                f"stale Property Setter {name} should have been deleted",
            )
        # JSON-defined MEM-IMP- now applies again
        self.assertIn(
            "MEM-IMP-",
            frappe.get_meta("Member Import").get_field("naming_series").options,
        )
