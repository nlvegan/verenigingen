"""#1282: one period-to-month conversion, honouring every billing_frequency option.

Three hand-rolled "full-period rate -> monthly-equivalent" conversions (the portal
payment dashboard, the revenue-projection report, and the SQL annualiser behind the
membership analytics page) listed Monthly/Quarterly/Semi-Annual/Annual and let
everything else fall back to 1 month or to the raw rate. A Weekly or Daily
``dues_rate`` was therefore reported as if it were already monthly, and the projected
payment schedule advanced by one MONTH per entry for a schedule billed every 7 days.

The authority for how long a period is, is the running-period model
(``calculate_coverage_end``). These tests derive the expected ratio from THAT, not from
a hand-written table, so a future option cannot silently fall back to 1 and a table
that drifts from the period model fails here.
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.services.billing import billing_period_calculator as bpc
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import build_billing_frequency_multiplier_sql
from verenigingen.verenigingen_payments.report.membership_revenue_projection import (
    membership_revenue_projection as report,
)

ANCHOR = getdate("2024-01-01")  # a leap year start: Annual == 366 days, others unremarkable


def _meta_options(fieldname):
    field = frappe.get_meta("Membership Dues Schedule").get_field(fieldname)
    return [o for o in (field.options or "").split("\n") if o]


def _period_days(frequency, number=None, unit=None):
    """Length of one running period, from the period model itself."""
    end = bpc.calculate_coverage_end(frequency, ANCHOR, number, unit)
    return (end - ANCHOR).days + 1


def _implied_periods_per_year(frequency, number=None, unit=None):
    return 365.0 / _period_days(frequency, number, unit)


class TestPeriodsPerYearCoversEveryOption(EnhancedTestCase):
    def test_every_billing_frequency_option_converts_or_is_refused_explicitly(self):
        options = _meta_options("billing_frequency")
        self.assertIn("Weekly", options, "control: the DocType meta must be the source of options")
        self.assertIn("Custom", options)
        for frequency in options:
            if frequency == "Custom":
                # Custom needs its own interval; without it the answer is "unknown".
                self.assertIsNone(bpc.get_periods_per_year(frequency), frequency)
                self.assertIsNone(bpc.get_monthly_equivalent_amount(10, frequency), frequency)
                continue
            per_year = bpc.get_periods_per_year(frequency)
            self.assertIsNotNone(per_year, f"{frequency} neither converts nor is refused")
            # Within 3% of what the running-period model implies (365-day year vs a
            # 12-month/52-week convention), but nowhere near a fall-back to 1/month
            # (Daily: 30x off) or Weekly-as-4 (8% off).
            expected = _implied_periods_per_year(frequency)
            self.assertAlmostEqual(per_year / expected, 1.0, delta=0.03, msg=frequency)

    def test_every_custom_unit_option_converts_for_a_known_interval(self):
        units = _meta_options("custom_frequency_unit")
        self.assertEqual(set(units), {"Days", "Weeks", "Months", "Years"}, "a new unit needs a decision")
        for unit in units:
            for number in (1, 2, 3):
                per_year = bpc.get_periods_per_year("Custom", number, unit)
                self.assertIsNotNone(per_year, f"Custom {number} {unit}")
                expected = _implied_periods_per_year("Custom", number, unit)
                self.assertAlmostEqual(per_year / expected, 1.0, delta=0.03, msg=f"{number} {unit}")

    def test_custom_with_unknown_interval_is_refused_not_guessed(self):
        self.assertIsNone(bpc.get_periods_per_year("Custom", None, "Weeks"))
        self.assertIsNone(bpc.get_periods_per_year("Custom", 0, "Weeks"))
        self.assertIsNone(bpc.get_periods_per_year("Custom", 2, None))
        self.assertIsNone(bpc.get_periods_per_year("Custom", 2, "Fortnights"))
        self.assertIsNone(bpc.get_periods_per_year("Fortnightly"))
        self.assertIsNone(bpc.get_periods_per_year(None))

    def test_monthly_equivalent_of_each_frequency_scales_the_given_rate(self):
        rate = 37.5
        for frequency in _meta_options("billing_frequency"):
            if frequency == "Custom":
                continue
            monthly = bpc.get_monthly_equivalent_amount(rate, frequency)
            self.assertAlmostEqual(
                monthly, rate * _implied_periods_per_year(frequency) / 12, delta=rate * 0.04, msg=frequency
            )

    def test_add_billing_periods_steps_by_the_real_period(self):
        start = getdate("2025-01-31")
        self.assertEqual(bpc.add_billing_periods(start, 3, "Daily"), add_days(start, 3))
        self.assertEqual(bpc.add_billing_periods(start, 3, "Weekly"), add_days(start, 21))
        # month-based steps are computed from the anchor, so month-end does not drift
        self.assertEqual(bpc.add_billing_periods(start, 1, "Monthly"), getdate("2025-02-28"))
        self.assertEqual(bpc.add_billing_periods(start, 2, "Monthly"), getdate("2025-03-31"))
        self.assertEqual(bpc.add_billing_periods(start, 1, "Quarterly"), getdate("2025-04-30"))
        self.assertEqual(bpc.add_billing_periods(start, 1, "Custom", 2, "Weeks"), add_days(start, 14))
        self.assertIsNone(bpc.add_billing_periods(start, 1, "Custom"))


class TestRevenueProjectionReport(EnhancedTestCase):
    def test_weekly_and_daily_rates_are_not_reported_as_monthly(self):
        rate = 41.0
        weekly = report.calculate_monthly_revenue(rate, "Weekly", None)
        daily = report.calculate_monthly_revenue(rate, "Daily", None)
        self.assertAlmostEqual(weekly, rate * 52 / 12, places=6)  # NOT rate, NOT rate * 4
        self.assertAlmostEqual(daily, rate * 365 / 12, places=6)

    def test_custom_uses_its_own_interval_and_refuses_without_one(self):
        rate = 24.0
        self.assertAlmostEqual(
            report.calculate_monthly_revenue(rate, "Custom", None, 2, "Months"), rate / 2, places=6
        )
        self.assertAlmostEqual(
            report.calculate_monthly_revenue(rate, "Custom", None, 2, "Weeks"), rate * 26 / 12, places=6
        )
        self.assertIsNone(report.calculate_monthly_revenue(rate, "Custom", None))

    def test_every_option_has_a_contribution_other_than_the_raw_rate_unless_monthly(self):
        rate = 100.0
        for frequency in _meta_options("billing_frequency"):
            if frequency == "Custom":
                continue
            contribution = report.calculate_monthly_revenue(rate, frequency, None)
            self.assertIsNotNone(contribution, frequency)
            if frequency == "Monthly":
                self.assertEqual(contribution, rate)
            else:
                self.assertNotAlmostEqual(contribution, rate, delta=1.0, msg=frequency)


class TestAnnualisingSql(EnhancedTestCase):
    def _annualised(self, frequency, number=None, unit=None, amount=100):
        sql = build_billing_frequency_multiplier_sql(
            frequency_column="billing_frequency",
            amount_expression="amount",
            include_custom=True,
        )
        row = frappe.db.sql(
            f"""SELECT {sql} AS annual FROM (
                SELECT %s AS billing_frequency, %s AS amount,
                       %s AS custom_frequency_number, %s AS custom_frequency_unit
            ) t""",
            (frequency, amount, number, unit),
            as_dict=True,
        )[0]
        return None if row.annual is None else float(row.annual)

    def test_every_option_annualises_by_its_real_period(self):
        amount = 100
        for frequency in _meta_options("billing_frequency"):
            if frequency == "Custom":
                continue
            annual = self._annualised(frequency, amount=amount)
            self.assertIsNotNone(annual, frequency)
            implied = _implied_periods_per_year(frequency)
            self.assertAlmostEqual(annual / amount, implied, delta=implied * 0.03, msg=frequency)

    def test_weekly_is_not_annualised_as_a_single_payment(self):
        # The old ELSE branch returned the amount itself (x1).
        self.assertAlmostEqual(self._annualised("Weekly", amount=10), 520.0, places=4)
        self.assertAlmostEqual(self._annualised("Daily", amount=2), 730.0, places=4)

    def test_custom_units_match_the_doctype_option_spelling(self):
        # The DocType options are plural ("Months"); the SQL used to test singular ("Month"),
        # so every Custom schedule fell through to x1.
        for unit in _meta_options("custom_frequency_unit"):
            annual = self._annualised("Custom", 2, unit, amount=100)
            expected = 100 * bpc.get_periods_per_year("Custom", 2, unit)
            self.assertAlmostEqual(annual, expected, places=3, msg=unit)
            self.assertNotAlmostEqual(annual, 100.0, delta=1.0, msg=unit)

    def test_custom_without_an_interval_contributes_nothing_rather_than_a_guess(self):
        self.assertIsNone(self._annualised("Custom", None, None))
        self.assertIsNone(self._annualised("Custom", 0, "Weeks"))


class TestDashboardsOnRealSchedules(EnhancedTestCase):
    """Real Daily/Weekly Membership Dues Schedules through the real call sites."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(first_name="MonthEq", last_name="Member", status="Active")
        self.create_test_membership(member_name=self.member.name)
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertIsNotNone(name, "Expected the membership to create an active dues schedule")
        self.schedule = frappe.get_doc("Membership Dues Schedule", name)

    def _make(self, frequency, extra, next_invoice_date=None, number=None, unit=None):
        # The schedule validator refuses a rate below the membership type's minimum, so the
        # rate is derived from the fixture's own minimum plus a distinguishing extra.
        self.schedule.billing_frequency = frequency
        self.schedule.dues_rate = flt(self.schedule.minimum_amount) + extra
        self.schedule.custom_frequency_number = number
        self.schedule.custom_frequency_unit = unit
        self.schedule.next_invoice_date = next_invoice_date or add_days(today(), 1)
        self.schedule.last_invoice_date = None
        self.schedule.save()
        self.schedule.reload()
        return self.schedule

    def _expected_monthly(self, schedule, per_year):
        return flt(schedule.dues_rate * per_year / 12, 2)

    def test_portal_monthly_amount_for_weekly_and_daily(self):
        from verenigingen.templates.pages import payment_dashboard

        for frequency, per_year in (("Weekly", 52), ("Daily", 365)):
            schedule = self._make(frequency, 7)
            self.assertEqual(schedule.billing_frequency, frequency, "fixture must keep the frequency")
            shown = payment_dashboard.get_current_dues_schedule(self.member.name)
            self.assertEqual(shown["billing_frequency"], frequency)
            # derived from the fixture's own rate
            self.assertEqual(shown["monthly_amount"], self._expected_monthly(schedule, per_year), frequency)
            self.assertNotEqual(shown["monthly_amount"], flt(schedule.dues_rate, 2), frequency)

    def test_portal_monthly_amount_for_custom_uses_its_interval(self):
        from verenigingen.templates.pages import payment_dashboard

        schedule = self._make("Custom", 30, number=2, unit="Weeks")
        shown = payment_dashboard.get_current_dues_schedule(self.member.name)
        self.assertEqual(shown["monthly_amount"], self._expected_monthly(schedule, 26))

    def test_portal_monthly_amount_is_none_for_custom_without_interval(self):
        from verenigingen.templates.pages import payment_dashboard

        # Probe shortcut: a validator may refuse to SAVE this state, so write it directly to
        # prove what the page does if such a row exists.
        self._make("Monthly", 30)
        frappe.db.set_value(
            "Membership Dues Schedule",
            self.schedule.name,
            {"billing_frequency": "Custom", "custom_frequency_number": 0, "custom_frequency_unit": None},
        )
        shown = payment_dashboard.get_current_dues_schedule(self.member.name)
        self.assertIsNone(shown["monthly_amount"])
        overview = payment_dashboard.get_financial_overview(self.member.name)
        self.assertEqual(overview["yearly_progress"], 0)  # no target, no crash

    def test_payment_schedule_steps_by_the_real_period(self):
        from verenigingen.api.payment_dashboard import get_payment_schedule

        for frequency, step_days, minimum_entries in (("Weekly", 7, 50), ("Daily", 1, 360)):
            schedule = self._make(frequency, 9)
            result = get_payment_schedule(self.member.name)
            self.assertTrue(result["success"], msg=result)
            entries = result["data"]
            self.assertGreaterEqual(len(entries), minimum_entries, frequency)
            dates = [getdate(e["date"]) for e in entries]
            self.assertEqual(dates[0], getdate(schedule.next_invoice_date))
            gaps = {(b - a).days for a, b in zip(dates, dates[1:])}
            self.assertEqual(gaps, {step_days}, frequency)
            # the amount per entry stays the full period rate (one invoice = one period)
            self.assertEqual({e["amount"] for e in entries}, {flt(schedule.dues_rate, 2)})

    def test_payment_schedule_custom_steps_by_its_interval(self):
        from verenigingen.api.payment_dashboard import get_payment_schedule

        self._make("Custom", 9, number=2, unit="Weeks")
        entries = get_payment_schedule(self.member.name)["data"]
        dates = [getdate(e["date"]) for e in entries]
        self.assertGreater(len(dates), 20)
        self.assertEqual({(b - a).days for a, b in zip(dates, dates[1:])}, {14})

    def test_payment_schedule_monthly_family_is_unchanged(self):
        from verenigingen.api.payment_dashboard import get_payment_schedule

        for frequency, step_months in (("Monthly", 1), ("Quarterly", 3), ("Semi-Annual", 6)):
            schedule = self._make(frequency, 9, next_invoice_date=add_days(today(), 3))
            entries = get_payment_schedule(self.member.name)["data"]
            start = getdate(schedule.next_invoice_date)
            expected = [
                frappe.utils.add_months(start, i) for i in range(0, 12, step_months)
            ]
            self.assertEqual([getdate(e["date"]) for e in entries], expected, frequency)
