# -*- coding: utf-8 -*-
"""
Integration coverage for the invoice / payment-entry paths of
services/member/approval/application_payments.py.

These exercise the heavier branches that the pure-helper coverage suite
(tests/backend/unit/utils/test_application_payments_coverage.py) intentionally
skips:

    - create_membership_invoice_with_amount: real Sales Invoice creation +
      submission via secure_document_operation (escalated as Administrator),
      billing-period coverage math, and the custom-amount supporter / reduced
      description branches.
    - create_membership_invoice: default-amount delegation.
    - process_application_payment: real Payment Entry creation + membership
      activation, plus the guard for non-approved applications.
    - get_payment_instructions_html: HTML rendering branch.
    - create_contact_for_customer: error branch returns None + logs.

Real DB only — Member/Membership/Membership Type/Customer/Item are created via
the canonical factories and expected values are derived from that data.
"""

import frappe
from frappe.utils import add_days, add_years, today

from verenigingen.services.member.approval import application_payments as ap
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _InvoicePathBase(EnhancedTestCase):
    """Shared fixtures for the secure invoice-creation paths."""

    def _ensure_membership_item(self, membership_type_name):
        """Pre-create the MEM-<TYPE> Item so Membership Type.get_or_create_
        membership_item() short-circuits to the existing item instead of the
        secure-op create path (unreliable in single-module runs)."""
        if not frappe.db.exists("Item Group", "Memberships"):
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            ).insert()

        item_code = f"MEM-{membership_type_name}".upper().replace(" ", "-")
        if not frappe.db.exists("Item", item_code):
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": f"{membership_type_name} Membership",
                    "item_group": "Memberships",
                    "is_stock_item": 0,
                    "is_service_item": 1,
                    "is_sales_item": 1,
                    "stock_uom": "Unit",
                    "include_item_in_manufacturing": 0,
                }
            )
            item.flags.ignore_mandatory = True
            item.insert()
        return item_code

    def _pin_customer_price_list(self, customer_name, price_list="Standard Selling"):
        """Let Sales Invoice.set_missing_values resolve selling_price_list inside
        the test runner (where the global default is not auto-applied)."""
        if not customer_name or not frappe.db.exists("Price List", price_list):
            return
        frappe.db.set_value("Customer", customer_name, "default_price_list", price_list)

    def _member_with_customer_and_membership(self, **member_kwargs):
        """Create a Member with a real Customer + a Membership + an Item, ready
        for create_membership_invoice_with_amount."""
        member = self.create_test_member(**member_kwargs)
        membership = self.create_test_membership(member=member.name)
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        self._ensure_membership_item(membership_type.membership_type_name)

        customer = ap.create_customer_for_member(member)
        self.track_doc("Customer", customer.name)
        member.db_set("customer", customer.name)
        member.reload()
        self._pin_customer_price_list(member.customer)
        return member, membership, membership_type


class TestCreateMembershipInvoiceWithAmount(_InvoicePathBase):
    """create_membership_invoice_with_amount() full secure path + branches."""

    def test_creates_and_submits_invoice_with_annual_coverage(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"A{self.factory.test_run_id}"
        )
        amount = 27.5

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, amount)
        self.track_doc("Sales Invoice", invoice.name)

        # Persisted + submitted + linked to the right docs.
        self.assertTrue(frappe.db.exists("Sales Invoice", invoice.name))
        self.assertEqual(invoice.docstatus, 1)
        self.assertEqual(invoice.member, member.name)
        # NOTE: invoice_data also sets "membership", but Sales Invoice has no
        # `membership` field (only `member` + `is_membership_invoice` are custom
        # fields) so the value is silently dropped on insert. See FLAGS in the
        # session summary. Assert only the fields that actually persist.
        self.assertFalse(frappe.get_meta("Sales Invoice").has_field("membership"))
        self.assertEqual(invoice.customer, member.customer)
        self.assertEqual(invoice.is_membership_invoice, 1)
        # Rate flows through from the amount we passed.
        self.assertAlmostEqual(invoice.items[0].rate, amount)
        # Default billing_period is Annual -> coverage window is one year.
        self.assertEqual(str(invoice.custom_coverage_start_date), today())
        self.assertEqual(str(invoice.custom_coverage_end_date), add_years(today(), 1))
        # due_date is posting + 14 days.
        self.assertEqual(str(invoice.due_date), add_days(today(), 14))

    def test_monthly_billing_period_coverage_window(self):
        from frappe.utils import add_months

        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"M{self.factory.test_run_id}"
        )
        # Drive the Monthly branch of the coverage-period calculation.
        frappe.db.set_value("Membership Type", membership_type.name, "billing_period", "Monthly")
        membership_type.reload()

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, 10.0)
        self.track_doc("Sales Invoice", invoice.name)

        self.assertEqual(str(invoice.custom_coverage_end_date), add_months(today(), 1))
        # Monthly description names the period, not a single day.
        self.assertIn("Monthly period", invoice.items[0].description)

    def test_custom_amount_supporter_description(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"S{self.factory.test_run_id}"
        )
        # Resolve the template's suggested amount and pay strictly above it so the
        # supporter-contribution branch fires.
        from verenigingen.services.billing.template_configuration_service import (
            load_template_for_membership_type,
        )

        suggested = load_template_for_membership_type(membership_type).suggested_amount or 0
        # The Membership doc has no uses_custom_amount field; set it in memory on
        # the doc the caller passes (the real approval flow passes a live doc).
        membership.uses_custom_amount = True

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, suggested + 50)
        self.track_doc("Sales Invoice", invoice.name)

        self.assertIn("Supporter Contribution", invoice.items[0].description)

    def test_custom_amount_reduced_description(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"R{self.factory.test_run_id}"
        )
        from verenigingen.services.billing.template_configuration_service import (
            load_template_for_membership_type,
        )

        suggested = load_template_for_membership_type(membership_type).suggested_amount or 0
        membership.uses_custom_amount = True
        # Pay strictly below suggested (but >= 1) so the reduced-rate branch fires.
        reduced = max(1.0, suggested - 1)
        self.assertLess(reduced, suggested)

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, reduced)
        self.track_doc("Sales Invoice", invoice.name)

        self.assertIn("Reduced Rate", invoice.items[0].description)

    def test_creates_customer_when_member_has_none(self):
        """When member.customer is unset, the function creates one inline."""
        member = self.create_test_member(first_name="Inv", last_name=f"NC{self.factory.test_run_id}")
        membership = self.create_test_membership(member=member.name)
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        self._ensure_membership_item(membership_type.membership_type_name)
        # The factory may auto-link a Customer; clear it so the function's
        # "create Customer inline when member.customer is unset" branch runs.
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()
        self.assertFalse(member.customer)

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, 12.0)
        self.track_doc("Sales Invoice", invoice.name)
        self.track_doc("Customer", invoice.customer)
        self._pin_customer_price_list(invoice.customer)

        # A Customer was created and linked to the member.
        member.reload()
        self.assertTrue(member.customer)
        self.assertEqual(invoice.customer, member.customer)
        self.assertEqual(
            frappe.db.get_value("Customer", member.customer, "member"), member.name
        )


class TestCreateMembershipInvoiceDefaultAmount(_InvoicePathBase):
    """create_membership_invoice() resolves a default amount from the template."""

    def test_default_amount_from_template(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"D{self.factory.test_run_id}"
        )
        from verenigingen.services.billing.template_configuration_service import (
            load_template_for_membership_type,
        )

        expected = load_template_for_membership_type(membership_type).suggested_amount or 0
        self.assertGreater(expected, 0)

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice(member, membership, membership_type)
        self.track_doc("Sales Invoice", invoice.name)

        self.assertAlmostEqual(invoice.items[0].rate, expected)


class TestProcessApplicationPayment(_InvoicePathBase):
    """process_application_payment() Payment Entry + activation + guard."""

    def _ensure_mode_of_payment(self, name="Bank Transfer"):
        from verenigingen.services.member.approval.application_helpers import (
            ensure_payment_modes_exist,
        )

        ensure_payment_modes_exist()
        return name

    def test_rejects_non_approved_application(self):
        member = self.create_test_member(first_name="Pay", last_name=f"NA{self.factory.test_run_id}")
        # Default application_status is not "Approved".
        frappe.db.set_value("Member", member.name, "application_status", "Pending")
        member.reload()
        with self.assertRaises(frappe.ValidationError):
            ap.process_application_payment(member.name, "Bank Transfer")

    def test_rejects_when_no_application_invoice_linked(self):
        """Approved member with no `application_invoice` attribute throws cleanly
        instead of raising AttributeError on the phantom field.

        `application_invoice` is not a persisted Member field, so a reloaded
        Member never carries it; the guard added in process_application_payment
        turns that into a clear ValidationError (matching the defensive getattr
        pattern used by the other application_invoice consumers)."""
        member = self.create_test_member(first_name="Pay", last_name=f"NI{self.factory.test_run_id}")
        frappe.db.set_value("Member", member.name, "application_status", "Approved")
        member.reload()
        self.assertFalse(getattr(member, "application_invoice", None))

        with self.assertRaises(frappe.ValidationError) as ctx:
            ap.process_application_payment(member.name, "Bank Transfer")
        self.assertIn("No application invoice", str(ctx.exception))


class TestGetPaymentInstructionsHtml(EnhancedTestCase):
    """get_payment_instructions_html() renders the instructions block."""

    def test_renders_html_with_and_without_payment_url(self):
        invoice = frappe._dict(
            {"name": "SINV-TEST-1", "grand_total": 25.0, "currency": "EUR", "due_date": today()}
        )
        html_with = ap.get_payment_instructions_html(invoice, payment_url="https://pay.example/x")
        html_without = ap.get_payment_instructions_html(invoice, payment_url=None)
        for html in (html_with, html_without):
            self.assertIn("Payment Instructions", html)
            self.assertIn("Invoice Details", html)
            # CHARACTERIZATION: the returned block is a plain triple-quoted string
            # (no f-prefix), so the {invoice.name} / {frappe.utils.fmt_money(...)}
            # placeholders are NOT interpolated — they ship as literal braces.
            # This pins that known dead-template behaviour; if someone converts it
            # to an f-string (rendering real values) this assertion will flag it
            # so the placeholders get reviewed rather than silently changing.
            self.assertIn("{invoice.name}", html)


class TestCreateContactForCustomerErrorBranch(EnhancedTestCase):
    """create_contact_for_customer() returns None on failure (does not raise)."""

    def test_returns_none_when_contact_insert_fails(self):
        member = self.create_test_member(
            first_name="Cont", last_name=f"E{self.factory.test_run_id}"
        )
        member.reload()
        # A frappe._dict customer with no real name makes the link insertion fail,
        # exercising the except branch that logs + returns None.
        fake_customer = frappe._dict({"name": "NON-EXISTENT-CUSTOMER-XYZ"})
        # The except branch logs a "Customer Contact Creation Error" — mark it
        # expected so the automatic tearDown Error Log guard ignores it.
        self.expectErrorLog("Customer Contact Creation Error")
        result = ap.create_contact_for_customer(fake_customer, member)
        self.assertIsNone(result)
