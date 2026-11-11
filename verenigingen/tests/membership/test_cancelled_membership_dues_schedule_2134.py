"""#2134: cancelling a Membership cancels its dues schedule; a rejoin reuses it.

Membership.on_cancel used to PAUSE the schedule. A Paused schedule still blocked the next Membership's
schedule, so the rejoining member had none. Maintainer ruling (2026-11-11): a docstatus-2 cancel and an
End-of-Period cancellation CANCEL the schedule; the next Membership REUSES it (#1741 model: reactivate,
new template and amount, re-anchor on the rejoin date, the gap never billed); a patch moves the
cancel-paused leftovers to Cancelled.

Real flow: submit a Membership (its on_submit makes the schedule), cancel() it, submit a second one.
Stated shortcuts:
- the End-of-Period test writes renewal_date directly (the job only finishes an EoP cancellation when the
  renewal date has been reached) and calls the job's per-membership body, because
  process_membership_statuses saves EVERY submitted Membership on the site;
- the patch fixtures reproduce the OLD on_cancel by pausing through the real pause API with the old note
  and then writing Membership.docstatus = 2 directly, since the code can no longer make that state.
"""

import frappe
from unittest import mock
from frappe.utils import add_days, add_months, getdate, now_datetime, today
from freezegun import freeze_time

from verenigingen.patches.v2_2 import cancel_schedules_paused_by_membership_cancel_2134 as patch
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.schedule_frequency_fixture import ScheduleFrequencyFixtureMixin
from verenigingen.verenigingen.doctype.membership import membership as membership_module


class TestCancelledMembershipDuesSchedule(ScheduleFrequencyFixtureMixin, VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.member = self._create_schedule_test_member("Cancel2134")

    # ---------------------------------------------------------------- helpers

    def _submit(self, frequency="Monthly", start_offset_days=-120):
        return self._submit_membership_via_template(
            self.member, frequency, frequency, start_date=add_days(today(), start_offset_days)
        )

    def _schedules(self):
        return frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "is_template": 0},
            fields=["name", "status", "membership", "billing_frequency", "template_reference"],
            order_by="creation asc",
        )

    def _only_schedule(self):
        schedules = self._schedules()
        self.assertEqual(len(schedules), 1, f"exactly one schedule expected, got {schedules}")
        return schedules[0]

    def _staff_cancel(self, membership):
        membership.reload()
        membership.flags.ignore_validate_update_after_submit = True
        # PROBE SHORTCUT: ignore_links, because a Membership that already has its dues invoice is
        # otherwise refused by Frappe's link check (staff cancel the invoice first or force it).
        membership.flags.ignore_links = True
        membership.cancel()

    # ------------------------------------------------------ on_cancel (rule 1)

    def test_a_staff_cancel_cancels_the_schedule_instead_of_pausing_it(self):
        membership = self._submit()
        self.assertEqual(self._only_schedule().status, "Active", "precondition")

        self._staff_cancel(membership)

        self.assertEqual(frappe.db.get_value("Membership", membership.name, "docstatus"), 2)
        self.assertEqual(self._only_schedule().status, "Cancelled")

    # ------------------------------------------------------- rejoin (rule 2)

    def test_a_rejoin_after_a_staff_cancel_reuses_the_schedule_and_never_bills_the_gap(self):
        # The first membership and its invoice happen 200 days ago (an invoice is dated by the clock).
        with freeze_time(add_days(today(), -200)):
            first = self._submit("Quarterly", 0)
            schedule = frappe.get_doc("Membership Dues Schedule", self._only_schedule().name)
            old_invoice = schedule.generate_invoice()
        self.assertIsNotNone(old_invoice, "precondition: the first membership was invoiced")
        old_coverage_end = getdate(old_invoice.custom_coverage_end_date)
        self._staff_cancel(first)

        second = self._submit_membership_via_template(self.member, "Monthly", "Monthly", start_date=today())

        reused = self._only_schedule()
        self.assertEqual(reused.name, schedule.name, "the schedule is reused, not duplicated")
        self.assertEqual(reused.status, "Active")
        self.assertEqual(reused.membership, second.name)
        self.assertEqual(reused.billing_frequency, "Monthly", "the new template is applied")
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", reused.name, "membership_type"),
            second.membership_type,
            "the new Membership's type, or invoicing refuses the schedule",
        )
        self.assertEqual(
            reused.template_reference,
            frappe.db.get_value(
                "Membership Dues Schedule",
                {"is_template": 1, "membership_type": second.membership_type},
                "name",
            ),
        )
        reused_doc = frappe.get_doc("Membership Dues Schedule", reused.name)
        self.assertEqual(getdate(reused_doc.coverage_anchor_date), getdate(second.start_date))
        self.assertEqual(getdate(reused_doc.next_invoice_date), getdate(add_months(second.start_date, 1)))
        self.assertIsNone(reused_doc.last_invoice_coverage_end)
        self.assertEqual(
            frappe.db.get_value("Member", self.member.name, "current_dues_schedule"), reused.name
        )

        self.assertGreater((getdate(second.start_date) - old_coverage_end).days, 30, "precondition: a gap")
        invoice = reused_doc.generate_invoice()
        self.assertIsNotNone(invoice, "the rejoiner is invoiced")
        self.assertEqual(getdate(invoice.custom_coverage_start_date), getdate(second.start_date))

    def test_a_schedule_that_a_termination_other_than_voluntary_cancelled_is_not_reused(self):
        """Control: the reuse rule is not 'any Cancelled schedule' (the #1741 gate stays)."""
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        membership = self._submit()
        schedule_name = self._only_schedule().name
        self._staff_cancel(membership)
        service = get_dues_schedule_lifecycle_service()
        self.assertTrue(service.is_reusable_for_rejoin(self.member.name, schedule_name), "precondition")

        termination = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.member.name,
                "termination_type": "Policy Violation",
                "termination_date": today(),
            }
        )
        termination.flags.ignore_mandatory = True
        termination.flags.ignore_validate = True
        termination.insert()
        # PROBE SHORTCUT: the status is written, not reached through the approval workflow.
        frappe.db.set_value("Membership Termination Request", termination.name, "status", "Executed")
        self.track_doc("Membership Termination Request", termination.name)

        self.assertFalse(service.is_reusable_for_rejoin(self.member.name, schedule_name))

    def test_a_schedule_cancelled_while_its_membership_lives_is_not_reused(self):
        """Control: schedule maintenance cancels a schedule of a LIVE Membership; that stays cancelled."""
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        self._submit()
        schedule_name = self._only_schedule().name
        service = get_dues_schedule_lifecycle_service()
        service.cancel_schedule(frappe.get_doc("Membership Dues Schedule", schedule_name), reason="admin")

        self.assertFalse(service.is_reusable_for_rejoin(self.member.name, schedule_name))
        self.assertIsNone(service.find_reusable_cancelled_schedule(self.member.name))

    # --------------------------------------------- End of Period (rule 3)

    def test_an_end_of_period_cancellation_cancels_the_schedule_when_the_period_is_reached(self):
        membership = self._submit()
        membership.reload()
        membership.cancellation_date = today()
        membership.cancellation_type = "End of Period"
        membership.flags.ignore_validate_update_after_submit = True
        membership.save()
        # PROBE SHORTCUT: the job finishes an EoP cancellation on the renewal date itself.
        frappe.db.set_value("Membership", membership.name, "renewal_date", today())
        self.assertEqual(self._only_schedule().status, "Active", "precondition: not cancelled yet")

        membership_module._process_membership_status(membership.name, getdate(today()))

        self.assertEqual(frappe.db.get_value("Membership", membership.name, "status"), "Cancelled")
        self.assertEqual(self._only_schedule().status, "Cancelled")

    def test_an_end_of_period_cancellation_reached_after_the_renewal_date_also_cancels_the_schedule(self):
        """The job's first branch (past the renewal date) marks the membership Expired; the schedule
        of an End-of-Period cancellation must stop there too."""
        membership = self._submit()
        membership.reload()
        membership.cancellation_date = today()
        membership.cancellation_type = "End of Period"
        membership.flags.ignore_validate_update_after_submit = True
        membership.save()
        # PROBE SHORTCUT: renewal date already past.
        frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), -3))

        membership_module._process_membership_status(membership.name, getdate(today()))

        self.assertEqual(frappe.db.get_value("Membership", membership.name, "status"), "Expired")
        self.assertEqual(self._only_schedule().status, "Cancelled")

    def test_the_expiry_scheduler_also_cancels_the_schedule_of_an_end_of_period_cancellation(self):
        """scheduler.process_expired_memberships marks an Active past-renewal membership Expired before
        the status job sees it; the schedule of an End-of-Period cancellation must stop there too."""
        from verenigingen.verenigingen.doctype.membership import scheduler

        membership = self._submit()
        membership.reload()
        membership.cancellation_date = today()
        membership.cancellation_type = "End of Period"
        membership.flags.ignore_validate_update_after_submit = True
        membership.save()
        # PROBE SHORTCUT: renewal date already past.
        frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), -3))

        scheduler._process_expired_memberships_impl()

        self.assertEqual(frappe.db.get_value("Membership", membership.name, "status"), "Expired")
        self.assertEqual(self._only_schedule().status, "Cancelled")

    def test_an_expiry_without_an_end_of_period_cancellation_leaves_the_schedule_alone(self):
        """Control: ordinary expiry is the billing system's business, not a cancellation."""
        membership = self._submit()
        # PROBE SHORTCUT: renewal date already past.
        frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), -3))

        membership_module._process_membership_status(membership.name, getdate(today()))

        self.assertEqual(frappe.db.get_value("Membership", membership.name, "status"), "Expired")
        self.assertEqual(self._only_schedule().status, "Active")

    # ----------------------------------------------------------- patch (rule 4)

    def _old_style_cancel_paused(self, membership):
        """What the old on_cancel left: Paused by the old note, its Membership docstatus 2."""
        schedule = frappe.get_doc("Membership Dues Schedule", self._only_schedule().name)
        schedule.pause_schedule(f"Membership {membership.name} cancelled on {today()}")
        frappe.db.set_value("Membership", membership.name, "docstatus", 2)
        return schedule.name

    def test_the_patch_cancels_a_schedule_left_paused_by_a_membership_cancel(self):
        membership = self._submit()
        schedule_name = self._old_style_cancel_paused(membership)
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule_name, "status"), "Paused")

        patch.execute()

        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule_name, "status"), "Cancelled")

    def test_the_patch_leaves_a_schedule_paused_for_another_reason_alone(self):
        """Control, both halves of the discriminator. (a) paused by staff, its Membership docstatus 2
        for an unrelated reason; (c) a different "cancelled on" pause reason, Membership docstatus 2;
        (b) carries the cancel note but its Membership is still live."""
        membership = self._submit()
        schedule = frappe.get_doc("Membership Dues Schedule", self._only_schedule().name)
        schedule.pause_schedule("Member requested pause")
        frappe.db.set_value("Membership", membership.name, "docstatus", 2)
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"), "Paused")

        patch.execute()
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"), "Paused", "(a)"
        )

        # (c) a pause reason that also says "cancelled on" but is not this Membership's cancel note.
        schedule.reload()
        schedule.db_set("notes", f"Paused on {today()}: SEPA mandate cancelled on {today()}")
        patch.execute()
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"), "Paused", "(c)"
        )

        frappe.db.set_value("Membership", membership.name, "docstatus", 1)
        schedule.reload()
        schedule.notes = f"Paused on {today()}: Membership {membership.name} cancelled on {today()}"
        schedule.db_set("notes", schedule.notes)
        patch.execute()
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"), "Paused", "(b)"
        )

    def test_the_patch_is_idempotent(self):
        membership = self._submit()
        schedule_name = self._old_style_cancel_paused(membership)
        patch.execute()
        notes = frappe.db.get_value("Membership Dues Schedule", schedule_name, "notes")
        patch.execute()
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule_name, "notes"), notes)

    def test_the_patch_is_registered_as_a_fragment(self):
        from frappe.modules import patch_handler

        from verenigingen.setup import patch_fragments

        patch_fragments.install()
        self.assertIn(
            "verenigingen.patches.v2_2.cancel_schedules_paused_by_membership_cancel_2134",
            patch_handler.get_patches_from_app("verenigingen"),
        )

    # ------------------------------------------- review round: clause-by-clause pins

    def _insert_schedule(self, membership, status):
        """A second schedule row for the member. PROBE SHORTCUT: a direct amendment-style insert,
        because the real flows no longer leave two schedules behind."""
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"R2134 {frappe.generate_hash(length=6)}",
                "member": self.member.name,
                "membership": membership.name,
                "membership_type": membership.membership_type,
                "contribution_mode": "Fixed",
                "dues_rate": 20,
                "billing_frequency": "Monthly",
                "status": status,
                "auto_generate": 1,
                "next_invoice_date": today(),
            }
        )
        schedule.flags.from_amendment = True
        schedule.insert()
        return schedule

    def _cancelled_name(self):
        return frappe.db.get_value(
            "Membership Dues Schedule", {"member": self.member.name, "status": "Cancelled"}, "name"
        )

    def _service(self):
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )

        return get_dues_schedule_lifecycle_service()

    def test_cancelling_the_last_membership_cancels_a_live_schedule_linked_to_an_older_one(self):
        """Member-wide: M1 Expired, its Active schedule still linked to M1 (M2's submit only re-types it).
        Cancelling M2 must stop that schedule, though it is not linked to M2."""
        first = self._submit("Monthly", -300)
        # PROBE SHORTCUT: M1 expired by a direct write.
        frappe.db.set_value("Membership", first.name, "status", "Expired")
        second = self._submit("Monthly", 0)
        schedule = self._only_schedule()
        self.assertEqual((schedule.status, schedule.membership), ("Active", first.name), "precondition")

        self._staff_cancel(second)

        self.assertEqual(self._only_schedule().status, "Cancelled")

    def test_cancelling_a_membership_leaves_the_schedule_while_another_live_membership_exists(self):
        """Control: M1 is still live (Active, its renewal date behind M2's start so they do not overlap)."""
        first = self._submit("Monthly", -300)
        # PROBE SHORTCUT: renewal date moved so the two periods do not overlap.
        frappe.db.set_value("Membership", first.name, "renewal_date", add_days(today(), -100))
        # The sanctioned override for a second live membership (the "Create Anyway" action).
        frappe.flags.allow_multiple_memberships = True
        try:
            second = self._submit("Monthly", 0)
        finally:
            frappe.flags.allow_multiple_memberships = False
        schedule = self._only_schedule()
        self.assertEqual((schedule.status, schedule.membership), ("Active", first.name), "precondition")

        self._staff_cancel(second)

        self.assertEqual(self._only_schedule().status, "Active")

    def test_a_rejoin_after_an_immediate_cancel_membership_reuses_the_schedule(self):
        """Only the status == Cancelled clause of the reuse rule (docstatus stays 1)."""
        first = self._submit("Monthly", -300)
        membership_module.cancel_membership(first.name, today(), "test", "Immediate")
        self.assertEqual(frappe.db.get_value("Membership", first.name, "docstatus"), 1, "precondition")
        schedule = self._only_schedule()
        self.assertEqual(schedule.status, "Cancelled", "precondition")

        second = self._submit("Monthly", 0)

        reused = self._only_schedule()
        self.assertEqual((reused.name, reused.status, reused.membership), (schedule.name, "Active", second.name))

    def test_a_rejoin_after_an_end_of_period_cancellation_reuses_the_schedule(self):
        """Only the Expired + End-of-Period clause: the membership is neither docstatus 2 nor Cancelled."""
        first = self._submit("Monthly", -300)
        first.reload()
        first.cancellation_date = today()
        first.cancellation_type = "End of Period"
        first.flags.ignore_validate_update_after_submit = True
        first.save()
        # PROBE SHORTCUT: renewal date already past.
        frappe.db.set_value("Membership", first.name, "renewal_date", add_days(today(), -100))
        membership_module._process_membership_status(first.name, getdate(today()))
        self.assertEqual(frappe.db.get_value("Membership", first.name, "status"), "Expired", "precondition")
        schedule = self._only_schedule()
        self.assertEqual(schedule.status, "Cancelled", "precondition")

        second = self._submit("Monthly", 0)

        reused = self._only_schedule()
        self.assertEqual((reused.name, reused.status, reused.membership), (schedule.name, "Active", second.name))

    def test_a_plain_expiry_is_not_a_reason_to_reuse_a_cancelled_schedule(self):
        """Control for the clause above: Expired WITHOUT an End-of-Period cancellation."""
        first = self._submit("Monthly", -300)
        schedule_name = self._only_schedule().name
        self._service().cancel_schedule(frappe.get_doc("Membership Dues Schedule", schedule_name), "admin")
        frappe.db.set_value("Membership", first.name, "status", "Expired")

        self.assertFalse(self._service().is_reusable_for_rejoin(self.member.name, schedule_name))

    def test_no_reuse_while_the_member_also_has_a_non_cancelled_schedule(self):
        first = self._submit("Monthly", -300)
        self._staff_cancel(first)
        self.assertIsNotNone(self._service().find_reusable_cancelled_schedule(self.member.name), "precondition")
        self._insert_schedule(first, "Paused")
        # PROBE SHORTCUT: the Cancelled schedule is made the LATEST, so only the all-Cancelled guard
        # (not the "latest is Cancelled" check) can refuse.
        frappe.db.set_value(
            "Membership Dues Schedule", self._cancelled_name(), "modified", add_days(now_datetime(), 1)
        )

        self.assertIsNone(self._service().find_reusable_cancelled_schedule(self.member.name))

    def test_with_two_cancelled_schedules_the_latest_is_the_one_reused(self):
        first = self._submit("Monthly", -300)
        self._staff_cancel(first)
        older = self._only_schedule().name
        newer = self._insert_schedule(first, "Cancelled").name
        self.assertNotEqual(older, newer)

        self.assertEqual(self._service().find_reusable_cancelled_schedule(self.member.name), newer)

    # ------------------------------------------ scheduler failure is visible (N3)

    def test_a_failing_end_of_period_cancel_is_logged_and_the_batch_continues(self):
        other = self._create_schedule_test_member("Cancel2134b")
        failing = self._submit("Monthly", -300)
        working = self._submit_membership_via_template(
            other, "Monthly", "Monthly", start_date=add_days(today(), -300)
        )
        for membership in (failing, working):
            membership.reload()
            membership.cancellation_date = today()
            membership.cancellation_type = "End of Period"
            membership.flags.ignore_validate_update_after_submit = True
            membership.save()
            # PROBE SHORTCUT: renewal date already past.
            frappe.db.set_value("Membership", membership.name, "renewal_date", add_days(today(), -3))
        real = membership_module.cancel_dues_schedule_if_end_of_period_cancelled

        def fail_for_one(membership):
            if membership.name == failing.name:
                raise frappe.ValidationError("probe: cancel refused")
            return real(membership)

        from verenigingen.verenigingen.doctype.membership import scheduler

        # Error Log is non-transactional and names are reused after a rollback: count the delta.
        logged_before = frappe.db.count("Error Log", {"method": ["like", f"%{failing.name}%"]})

        # Mock justified: fault injection. A schedule that cannot be cancelled cannot be built on demand.
        with mock.patch.object(
            membership_module, "cancel_dues_schedule_if_end_of_period_cancelled", fail_for_one
        ):
            scheduler._process_expired_memberships_impl()

        self.assertEqual(frappe.db.get_value("Membership", working.name, "status"), "Expired")
        self.assertEqual(frappe.db.get_value("Membership", failing.name, "status"), "Active")
        logged = frappe.db.count("Error Log", {"method": ["like", f"%{failing.name}%"]})
        self.assertEqual(logged - logged_before, 1, "the stuck membership leaves an Error Log row")
