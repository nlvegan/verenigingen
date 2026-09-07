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
from verenigingen.templates.pages.ponto_pay import PONTO_PAY_TOKEN_PURPOSE
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.guest_return_tokens import (
    generate_guest_return_token,
    verify_guest_return_token,
)

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

    def _form_dict_with_valid_token(self, link):
        """id + the HMAC proof get_payment_url() would embed for this link (#1053)."""
        token = generate_guest_return_token(PONTO_PAY_TOKEN_PURPOSE, link.name)
        return frappe._dict({"id": link.name, "token": token})

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
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
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
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_complete"))
        self.assertIsNotNone(context.get("success_message"))

    def test_cancelled_link_marks_failed(self):
        """A Cancelled link sets payment_failed and an explanatory error."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Cancelled")
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_failed"))
        self.assertIsNotNone(context.get("error"))

    def test_expired_link_marks_expired(self):
        """An Expired link sets payment_expired and an error message."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "status", "Expired")
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertTrue(context.get("payment_expired"))

    def test_missing_redirect_link_warns(self):
        """A pending link without a redirect link tells the user it is not ready yet."""
        link = self._make_link(status="Pending Authorization")
        frappe.db.set_value("Ponto Payment Link", link.name, "redirect_link", "")
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNotNone(context.get("error"))

    def test_linked_member_name_surfaced(self):
        """When linked to a Member, the member's full name is added to the context."""
        member = self.create_test_member(first_name="Ponto", last_name="Payer", birth_date="1990-01-01")
        link = self._make_link(member=member.name)
        frappe.local.form_dict = self._form_dict_with_valid_token(link)
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertEqual(context.payment_link["member_name"], member.full_name)

    # -- #1053: a guest supplying a real, guessable link id with no/wrong
    # proof must be refused exactly like an unknown id -- no amount,
    # creditor_name or member_name disclosed. ----------------------------

    def test_real_id_with_no_token_discloses_nothing(self):
        """A real link id with NO token gets the same refusal as an unknown id."""
        link = self._make_link(amount=99.0, creditor_name="Real Creditor")
        frappe.local.form_dict = frappe._dict({"id": link.name})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNone(context.payment_link)
        self.assertIsNotNone(context.error)

    def test_real_id_with_wrong_token_discloses_nothing(self):
        """A real link id with a WRONG token gets the same refusal as an unknown id."""
        link = self._make_link(amount=99.0, creditor_name="Real Creditor")
        frappe.local.form_dict = frappe._dict({"id": link.name, "token": "0" * 64})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNone(context.payment_link)
        self.assertIsNotNone(context.error)

    def test_non_ascii_token_is_refused_not_raised(self):
        """A non-ASCII token must be REFUSED, not raise.

        ``hmac.compare_digest`` rejects non-ASCII ``str`` with a TypeError, and
        ponto_pay's token check sits OUTSIDE this controller's try/except -- so
        before the guard caught it, ``?token=h\u00e9llo`` produced a traceback
        instead of the ordinary refusal. No document data leaked either way
        (the raise happens before any get_doc), but a guest-supplied byte
        should never decide whether a page 500s.
        """
        link = self._make_link(amount=99.0, creditor_name="Real Creditor")
        frappe.local.form_dict = frappe._dict({"id": link.name, "token": "h\u00e9llo"})
        context = frappe._dict()

        ponto_pay.get_context(context)

        # Same refusal as any other bad token -- not a distinct error, and not a raise.
        self.assertIsNone(context.payment_link)
        self.assertIsNotNone(context.error)

    def test_verify_token_refuses_non_ascii_at_the_helper(self):
        """The helper itself fails closed, so every caller is covered, not just
        the two that happen to sit inside a try/except."""
        self.assertFalse(
            verify_guest_return_token(PONTO_PAY_TOKEN_PURPOSE, "PONTO-LINK-0001", "h\u00e9llo")
        )

    def test_get_payment_url_embeds_a_valid_token(self):
        """Ponto Payment Link.get_payment_url() mints a token get_context accepts."""
        link = self._make_link(amount=15.0)
        url = link.get_payment_url()
        self.assertIn(f"id={link.name}", url)
        self.assertIn("token=", url)
        token = url.split("token=", 1)[1].split("&", 1)[0]
        frappe.local.form_dict = frappe._dict({"id": link.name, "token": token})
        context = frappe._dict()
        ponto_pay.get_context(context)
        self.assertIsNotNone(context.payment_link)
