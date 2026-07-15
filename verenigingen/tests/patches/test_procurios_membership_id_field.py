import frappe
from frappe.tests.utils import FrappeTestCase


class TestProcuriosMembershipIdField(FrappeTestCase):
    def test_field_exists_on_membership(self):
        meta = frappe.get_meta("Membership")
        field = meta.get_field("procurios_membership_id")
        self.assertIsNotNone(field, "procurios_membership_id custom field missing on Membership")
        self.assertEqual(field.fieldtype, "Data")
