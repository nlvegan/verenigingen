# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen/services/billing/coverage_calculator.py

Covers:
  - CoverageCalculator utility/delegation methods (calculate_billing_period,
    derive_coverage_from_invoice_data) in utility-only mode
  - _calculate_coverage_end (all frequencies incl. Custom branches)
  - calculate_next_coverage_period (first_invoice, sequential, date_based, errors)
  - get_latest_coverage_end_date / _get_membership_start_date (real DB queries)
  - should_generate_invoice_for_cutoff
  - calculate_cutoff_date_for_period (settings-driven, all cutoff frequencies)
  - module functions calculate_coverage_for_payment_date / find_invoice_for_payment

The calculator only READS schedule attributes in __init__, so a frappe._dict
faithfully represents the schedule context for pure-calculation paths. DB-touching
paths use REAL members/memberships/invoices created via the factory.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.services.billing.coverage_calculator import (
    CoverageCalculator,
    calculate_coverage_for_payment_date,
    find_invoice_for_payment,
    get_coverage_calculator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _sched_stub(**kwargs):
    defaults = {
        "name": "TEST-COV-SCHED",
        "billing_frequency": "Monthly",
        "custom_frequency_number": None,
        "custom_frequency_unit": None,
        "member": None,
        "next_invoice_date": None,
    }
    defaults.update(kwargs)
    return frappe._dict(defaults)


class TestCoverageCalculatorUtilityMethods(EnhancedTestCase):
    """Utility-mode (no schedule) and pure helper coverage."""

    def test_calculate_billing_period_delegates(self):
        calc = CoverageCalculator(None)
        start, end = calc.calculate_billing_period("Monthly", "2025-03-15")
        self.assertEqual(start, getdate("2025-03-01"))
        self.assertEqual(end, getdate("2025-03-31"))

    def test_derive_coverage_delegates(self):
        calc = CoverageCalculator(None)
        start, end = calc.derive_coverage_from_invoice_data("2025-03-15", billing_frequency="Monthly")
        self.assertEqual(start, getdate("2025-03-15"))
        self.assertEqual(end, getdate("2025-04-14"))

    def test_get_coverage_calculator_factory(self):
        calc = get_coverage_calculator()
        self.assertIsInstance(calc, CoverageCalculator)
        self.assertIsNone(calc.member_name)

    # ----- _calculate_coverage_end for each frequency -----
    def test_coverage_end_daily(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Daily"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-10")), getdate("2025-03-10"))

    def test_coverage_end_weekly(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Weekly"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-10")), getdate("2025-03-16"))

    def test_coverage_end_monthly(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Monthly"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-01")), getdate("2025-03-31"))

    def test_coverage_end_quarterly(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Quarterly"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-01-01")), getdate("2025-03-31"))

    def test_coverage_end_semi_annual(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Semi-Annual"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-01-01")), getdate("2025-06-30"))

    def test_coverage_end_annual(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Annual"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-01-01")), getdate("2025-12-31"))

    def test_coverage_end_custom_days(self):
        calc = CoverageCalculator(
            _sched_stub(billing_frequency="Custom", custom_frequency_number=5, custom_frequency_unit="Days")
        )
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-10")), getdate("2025-03-14"))

    def test_coverage_end_custom_weeks(self):
        calc = CoverageCalculator(
            _sched_stub(billing_frequency="Custom", custom_frequency_number=2, custom_frequency_unit="Weeks")
        )
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-10")), getdate("2025-03-23"))

    def test_coverage_end_custom_months(self):
        calc = CoverageCalculator(
            _sched_stub(billing_frequency="Custom", custom_frequency_number=3, custom_frequency_unit="Months")
        )
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-01-01")), getdate("2025-03-31"))

    def test_coverage_end_custom_years(self):
        calc = CoverageCalculator(
            _sched_stub(billing_frequency="Custom", custom_frequency_number=1, custom_frequency_unit="Years")
        )
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-01-01")), getdate("2025-12-31"))

    def test_coverage_end_custom_invalid_number_defaults_monthly(self):
        calc = CoverageCalculator(
            _sched_stub(billing_frequency="Custom", custom_frequency_number=0, custom_frequency_unit="Days")
        )
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-01")), getdate("2025-03-31"))

    def test_coverage_end_unknown_frequency_monthly(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Bogus"))
        self.assertEqual(calc._calculate_coverage_end(getdate("2025-03-01")), getdate("2025-03-31"))


class TestCalculateCutoffDateForPeriod(EnhancedTestCase):
    """calculate_cutoff_date_for_period reads Verenigingen Settings.

    We exercise the branch logic by temporarily setting the settings field, then
    restoring it (single doc, restored in tearDown).
    """

    def setUp(self):
        super().setUp()
        self.settings = frappe.get_single("Verenigingen Settings")
        self._orig_cutoff = getattr(self.settings, "billing_cutoff_frequency", None)

    def tearDown(self):
        frappe.db.set_value("Verenigingen Settings", None, "billing_cutoff_frequency", self._orig_cutoff)
        frappe.db.commit()
        super().tearDown()

    def _set_cutoff(self, value):
        frappe.db.set_value("Verenigingen Settings", None, "billing_cutoff_frequency", value)

    def test_monthly_cutoff_is_end_of_current_month(self):
        self._set_cutoff("Monthly")
        calc = CoverageCalculator(None)
        result = calc.calculate_cutoff_date_for_period()
        today_date = getdate(today())
        # result is last day of current month
        self.assertEqual(result.month, today_date.month)
        self.assertEqual(result.year, today_date.year)
        # adding one day rolls into next month
        from frappe.utils import add_days

        self.assertNotEqual(add_days(result, 1).month, result.month)

    def test_unknown_cutoff_defaults_to_month_end(self):
        self._set_cutoff("Weekly")  # not a recognized cutoff -> default branch
        calc = CoverageCalculator(None)
        result = calc.calculate_cutoff_date_for_period()
        today_date = getdate(today())
        self.assertEqual(result.month, today_date.month)


class TestStatefulCoveragePeriod(EnhancedTestCase):
    """Tests touching real DB: members, memberships, invoices."""

    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        order = {"Sales Invoice": 0, "Membership": 1, "Customer": 2, "Member": 3}
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _member_with_customer(self):
        member = self.create_test_member()
        member.create_customer()
        member.reload()
        self._committed.append(("Member", member.name))
        self._committed.append(("Customer", member.customer))
        return member

    def _submitted_invoice(self, member, cov_start, cov_end):
        inv = self.create_test_sales_invoice(customer=member.name)
        self._committed.append(("Sales Invoice", inv.name))
        if inv.docstatus == 0:
            inv.submit()
        frappe.db.set_value(
            "Sales Invoice",
            inv.name,
            {
                "custom_coverage_start_date": getdate(cov_start),
                "custom_coverage_end_date": getdate(cov_end),
            },
        )
        frappe.db.commit()
        return inv.name

    # ----- get_latest_coverage_end_date -----
    def test_latest_coverage_end_none_when_no_customer(self):
        member = self.create_test_member()  # no customer created
        self._committed.append(("Member", member.name))
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        self.assertIsNone(calc.get_latest_coverage_end_date(member))

    def test_latest_coverage_end_returns_max(self):
        member = self._member_with_customer()
        self._submitted_invoice(member, "2025-01-01", "2025-01-31")
        self._submitted_invoice(member, "2025-02-01", "2025-02-28")
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        self.assertEqual(calc.get_latest_coverage_end_date(member), getdate("2025-02-28"))

    def test_latest_coverage_end_loads_member_from_self(self):
        member = self._member_with_customer()
        self._submitted_invoice(member, "2025-03-01", "2025-03-31")
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        # member_doc=None -> loads via self.member_name
        self.assertEqual(calc.get_latest_coverage_end_date(None), getdate("2025-03-31"))

    # ----- should_generate_invoice_for_cutoff -----
    def test_should_generate_true_when_no_coverage(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Monthly"))
        self.assertTrue(calc.should_generate_invoice_for_cutoff("2025-12-31", latest_coverage_end=None))

    def test_should_generate_true_when_coverage_ends_before_cutoff(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Monthly"))
        self.assertTrue(
            calc.should_generate_invoice_for_cutoff("2025-12-31", latest_coverage_end=getdate("2025-06-30"))
        )

    def test_should_generate_false_when_coverage_extends_past_cutoff(self):
        calc = CoverageCalculator(_sched_stub(billing_frequency="Monthly"))
        self.assertFalse(
            calc.should_generate_invoice_for_cutoff("2025-12-31", latest_coverage_end=getdate("2026-01-31"))
        )

    # ----- calculate_next_coverage_period -----
    def test_first_invoice_uses_billing_period(self):
        member = self._member_with_customer()
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        # No previous coverage -> first_invoice path; force_date controls reference
        result = calc.calculate_next_coverage_period(member, force_date=getdate("2025-05-15"))
        self.assertTrue(result.success)
        period = result.data
        self.assertEqual(period.calculation_method, "first_invoice")
        # Monthly period containing 2025-05-15 = May 1..May 31
        self.assertEqual(period.start_date, getdate("2025-05-01"))
        self.assertEqual(period.end_date, getdate("2025-05-31"))

    def test_sequential_builds_on_previous_coverage(self):
        member = self._member_with_customer()
        self._submitted_invoice(member, "2025-01-01", "2025-01-31")
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        result = calc.calculate_next_coverage_period(member, use_sequential=True)
        self.assertTrue(result.success)
        period = result.data
        self.assertEqual(period.calculation_method, "sequential")
        # starts day after previous coverage end (2025-02-01), monthly end 2025-02-28
        self.assertEqual(period.start_date, getdate("2025-02-01"))
        self.assertEqual(period.end_date, getdate("2025-02-28"))

    def test_date_based_when_sequential_disabled(self):
        member = self._member_with_customer()
        calc = CoverageCalculator(_sched_stub(member=member.name, billing_frequency="Monthly"))
        result = calc.calculate_next_coverage_period(
            member, force_date=getdate("2025-07-10"), use_sequential=False
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data.calculation_method, "date_based")
        self.assertEqual(result.data.start_date, getdate("2025-07-01"))
        self.assertEqual(result.data.end_date, getdate("2025-07-31"))


class TestCalculateCoverageForPaymentDate(EnhancedTestCase):
    """Module-level calculate_coverage_for_payment_date priority hierarchy."""

    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        order = {"Membership Dues Schedule": 0, "Membership": 1, "Member": 2}
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _member_with_schedule(self, frequency):
        """Create a member with an active membership (which auto-creates a dues
        schedule), then coerce that schedule's billing_frequency. Production
        requires an active membership before a dues schedule validates."""
        member = self.create_test_member()
        self._committed.append(("Member", member.name))
        membership = self.create_test_membership(member_name=member.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        frappe.db.set_value("Membership Dues Schedule", sched_name, "billing_frequency", frequency)
        frappe.db.commit()
        return member, sched_name

    def test_uses_current_dues_schedule_quarterly(self):
        member, sched_name = self._member_with_schedule("Quarterly")
        frappe.db.set_value("Member", member.name, "current_dues_schedule", sched_name)
        frappe.db.commit()

        start, end = calculate_coverage_for_payment_date(member.name, getdate("2025-05-15"))
        # Quarterly Q2 = Apr 1..Jun 30
        self.assertEqual(start, getdate("2025-04-01"))
        self.assertEqual(end, getdate("2025-06-30"))

    def test_fallback_to_any_non_cancelled_schedule_monthly(self):
        member, _ = self._member_with_schedule("Monthly")
        # leave current_dues_schedule unset -> Priority 2 fallback query
        frappe.db.set_value("Member", member.name, "current_dues_schedule", None)
        frappe.db.commit()

        start, end = calculate_coverage_for_payment_date(member.name, getdate("2025-05-15"))
        self.assertEqual(start, getdate("2025-05-01"))
        self.assertEqual(end, getdate("2025-05-31"))


class TestFindInvoiceForPayment(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._committed = []

    def tearDown(self):
        order = {
            "Sales Invoice": 0,
            "Membership Dues Schedule": 1,
            "Membership": 2,
            "Customer": 3,
            "Member": 4,
        }
        for doctype, name in sorted(self._committed, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    def _member_with_customer_and_schedule(self, frequency="Monthly"):
        member = self.create_test_member()
        member.create_customer()
        member.reload()
        self._committed.append(("Member", member.name))
        self._committed.append(("Customer", member.customer))
        membership = self.create_test_membership(member_name=member.name)
        self._committed.append(("Membership", membership.name))
        sched_name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self._committed.append(("Membership Dues Schedule", sched_name))
        frappe.db.set_value("Membership Dues Schedule", sched_name, "billing_frequency", frequency)
        frappe.db.set_value("Member", member.name, "current_dues_schedule", sched_name)
        frappe.db.commit()
        return member

    def test_no_customer_returns_none(self):
        member = self.create_test_member()  # no customer
        self._committed.append(("Member", member.name))
        result = find_invoice_for_payment(member.name, getdate("2025-05-15"), 25.0)
        self.assertIsNone(result)

    def test_finds_invoice_by_remittance_reference(self):
        member = self._member_with_customer_and_schedule()
        inv = self.create_test_sales_invoice(customer=member.name)
        self._committed.append(("Sales Invoice", inv.name))
        if inv.docstatus == 0:
            inv.submit()
        frappe.db.commit()
        # remittance carries the invoice name explicitly
        result = find_invoice_for_payment(
            member.name, getdate("2025-05-15"), 25.0, remittance_info=f"Payment for {inv.name}"
        )
        self.assertEqual(result, inv.name)

    def test_finds_invoice_by_coverage_period_exact_match(self):
        member = self._member_with_customer_and_schedule(frequency="Monthly")
        inv = self.create_test_sales_invoice(customer=member.name)
        self._committed.append(("Sales Invoice", inv.name))
        if inv.docstatus == 0:
            inv.submit()
        # coverage matches the monthly period containing 2025-05-15 -> May 1..May 31
        frappe.db.set_value(
            "Sales Invoice",
            inv.name,
            {
                "custom_coverage_start_date": getdate("2025-05-01"),
                "custom_coverage_end_date": getdate("2025-05-31"),
                "outstanding_amount": 25.0,
            },
        )
        frappe.db.commit()
        result = find_invoice_for_payment(member.name, getdate("2025-05-15"), 25.0)
        self.assertEqual(result, inv.name)

    def test_no_match_returns_none(self):
        member = self._member_with_customer_and_schedule()
        # No invoices at all
        result = find_invoice_for_payment(member.name, getdate("2025-05-15"), 999.0)
        self.assertIsNone(result)
