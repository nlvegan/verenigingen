"""Tests for the stock Email Template restore helper (#1981, #1982)."""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.stock_email_templates import (
    _cleanup_stock_email_templates,
    _load_fixture_rows,
)

STOCK = "membership_application_approved"
NOT_STOCK = "test_1981_not_in_fixture"


class TestStockEmailTemplates(VereningingenTestCase):
    @classmethod
    def tearDownClass(cls):
        _cleanup_stock_email_templates([STOCK, NOT_STOCK])
        super().tearDownClass()

    def test_polluted_stock_row_is_overwritten_with_the_fixture_body(self):
        fixture_row = _load_fixture_rows()[STOCK]
        junk = "<p>JUNK {{ membership_type.membership_type_name }}</p>"
        _cleanup_stock_email_templates([STOCK])
        frappe.db.set_value("Email Template", STOCK, {"response_html": junk, "use_html": 0})
        self.assertEqual(frappe.db.get_value("Email Template", STOCK, "response_html"), junk)

        _cleanup_stock_email_templates([STOCK])

        doc = frappe.get_doc("Email Template", STOCK)
        self.assertEqual(doc.response_html, fixture_row["response_html"])
        self.assertEqual(doc.use_html, fixture_row["use_html"])
        self.assertEqual(doc.subject, fixture_row["subject"])

    def test_deleted_stock_row_is_recreated(self):
        frappe.delete_doc("Email Template", STOCK, force=True)
        self.assertFalse(frappe.db.exists("Email Template", STOCK))

        _cleanup_stock_email_templates([STOCK])

        fixture_row = _load_fixture_rows()[STOCK]
        doc = frappe.get_doc("Email Template", STOCK)
        self.assertEqual(doc.response_html, fixture_row["response_html"])
        self.assertEqual(doc.use_html, fixture_row["use_html"])
        self.assertEqual(doc.subject, fixture_row["subject"])

    def test_row_with_a_non_doctype_reference_doctype_is_restored(self):
        """The fixture row's reference_doctype ('Membership Application') is not a
        DocType here; link validation on re-insert raised after the delete."""
        name = "membership_application_confirmation"
        fixture_row = _load_fixture_rows()[name]
        self.assertFalse(frappe.db.exists("DocType", fixture_row["reference_doctype"]))

        _cleanup_stock_email_templates([name])

        doc = frappe.get_doc("Email Template", name)
        self.assertEqual(doc.subject, fixture_row["subject"])
        self.assertEqual(doc.reference_doctype, fixture_row["reference_doctype"])

    def test_name_not_in_the_fixture_is_left_deleted(self):
        self.assertNotIn(NOT_STOCK, _load_fixture_rows())
        frappe.get_doc(
            {"doctype": "Email Template", "name": NOT_STOCK, "subject": "x", "response": "x"}
        ).insert()
        self.assertTrue(frappe.db.exists("Email Template", NOT_STOCK))

        _cleanup_stock_email_templates([NOT_STOCK])

        self.assertFalse(frappe.db.exists("Email Template", NOT_STOCK))

    def test_a_name_not_listed_is_not_touched(self):
        """Control: only the named rows are restored."""
        frappe.db.set_value("Email Template", STOCK, "subject", "UNTOUCHED")
        _cleanup_stock_email_templates([NOT_STOCK])
        self.assertEqual(frappe.db.get_value("Email Template", STOCK, "subject"), "UNTOUCHED")
