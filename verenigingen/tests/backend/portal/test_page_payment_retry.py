# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the payment retry page controller
(``verenigingen/templates/pages/payment_retry.py``).

The page resolves a Member + Sales Invoice from URL params. Two checks must
both pass before anything is exposed on the context: the invoice must
actually belong to that member (mutual consistency of the two supplied
params), AND the requesting session must be logged in as that same member
(#1052) -- Member.autoname and Sales Invoice's naming_series are both
sequential/guessable, so the first check alone lets any caller who guesses a
matching pair see another member's name, membership type and invoice total.
All documents are real ORM records.
"""

import frappe

from verenigingen.templates.pages import payment_retry
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import member_solely_holds_customer

_MEMBER_ROLE = "Verenigingen Member"


class TestPagePaymentRetry(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()
        self._original_user = frappe.session.user

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        frappe.set_user(self._original_user)
        super().tearDown()

    def _member_with_invoice(self):
        member = self.create_test_member(first_name="Retry", last_name="Member", birth_date="1990-01-01")
        # Inlined rather than kept as a helper: this was a 9th copy of a
        # helper name that already has 8 definitions across the portal tests,
        # and the clone gate blocks a new one. It has a single call site, so
        # an abstraction buys nothing here. The wider consolidation is #401.
        if not frappe.db.exists("User", member.email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": member.email,
                    "first_name": "Retry",
                    "send_welcome_email": 0,
                    "enabled": 1,
                    "roles": [{"role": _MEMBER_ROLE}],
                }
            ).insert(ignore_permissions=True)
        if member.user != member.email:
            member.db_set("user", member.email, update_modified=False)
            member.reload()
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

    def test_matching_member_invoice_populates_context_for_the_owning_session(self):
        """The member's OWN logged-in session sees their own invoice + payment methods."""
        member, invoice = self._member_with_invoice()
        frappe.set_user(member.email)
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
        member_b, _ = self._member_with_invoice()
        frappe.set_user(member_b.email)
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

    # -- #1052: a guest, or a logged-in stranger, supplying someone else's
    # real (member, invoice) pair must be refused exactly like a mismatched
    # pair -- no name, membership type or invoice total disclosed. --------

    def test_guest_with_real_matching_pair_discloses_nothing(self):
        """A Guest supplying a real, mutually-consistent (member, invoice) pair gets no data: login redirect (#2109)."""
        member, invoice = self._member_with_invoice()
        frappe.set_user("Guest")
        frappe.local.form_dict = frappe._dict({"member": member.name, "invoice": invoice.name})
        context = frappe._dict()
        with self.assertRaises(frappe.Redirect):
            payment_retry.get_context(context)
        self.assertIsNone(context.get("member"))
        self.assertIsNone(context.get("invoice"))

    def test_other_logged_in_member_with_real_matching_pair_discloses_nothing(self):
        """A DIFFERENT logged-in member supplying a real matching pair is refused."""
        member, invoice = self._member_with_invoice()
        stranger, _ = self._member_with_invoice()
        frappe.set_user(stranger.email)
        frappe.local.form_dict = frappe._dict({"member": member.name, "invoice": invoice.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        self.assertIsNone(context.member)
        self.assertIsNone(context.invoice)

    # -- #2493, ruling (a): a blank-member invoice is claimed through its Customer alone, which is
    # refused when another Member shares that Customer. ---------------------------------------

    def _open_page_2493(self, member, invoice):
        frappe.set_user(member.email)
        frappe.local.form_dict = frappe._dict({"member": member.name, "invoice": invoice.name})
        context = frappe._dict()
        payment_retry.get_context(context)
        return context

    def _blank_member_invoice_2493(self):
        """A member and an invoice carrying only that member's Customer (`member` blank, as real ones)."""
        member, invoice = self._member_with_invoice()
        frappe.db.set_value("Sales Invoice", invoice.name, "member", None)
        invoice.reload()
        self.assertFalse(invoice.member)
        self.assertEqual(frappe.db.get_value("Member", member.name, "customer"), invoice.customer)
        return member, invoice

    def test_blank_member_invoice_opens_for_the_only_member_of_its_customer_2493(self):
        """CONTROL: exactly one Member holds the Customer, so the fallback still admits them."""
        member, invoice = self._blank_member_invoice_2493()
        context = self._open_page_2493(member, invoice)
        self.assertEqual(context.invoice.name, invoice.name)

    def test_blank_member_invoice_refused_when_its_customer_is_shared_2493(self):
        """BOTH Members linked to the Customer are refused, each exactly like an unknown invoice."""
        member, invoice = self._blank_member_invoice_2493()
        housemate, _ = self._member_with_invoice()
        frappe.db.set_value("Member", housemate.name, "customer", invoice.customer)
        for caller in (member, housemate):
            refused = self._open_page_2493(caller, invoice)
            frappe.local.form_dict = frappe._dict(
                {"member": caller.name, "invoice": "ACC-SINV-DOES-NOT-EXIST-2493"}
            )
            unknown_ctx = frappe._dict()
            payment_retry.get_context(unknown_ctx)
            self.assertIsNone(refused.member, caller.name)
            self.assertIsNone(refused.invoice, caller.name)
            self.assertEqual(dict(refused), dict(unknown_ctx))

    def test_member_solely_holds_customer_2493(self):
        """The one rule: true only for the single Member linked to the Customer."""
        member, invoice = self._member_with_invoice()
        other, _ = self._member_with_invoice()
        customer = invoice.customer
        self.assertTrue(member_solely_holds_customer(member.name, customer))
        # a non-holder on a single-holder Customer
        self.assertFalse(member_solely_holds_customer(other.name, customer))
        frappe.db.set_value("Member", other.name, "customer", customer)
        # two holders: false for BOTH (kills pick-first and limit=1 variants)
        self.assertFalse(member_solely_holds_customer(member.name, customer))
        self.assertFalse(member_solely_holds_customer(other.name, customer))
        self.assertFalse(member_solely_holds_customer("", customer))
        self.assertFalse(member_solely_holds_customer(member.name, ""))
        self.assertFalse(member_solely_holds_customer(None, None))

    def test_member_set_invoice_unaffected_when_customer_is_shared_2493(self):
        """CONTROL: an invoice naming the member stays theirs even if the Customer is shared."""
        member, invoice = self._member_with_invoice()
        housemate = self.create_test_member(first_name="Housemate", last_name="Retry", birth_date="1991-01-01")
        frappe.db.set_value("Member", housemate.name, "customer", invoice.customer)
        self.assertEqual(invoice.member, member.name)
        context = self._open_page_2493(member, invoice)
        self.assertEqual(context.invoice.name, invoice.name)
