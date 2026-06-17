# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment retry page controller
(``verenigingen/templates/pages/payment_retry.py``).

The page resolves a Member + Sales Invoice from URL params and only exposes
them on the context when the invoice actually belongs to that member (an
ownership check). All documents are real ORM records.
"""

import frappe

from verenigingen.templates.pages import payment_retry
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPagePaymentRetry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        super().tearDown()

    def _member_with_invoice(self):
        member = self.create_test_member(first_name="Retry", last_name="Member", birth_date="1990-01-01")
        # The factory resolves the Member to its Customer (creating one if needed).
        invoice = self.create_test_sales_invoice(customer=member.name)
        self.track_doc("Sales Invoice", invoice.name)
        # Link the invoice back to the member (the page checks invoice.member).
        frappe.db.set_value("Sales Invoice", invoice.name, "member", member.name)
        invoice.reload()
        return member, invoice

    def test_missing_params_yields_no_member(self):
        """No member/invoice params => no member, no invoice on context."""
        frappe.local.form_dict = frappe._dict()
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.member)
        self.assertIsNone(context.invoice)

    def test_matching_member_invoice_populates_context(self):
        """A member + their own invoice populate the context plus payment methods."""
        member, invoice = self._member_with_invoice()
        frappe.local.form_dict = frappe._dict({"member": member.name, "invoice": invoice.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNotNone(context.member)
        self.assertEqual(context.member.name, member.name)
        self.assertEqual(context.invoice.name, invoice.name)
        # Enabled modes of payment are exposed for the retry UI.
        self.assertIsInstance(context.payment_methods, list)

    def test_invoice_belonging_to_other_member_is_rejected(self):
        """An invoice that does not belong to the member is NOT exposed (ownership guard)."""
        member_a, invoice_a = self._member_with_invoice()
        member_b = self.create_test_member(first_name="Other", last_name="Member", birth_date="1991-02-02")
        frappe.local.form_dict = frappe._dict({"member": member_b.name, "invoice": invoice_a.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.member)
        self.assertIsNone(context.invoice)

    def test_unknown_member_is_handled_gracefully(self):
        """A bogus member id is caught and yields no member rather than a 500."""
        frappe.local.form_dict = frappe._dict({"member": "Member-DOES-NOT-EXIST", "invoice": "X"})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.member)
        self.assertIsNone(context.invoice)
