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
    - create_contact_for_customer: error branch returns None + logs.

Real DB only — Member/Membership/Membership Type/Customer/Item are created via
the canonical factories and expected values are derived from that data.
"""

import frappe
from frappe.utils import add_days, add_months, add_years, getdate, today

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
        # Sales Invoice now has a `membership` Link(Membership) custom field
        # (added so the dues generator's / this path's assignment persists).
        # This path links the invoice to the Membership record.
        self.assertTrue(frappe.get_meta("Sales Invoice").has_field("membership"))
        self.assertEqual(invoice.membership, membership.name)
        self.assertEqual(invoice.customer, member.customer)
        self.assertEqual(invoice.is_membership_invoice, 1)
        # Rate flows through from the amount we passed.
        self.assertAlmostEqual(invoice.items[0].rate, amount)
        # Default billing_period is Annual. Coverage is INCLUSIVE of both ends, so
        # the period must stop the day BEFORE the anniversary - the anniversary
        # itself is the first day of the NEXT period (#206).
        self.assertEqual(str(invoice.custom_coverage_start_date), today())
        self.assertEqual(str(invoice.custom_coverage_end_date), add_days(add_years(today(), 1), -1))
        # The anniversary must not be inside this period at all.
        self.assertNotEqual(str(invoice.custom_coverage_end_date), add_years(today(), 1))
        # One inclusive year: 365 days, or 366 when the window contains a Feb 29.
        inclusive_days = (
            getdate(invoice.custom_coverage_end_date) - getdate(invoice.custom_coverage_start_date)
        ).days + 1
        self.assertIn(inclusive_days, (365, 366))
        # due_date is posting + 14 days.
        self.assertEqual(str(invoice.due_date), add_days(today(), 14))

    def test_monthly_billing_period_coverage_window(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"M{self.factory.test_run_id}"
        )
        # Drive the Monthly branch of the coverage-period calculation.
        frappe.db.set_value("Membership Type", membership_type.name, "billing_period", "Monthly")
        membership_type.reload()

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, 10.0)
        self.track_doc("Sales Invoice", invoice.name)

        # Inclusive month: ends the day before the same day-of-month next month.
        self.assertEqual(str(invoice.custom_coverage_end_date), add_days(add_months(today(), 1), -1))
        # Monthly description names the period, not a single day.
        self.assertIn("Monthly period", invoice.items[0].description)

    def test_daily_billing_period_covers_a_single_day(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"DY{self.factory.test_run_id}"
        )
        frappe.db.set_value("Membership Type", membership_type.name, "billing_period", "Daily")
        membership_type.reload()

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, 1.0)
        self.track_doc("Sales Invoice", invoice.name)

        # A Daily period is ONE day: an inclusive period whose end is its start.
        self.assertEqual(str(invoice.custom_coverage_start_date), today())
        self.assertEqual(str(invoice.custom_coverage_end_date), today())

    def test_quarterly_biannual_and_custom_periods_stop_before_the_next_one(self):
        """Every non-Annual branch is the same defect as #206's Annual branch."""
        cases = [
            # (billing_period, billing_period_in_months, expected inclusive end)
            ("Quarterly", None, add_days(add_months(today(), 3), -1)),
            ("Biannual", None, add_days(add_months(today(), 6), -1)),
            ("Custom", 4, add_days(add_months(today(), 4), -1)),
            # Lifetime has no period of its own; this path has always billed a
            # first Annual period for it, and that must stay Annual - not the
            # Monthly that an unmapped frequency would fall back to.
            ("Lifetime", None, add_days(add_years(today(), 1), -1)),
        ]
        for idx, (billing_period, months, expected_end) in enumerate(cases):
            with self.subTest(billing_period=billing_period):
                member, membership, membership_type = self._member_with_customer_and_membership(
                    first_name="Inv", last_name=f"P{idx}{self.factory.test_run_id}"
                )
                frappe.db.set_value("Membership Type", membership_type.name, "billing_period", billing_period)
                if months is not None:
                    frappe.db.set_value(
                        "Membership Type", membership_type.name, "billing_period_in_months", months
                    )
                membership_type.reload()

                with self.assertNoErrorLog():
                    invoice = ap.create_membership_invoice_with_amount(member, membership, 5.0)
                self.track_doc("Sales Invoice", invoice.name)

                self.assertEqual(str(invoice.custom_coverage_start_date), today())
                self.assertEqual(str(invoice.custom_coverage_end_date), expected_end)

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
        self.assertEqual(frappe.db.get_value("Customer", member.customer, "member"), member.name)


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


class TestCreateContactForCustomerErrorBranch(EnhancedTestCase):
    """create_contact_for_customer() returns None on failure (does not raise)."""

    def test_returns_none_when_contact_insert_fails(self):
        member = self.create_test_member(first_name="Cont", last_name=f"E{self.factory.test_run_id}")
        member.reload()
        # A frappe._dict customer with no real name makes the link insertion fail,
        # exercising the except branch that logs + returns None.
        fake_customer = frappe._dict({"name": "NON-EXISTENT-CUSTOMER-XYZ"})
        # The except branch logs a "Customer Contact Creation Error" — mark it
        # expected so the automatic tearDown Error Log guard ignores it.
        self.expectErrorLog("Customer Contact Creation Error")
        result = ap.create_contact_for_customer(fake_customer, member)
        self.assertIsNone(result)


class TestApprovalInvoiceSeedsTheCoverageSequence(_InvoicePathBase):
    """The approval invoice is the FIRST period of the coverage sequence.

    Every later period is rolled off the previous one's end date
    (CoverageCalculator's sequential branch starts at previous_end + 1), so a
    first period that ends one day late shifts the whole sequence off the
    membership anniversary for good (#206).
    """

    def test_next_period_starts_on_the_anniversary_of_the_first(self):
        member, membership, membership_type = self._member_with_customer_and_membership(
            first_name="Inv", last_name=f"SQ{self.factory.test_run_id}"
        )
        # Default billing_period is Annual; make it explicit so the schedule and
        # the membership type cannot disagree.
        frappe.db.set_value("Membership Type", membership_type.name, "billing_period", "Annual")
        membership_type.reload()

        with self.assertNoErrorLog():
            invoice = ap.create_membership_invoice_with_amount(member, membership, 15.0)
        self.track_doc("Sales Invoice", invoice.name)

        schedule = self.create_test_dues_schedule(
            member=member.name,
            membership_type=membership.membership_type,
            amount=15.0,
            frequency="annual",
        )

        from verenigingen.services.billing.coverage_calculator import CoverageCalculator

        member.reload()
        result = CoverageCalculator(schedule).calculate_next_coverage_period(member)
        self.assertTrue(result.success, getattr(result, "message", None))
        period = result.data

        first_start = getdate(invoice.custom_coverage_start_date)
        first_end = getdate(invoice.custom_coverage_end_date)

        # The sequence continues with no gap and no overlap.
        self.assertEqual(period.start_date, add_days(first_end, 1))
        # ...and it is still anniversary-aligned: period two starts exactly one
        # year after period one did. A 366-day first period pushes this to
        # anniversary + 1 and every later period inherits the drift.
        self.assertEqual(period.start_date, getdate(add_years(str(first_start), 1)))


class TestCoverageEndForBillingPeriod(EnhancedTestCase):
    """coverage_end_for_billing_period() - the arithmetic, on fixed dates.

    create_membership_invoice_with_amount() always starts the period at today(),
    so the leap-year windows below are unreachable through the invoice path on
    all but two days of the year. They are exercised here on explicit dates.
    """

    def test_annual_periods_across_leap_boundaries(self):
        cases = [
            # A period that CONTAINS a leap day: 366 inclusive days.
            ("2023-03-01", "2024-02-29"),
            # Calendar year in, calendar year out.
            ("2024-01-01", "2024-12-31"),
            # The veg11 rows in #206: 2026-06-25 was being covered through
            # 2027-06-25, the day the NEXT period starts.
            ("2026-06-25", "2027-06-24"),
            # A period that BEGINS on a leap day. add_months clamps the
            # anniversary to 2025-02-28, so the period ends the day before that
            # - one day short of a year, which is what every other path in the
            # pipeline also produces for this start.
            ("2024-02-29", "2025-02-27"),
        ]
        for start, expected_end in cases:
            with self.subTest(start=start):
                end = ap.coverage_end_for_billing_period("Annual", start)
                self.assertEqual(end, getdate(expected_end))
                # The invariant these dates encode: the period stops the day
                # before the next one starts.
                self.assertEqual(add_days(end, 1), add_months(getdate(start), 12))

    def test_shorter_periods_end_the_day_before_the_next_one_starts(self):
        cases = [
            # (billing_period, start, custom months, expected end, months in period)
            ("Daily", "2024-02-29", None, "2024-02-29", None),
            ("Monthly", "2024-01-31", None, "2024-02-28", 1),
            ("Monthly", "2023-01-31", None, "2023-02-27", 1),
            ("Quarterly", "2024-11-30", None, "2025-02-27", 3),
            ("Biannual", "2024-08-31", None, "2025-02-27", 6),
            ("Custom", "2024-12-15", 3, "2025-03-14", 3),
        ]
        for billing_period, start, months, expected_end, period_months in cases:
            with self.subTest(billing_period=billing_period, start=start):
                end = ap.coverage_end_for_billing_period(billing_period, start, months)
                self.assertEqual(end, getdate(expected_end))
                if period_months:
                    self.assertEqual(add_days(end, 1), add_months(getdate(start), period_months))
                else:
                    # A Daily period is a single inclusive day.
                    self.assertEqual(end, getdate(start))

    def test_unknown_and_lifetime_periods_stay_annual(self):
        """This path has always defaulted to a one-year first period."""
        for billing_period in ("Lifetime", "", None, "Fortnightly"):
            with self.subTest(billing_period=billing_period):
                self.assertEqual(
                    ap.coverage_end_for_billing_period(billing_period, "2025-01-01"),
                    getdate("2025-12-31"),
                )

    def test_custom_without_a_month_count_is_twelve_months(self):
        self.assertEqual(
            ap.coverage_end_for_billing_period("Custom", "2025-01-01", None),
            getdate("2025-12-31"),
        )
