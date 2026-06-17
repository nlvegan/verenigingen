# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the customer-facing Ponto payment link page controller
(``verenigingen/templates/pages/ponto_pay.py``).

The page resolves a ``Ponto Payment Link`` from the ``id`` URL param and builds
a sanitised context describing the payment and its status. All Ponto Payment
Link documents are real ORM records created in setUp; nothing about Ponto's
HTTP API is exercised here (the page only reads stored fields).
"""

import frappe

from verenigingen.templates.pages import ponto_pay
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# A structurally valid Dutch IBAN; creditor_iban is mandatory on the doctype.
_VALID_IBAN = "NL39RABO0300065264"


class TestPagePontoPay(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        super().tearDown()

    def _make_link(self, status="Pending Authorization", **kwargs):
        data = {
            "doctype": "Ponto Payment Link",
            "amount": kwargs.pop("amount", 25.0),
            "currency": "EUR",
            "description": kwargs.pop("description", "Membership payment"),
            "creditor_name": "Test Org",
            "creditor_iban": _VALID_IBAN,
            "payment_type": "One-Time",
            "status": status,
            "redirect_link": kwargs.pop("redirect_link", "https://bank.example/auth/abc"),
        }
        data.update(kwargs)
        link = frappe.get_doc(data)
        link.insert()
        self.track_doc("Ponto Payment Link", link.name)
        return link

    def test_missing_id_sets_error(self):
        """No id param => explicit error, no payment_link in context."""
        frappe.local.form_dict = frappe._dict()
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNotNone(context.error)
        self.assertIsNone(context.payment_link)

    def test_unknown_link_sets_not_found(self):
        """A non-existent payment link id resolves to a 'not found' error."""
        frappe.local.form_dict = frappe._dict({"id": "PONTO-LINK-DOES-NOT-EXIST"})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNotNone(context.error)
        self.assertIsNone(context.payment_link)

    def test_pending_link_builds_full_context(self):
        """A pending link exposes the sanitised payment detail dict on the context."""
        link = self._make_link(status="Pending Authorization", amount=42.5)
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)

        self.assertIsNotNone(context.payment_link)
        self.assertEqual(context.payment_link["name"], link.name)
        self.assertEqual(float(context.payment_link["amount"]), 42.5)
        self.assertEqual(context.payment_link["status"], "Pending Authorization")
        # A pending link with a redirect_link should not have set an error.
        self.assertIsNone(context.get("error"))

    def test_executed_link_marks_complete(self):
        """An Executed link sets payment_complete + success message."""
        link = self._make_link(status="Pending Authorization")
        # Move to Executed directly in the DB (submittable lifecycle is internal).
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Executed")
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_complete"))
        self.assertIsNotNone(context.get("success_message"))

    def test_cancelled_link_marks_failed(self):
        """A Cancelled link sets payment_failed and an explanatory error."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Cancelled")
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_failed"))
        self.assertIsNotNone(context.get("error"))

    def test_expired_link_marks_expired(self):
        """An Expired link sets payment_expired and an error message."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Expired")
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_expired"))

    def test_missing_redirect_link_warns(self):
        """A pending link without a redirect link tells the user it is not ready yet."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "redirect_link", "")
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNotNone(context.get("error"))

    def test_linked_member_name_surfaced(self):
        """When linked to a Member, the member's full name is added to the context."""
        member = self.create_test_member(first_name="Ponto", last_name="Payer", birth_date="1990-01-01")
        link = self._make_link(member=member.name)
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertEqual(context.payment_link["member_name"], member.full_name)
