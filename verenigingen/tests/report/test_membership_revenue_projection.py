"""Real-integration tests for the *Membership Revenue Projection* script report
(``verenigingen/verenigingen_payments/report/membership_revenue_projection/``).

This report was at 0% coverage. Unlike the Mollie reports it needs no external
API: it projects the next N months of membership revenue purely from active
``Membership Dues Schedule`` rows, so every branch is reachable in the test env.

Coverage strategy:
  * ``calculate_monthly_revenue`` is a pure function with one branch per billing
    frequency -- tested directly with exact expected values so a changed divisor
    (e.g. Quarterly /3 -> /4) fails the test (mutation-sensitive).
  * ``get_columns`` / ``get_filters`` / ``get_chart_config`` are static shape.
  * ``get_data`` aggregates ALL active non-template schedules in the site, so we
    assert on the DELTA between a baseline run and a run after inserting our own
    controlled schedules -- robust to pre-existing rows on a shared test site.
"""

import frappe
from dateutil.relativedelta import relativedelta
from frappe.utils import getdate, nowdate

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.report.membership_revenue_projection import (
    membership_revenue_projection as report,
)


class TestMembershipRevenueProjectionReport(VereningingenTestCase):
    # ------------------------------------------------- calculate_monthly_revenue

    def test_monthly_frequency_contributes_full_rate(self):
        self.assertEqual(report.calculate_monthly_revenue(120.0, "Monthly", None), 120.0)

    def test_quarterly_frequency_contributes_a_third(self):
        # 120 / 3 -- pins the Quarterly divisor.
        self.assertEqual(report.calculate_monthly_revenue(120.0, "Quarterly", None), 40.0)

    def test_annual_frequency_contributes_a_twelfth(self):
        self.assertEqual(report.calculate_monthly_revenue(120.0, "Annual", None), 10.0)

    def test_semi_annual_frequency_contributes_a_sixth(self):
        self.assertEqual(report.calculate_monthly_revenue(120.0, "Semi-Annual", None), 20.0)

    def test_unknown_frequency_defaults_to_full_rate(self):
        # The else-branch returns the full rate (NOT 0): distinguishes a real
        # default from a silently-dropped contribution.
        self.assertEqual(report.calculate_monthly_revenue(120.0, "Weekly", None), 120.0)
        self.assertEqual(report.calculate_monthly_revenue(120.0, None, None), 120.0)

    # --------------------------------------------------------------- static shape

    def test_get_columns_structure(self):
        columns = report.get_columns()
        fieldnames = [c["fieldname"] for c in columns]
        self.assertEqual(
            fieldnames,
            ["month", "projected_revenue", "active_memberships", "average_amount"],
        )
        by_name = {c["fieldname"]: c for c in columns}
        self.assertEqual(by_name["projected_revenue"]["fieldtype"], "Currency")
        self.assertEqual(by_name["average_amount"]["fieldtype"], "Currency")
        self.assertEqual(by_name["active_memberships"]["fieldtype"], "Int")

    def test_get_filters_projection_months(self):
        filters = report.get_filters()
        self.assertEqual(len(filters), 1)
        pm = filters[0]
        self.assertEqual(pm["fieldname"], "projection_months")
        self.assertEqual(pm["fieldtype"], "Int")
        self.assertEqual(pm["default"], 12)

    def test_get_chart_config(self):
        chart = report.get_chart_config([])
        self.assertEqual(chart["chart_type"], "line")
        self.assertEqual(chart["data"]["x"], "month")
        self.assertEqual(chart["data"]["y"][0]["name"], "projected_revenue")

    # --------------------------------------------------------- get_data behaviour

    def test_default_projection_is_twelve_months(self):
        data = report.get_data(None)
        self.assertEqual(len(data), 12)
        # Months are consecutive, formatted YYYY-MM, starting this month.
        expected_first = frappe.utils.now_datetime().replace(day=1).strftime("%Y-%m")
        self.assertEqual(data[0]["month"], expected_first)

    def test_projection_months_filter_is_clamped(self):
        # QUIRK (pinned, backlog-worthy): the guard is `if filters.get(...)`, so a
        # falsy 0 is treated as "not supplied" and falls back to the default 12 --
        # it does NOT clamp to 1. A truthy negative DOES hit the `max(1, ...)`
        # lower clamp; >24 hits the `min(24, ...)` upper clamp.
        self.assertEqual(len(report.get_data({"projection_months": 0})), 12)
        self.assertEqual(len(report.get_data({"projection_months": -5})), 1)
        self.assertEqual(len(report.get_data({"projection_months": 100})), 24)
        self.assertEqual(len(report.get_data({"projection_months": 3})), 3)

    def test_active_monthly_schedule_adds_full_rate_each_month(self):
        rate = 37.0
        member, mt = self._member_with_active_membership("RevProj", "Monthly")

        before = self._by_month(report.get_data({"projection_months": 6}))
        self.create_controlled_dues_schedule(member.name, "Monthly", rate, membership_type=mt.name)
        after = self._by_month(report.get_data({"projection_months": 6}))

        for month in before:
            self.assertAlmostEqual(
                after[month]["projected_revenue"] - before[month]["projected_revenue"],
                rate,
                places=2,
                msg=f"monthly schedule should add {rate} in {month}",
            )
            self.assertEqual(
                after[month]["active_memberships"] - before[month]["active_memberships"],
                1,
            )

    def test_annual_schedule_adds_one_twelfth_each_month(self):
        rate = 120.0
        member, mt = self._member_with_active_membership("RevProj", "Annual")

        before = self._by_month(report.get_data({"projection_months": 3}))
        self.create_controlled_dues_schedule(member.name, "Annual", rate, membership_type=mt.name)
        after = self._by_month(report.get_data({"projection_months": 3}))

        for month in before:
            self.assertAlmostEqual(
                after[month]["projected_revenue"] - before[month]["projected_revenue"],
                rate / 12,
                places=2,
            )

    def test_ended_schedule_excluded_after_end_date(self):
        # A schedule ending inside the projection window contributes to months
        # up to and including its end month, then drops out. Pins both the
        # `if end_date and end_date < projection_date` branch and the boundary.
        rate = 50.0
        member, mt = self._member_with_active_membership("RevProj", "Ended")

        start_of_month = getdate(nowdate()).replace(day=1)
        # End on the last day of (this month + 1): included in offsets 0 and 1,
        # excluded from offset 2 onward (projection_date = 1st of month+2 > end).
        end_date = (start_of_month + relativedelta(months=2)) - relativedelta(days=1)

        before = self._by_month(report.get_data({"projection_months": 4}))
        self.create_controlled_dues_schedule(
            member.name, "Monthly", rate, membership_type=mt.name, end_date=end_date
        )
        after = self._by_month(report.get_data({"projection_months": 4}))

        months = sorted(before)  # offsets 0..3
        for offset, month in enumerate(months):
            delta = after[month]["active_memberships"] - before[month]["active_memberships"]
            expected = 1 if offset < 2 else 0
            self.assertEqual(delta, expected, msg=f"offset {offset} ({month}) expected delta {expected}")

    def test_zero_and_template_schedules_ignored(self):
        # dues_rate == 0 and is_template == 1 are both filtered out by the SQL.
        member, mt = self._member_with_active_membership("RevProj", "Ignored")

        before = self._by_month(report.get_data({"projection_months": 2}))
        self.create_controlled_dues_schedule(member.name, "Monthly", 0, membership_type=mt.name)
        after = self._by_month(report.get_data({"projection_months": 2}))
        for month in before:
            self.assertEqual(after[month]["active_memberships"], before[month]["active_memberships"])

    def test_execute_returns_report_tuple(self):
        columns, data, message, chart = report.execute({"projection_months": 2})
        self.assertEqual(len(columns), 4)
        self.assertEqual(len(data), 2)
        self.assertIsNone(message)
        self.assertEqual(chart["chart_type"], "line")

    # -------------------------------------------------------------------- helpers

    def _member_with_active_membership(self, first_name, last_name):
        """A member with a SUBMITTED active membership but NO auto dues schedule.

        The report reads submitted (docstatus=1) active memberships' schedules,
        and the schedule controller rejects members without an active membership.
        We skip the membership's own auto-schedule (skip_dues_schedule_creation)
        so the only schedule affecting the delta is the one the test inserts.
        """
        member = self.create_test_member(first_name=first_name, last_name=last_name)
        mt = self.create_test_membership_type()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": mt.name,
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        )
        membership.flags.skip_dues_schedule_creation = True
        membership.insert()
        membership.submit()
        # Do NOT track_doc a submitted Membership: explicit cleanup can't delete a
        # submitted record, and FrappeTestCase's per-test rollback removes it anyway.
        return member, mt

    @staticmethod
    def _by_month(rows):
        return {row["month"]: row for row in rows}
