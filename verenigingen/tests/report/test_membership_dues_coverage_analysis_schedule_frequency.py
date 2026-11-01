"""Regression tests for #1909.

The coverage report took a member's expected billing frequency from
``Membership Type.billing_period``. The member is billed by their own active
``Membership Dues Schedule`` (built from a template whose frequency may differ
from the Type's), so gaps were classified against the wrong cadence.

Fixtures go through the normal path: the Membership Type's auto-created
template is saved with the wanted billing_frequency, then submitting a
Membership auto-creates the member's Active dues schedule from it. The one
direct write is in the no-schedule test, which DELETES the auto-created
schedule (``frappe.delete_doc``) to stand in for a member who has none.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)

GAP_DAYS = 70  # Monthly thresholds -> "Critical"; neutral base classification -> "Significant"


class TestCoverageReportUsesScheduleFrequency(VereningingenTestCase):
    def _member_billed_by_template(self, type_period, template_frequency):
        member = self.create_test_member(
            first_name="SchedFreq",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"schedfreq.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        membership_type = self.create_test_membership_type(billing_period=type_period)
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": membership_type.name}
        )
        template_doc = frappe.get_doc("Membership Dues Schedule", template)
        template_doc.billing_frequency = template_frequency
        template_doc.save()
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.start_date = add_days(today(), -120)
        membership.submit()
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active", "is_template": 0},
            ["name", "billing_frequency"],
            as_dict=True,
        )
        return member, membership_type, schedule

    def _gap(self, member):
        start = getdate(add_days(today(), -120))
        gaps = report.identify_coverage_gaps([], start, add_days(start, GAP_DAYS - 1), member.name)
        self.assertEqual(len(gaps), 1)
        return gaps[0]

    def test_mismatched_type_and_schedule_follows_the_schedule(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Annual")
        self.assertIsNotNone(schedule, "fixture: membership submit must create an Active schedule")
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(frappe.db.get_value("Membership Type", mtype.name, "billing_period"), "Monthly")

        start = getdate(add_days(today(), -120))
        end = add_days(start, GAP_DAYS - 1)
        self.assertEqual(report.get_expected_billing_frequency(member.name, start, end), "Annual")
        gap = self._gap(member)
        self.assertEqual(gap["gap_type"], "Significant", "Annual schedule: not a monthly 'Critical'")
        self.assertIn("annual", gap["gap_reason"])

    def test_matched_type_and_schedule_control(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Monthly")
        self.assertEqual(schedule.billing_frequency, "Monthly")
        gap = self._gap(member)
        self.assertEqual(gap["gap_type"], "Critical")
        self.assertIn("monthly", gap["gap_reason"])

    def test_no_active_schedule_falls_back_to_membership_type(self):
        member, mtype, schedule = self._member_billed_by_template("Monthly", "Annual")
        # Direct delete stands in for a member with no schedule.
        frappe.delete_doc("Membership Dues Schedule", schedule.name, force=True)
        start = getdate(add_days(today(), -120))
        end = add_days(start, GAP_DAYS - 1)
        self.assertEqual(report.get_expected_billing_frequency(member.name, start, end), "Monthly")
        self.assertEqual(self._gap(member)["gap_type"], "Critical")
