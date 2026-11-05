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

from verenigingen.repositories.dues_schedule_repository import DuesScheduleRepository
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.schedule_frequency_fixture import ScheduleFrequencyFixtureMixin
from verenigingen.verenigingen.doctype.membership.membership import cancel_membership
from verenigingen.verenigingen.report.membership_dues_coverage_analysis import (
    membership_dues_coverage_analysis as report,
)

GAP_DAYS = 70  # Monthly thresholds -> "Critical"; neutral base classification -> "Significant"


class TestCoverageReportUsesScheduleFrequency(ScheduleFrequencyFixtureMixin, VereningingenTestCase):
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

    def _insert_schedule(self, member, membership, frequency, status):
        """Insert a schedule with the fields create_dues_schedule_for_amendment sets
        that are real fields here (from_amendment flag, Fixed mode, auto_generate=1,
        test_mode=0); its effective_date and notes are not set. The helper's cancelled
        schedules and this insert are the only extra schedules these tests make."""
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"CovFreq {frappe.generate_hash(length=6)}",
                "member": member.name,
                "membership": membership.name,
                "membership_type": membership.membership_type,
                "contribution_mode": "Fixed",
                "dues_rate": 20,
                "billing_frequency": frequency,
                "status": status,
                "auto_generate": 1,
                "test_mode": 0,
                "next_invoice_date": today(),
            }
        )
        schedule.flags.from_amendment = True
        schedule.insert()
        return schedule

    def _live_schedule_linked_to_old_membership(self, member, old, new_frequency, new_start_offset_days):
        """Old Monthly Membership cancelled, a new Membership submitted, and the member's
        only live schedule is a Monthly one still linked to the OLD Membership.

        #1938 is fixed: cancel_membership now cancels the old schedule and the new
        Membership gets its own. This state is no longer reachable through that flow, so it
        is built from real steps: the new Membership's own schedule is cancelled through the
        repository, then an amendment-style schedule is inserted for the old Membership
        (_insert_schedule, the one direct write; it stands in for a writer that links a
        live schedule to an older Membership). It keeps rule (b) of
        _get_schedule_frequency pinned."""
        cancel_membership(old.name, add_days(today(), -150), "test", "Immediate")
        new = self._covfreq_submit_membership(member, new_frequency, new_start_offset_days)
        own = self._live_schedule(member)
        self.assertEqual(own.membership, new.name, "fixture: the new Membership has its own schedule")
        self.assertTrue(DuesScheduleRepository().cancel_schedule(own.name, "test").success)
        self._insert_schedule(member, old, "Monthly", "Active")
        live = self._live_schedule(member)
        self.assertEqual((live.membership, live.billing_frequency), (old.name, "Monthly"))
        return new

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

    def test_current_period_follows_the_schedule_that_bills_even_if_linked_to_an_old_membership(self):
        """Rule (b): the member's live schedule bills the current period even when it is
        linked to an older Membership (here an amendment-style schedule, see the helper)."""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        self._live_schedule_linked_to_old_membership(member, old, "Annual", -100)

        self.assertEqual(self._frequency_over(member, -300, -160), "Monthly", "old period: linked schedule")
        self.assertEqual(self._frequency_over(member, -100, 0), "Monthly", "current period: live schedule")

    def test_new_membership_after_cancel_is_reported_by_its_own_schedule(self):
        """#1938 fixed, real flow: cancel_membership cancels the old schedule and the new
        Membership gets its own Annual one, so the current period is Annual and the old
        period (its schedule is Cancelled) falls back to its own Type."""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        cancel_membership(old.name, add_days(today(), -150), "test", "Immediate")
        new = self._covfreq_submit_membership(member, "Annual", -100)

        schedule = self._live_schedule(member)
        self.assertEqual((schedule.membership, schedule.billing_frequency), (new.name, "Annual"))
        self.assertEqual(self._frequency_over(member, -300, -160), "Monthly", "old period: its Type")
        self.assertEqual(self._frequency_over(member, -100, 0), "Annual", "current period: own schedule")

    def test_older_period_without_its_own_schedule_uses_its_type(self):
        """(c): cancel_membership cancels the old Membership's schedule and the new
        Membership gets its own Annual one (#1938). The OLD period is not current and the
        live schedule is linked to the new Membership, so the old period must use its own
        Type."""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        cancel_membership(old.name, add_days(today(), -150), "test", "Immediate")
        new = self._covfreq_submit_membership(member, "Annual", -100)

        schedule = self._live_schedule(member)
        self.assertEqual((schedule.membership, schedule.billing_frequency), (new.name, "Annual"))
        self.assertEqual(self._frequency_over(member, -300, -160), "Monthly")
        self.assertEqual(self._frequency_over(member, -100, 0), "Annual")

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

        other = self._insert_schedule(member, membership, "Monthly", "Cancelled")
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", other.name, "status"), "Cancelled")
        self.assertEqual(self._frequency_over(member, -60, -1), "Annual")

    # ------------------------------------------ non-Active states (item 3)

    def test_every_live_status_defines_the_cadence_and_terminal_ones_do_not(self):
        """Probe shortcut: the status is written directly with db.set_value for
        each state (only Paused has a real flow, covered separately above)."""
        member = self._covfreq_member()
        self._covfreq_submit_membership(member, "Monthly", -60)
        schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0}, "name"
        )
        frappe.db.set_value("Membership Dues Schedule", schedule, "billing_frequency", "Annual")
        for status in ("Active", "Paused", "Grace Period", "Suspended", "Payment Plan Active"):
            with self.subTest(status=status):
                frappe.db.set_value("Membership Dues Schedule", schedule, "status", status)
                self.assertEqual(self._frequency_over(member, -60, 0), "Annual")
        for status in ("Cancelled", "Test"):
            with self.subTest(status=status):
                frappe.db.set_value("Membership Dues Schedule", schedule, "status", status)
                self.assertEqual(self._frequency_over(member, -60, 0), "Monthly", "falls back to the Type")

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

    # ------------------------------ report path with a past to_date (#1938)

    def test_current_membership_stays_current_when_the_report_clamps_to_a_past_to_date(self):
        """Report path: get_membership_periods clamps the period end to to_date, so
        with to_date in the past the NEW Membership's period ends before today. It is
        still the current Membership, so the live Monthly schedule (linked to the old
        one (see the helper) must still apply rather than the new Type's Annual."""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        self._live_schedule_linked_to_old_membership(member, old, "Annual", -100)

        for to_offset in (0, -1, -10):
            with self.subTest(to_date_offset=to_offset):
                periods = report.get_membership_periods(member.name, None, add_days(today(), to_offset))
                start, end = periods[-1]  # ordered by start: the new Membership
                self.assertEqual(start, getdate(add_days(today(), -100)))
                self.assertEqual(report.get_expected_billing_frequency(member.name, start, end), "Monthly")

    # ------------------------------------------- template filter (defensive)

    def test_a_template_cannot_carry_a_member_so_the_is_template_filter_is_defensive(self):
        member = self._covfreq_member()
        mtype = self.create_test_membership_type(billing_period="Monthly")
        template = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"CovFreq tpl {frappe.generate_hash(length=6)}",
                "is_template": 1,
                "member": member.name,
                "membership_type": mtype.name,
                "billing_frequency": "Daily",
                "dues_rate": 5,
                "contribution_mode": "Fixed",
                "status": "Active",
            }
        )
        with self.assertRaisesRegex(frappe.ValidationError, "Templates cannot have a specific member"):
            template.insert()

    def test_future_dated_membership_does_not_take_the_old_live_schedule(self):
        """Pins the `start_date <= today` guard in _get_schedule_frequency. The
        live schedule is Monthly, linked to the old Membership (see the helper).
        An Annual Membership that starts in the future and ends later is not
        billed yet, so its period must use its own Type, not rule (b)."""
        member = self._covfreq_member()
        old = self._covfreq_submit_membership(member, "Monthly", -300)
        # (a second ACTIVE Membership is refused, so the future one follows the cancelled old one)
        future = self._live_schedule_linked_to_old_membership(member, old, "Annual", 10)
        # End of Period keeps it Active while giving it a future end date.
        cancel_membership(future.name, add_days(today(), 300), "test", "End of Period")

        schedule = self._live_schedule(member)
        self.assertEqual((schedule.membership, schedule.billing_frequency), (old.name, "Monthly"))
        fut = frappe.db.get_value("Membership", future.name, ["start_date", "cancellation_date"], as_dict=True)
        self.assertEqual(getdate(fut.start_date), getdate(add_days(today(), 10)))
        self.assertEqual(getdate(fut.cancellation_date), getdate(add_days(today(), 300)))

        self.assertEqual(self._frequency_over(member, 10, 50), "Annual")
