# -*- coding: utf-8 -*-
"""
Coverage tests for services/member/approval/application_payments.py

Targets the pure / lightly-DB-backed helpers:
    - validate_payment_amount (correct / underpayment / overpayment)
    - calculate_membership_amount_with_discounts (base resolution + min floor)
    - format_currency_for_display
    - get_payment_methods (DB-backed list)
    - get_membership_item (throw path when no item configured)
    - create_customer_for_member (real Customer + Contact creation, dedup)

Note: invoice/payment-entry submission paths require an ERPNext company +
items chain and are exercised by the integration approval suites, not here.
"""

import frappe

from verenigingen.services.member.approval import application_payments as ap
from verenigingen.tests.utils.base import VereningingenTestCase


class TestValidatePaymentAmount(VereningingenTestCase):
    """validate_payment_amount() tolerance branches."""

    def _invoice(self, grand_total):
        return frappe._dict({"grand_total": grand_total})

    def test_exact_amount_valid(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 50.0)
        self.assertTrue(result["valid"])

    def test_within_tolerance_valid(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 50.005)
        self.assertTrue(result["valid"])

    def test_underpayment_invalid(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 40.0)
        self.assertFalse(result["valid"])
        self.assertIn("less than", result["message"])

    def test_overpayment_treated_as_donation(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 75.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["overpayment"], 25.0)
        self.assertIn("donation", result["message"])


class TestCalculateMembershipAmountWithDiscounts(VereningingenTestCase):
    """calculate_membership_amount_with_discounts() base resolution + floor."""

    def test_resolves_base_from_template_and_applies_floor(self):
        mt = self.create_test_membership_type(minimum_amount=15.0)
        result = ap.calculate_membership_amount_with_discounts(mt, {})
        # Auto-created template has dues_rate / suggested → base > 0.
        self.assertGreater(result["base_amount"], 0)
        # No discounts wired → final equals base.
        self.assertEqual(result["final_amount"], result["base_amount"])
        self.assertEqual(result["discounts_applied"], [])
        self.assertEqual(result["total_discount"], 0)

    def test_minimum_floor_of_one(self):
        """When the resolved base is below 1, the final amount is floored to 1."""
        mt = self.create_test_membership_type(minimum_amount=0)
        template = frappe.get_doc("Membership Dues Schedule", mt.dues_schedule_template)
        template.suggested_amount = 0
        template.dues_rate = 0
        template.save()

        result = ap.calculate_membership_amount_with_discounts(mt, {})
        self.assertEqual(result["base_amount"], 0)
        self.assertEqual(result["final_amount"], 1)


class TestFormatCurrencyForDisplay(VereningingenTestCase):
    """format_currency_for_display() delegates to fmt_money."""

    def test_formats_amount(self):
        out = ap.format_currency_for_display(12.5, currency="EUR")
        self.assertIn("12.50", out)


class TestGetPaymentMethods(VereningingenTestCase):
    """get_payment_methods() returns enabled modes with descriptions."""

    def test_returns_enabled_modes(self):
        from verenigingen.services.member.approval.application_helpers import ensure_payment_modes_exist

        ensure_payment_modes_exist()
        result = ap.get_payment_methods()
        self.assertTrue(result["success"])
        names = {m["name"] for m in result["payment_methods"]}
        self.assertIn("Bank Transfer", names)
        # Known modes get a description string.
        bt = next(m for m in result["payment_methods"] if m["name"] == "Bank Transfer")
        self.assertTrue(bt["description"])


class TestGetMembershipItem(VereningingenTestCase):
    """get_membership_item() throws when no item is configured."""

    def test_throws_without_item_method(self):
        # A plain object lacking get_or_create_membership_item triggers the throw.
        # NOTE: frappe._dict cannot be used — its __getattr__ returns None for any
        # missing key, so hasattr(...) is True and the code would call None().
        class _FakeType:
            membership_type_name = "Fake Type"

        with self.assertRaises(frappe.ValidationError):
            ap.get_membership_item(_FakeType())


class TestCreateCustomerForMember(VereningingenTestCase):
    """create_customer_for_member() real Customer + Contact + dedup."""

    def _ensure_staff_role(self):
        """Customer/Contact create perms are gated to Verenigingen Staff; the
        test runs as Administrator (System Manager) which has create perms, but
        the no-bypass insert path still requires permission. Administrator has
        full perms, so no role juggling is needed here."""
        return

    def test_creates_customer_and_contact(self):
        member = self.create_test_member(
            email=f"cust-{frappe.generate_hash(length=6)}@example.com", contact_number="+31611111111"
        )
        member.reload()

        with self.assertNoErrorLog():
            customer = ap.create_customer_for_member(member)
        self.track_doc("Customer", customer.name)

        self.assertEqual(customer.member, member.name)
        self.assertTrue(customer.customer_primary_contact)
        # The denormalised email field is synced from the primary Contact.
        self.assertEqual(customer.email_id, member.email)

    def test_existing_customer_returned_not_duplicated(self):
        member = self.create_test_member(email=f"cust2-{frappe.generate_hash(length=6)}@example.com")
        member.reload()

        first = ap.create_customer_for_member(member)
        self.track_doc("Customer", first.name)
        # Link the customer onto the member as the real flow does.
        member.db_set("customer", first.name)

        second = ap.create_customer_for_member(member)
        self.assertEqual(first.name, second.name)
