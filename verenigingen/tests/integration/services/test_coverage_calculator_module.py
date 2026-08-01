# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for the module-level functions and lower-level methods of
``coverage_calculator.py`` that the existing ``test_coverage_calculator.py`` suite
does not exercise:

- ``CoverageCalculator.calculate_cutoff_date_for_period`` (Monthly/Quarterly/Yearly/default)
- ``CoverageCalculator.derive_coverage_from_invoice_data``
- ``CoverageCalculator._calculate_coverage_end`` (Weekly / Semi-Annual / Custom unit branches)
- ``CoverageCalculator.get_latest_coverage_end_date`` (member_doc=None and no-customer paths)
- ``CoverageCalculator.calculate_next_coverage_period`` validation/failure branches
- module-level ``calculate_coverage_for_payment_date`` (all 3 priority sources)
- module-level ``find_invoice_for_payment`` (remittance / coverage / amount strategies)

All tests use real DB fixtures via Enhanced Test Factory - no business-logic mocks.
Expected values are derived from the data each test creates.
"""

import unittest
from datetime import date

import frappe
from frappe.utils import getdate

from verenigingen.services.billing.coverage_calculator import (
    CoverageCalculator,
    calculate_coverage_for_payment_date,
    find_invoice_for_payment,
    get_coverage_calculator,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestCoverageCalculatorCutoffMethod(EnhancedTestCase):
    """Exercise CoverageCalculator.calculate_cutoff_date_for_period across frequencies.

    Note: the method reads today() at call time, so assertions are derived from the
    actual cutoff result relative to today rather than hard-coded calendar dates.
    """

    def setUp(self):
        super().setUp()
        # creation_user is mandatory on the Single; populate so .save() works.
        if not frappe.db.get_single_value("Verenigingen Settings", "creation_user"):
            frappe.db.set_single_value("Verenigingen Settings", "creation_user", "Administrator")
        self.settings = frappe.get_single("Verenigingen Settings")
        self._orig_freq = self.settings.billing_cutoff_frequency
        self._orig_start = getattr(self.settings, "book_year_start_month", 1)
        self._orig_end_month = getattr(self.settings, "book_year_end_month", 12)
        self._orig_end_day = getattr(self.settings, "book_year_end_day", 31)

    def tearDown(self):
        self.settings.billing_cutoff_frequency = self._orig_freq
        self.settings.book_year_start_month = self._orig_start
        self.settings.book_year_end_month = self._orig_end_month
        self.settings.book_year_end_day = self._orig_end_day
        self.settings.save()
        frappe.db.commit()
        super().tearDown()

    def _set(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self.settings, k, v)
        self.settings.save()
        frappe.db.commit()

    def test_monthly_cutoff_is_last_day_of_current_month(self):
        self._set(billing_cutoff_frequency="Monthly")
        calc = CoverageCalculator(None)
        cutoff = getdate(calc.calculate_cutoff_date_for_period())

        today = getdate(frappe.utils.today())
        import calendar

        last_day = calendar.monthrange(today.year, today.month)[1]
        self.assertEqual(cutoff, date(today.year, today.month, last_day))

    def test_yearly_cutoff_calendar_book_year(self):
        # Calendar book year: end month 12 does not precede start month 1, so the
        # book year ends in the same calendar year as today.
        self._set(
            billing_cutoff_frequency="Yearly",
            book_year_start_month=1,
            book_year_end_month=12,
            book_year_end_day=31,
        )
        calc = CoverageCalculator(None)
        cutoff = getdate(calc.calculate_cutoff_date_for_period())
        today = getdate(frappe.utils.today())
        self.assertEqual(cutoff, date(today.year, 12, 31))

    def test_quarterly_cutoff_returns_quarter_end(self):
        # Quarterly cutoff should be the last day of the current quarter's end month
        # and never resolve to a year in the past (the bug fixed earlier).
        self._set(billing_cutoff_frequency="Quarterly", book_year_start_month=1)
        calc = CoverageCalculator(None)
        cutoff = getdate(calc.calculate_cutoff_date_for_period())
        today = getdate(frappe.utils.today())

        # End month is a quarter boundary (Mar/Jun/Sep/Dec) and the result is >= today.
        self.assertIn(cutoff.month, (3, 6, 9, 12))
        self.assertGreaterEqual(cutoff, today)
        # Last day of that month
        import calendar

        self.assertEqual(cutoff.day, calendar.monthrange(cutoff.year, cutoff.month)[1])

    def test_unknown_cutoff_frequency_defaults_to_month_end(self):
        # An unrecognised value should fall through the else branch -> end of month.
        self._set(billing_cutoff_frequency="Weekly")  # not a handled cutoff value
        calc = CoverageCalculator(None)
        cutoff = getdate(calc.calculate_cutoff_date_for_period())
        today = getdate(frappe.utils.today())
        import calendar

        last_day = calendar.monthrange(today.year, today.month)[1]
        self.assertEqual(cutoff, date(today.year, today.month, last_day))


class TestCoverageCalculatorCoverageEnd(EnhancedTestCase):
    """Exercise _calculate_coverage_end branches via the public calculate_next_coverage_period.

    Uses the sequential path (previous coverage exists) so coverage_end is produced by
    _calculate_coverage_end for the configured billing_frequency.
    """

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(membership_type_name="CovEnd Test Type")
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="CovEnd",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )

    def _make_prev_invoice(self, coverage_start, coverage_end):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        gen = InvoiceGenerator(self.schedule)
        res = gen.generate_invoice(
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            member_doc=self.member,
        )
        self.assertTrue(res.success, f"invoice setup failed: {res.errors if hasattr(res, 'errors') else res}")
        frappe.db.commit()

    def _next_period_for_frequency(self, frequency, prev_end, **extra):
        self.schedule.billing_frequency = frequency
        for k, v in extra.items():
            setattr(self.schedule, k, v)
        self.schedule.save()
        frappe.db.commit()
        calc = CoverageCalculator(self.schedule)
        result = calc.calculate_next_coverage_period(self.member)
        self.assertTrue(result.success, result.message if hasattr(result, "message") else None)
        self.assertEqual(result.data.calculation_method, "sequential")
        # Sequential coverage starts the day after prev_end
        from frappe.utils import add_days

        self.assertEqual(result.data.start_date, getdate(add_days(prev_end, 1)))
        return result.data

    def test_weekly_coverage_end_is_six_days_after_start(self):
        prev_end = date(2025, 1, 31)
        self._make_prev_invoice(date(2025, 1, 1), prev_end)
        period = self._next_period_for_frequency("Weekly", prev_end)
        # Start Feb 1 + 6 days = Feb 7
        self.assertEqual(period.end_date, date(2025, 2, 7))

    def test_semi_annual_coverage_end(self):
        prev_end = date(2025, 1, 31)
        self._make_prev_invoice(date(2025, 1, 1), prev_end)
        period = self._next_period_for_frequency("Semi-Annual", prev_end)
        # Start Feb 1, +6 months -1 day = Jul 31
        self.assertEqual(period.end_date, date(2025, 7, 31))

    def test_custom_days_unit_coverage_end(self):
        prev_end = date(2025, 1, 31)
        self._make_prev_invoice(date(2025, 1, 1), prev_end)
        period = self._next_period_for_frequency(
            "Custom", prev_end, custom_frequency_number=10, custom_frequency_unit="Days"
        )
        # Start Feb 1 + (10-1) days = Feb 10
        self.assertEqual(period.end_date, date(2025, 2, 10))

    def test_custom_weeks_unit_coverage_end(self):
        prev_end = date(2025, 1, 31)
        self._make_prev_invoice(date(2025, 1, 1), prev_end)
        period = self._next_period_for_frequency(
            "Custom", prev_end, custom_frequency_number=2, custom_frequency_unit="Weeks"
        )
        # Start Feb 1 + (2*7 - 1) = 13 days = Feb 14
        self.assertEqual(period.end_date, date(2025, 2, 14))

    def test_custom_years_unit_coverage_end(self):
        prev_end = date(2025, 1, 31)
        self._make_prev_invoice(date(2025, 1, 1), prev_end)
        period = self._next_period_for_frequency(
            "Custom", prev_end, custom_frequency_number=1, custom_frequency_unit="Years"
        )
        # Start Feb 1 2025, +12 months -1 day = Jan 31 2026
        self.assertEqual(period.end_date, date(2026, 1, 31))

    def test_custom_invalid_number_defaults_to_monthly(self):
        # The DocType rejects custom_frequency_number<1 at save time, so the
        # "< 1" defensive fallback in _calculate_coverage_end is only reachable by
        # invoking the helper directly with an invalid in-memory value. Construct a
        # utility calculator and override its custom attributes (no save needed).
        calc = CoverageCalculator(None)
        calc.billing_frequency = "Custom"
        calc.custom_frequency_number = 0
        calc.custom_frequency_unit = "Months"
        end = calc._calculate_coverage_end(date(2025, 2, 1))
        # 0 (< 1) falls back to monthly: Feb 1 +1 month -1 day = Feb 28
        self.assertEqual(getdate(end), date(2025, 2, 28))

    def test_unknown_frequency_defaults_to_monthly(self):
        # Unknown billing_frequency hits the final else fallback in _calculate_coverage_end.
        calc = CoverageCalculator(None)
        calc.billing_frequency = "Fortnightly"  # not a recognised value
        end = calc._calculate_coverage_end(date(2025, 2, 1))
        self.assertEqual(getdate(end), date(2025, 2, 28))

    def test_custom_unknown_unit_defaults_to_monthly(self):
        # Custom with an unrecognised unit hits the inner else fallback.
        calc = CoverageCalculator(None)
        calc.billing_frequency = "Custom"
        calc.custom_frequency_number = 3
        calc.custom_frequency_unit = "Decades"  # unrecognised
        end = calc._calculate_coverage_end(date(2025, 2, 1))
        self.assertEqual(getdate(end), date(2025, 2, 28))


class TestGetLatestCoverageEndEdgeCases(EnhancedTestCase):
    """Cover the get_latest_coverage_end_date paths not hit by existing tests."""

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(membership_type_name="LatestCov Test Type")
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="LatestCov",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )

    def test_member_doc_none_uses_self_member_name(self):
        # member_doc=None branch loads Member via self.member_name. With no invoices
        # the result is None, proving the load + no-result path executed.
        calc = CoverageCalculator(self.schedule)
        self.assertIsNone(calc.get_latest_coverage_end_date(None))

    def test_member_doc_none_with_no_member_name_returns_none(self):
        # Utility-only calculator (schedule_doc=None) has member_name=None.
        calc = CoverageCalculator(None)
        self.assertIsNone(calc.get_latest_coverage_end_date(None))

    def test_member_without_customer_returns_none(self):
        # Create a bare member with no linked customer.
        member = self.create_test_member(first_name="NoCust", last_name="Test", birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "customer", None)
        member.reload()
        calc = CoverageCalculator(None)
        self.assertIsNone(calc.get_latest_coverage_end_date(member))


class TestCalculateNextCoveragePeriodFailures(EnhancedTestCase):
    """Cover validation/failure branches of calculate_next_coverage_period."""

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(membership_type_name="CovFail Test Type")
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="CovFail",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )

    def test_get_coverage_calculator_factory_returns_instance(self):
        calc = get_coverage_calculator(self.schedule)
        self.assertIsInstance(calc, CoverageCalculator)
        self.assertEqual(calc.member_name, self.member.name)

    def test_date_based_branch_uses_force_date(self):
        # use_sequential=False explicitly takes the date_based branch (line ~159).
        calc = CoverageCalculator(self.schedule)
        result = calc.calculate_next_coverage_period(
            self.member, force_date=date(2025, 3, 15), use_sequential=False
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data.calculation_method, "date_based")
        self.assertLessEqual(result.data.start_date, result.data.end_date)


class TestCalculateCoverageForPaymentDate(EnhancedTestCase):
    """Cover the module-level calculate_coverage_for_payment_date priority hierarchy."""

    def setUp(self):
        super().setUp()
        if not frappe.db.get_single_value("Verenigingen Settings", "creation_user"):
            frappe.db.set_single_value("Verenigingen Settings", "creation_user", "Administrator")
        self.membership_type = self.create_test_membership_type(membership_type_name="PayCov Test Type")

    def test_priority1_current_dues_schedule_active(self):
        # Member with current_dues_schedule pointing at an Active Quarterly schedule.
        member, schedule = self.create_test_member_with_schedule(
            first_name="PayP1",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )
        schedule.billing_frequency = "Quarterly"
        schedule.save()
        frappe.db.commit()
        frappe.db.set_value("Member", member.name, "current_dues_schedule", schedule.name)

        start, end = calculate_coverage_for_payment_date(member.name, date(2025, 5, 15))
        # Quarterly period containing May 15 = Apr 1 - Jun 30
        self.assertEqual(getdate(start), date(2025, 4, 1))
        self.assertEqual(getdate(end), date(2025, 6, 30))

    def test_priority2_fallback_schedule_query(self):
        # current_dues_schedule unset -> falls back to any non-cancelled schedule.
        member, schedule = self.create_test_member_with_schedule(
            first_name="PayP2",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )
        schedule.billing_frequency = "Monthly"
        schedule.save()
        frappe.db.commit()
        frappe.db.set_value("Member", member.name, "current_dues_schedule", None)

        start, end = calculate_coverage_for_payment_date(member.name, date(2025, 5, 15))
        # Monthly period containing May 15 = May 1 - May 31
        self.assertEqual(getdate(start), date(2025, 5, 1))
        self.assertEqual(getdate(end), date(2025, 5, 31))

    def test_priority3_settings_fallback_no_schedule(self):
        # A member with NO dues schedule at all -> settings billing_cutoff_frequency.
        member = self.create_test_member(first_name="PayP3", last_name="Test", birth_date="1990-01-01")
        # Ensure no schedules exist for this member.
        self.assertEqual(frappe.db.count("Membership Dues Schedule", {"member": member.name}), 0)
        settings = frappe.get_single("Verenigingen Settings")
        orig = settings.billing_cutoff_frequency
        settings.billing_cutoff_frequency = "Quarterly"
        settings.save()
        frappe.db.commit()
        try:
            start, end = calculate_coverage_for_payment_date(member.name, date(2025, 5, 15))
            # Maps Quarterly -> Quarterly: Apr 1 - Jun 30
            self.assertEqual(getdate(start), date(2025, 4, 1))
            self.assertEqual(getdate(end), date(2025, 6, 30))
        finally:
            settings.billing_cutoff_frequency = orig
            settings.save()
            frappe.db.commit()


class TestCoverageForPaymentDateFollowsTheMembersOwnPeriods(EnhancedTestCase):
    """
    Payments must be matched against the period the member is actually billed for.

    Coverage periods run from the member's join date, so a member who joined
    mid-month has periods that straddle two calendar months. Every consumer of
    calculate_coverage_for_payment_date compares its result to the invoice's
    custom_coverage_* fields for EXACT equality
    (find_invoice_for_payment strategy 2, DuesPaymentProcessor, and the Mollie
    orchestrator), so returning the calendar period means an off-calendar member's
    payment matches no invoice at all - and the create-invoice paths would go on to
    write calendar-aligned invoices that overlap the member's own sequence.
    """

    JOIN_DATE = date(2025, 6, 3)
    FIRST_PERIOD_END = date(2025, 7, 2)
    PAYMENT_DATE = date(2025, 6, 20)  # inside the first period, mid calendar month

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(
            membership_type_name="OffCalendar PayCov Type"
        )
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="OffCalendar",
            last_name="Payer",
            membership_type_name=self.membership_type.name,
            start_date=self.JOIN_DATE,
        )
        self.schedule.billing_frequency = "Monthly"
        self.schedule.save()
        frappe.db.commit()
        self.member.reload()

    def _make_first_invoice(self):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        result = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=self.JOIN_DATE,
            coverage_end=self.FIRST_PERIOD_END,
            member_doc=self.member,
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        frappe.db.commit()
        return result.data.name

    def test_payment_inside_an_off_calendar_period_resolves_to_that_period(self):
        """
        The returned period must be the invoice's own, not the calendar month.

        The seeded period deliberately ends on the 10th rather than a natural monthly
        boundary. With a sequential end date this test would also pass by rolling from
        the membership start, so it would not actually pin the invoice lookup it names.
        """
        irregular_end = date(2025, 7, 10)
        self._make_invoice(self.JOIN_DATE, irregular_end)

        start, end = calculate_coverage_for_payment_date(self.member.name, self.PAYMENT_DATE)

        self.assertEqual(getdate(start), self.JOIN_DATE)
        self.assertEqual(getdate(end), irregular_end)

    def _make_invoice(self, coverage_start, coverage_end, submit=True):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        result = InvoiceGenerator(self.schedule).generate_invoice(
            coverage_start=coverage_start, coverage_end=coverage_end, member_doc=self.member
        )
        self.assertTrue(result.success, getattr(result, "error_message", None))
        if not submit:
            frappe.db.set_value("Sales Invoice", result.data.name, "docstatus", 0)
        frappe.db.commit()
        return result.data.name

    def test_payment_inside_a_coverage_gap_resolves_to_the_members_own_period(self):
        """
        A payment landing in a GAP between two invoiced periods must still resolve to
        the member's own boundary, not the calendar.

        This is the case that made the previous implementation's third preference
        unreachable: anchoring on the LATEST coverage end returned None whenever any
        later invoice existed, and the calendar fallback then handed the Mollie
        orchestrator a calendar-aligned period which it would CREATE an invoice for -
        permanently corrupting an off-calendar member's sequence. Gaps are an expected
        state here, not a hypothetical: the codebase carries _detect_coverage_gaps and
        GAP_RESET_THRESHOLD_DAYS specifically for them.
        """
        self._make_invoice(self.JOIN_DATE, self.FIRST_PERIOD_END)
        self._make_invoice(date(2025, 10, 3), date(2025, 11, 2))

        start, end = calculate_coverage_for_payment_date(self.member.name, date(2025, 8, 15))

        self.assertEqual(getdate(start), date(2025, 8, 3))
        self.assertEqual(getdate(end), date(2025, 9, 2))

    def test_draft_invoice_coverage_is_ignored_so_the_safe_branch_stays_reachable(self):
        """
        A DRAFT invoice must not supply the period, even though the consumers' overlap
        detectors do match drafts (docstatus < 2).

        Returning the draft's own period would guarantee `exact_match` in
        check_coverage_overlap, and a draft's outstanding_amount is 0, which
        mollie_payment_orchestrator._create_invoice_if_safe and dues_payment_processor
        both read as "already paid" - their cue to create ANOTHER invoice for the same
        period. Deriving a different period instead leaves them on the partial-overlap
        branch, which returns None for manual review. Until those callers check
        docstatus before trusting outstanding_amount, submitted-only is the safe answer.

        The draft's period is deliberately irregular (ends the 10th), so a resolver that
        ignored drafts and rolled from the membership start could not reproduce it by
        coincidence - which is what makes this test discriminating.
        """
        self._make_invoice(self.JOIN_DATE, date(2025, 7, 10), submit=False)

        start, end = calculate_coverage_for_payment_date(self.member.name, self.PAYMENT_DATE)

        self.assertNotEqual(getdate(end), date(2025, 7, 10), "the draft's own period was used as the answer")
        # No submitted coverage exists, so the membership-start roll supplies the period.
        self.assertEqual(getdate(start), self.JOIN_DATE)
        self.assertEqual(getdate(end), self.FIRST_PERIOD_END)

    def test_payment_predating_all_coverage_falls_back_to_the_calendar(self):
        """
        A payment before the member's first invoiced period has no position in the
        sequence, so it must fall back rather than have one invented from the
        membership start date.

        The payment is deliberately AFTER the membership start (2025-06-03) but before
        the only invoiced period. With the "coverage exists but all of it is later"
        guard removed, control reaches the membership-start roll, which happily produces
        2025-07-03..2025-08-02 - so this pins the guard rather than the pre-existing
        `membership_start <= payment_date` check.
        """
        self._make_invoice(date(2025, 9, 3), date(2025, 10, 2))

        start, end = calculate_coverage_for_payment_date(self.member.name, date(2025, 7, 15))

        self.assertEqual(getdate(start), date(2025, 7, 1))
        self.assertEqual(getdate(end), date(2025, 7, 31))

    def test_off_calendar_invoice_is_found_for_a_payment_inside_its_coverage(self):
        """
        End-to-end: the payment must resolve to the invoice covering it.

        The payment amount is deliberately mismatched so strategy 3 (unpaid-amount
        match) cannot fire and the assertion pins strategy 2, the coverage-period
        match, which is the strategy that breaks for off-calendar members.
        """
        invoice_name = self._make_first_invoice()
        outstanding = frappe.db.get_value("Sales Invoice", invoice_name, "outstanding_amount")
        mismatched_amount = float(outstanding) + 1000.0

        found = find_invoice_for_payment(self.member.name, self.PAYMENT_DATE, mismatched_amount)

        self.assertEqual(found, invoice_name)


class TestFindInvoiceForPayment(EnhancedTestCase):
    """Cover the module-level find_invoice_for_payment matching strategies."""

    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type(membership_type_name="FindInv Test Type")
        self.member, self.schedule = self.create_test_member_with_schedule(
            first_name="FindInv",
            last_name="Test",
            membership_type_name=self.membership_type.name,
            start_date="2025-01-01",
        )
        self.member.reload()

    def _make_invoice(self, coverage_start, coverage_end):
        from verenigingen.services.billing.invoice_generator import InvoiceGenerator

        gen = InvoiceGenerator(self.schedule)
        res = gen.generate_invoice(
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            member_doc=self.member,
        )
        self.assertTrue(res.success)
        frappe.db.commit()
        # generate_invoice returns the SalesInvoice document; callers want its name.
        return res.data.name

    def _make_draft_invoice(self, coverage_start, coverage_end):
        """A DRAFT membership invoice, produced the way production produces one.

        `auto_submit_membership_invoices` is a supported setting; with it off,
        InvoiceGenerator._submit_invoice deliberately leaves the invoice as a draft.
        That is how a draft carrying real custom_coverage_* dates comes to exist,
        so the fixture flips the setting rather than hand-building an invoice.
        """
        orig = frappe.db.get_single_value("Verenigingen Settings", "auto_submit_membership_invoices")
        frappe.db.set_single_value("Verenigingen Settings", "auto_submit_membership_invoices", 0)
        try:
            return self._make_invoice(coverage_start, coverage_end)
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "auto_submit_membership_invoices", orig)
            frappe.db.commit()

    def test_no_customer_returns_none(self):
        member = self.create_test_member(first_name="NoCustFind", last_name="Test", birth_date="1990-01-01")
        frappe.db.set_value("Member", member.name, "customer", None)
        self.assertIsNone(find_invoice_for_payment(member.name, date(2025, 5, 15), 25.0))

    def test_remittance_info_invoice_reference(self):
        invoice_name = self._make_invoice(date(2025, 1, 1), date(2025, 3, 31))
        # Reference the real invoice name in remittance info.
        remittance = f"Payment for {invoice_name} thanks"
        found = find_invoice_for_payment(
            self.member.name, date(2025, 1, 15), 25.0, remittance_info=remittance
        )
        self.assertEqual(found, invoice_name)

    def test_coverage_period_exact_match(self):
        # Quarterly schedule; invoice covers Apr 1 - Jun 30 (the quarter for a May payment).
        self.schedule.billing_frequency = "Quarterly"
        self.schedule.save()
        frappe.db.commit()
        invoice_name = self._make_invoice(date(2025, 4, 1), date(2025, 6, 30))

        # Deliberately pin Strategy 2 (coverage-period match): pass a payment amount
        # that does NOT match the invoice outstanding so Strategy 3 (amount match)
        # cannot fire. The coverage window for a May 15 payment on a Quarterly schedule
        # is Apr 1 - Jun 30, which exactly matches the invoice -> coverage match wins.
        invoice_outstanding = frappe.db.get_value("Sales Invoice", invoice_name, "outstanding_amount")
        mismatched_amount = float(invoice_outstanding) + 1000.0
        found = find_invoice_for_payment(self.member.name, date(2025, 5, 15), mismatched_amount)
        self.assertEqual(found, invoice_name)

    def test_draft_invoice_with_exact_coverage_is_not_matched(self):
        """Strategy 2 must not hand back a DRAFT invoice.

        Strategies 1 and 3 both pin `docstatus = 1`; strategy 2 went through
        `check_coverage_overlap`, which matches `docstatus < 2`, and then gated only on
        `outstanding_amount > 0`. A draft carries its full grand_total as outstanding
        (ERPNext recomputes it on every non-cancelled save), so the gate let drafts
        through.

        The caller that pays for this is the Ponto webhook handler: it saves the match
        onto `Ponto Payment Link.sales_invoice` and hands it to `get_payment_entry`,
        which refuses an unsubmitted reference ("must be submitted"). That raise is
        swallowed by a broad `except Exception`, so the payment is silently dropped.
        """
        self.schedule.billing_frequency = "Quarterly"
        self.schedule.save()
        frappe.db.commit()
        draft_name = self._make_draft_invoice(date(2025, 4, 1), date(2025, 6, 30))

        # Pin the premise rather than assuming it: a draft is not "already paid".
        draft = frappe.db.get_value(
            "Sales Invoice", draft_name, ["docstatus", "outstanding_amount"], as_dict=True
        )
        self.assertEqual(draft.docstatus, 0)
        self.assertGreater(
            float(draft.outstanding_amount),
            0,
            "a draft carries a non-zero outstanding_amount - the outstanding gate alone " "cannot exclude it",
        )

        # Mismatch the amount so strategy 3 cannot fire and the assertion pins strategy 2.
        mismatched_amount = float(draft.outstanding_amount) + 1000.0
        found = find_invoice_for_payment(self.member.name, date(2025, 5, 15), mismatched_amount)

        self.assertIsNone(
            found, "a draft invoice must not be matched to a payment - it cannot be allocated to"
        )

    def test_no_match_returns_none(self):
        # Invoice exists but for a coverage window far from the payment and a
        # non-matching amount; remittance has no reference.
        self._make_invoice(date(2025, 1, 1), date(2025, 1, 31))
        found = find_invoice_for_payment(
            self.member.name, date(2025, 11, 15), 9999.99, remittance_info="no reference here"
        )
        self.assertIsNone(found)


if __name__ == "__main__":
    unittest.main()
