"""Regression tests for #890.

``generate_catchup_invoices``'s ``is_current_period`` branch (membership_dues_
coverage_analysis.py, inside the catch-up loop) used to extend the current
period's end with ``calculate_billing_period()`` -- the CALENDAR period
surrounding ``period_start`` -- instead of ``calculate_coverage_end()``, the
RUNNING period that actually runs from ``period_start`` (see that function's
own docstring, and CLAUDE.md's "running periods" section). For a member whose
cycle is not anchored to a calendar boundary, the two disagree: the calendar
call over/under-bills the current period and drags the next period's anchor
onto the calendar grid.

**Every fixture below anchors off EVERY calendar boundary the affected
frequencies care about** (Annual: 1 Jan; Monthly: 1st of the month;
Quarterly: 1 Jan/Apr/Jul/Oct) by using day=17. A boundary-anchored fixture
(the 1st, or 1 January) passes identically whether the buggy calendar call
or the fixed running-period call is used, and proves nothing -- see the
investigation posted on #890.

Scope note on Monthly/Quarterly: ``_calculate_periods_within_segment`` (the
gap-splitting helper feeding this call site, #884, out of scope here)
unconditionally re-anchors Monthly/Quarterly period starts to the calendar
grid (``current_date.replace(day=1)`` / quarter start) *before* the
``is_current_period`` branch ever runs, so an off-boundary member anchor
cannot reach this call site through the full report pipeline for those two
frequencies -- only Annual's period roll-forward preserves the anchor
end-to-end. The Monthly/Quarterly tests below therefore stub the upstream
period list (``calculate_coverage_timeline``) with an explicit off-boundary
``period_start``, which isolates the branch actually under fix here without
asserting anything about #884's separate bug.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.services.billing.billing_period_calculator import (
    calculate_billing_period,
    calculate_coverage_end,
)
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)


class TestCurrentPeriodUsesRunningEnd(VereningingenTestCase):
    # A ~12-month book year is required by the catch-up / book-year split math
    # (test_site_1 ships a ~90-day config that split_gap_by_book_year rejects) --
    # same setup as test_membership_dues_coverage_analysis_actions.py.
    BOOK_YEAR_FIELDS = (
        ("book_year_start_month", 1),
        ("book_year_start_day", 1),
        ("book_year_end_month", 12),
        ("book_year_end_day", 31),
    )

    def setUp(self):
        super().setUp()
        self._orig_book_year = {
            field: frappe.db.get_single_value("Verenigingen Settings", field)
            for field, _ in self.BOOK_YEAR_FIELDS
        }
        for field, value in self.BOOK_YEAR_FIELDS:
            frappe.db.set_single_value("Verenigingen Settings", field, value)

    def tearDown(self):
        for field, orig in self._orig_book_year.items():
            frappe.db.set_single_value("Verenigingen Settings", field, orig)
        super().tearDown()

    # ------------------------------------------------------------- Annual

    def test_annual_current_period_uses_running_end_not_calendar_end(self):
        """Full pipeline, real fixture. The member's cycle anchors on day=17,
        a few months ago, with NO prior coverage invoice, so the whole span is
        one open gap and the catch-up generator's only (in-progress) period
        is the one this issue is about.

        Anchor must stay within the last ~12 months: Membership computes its
        own status from a one-year renewal cycle, and an anchor older than
        that turns the fixture "Expired" (no active dues schedule at all)
        rather than "Active" -- unrelated to #890, just a fixture constraint.
        """
        anchor = add_months(getdate(today()).replace(day=17), -3)

        member = self._anchor_member(anchor, suffix="Annual")
        # Default Membership Type template billing_frequency is Annual.

        result = report.generate_catchup_invoices([{"member": member.name}])

        self.assertGreaterEqual(len(result["generated_invoices"]), 1, result)

        invoices = [frappe.get_doc("Sales Invoice", gen["invoice"]) for gen in result["generated_invoices"]]
        # The CURRENT (in-progress) period is the one with the latest start --
        # _calculate_annual_periods rolls full 12-month periods forward, so
        # this is the still-open one clipped to today().
        current = max(invoices, key=lambda inv: getdate(inv.custom_coverage_start_date))

        start = getdate(current.custom_coverage_start_date)
        end = getdate(current.custom_coverage_end_date)

        # START: the member's own anchor. Annual periods roll 12 months
        # forward each time, so day/month never drift off the anchor.
        self.assertEqual((start.day, start.month), (17, anchor.month), "period start drifted off the anchor")

        # END: one full RUNNING year from that start, not the calendar year.
        expected_end = calculate_coverage_end("Annual", start)
        wrong_calendar_end = calculate_billing_period("Annual", start)[1]
        self.assertNotEqual(
            wrong_calendar_end, expected_end, "fixture anchor must be off a calendar boundary"
        )
        self.assertEqual(end, expected_end, "current period end must be the running-period end")
        self.assertNotEqual(end, wrong_calendar_end, "current period end must NOT be the calendar-year end")

    # ------------------------------------------------------------ Monthly

    def test_monthly_current_period_uses_running_end_not_calendar_end(self):
        self._assert_current_period_uses_running_end("Monthly")

    # ---------------------------------------------------------- Quarterly

    def test_quarterly_current_period_uses_running_end_not_calendar_end(self):
        self._assert_current_period_uses_running_end("Quarterly")

    # --------------------------------------------------------------- helpers

    def _assert_current_period_uses_running_end(self, billing_frequency):
        """Monthly/Quarterly: stub calculate_coverage_timeline with a single
        catch-up period anchored off-boundary (day=17), so it reaches the
        is_current_period branch unmolested by #884's separate calendar-
        realignment bug in the upstream gap-splitting helper.
        """
        anchor = add_months(getdate(today()).replace(day=17), -1)

        member = self._anchor_member(anchor, suffix=billing_frequency)
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "status": "Active"}, "name"
        )
        self.assertTrue(schedule_name, "fixture must have an active dues schedule")
        frappe.db.set_value("Membership Dues Schedule", schedule_name, "billing_frequency", billing_frequency)

        fake_analysis = {
            "timeline": [],
            "gaps": [],
            "stats": {
                "total_active_days": 0,
                "covered_days": 0,
                "gap_days": 0,
                "coverage_percentage": 0,
                "unpaid_coverage_days": 0,
                "outstanding_amount": 0,
            },
            "catchup": {
                "periods": [{"start": anchor, "end": today(), "amount": 15}],
                "total_amount": 15,
                "required": True,
                "summary": "1 period(s) needed",
            },
        }

        with patch.object(report, "calculate_coverage_timeline", return_value=fake_analysis):
            result = report.generate_catchup_invoices([{"member": member.name}])

        self.assertEqual(len(result["generated_invoices"]), 1, result)
        invoice = frappe.get_doc("Sales Invoice", result["generated_invoices"][0]["invoice"])

        start = getdate(invoice.custom_coverage_start_date)
        end = getdate(invoice.custom_coverage_end_date)

        self.assertEqual(start, anchor, "period start must be passed through unchanged")
        self.assertEqual(start.day, 17, "fixture anchor must be off a calendar boundary")

        expected_end = calculate_coverage_end(billing_frequency, start)
        wrong_calendar_end = calculate_billing_period(billing_frequency, start)[1]
        self.assertNotEqual(
            wrong_calendar_end, expected_end, "fixture anchor must be off a calendar boundary"
        )
        self.assertEqual(end, expected_end, "current period end must be the running-period end")
        self.assertNotEqual(end, wrong_calendar_end, "current period end must NOT be the calendar-period end")

    def _anchor_member(self, start_date, suffix):
        """A member + submitted Membership anchored at start_date, with NO
        prior coverage invoice (member_end_date left blank so the
        is_current_period branch's "not quitting" arm is taken)."""
        member = self.create_test_member(
            first_name="Anchor",
            last_name=f"{suffix}{frappe.generate_hash(length=4)}",
            email=f"anchor.{suffix.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        membership_type = self.create_test_membership_type()
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.start_date = start_date
        membership.submit()  # on_submit auto-creates the Active dues schedule
        return member
