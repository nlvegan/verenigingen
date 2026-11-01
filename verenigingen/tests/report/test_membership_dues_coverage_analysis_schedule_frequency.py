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
from verenigingen.verenigingen.doctype.membership.membership import cancel_membership
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

    # ---------------------------------------------------------------- helpers

    def _set_template_frequency(self, membership_type, frequency):
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": membership_type.name}
        )
        template_doc = frappe.get_doc("Membership Dues Schedule", template)
        template_doc.billing_frequency = frequency
        template_doc.save()

    def _covfreq_member(self):
        member = self.create_test_member(
            first_name="SchedFreq",
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"schedfreq.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        return member

    def _covfreq_submit_membership(self, member, frequency, start_offset_days):
        mtype = self.create_test_membership_type(billing_period=frequency)
        self._set_template_frequency(mtype, frequency)
        membership = self.create_test_membership(member=member.name, membership_type=mtype.name)
        membership.start_date = add_days(today(), start_offset_days)
        membership.submit()
        return membership

    def _live_schedule(self, member):
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": ["in", report.LIVE_SCHEDULE_STATUSES], "is_template": 0},
            ["name", "membership", "billing_frequency", "status"],
            as_dict=True,
        )

    def _frequency_over(self, member, start_offset_days, end_offset_days):
        return report.get_expected_billing_frequency(
            member.name, add_days(today(), start_offset_days), add_days(today(), end_offset_days)
        )

    # ---------------------------------------------- period-aware (item 1)

    def test_schedule_is_applied_only_to_the_membership_it_bills(self):
        """Two real Memberships: a Monthly one ended via cancel_membership, then an
        Annual one. The real flow leaves the member's ONE live schedule (Monthly)
        linked to the OLD membership; it must not classify the new Annual period.
        (The doctype has no start/end window, so the Membership link is the only
        way to place a schedule in time -- see get_expected_billing_frequency.)"""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        cancel_membership(old.name, add_days(today(), -150), "test", "Immediate")
        new = self._covfreq_submit_membership(member, "Annual", -100)

        schedule = self._live_schedule(member)
        self.assertEqual(schedule.membership, old.name, "fixture: real flow keeps the old schedule")
        self.assertEqual(schedule.billing_frequency, "Monthly")

        self.assertEqual(self._frequency_over(member, -300, -160), "Monthly", "old period: its schedule")
        self.assertEqual(self._frequency_over(member, -100, -10), "Annual", "new period: its own Type")

    # --------------------------------------- which schedule wins (item 2)

    def test_cancelled_schedule_of_other_frequency_is_ignored(self):
        """Active Annual schedule (older) beside a NEWER Cancelled Monthly one. A
        query without the status filter picks the newest row, so this goes red if
        the filter is dropped. The second schedule is inserted like the amendment
        service does and then cancelled through the repository's real cancel path."""
        member = self._covfreq_member()
        membership = self._covfreq_submit_membership(member, "Annual", -60)
        active = self._live_schedule(member)
        self.assertEqual(active.billing_frequency, "Annual")

        other = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Cancelled {frappe.generate_hash(length=6)}",
                "member": member.name,
                "membership": membership.name,
                "membership_type": membership.membership_type,
                "contribution_mode": "Fixed",
                "dues_rate": frappe.db.get_value("Membership Dues Schedule", active.name, "dues_rate"),
                "billing_frequency": "Monthly",
                "status": "Cancelled",
                "auto_generate": 0,
                "next_invoice_date": today(),
            }
        )
        other.flags.from_amendment = True
        other.insert()
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", other.name, "status"), "Cancelled")
        self.assertEqual(self._frequency_over(member, -60, -1), "Annual")

    # ------------------------------------------ non-Active states (item 3)

    def test_paused_schedule_still_defines_the_cadence(self):
        member = self._covfreq_member()
        self._covfreq_submit_membership(member, "Monthly", -60)
        # Annual template, Monthly Type: build the mismatch, then pause for real.
        mtype = frappe.db.get_value("Membership", {"member": member.name, "docstatus": 1}, "membership_type")
        schedule = self._live_schedule(member)
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "billing_frequency", "Annual")
        frappe.get_doc("Membership Dues Schedule", schedule.name).pause_schedule("test")
        paused = frappe.db.get_value("Membership Dues Schedule", schedule.name, ["status", "billing_frequency"])
        self.assertEqual(paused, ("Paused", "Annual"))
        self.assertEqual(frappe.db.get_value("Membership Type", mtype, "billing_period"), "Monthly")
        self.assertEqual(self._frequency_over(member, -60, -1), "Annual")
