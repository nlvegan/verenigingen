"""Regression tests for #1934.

``member_portal.get_payment_status`` took the member's billing frequency from
``Membership Type.billing_period``. The member is billed by their own live
``Membership Dues Schedule`` (built from a template whose frequency may differ
from the Type's), so the portal showed the wrong cadence AND formatted each
outstanding invoice's coverage period for the wrong cadence (#1909 sibling).

Fixtures go through the normal path: the Membership Type's auto-created template
is saved with the wanted billing_frequency, submitting a Membership auto-creates
the member's Active schedule from it, and the invoice comes from
``generate_manual_invoice``. The no-schedule test ends the schedule through
the repository's real cancel path. No fixture writes a field directly.
"""

import frappe
from frappe.utils import getdate, today

from verenigingen.api.manual_invoice_generation import generate_manual_invoice
from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.templates.pages import member_portal
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.schedule_frequency_fixture import ScheduleFrequencyFixtureMixin
from verenigingen.utils.member_portal_utils import format_coverage_period
from verenigingen.utils.member_utils import get_active_membership_for_member


JAN_1 = getdate(today()).replace(month=1, day=1)  # Annual period = one calendar year


class TestPortalBillingFrequencyFollowsSchedule(ScheduleFrequencyFixtureMixin, VereningingenTestCase):
    def _portal_status(self, member):
        member_doc = frappe.get_doc("Member", member.name)
        membership = get_active_membership_for_member(
            member.name, ["name", "membership_type", "start_date", "renewal_date", "status", "cancellation_date"]
        )
        self.assertTrue(membership, "fixture: member must have an active membership")
        return member_portal.get_payment_status(member_doc, membership)

    def _manual_invoice_for(self, member):
        result = generate_manual_invoice(member.name)
        self.assertTrue(result.get("success"), result)
        data = result["data"]
        name = data["invoice_name"]
        name = name if isinstance(name, str) else getattr(name, "name", None) or name.get("name")
        self.track_doc("Sales Invoice", name)
        return frappe.db.get_value(
            "Sales Invoice",
            name,
            ["name", "custom_coverage_start_date", "custom_coverage_end_date"],
            as_dict=True,
        )

    def test_mismatched_type_and_schedule_shows_the_schedule_frequency(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Annual")
        self.assertEqual(schedule.billing_frequency, "Annual", "fixture: schedule is Annual")
        self.assertEqual(frappe.db.get_value("Membership Type", mtype.name, "billing_period"), "Monthly")

        self.assertEqual(self._portal_status(member)["billing_frequency"], "Annually")

    def test_coverage_period_is_formatted_for_the_schedule_frequency(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Annual", start_date=JAN_1)
        invoice = self._manual_invoice_for(member)
        start, end = invoice.custom_coverage_start_date, invoice.custom_coverage_end_date
        expected = format_coverage_period(start, end, "Annual")
        wrong = format_coverage_period(start, end, "Monthly")
        self.assertNotEqual(expected, wrong, "fixture: the two cadences must format differently")

        shown = {i["name"]: i["coverage_period"] for i in self._portal_status(member)["outstanding_invoices"]}
        self.assertEqual(shown[invoice.name], expected)

    def test_matched_type_and_schedule_control(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Monthly")
        self.assertEqual(schedule.billing_frequency, "Monthly")
        self.assertEqual(self._portal_status(member)["billing_frequency"], "Monthly")

    def test_quarterly_schedule_under_annual_type_shows_quarterly(self):
        """The reverse mismatch, and a value that is not the Type's."""
        member, mtype, schedule = self._member_billed_by_template("Annual", "Quarterly")
        self.assertEqual(schedule.billing_frequency, "Quarterly")
        self.assertEqual(self._portal_status(member)["billing_frequency"], "Quarterly")

    def test_no_live_schedule_falls_back_to_membership_type(self):
        member, mtype, schedule = self._member_billed_by_template("Quarterly", "Annual")
        # The repository's real cancel path leaves the member with no live schedule.
        self.assertTrue(DuesScheduleRepository().cancel_schedule(schedule.name, "test").success)
        self.assertEqual(self._portal_status(member)["billing_frequency"], "Quarterly")

    def test_semi_annual_schedule_shows_biannually(self):
        """Schedule vocabulary ("Semi-Annual") differs from the Type's ("Biannual")."""
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Semi-Annual")
        self.assertEqual(schedule.billing_frequency, "Semi-Annual")
        self.assertEqual(self._portal_status(member)["billing_frequency"], "Biannually")
