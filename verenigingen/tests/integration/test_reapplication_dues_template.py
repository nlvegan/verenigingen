# -*- coding: utf-8 -*-
"""
#1730: a reapplying Member must be approved on the template and amount of the
reapplication, not on the ones from the earlier application.

Everything is driven through the REAL flow: submit_application -> the emailed confirm link ->
approve_application (a new Member), a real voluntary termination (Quit), then submit_application
(same email) -> confirm -> approve_application again. Nothing is seeded with db_set; the expected
template and rate are read from the fixtures the test creates.

Since #1765 an application is its own record: a REJECTED application never leaves a Member behind, so
the old "reject, then reapply" route to a reapplying Member (and the Pending Member updated before
review) no longer exists. The Member a reapplication updates is a voluntarily-Quit one. Where the subject
is the Member BEFORE approval (what the reapplication wrote onto it), materialise_member is called on the
confirmed application, because approve_application would carry the member on to Active.
"""

import frappe
from frappe.utils import add_days, add_months, flt, getdate, today
from freezegun import freeze_time

from verenigingen.services.member.application.application_materialiser import materialise_member
from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase


class TestReapplicationDuesTemplate(ApprovalCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.default_template = frappe.get_doc(
            "Membership Dues Schedule", self.membership_type.dues_schedule_template
        )
        self.minimum = flt(self.membership_type.minimum_amount or 0)
        # Two templates of DIFFERENT frequency and rate for the same type.
        self.monthly_template = self._template(f"Reapp Monthly {run}", "Monthly", self.minimum + 11)
        self.annual_template = self._template(f"Reapp Annual {run}", "Annual", self.minimum + 123)

    def _template(self, name, frequency, rate):
        return self.ensure_dues_schedule_template(
            name,
            {
                "billing_frequency": frequency,
                "dues_rate": rate,
                "suggested_amount": rate,
                "minimum_amount": self.minimum,
                "membership_type": self.membership_type.name,
                "contribution_mode": "Fixed",
            },
        )

    # -- real-flow helpers -------------------------------------------------

    def _apply_for_membership(self, email, template=None, amount=None):
        """Submit the full form as Guest and follow the emailed link; returns the application's name."""
        overrides = {"email": email}
        if template:
            overrides["selected_dues_schedule"] = template.name
        if amount is not None:
            overrides["custom_contribution_fee"] = amount
            overrides["uses_custom_amount"] = 1
        return self._stage_and_confirm(**overrides)

    def _approve_for_schedule(self, application):
        """approve_application as an administrator; returns the Member's non-template dues schedule row."""
        result = self._approve_as(
            application,
            membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            notes="reapplication test",
        )
        self.assertTrue(result.get("success"), f"Approval failed: {result}")
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": result["member"], "is_template": 0},
            ["name", "template_reference", "billing_frequency", "dues_rate"],
            as_dict=True,
        )

    def _member_of(self, application):
        return frappe.db.get_value(SUBMISSION, application, "member")

    def _approved_member(self, email, template=None, amount=None):
        application = self._apply_for_membership(email, template, amount)
        self._approve_for_schedule(application)
        return self._member_of(application)

    def _fresh_email(self):
        return f"reapp-{frappe.generate_hash(length=8)}@example.com"

    # -- tests --------------------------------------------------------------

    def test_a_second_application_before_review_uses_the_latest_choice(self):
        """The applicant applies again while the first is still waiting: the older application is
        superseded and approval uses the latest choice (Monthly + amount, then Annual and no amount)."""
        email = self._fresh_email()
        older = self._apply_for_membership(email, self.monthly_template, self.minimum + 7.5)
        newer = self._apply_for_membership(email, self.annual_template, None)
        self.assertEqual(frappe.db.get_value(SUBMISSION, older, "status"), "Superseded")

        schedule = self._approve_for_schedule(newer)

        self.assertEqual(frappe.db.count("Member", {"email": email}), 1)
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(self.annual_template.dues_rate))

    def test_voluntary_quit_reapplication_records_the_new_template_on_the_member(self):
        """Narrow on purpose: only Member.application_dues_schedule, after a voluntary Quit.

        What approval then does with the reused schedule is pinned by the test_quit_rejoiner_* tests
        below (#1737, #1741). materialise_member is called on the confirmed application because the
        subject is what the reapplication wrote onto the Member BEFORE approval.
        PROBE SHORTCUT: the Membership's commitment_end_date is backdated so a genuine past-dated
        termination can run; the termination and reapplication are real.
        """
        email = self._fresh_email()
        member = self._approved_member(email, self.monthly_template, None)
        self._quit(member)

        application = self._apply_for_membership(email, self.annual_template, None)
        materialise_member(frappe.get_doc(SUBMISSION, application))

        self.assertEqual(
            frappe.db.get_value("Member", member, "application_dues_schedule"), self.annual_template.name
        )

    # -- voluntary-Quit rejoiner (#1741, #1737) ----------------------------

    def _quit(self, member, termination_date=None):
        """Run a REAL voluntary termination (status Executed) on an approved ``member``.

        PROBE SHORTCUT: only the Membership's commitment_end_date is backdated, so a
        genuine past-dated termination is allowed. The termination itself, and every
        status it leaves behind, is written by TerminationExecutionService.
        """
        from verenigingen.tests.support.termination_request import execute_real_termination

        termination_date = termination_date or add_days(today(), -30)
        old_membership = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", old_membership, "commitment_end_date", add_days(termination_date, -30))
        request = execute_real_termination(self, member, termination_date)
        self.assertEqual(request.status, "Executed")
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")
        return old_membership

    def _quit_and_rejoin(self, first, second):
        """first/second are (template, amount); returns (member, old_schedule, old_membership, rejoin_application)."""
        email = self._fresh_email()
        member = self._approved_member(email, *first)
        old_membership = self._quit(member)
        old_schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member, "is_template": 0}, "name"
        )
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", old_schedule, "status"),
            "Cancelled",
            "precondition: the real termination cancelled the schedule",
        )
        return member, old_schedule, old_membership, self._apply_for_membership(email, *second)

    def _schedules(self, member):
        return frappe.get_all(
            "Membership Dues Schedule", filters={"member": member, "is_template": 0}, pluck="name"
        )

    def test_quit_rejoiner_reuses_and_reactivates_the_schedule_on_a_new_membership(self):
        member, old_schedule, old_membership, rejoin = self._quit_and_rejoin(
            (self.monthly_template, None), (self.annual_template, None)
        )
        self._approve_for_schedule(rejoin)

        self.assertEqual(self._member_of(rejoin), member, "the rejoin updates the same Member")
        self.assertEqual(self._schedules(member), [old_schedule], "the earlier schedule is reused")
        schedule = frappe.get_doc("Membership Dues Schedule", old_schedule)
        self.assertEqual(schedule.status, "Active")
        new_membership = frappe.db.get_value("Member", member, "current_membership_plan")
        self.assertNotEqual(new_membership, old_membership, "a rejoiner gets a NEW Membership")
        self.assertTrue(frappe.db.exists("Membership", old_membership), "the old Membership is kept")
        self.assertEqual(schedule.membership, new_membership)
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")

    def test_quit_rejoiner_with_other_template_and_no_amount_uses_the_new_template(self):
        """Monthly template + custom amount first, Annual template and NO amount on the rejoin."""
        old_amount = self.minimum + 7.5
        _, old_schedule, _, rejoin = self._quit_and_rejoin(
            (self.monthly_template, old_amount), (self.annual_template, None)
        )
        schedule = self._approve_for_schedule(rejoin)
        self.assertEqual(schedule.name, old_schedule)
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(self.annual_template.dues_rate))
        self.assertNotEqual(flt(schedule.dues_rate), flt(old_amount))

    def test_quit_rejoiner_is_approved_on_the_new_template_and_chosen_amount(self):
        chosen = self.minimum + 200.25
        _, old_schedule, _, rejoin = self._quit_and_rejoin(
            (self.monthly_template, self.minimum + 7.5), (self.annual_template, chosen)
        )
        schedule = self._approve_for_schedule(rejoin)
        self.assertEqual(schedule.name, old_schedule)
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(schedule.billing_frequency, "Annual")
        self.assertEqual(flt(schedule.dues_rate), flt(chosen), "the applicant's amount, not the template's")
        self.assertNotEqual(flt(chosen), flt(self.annual_template.dues_rate))

    def test_quit_rejoiner_with_same_template_and_new_amount_gets_the_new_amount(self):
        """The template is unchanged, so only the amount can differ: the #1737 core case."""
        chosen = self.minimum + 33.5
        _, _, _, rejoin = self._quit_and_rejoin(
            (self.monthly_template, self.minimum + 7.5), (self.monthly_template, chosen)
        )
        self.assertEqual(flt(self._approve_for_schedule(rejoin).dues_rate), flt(chosen))

    def test_quit_rejoiner_picking_nothing_gets_the_type_default_template(self):
        """A reapplication that picks nothing must not inherit the earlier template or fee."""
        old_amount = self.minimum + 7.5
        member, _, _, rejoin = self._quit_and_rejoin((self.monthly_template, old_amount), (None, None))
        schedule = self._approve_for_schedule(rejoin)
        self.assertNotEqual(schedule.template_reference, self.monthly_template.name)
        self.assertEqual(schedule.template_reference, self.default_template.name)
        self.assertNotEqual(flt(schedule.dues_rate), flt(old_amount))
        self.assertEqual(flt(schedule.dues_rate), self._default_rate())
        self.assertEqual(frappe.db.get_value("Member", member, "application_dues_schedule"), None)
        self.assertFalse(frappe.db.get_value("Member", member, "application_custom_fee"))

    def test_quit_rejoiner_picking_nothing_is_not_pinned_to_the_earlier_templates_rate(self):
        """Member.dues_rate mirrors the earlier schedule (here the Monthly template's rate) but
        is no choice: the rejoiner who picks nothing gets the default template's own rate."""
        member, _, _, rejoin = self._quit_and_rejoin((self.monthly_template, None), (None, None))
        mirrored = flt(frappe.db.get_value("Member", member, "dues_rate"))
        self.assertEqual(mirrored, flt(self.monthly_template.dues_rate), "precondition: stale mirror")
        self.assertNotEqual(mirrored, self._default_rate(), "precondition: the two rates differ")
        schedule = self._approve_for_schedule(rejoin)
        self.assertEqual(schedule.template_reference, self.default_template.name)
        self.assertEqual(flt(schedule.dues_rate), self._default_rate())

    def _default_rate(self):
        return flt(self.default_template.dues_rate or self.default_template.suggested_amount)

    def test_quit_rejoiner_is_billed_from_the_rejoin_not_for_the_months_away(self):
        """The gap is never caught up (#1741 point 3).

        Measured on develop (schedule forced Active by hand): the first invoice after the
        rejoin covered the month after the OLD coverage ended, 200 days earlier, because the
        coverage sequence chains onto the latest invoice, not onto next_invoice_date.
        The earlier membership, its invoice and the real termination happen 200 days in the
        past (freezegun); the reapplication and approval happen now.
        """
        email = self._fresh_email()
        with freeze_time(add_days(today(), -200)):
            member = self._approved_member(email, self.monthly_template, None)
            schedule_name = self._schedules(member)[0]
            first = frappe.get_doc("Membership Dues Schedule", schedule_name).generate_invoice()
        self.assertIsNotNone(first, "precondition: the first membership was invoiced")
        old_coverage_end = getdate(first.custom_coverage_end_date)
        # Terminated 10 days after that coverage ended, so termination keeps the invoice
        # (it cancels only invoices covering time after the termination date).
        self._quit(member, termination_date=add_days(old_coverage_end, 10))
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", first.name, "docstatus"),
            1,
            "precondition: the earlier invoice survives the termination",
        )
        self._approve_for_schedule(self._apply_for_membership(email, self.monthly_template, None))

        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        rejoin_start = getdate(frappe.db.get_value("Member", member, "member_since"))
        self.assertEqual(rejoin_start, getdate(today()))
        self.assertGreater((rejoin_start - old_coverage_end).days, 150, "precondition: a real gap")
        self.assertEqual(str(schedule.coverage_anchor_date), str(rejoin_start))
        self.assertEqual(getdate(schedule.next_invoice_date), getdate(add_months(rejoin_start, 1)))
        self.assertIsNone(schedule.last_invoice_coverage_end)

        invoice = schedule.generate_invoice()
        self.assertIsNotNone(invoice, "the rejoiner is invoiced")
        self.assertEqual(getdate(invoice.custom_coverage_start_date), rejoin_start)

    def test_a_schedule_cancelled_any_other_way_is_not_reactivated_by_approval(self):
        """Control: only a voluntary Quit's schedule is reused.

        UNIT-LEVEL: a lifecycle cancel_schedule() on an approved member's schedule stands in for
        schedule maintenance / an admin, and _ensure_dues_schedule_exists is called directly
        because an Active member cannot be re-approved through the real flow.
        """
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        member = self._approved_member(self._fresh_email(), self.monthly_template, None)
        schedule_name = self._schedules(member)[0]
        get_dues_schedule_lifecycle_service().cancel_schedule(
            frappe.get_doc("Membership Dues Schedule", schedule_name), reason="admin cleanup"
        )
        member_doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", member_doc.current_membership_plan)
        self.assertFalse(
            frappe.db.exists(
                "Membership Termination Request", {"member": member, "termination_type": "Voluntary"}
            ),
            "precondition: no voluntary termination for this member",
        )
        MembershipCreationService()._ensure_dues_schedule_exists(member_doc, membership, self.membership_type)
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", schedule_name, "status"), "Cancelled")

    def test_a_later_involuntary_termination_overrides_an_earlier_voluntary_one(self):
        """Control: the LATEST executed termination decides, as at the Quit reapplication gate.

        A real voluntary Quit leaves the schedule Cancelled. PROBE SHORTCUT: a second,
        Executed "Expulsion" request is then written directly (the member is already Quit, so
        the real executor cannot run again) with a later execution_date, and
        _ensure_dues_schedule_exists is called directly (UNIT-LEVEL) because the gate would
        refuse this member before approval; the new Membership is built by the service's own
        _create_new_membership rather than through approve_application.
        """
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        member = self._approved_member(self._fresh_email(), None, None)
        old_membership = self._quit(member)
        voluntary = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member, "status": "Executed", "termination_type": "Voluntary"},
            pluck="name",
        )
        self.assertEqual(len(voluntary), 1, "precondition: the real voluntary termination")
        later = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member,
                "termination_type": "Expulsion",
                "termination_reason": "later expulsion",
                "termination_date": today(),
                "requested_by": frappe.session.user,
                "request_date": today(),
                "status": "Executed",
            }
        )
        later.insert()
        self.track_doc("Membership Termination Request", later.name)
        frappe.db.set_value(
            "Membership Termination Request",
            later.name,
            {"status": "Executed", "execution_date": add_days(today(), 1)},
        )
        member_doc = frappe.get_doc("Member", member)
        service = MembershipCreationService()
        # The membership approval really passes: a fresh submitted one. Under an "any Voluntary
        # request" check the reactivation then SUCCEEDS, so the status assertion is what fails.
        membership = service._create_new_membership(member_doc, self.membership_type, today(), False)
        self.assertNotEqual(membership.name, old_membership)
        service._ensure_dues_schedule_exists(member_doc, membership, self.membership_type)
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", self._schedules(member)[0], "status"),
            "Cancelled",
        )

    def test_cancelled_to_active_is_still_refused_without_the_rejoin_flag(self):
        """Control: the rejoin flag is the only way out of Cancelled.

        UNIT-LEVEL: the transition validator is called directly on a real Cancelled schedule
        (a save() would stop earlier, on the member having no active membership).
        """
        from verenigingen.services.billing.dues_schedule_lifecycle_service import (
            get_dues_schedule_lifecycle_service,
        )
        from verenigingen.utils.exceptions import InvalidStatusTransitionError

        member = self._approved_member(self._fresh_email(), None, None)
        self._quit(member)
        name = self._schedules(member)[0]
        schedule = frappe.get_doc("Membership Dues Schedule", name)
        schedule._doc_before_save = frappe.get_doc("Membership Dues Schedule", name)
        schedule.status = "Active"
        service = get_dues_schedule_lifecycle_service()
        with self.assertRaises(InvalidStatusTransitionError):
            service.validate_status_transition(schedule)
        schedule.flags.rejoin_reactivation = True
        service.validate_status_transition(schedule)

    def test_a_template_change_on_a_live_schedule_keeps_the_chosen_amount(self):
        """#1737 on the non-rejoin path of the same branch.

        UNIT-LEVEL: member.application_dues_schedule and the fee fields are set by hand on an
        approved member's in-memory doc to reach the 'schedule exists, other template chosen' branch.
        """
        from verenigingen.services.member.approval.membership_creation_service import (
            MembershipCreationService,
        )

        chosen = self.minimum + 77.5
        member = self._approved_member(self._fresh_email(), self.monthly_template, None)
        member_doc = frappe.get_doc("Member", member)
        membership = frappe.get_doc("Membership", member_doc.current_membership_plan)
        member_doc.application_dues_schedule = self.annual_template.name
        member_doc.dues_rate = chosen
        member_doc.fee_override_reason = "Custom amount selected during application: test"
        MembershipCreationService()._ensure_dues_schedule_exists(member_doc, membership, self.membership_type)
        schedule = frappe.get_doc("Membership Dues Schedule", self._schedules(member)[0])
        self.assertEqual(schedule.template_reference, self.annual_template.name)
        self.assertEqual(flt(schedule.dues_rate), flt(chosen))

    def test_staff_override_on_the_member_survives_a_reapplication(self):
        """A fee override staff saved on the Member is not the application's: keep it.

        The Member is a voluntarily-Quit one (the only kind a reapplication updates since #1765).
        materialise_member is called on the confirmed application because the subject is what the
        reapplication writes onto the Member BEFORE approval.
        """
        email = self._fresh_email()
        member = self._approved_member(email, self.monthly_template, None)
        self._quit(member)
        staff_amount = self.minimum + 1
        with self.as_user(self.admin_user.email):
            doc = frappe.get_doc("Member", member)
            doc.dues_rate = staff_amount
            doc.fee_override_reason = "krappe beurs"
            doc.save()
        stored = frappe.db.get_value("Member", member, ["dues_rate", "fee_override_reason"], as_dict=True)
        self.assertEqual(flt(stored.dues_rate), flt(staff_amount), "precondition: staff save persisted")

        application = self._apply_for_membership(email, self.annual_template, None)
        materialise_member(frappe.get_doc(SUBMISSION, application))

        kept = frappe.db.get_value(
            "Member", member, ["dues_rate", "fee_override_reason", "application_dues_schedule"], as_dict=True
        )
        self.assertEqual(flt(kept.dues_rate), flt(staff_amount))
        self.assertEqual(kept.fee_override_reason, "krappe beurs")
        self.assertEqual(kept.application_dues_schedule, self.annual_template.name)
