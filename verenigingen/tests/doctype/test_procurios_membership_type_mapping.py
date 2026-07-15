import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcuriosMembershipTypeMapping(FrappeTestCase):
    def test_doctype_is_child_with_expected_fields(self):
        meta = frappe.get_meta("Procurios Membership Type Mapping")
        self.assertTrue(meta.istable, "must be a child table")
        self.assertEqual(meta.get_field("membership_type").options, "Membership Type")
        self.assertTrue(meta.get_field("procurios_type").read_only)
