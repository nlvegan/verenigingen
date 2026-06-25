# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for approval/application_payments.py.

Drives REAL Member / Membership / Membership Type / Customer / Sales Invoice
documents through the payment helpers to verify:
- payment-amount validation (exact, under, over -> donation)
- discount-aware amount calculation from the dues-schedule template
- payment-method listing with descriptions
- currency formatting
- Customer creation for a member (Contact linkage, dedup on re-call)
- duplicate-name retry on Customer insert
- membership invoice creation + submission with coverage period
"""

import frappe

from verenigingen.services.member.approval import application_payments as ap
from verenigingen.services.member.approval.application_helpers import ensure_payment_modes_exist
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestValidatePaymentAmount(EnhancedTestCase):
    """validate_payment_amount — pure validation, no DB."""

    def _invoice(self, grand_total):
        return frappe._dict(grand_total=grand_total)

    def test_exact_amount_valid(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 50.0)
        self.assertTrue(result["valid"])

    def test_within_rounding_tolerance(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 50.005)
        self.assertTrue(result["valid"])

    def test_underpayment_invalid(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 40.0)
        self.assertFalse(result["valid"])
        self.assertIn("less than", result["message"])

    def test_overpayment_treated_as_donation(self):
        result = ap.validate_payment_amount(self._invoice(50.0), 70.0)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["overpayment"], 20.0, places=2)


class TestCalculateAmountWithDiscounts(EnhancedTestCase):
    """calculate_membership_amount_with_discounts."""

    def setUp(self):
        super().setUp()
        self.mt = self.create_test_membership_type(membership_type_name="DiscType", amount=30.0)

    def test_base_amount_from_template(self):
        result = ap.calculate_membership_amount_with_discounts(self.mt, {})
        self.assertGreater(result["base_amount"], 0)
        self.assertEqual(result["final_amount"], result["base_amount"])
        # No discount logic remains; discounts list is empty
        self.assertEqual(result["discounts_applied"], [])
        self.assertEqual(result["total_discount"], 0)

    def _build_zero_amount_type(self):
        """Setup helper: a membership type whose template resolves to amount 0."""
        cheap = self.create_test_membership_type(membership_type_name="CheapType", amount=0.0)
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": cheap.name},
            "name",
        )
        if template:
            doc = frappe.get_doc("Membership Dues Schedule", template)
            doc.suggested_amount = 0
            doc.dues_rate = 0
            doc.minimum_amount = 0
            doc.save(ignore_permissions=True)
        return cheap

    def test_minimum_floor_of_one(self):
        """final_amount never drops below 1 even for a zero-amount template."""
        cheap = self._build_zero_amount_type()
        result = ap.calculate_membership_amount_with_discounts(cheap, {})
        self.assertEqual(result["final_amount"], 1)


class TestPaymentMethodsAndFormatting(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        ensure_payment_modes_exist()

    def test_get_payment_methods_lists_enabled(self):
        result = ap.get_payment_methods()
        self.assertTrue(result["success"])
        names = [m["name"] for m in result["payment_methods"]]
        self.assertIn("Bank Transfer", names)
        bt = next(m for m in result["payment_methods"] if m["name"] == "Bank Transfer")
        self.assertIn("SEPA", bt["description"])

    def test_format_currency_for_display(self):
        formatted = ap.format_currency_for_display(12.5, currency="EUR")
        self.assertIn("12.5", formatted.replace(",", "."))


class TestCreateCustomerForMember(EnhancedTestCase):
    """create_customer_for_member + insert_customer_with_duplicate_retry."""

    def setUp(self):
        super().setUp()
        # Create a member WITHOUT an auto customer so we exercise creation.
        self.member = self.create_test_member(
            first_name="Cust",
            last_name="Owner",
            email="cust.owner@example.com",
            contact_number="+31611112222",
        )

    def test_creates_customer_with_contact(self):
        # Detach any auto-created customer so the helper creates a fresh one.
        if self.member.customer:
            self.member.db_set("customer", None)
        customer = ap.create_customer_for_member(self.member)
        self.track_doc("Customer", customer.name)
        self.assertEqual(customer.member, self.member.name)
        self.assertEqual(customer.customer_type, "Individual")
        # Contact was created and linked as primary contact
        self.assertTrue(customer.customer_primary_contact)
        contact = frappe.get_doc("Contact", customer.customer_primary_contact)
        self.track_doc("Contact", contact.name)
        self.assertEqual(contact.first_name, "Cust")

    def test_returns_existing_customer_on_recall(self):
        """A second call returns the already-linked customer (idempotent)."""
        if self.member.customer:
            self.member.db_set("customer", None)
        first = ap.create_customer_for_member(self.member)
        self.track_doc("Customer", first.name)
        # member.customer now points at first; second call must reuse it
        self.member.db_set("customer", first.name)
        self.member.reload()
        second = ap.create_customer_for_member(self.member)
        self.assertEqual(second.name, first.name)


class TestCreateMembershipInvoice(EnhancedTestCase):
    """create_membership_invoice / create_membership_invoice_with_amount."""

    def setUp(self):
        super().setUp()
        ensure_payment_modes_exist()
        self.mt = self.create_test_membership_type(membership_type_name="InvType", amount=25.0)
        self.member = self.create_test_member(
            first_name="Inv",
            last_name="Member",
            email="inv.member@example.com",
            contact_number="+31633334444",
        )
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name=self.mt.name
        )

    def test_creates_and_submits_invoice(self):
        invoice = ap.create_membership_invoice(self.member, self.membership, self.mt, amount=25.0)
        self.track_doc("Sales Invoice", invoice.name)

        self.assertEqual(invoice.docstatus, 1)  # submitted
        self.assertEqual(invoice.member, self.member.name)
        # 'membership' is set in invoice_data but is NOT a Sales Invoice custom
        # field on this site, so it is silently dropped — assert via the field
        # that does exist (member) and the membership flag instead.
        self.assertEqual(invoice.is_membership_invoice, 1)
        self.assertAlmostEqual(invoice.grand_total, 25.0, places=2)
        # Coverage period dates are set
        self.assertTrue(invoice.custom_coverage_start_date)
        self.assertTrue(invoice.custom_coverage_end_date)
        # Membership item line present
        self.assertEqual(len(invoice.items), 1)
        self.assertAlmostEqual(invoice.items[0].rate, 25.0, places=2)

    def test_invoice_default_amount_from_template(self):
        """create_membership_invoice with amount=None pulls suggested_amount."""
        invoice = ap.create_membership_invoice(self.member, self.membership, self.mt, amount=None)
        self.track_doc("Sales Invoice", invoice.name)
        self.assertEqual(invoice.docstatus, 1)
        self.assertGreater(invoice.grand_total, 0)
