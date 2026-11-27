# -*- coding: utf-8 -*-
"""
#3450: opt-in fixed-date billing periods for /word-lid door plans.

A door plan may say its billing periods start on one day of the year (`period_anchor` = Fixed date) and that
someone approved within `waive_final_months` before the next such day starts there with nothing billed
until then. Approval writes that day to the dues schedule's `coverage_anchor_date`, invoices the period from
it (past anchor) or invoices nothing yet (future anchor), and the scheduler is untouched.

Driven through the real flow: submit_short_application as Guest -> the confirm link -> approve_application
as staff -> the dues schedule's own generate_invoice for the scheduler's step. Dates are relative to the
site's `today()` (the bench is Asia/Kolkata, CI is UTC, so a literal calendar date would be a different
day on one of them); the anchor is never the real use case's (1 September). Probe shortcut, stated: the
failing invoice in the retry test is produced by pointing Verenigingen Settings at a company that does not
exist, as test_approval_without_invoice does.
"""

import unittest
from datetime import date

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.api import short_application as sa
from verenigingen.api.membership_application_review import retry_application_invoice
from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.services.billing.fixed_date_period_anchor import anchor_for_approval
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.tests.integration.test_application_record_approval import IBAN, SUBMISSION, ApprovalCase
from verenigingen.tests.utils.reminder_mail_state import ensure_outgoing_email_account
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token


class TestFixedDateAnchorRule(unittest.TestCase):
    """The pure rule, on explicit dates. An anchor of 1 April with a 2-month waiver."""

    def _anchor(self, approved, waive=2, month=4, day=1):
        return anchor_for_approval(month, day, waive, approved)

    def test_approved_mid_may_runs_from_the_april_just_gone(self):
        self.assertEqual(self._anchor(date(2031, 5, 15)), date(2031, 4, 1))

    def test_approved_in_the_waiver_window_runs_from_the_next_april(self):
        self.assertEqual(self._anchor(date(2031, 2, 14)), date(2031, 4, 1))
        self.assertEqual(self._anchor(date(2031, 3, 31)), date(2031, 4, 1))

    def test_the_window_opens_exactly_waive_months_before_the_anchor(self):
        self.assertEqual(self._anchor(date(2031, 2, 1)), date(2031, 4, 1))
        self.assertEqual(self._anchor(date(2031, 1, 31)), date(2030, 4, 1))

    def test_approved_on_the_anchor_is_the_current_period(self):
        self.assertEqual(self._anchor(date(2031, 4, 1)), date(2031, 4, 1))

    def test_no_waiver_runs_from_the_previous_anchor_even_the_day_before(self):
        self.assertEqual(self._anchor(date(2031, 2, 14), waive=0), date(2030, 4, 1))
        self.assertEqual(self._anchor(date(2031, 3, 31), waive=0), date(2030, 4, 1))

    def test_a_year_boundary_between_approval_and_anchor(self):
        # anchor 1 February, approved mid-December: the next anchor is in the new year
        self.assertEqual(self._anchor(date(2030, 12, 15), month=2), date(2031, 2, 1))
        self.assertEqual(self._anchor(date(2030, 12, 15), waive=1, month=2), date(2030, 2, 1))


class FixedDateCase(ApprovalCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)

    # -- fixtures --------------------------------------------------------------------------------

    def _anchor_in(self, days):
        """A date `days` from the site's today that is a real anchor in every year (never 29 February)."""
        anchor = getdate(add_days(today(), days))
        return add_days(anchor, 1) if (anchor.month, anchor.day) == (2, 29) else anchor

    def _fixed_plan_row(self, template, anchor, waive=2, is_default=1):
        return {
            "dues_template": template,
            "is_default": is_default,
            "period_anchor": "Fixed date",
            "anchor_month": anchor.month,
            "anchor_day": anchor.day,
            "waive_final_months": waive,
        }

    def _fixed_door(self, anchor, waive=2, frequency="Annual"):
        """(door, template) of a door with ONE Fixed date plan anchored on `anchor`'s month and day."""
        rate = (self.membership_type.minimum_amount or 0) + 41
        template = self._plan_template(frequency, mode="Fixed", dues_rate=rate, minimum_amount=0)
        door = self._door(plans=[self._fixed_plan_row(template, anchor, waive)])
        return door, template

    def _stage_fixed_plan(self, door, template, **overrides):
        plan = frappe.db.get_value(
            "Membership Application Door Plan", {"parent": door.name, "dues_template": template}, "name"
        )
        rate = frappe.db.get_value("Membership Dues Schedule", template, "dues_rate")
        data = {
            "first_name": "Anna",
            "last_name": f"Berg{frappe.generate_hash(length=8)}",  # a Customer per applicant: coverage is read by customer
            "email": self.email,
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "city": f"Nergenshuizen-{frappe.generate_hash(length=6)}",
            "country": "Netherlands",
            "plan": plan,
            "amount": str(rate),
            "iban": IBAN,
            "bank_account_name": "A. Berg",
            "consent": "1",
            "leave_this_empty": "",
            "magazine_delivery": "Geen",
            "starter_guide_delivery": "Geen",
        }
        data.update(overrides)
        previous = frappe.session.user
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door.name, **data)
        finally:
            frappe.set_user(previous)
        self.assertTrue(response["success"], response)
        name = frappe.get_all(SUBMISSION, {"email": self.email, "status": "Unconfirmed"}, pluck="name")[0]
        self.track_doc(SUBMISSION, name)
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            confirmed = sa.confirm_short_application(name, token)
        finally:
            frappe.set_user(previous)
        self.assertTrue(confirmed["success"], confirmed)
        return name

    def _approve_fixed(self, application, create_invoice=True):
        return self._approve_as(
            application,
            membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            create_invoice=create_invoice,
        )

    def _apply_and_approve(self, door, template, **approve):
        application = self._stage_fixed_plan(door, template)
        return application, self._approve_fixed(application, **approve)

    def _fixed_schedule(self, member):
        return frappe.get_doc(
            "Membership Dues Schedule",
            frappe.db.get_value(
                "Membership Dues Schedule", {"member": member, "is_template": 0, "status": "Active"}, "name"
            ),
        )

    def _fixed_invoices(self, member):
        # By the invoice's own member link (the applicants' names are unique, so are their customers).
        return frappe.get_all(
            "Sales Invoice",
            {"member": member, "docstatus": 1},
            ["name", "custom_coverage_start_date", "custom_coverage_end_date"],
            order_by="custom_coverage_start_date asc",
        )

    def _one_period_from(self, start):
        return add_days(add_months(getdate(start), 12), -1)


class TestFixedDateApproval(FixedDateCase):
    def test_approved_after_the_anchor_is_invoiced_one_full_period_from_it(self):
        anchor = self._anchor_in(-45)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        self.assertFalse(result["invoice_failed"], result)
        [invoice] = self._fixed_invoices(result["member"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), anchor)
        self.assertEqual(getdate(invoice.custom_coverage_end_date), self._one_period_from(anchor))
        schedule = self._fixed_schedule(result["member"])
        self.assertEqual(getdate(schedule.coverage_anchor_date), anchor)
        self.assertEqual(frappe.db.get_value("Member", result["member"], "status"), "Active")

    def test_an_anchor_in_the_past_leaves_the_renewal_date_at_a_year_from_approval(self):
        """Control for the renewal date: a past anchor must not move it (a year from approval already lies
        beyond the period the invoice paid for)."""
        anchor = self._anchor_in(-45)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        membership = frappe.get_doc("Membership", frappe.db.get_value("Member", result["member"], "current_membership_plan"))
        self.assertEqual(getdate(membership.renewal_date), getdate(add_months(membership.start_date, 12)))

    def test_approved_before_the_next_anchor_within_the_waiver_bills_nothing_yet(self):
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor, waive=2)

        application, result = self._apply_and_approve(door, template)

        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], "no invoice was due, so nothing failed")
        self.assertIsNone(result["invoice"])
        self.assertEqual(self._fixed_invoices(result["member"]), [])
        self.assertFalse(frappe.db.get_value(SUBMISSION, application, "invoice_failed_on"), "no retry marker")
        schedule = self._fixed_schedule(result["member"])
        self.assertEqual(getdate(schedule.coverage_anchor_date), anchor)
        self.assertEqual(getdate(schedule.next_invoice_date), anchor)

    def test_the_member_waiting_for_the_anchor_is_active_and_eligible_not_unpaid(self):
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        member = frappe.get_doc("Member", result["member"])
        membership = frappe.get_doc("Membership", member.current_membership_plan)
        self.assertEqual((member.status, membership.status), ("Active", "Active"))
        self.assertEqual(self._fixed_invoices(member.name), [], "no invoice, so nothing to be unpaid")
        self.assertTrue(self._fixed_schedule(result["member"]).validate_member_eligibility_for_invoice())

    def test_the_renewal_date_follows_the_anchor_when_billing_starts_later(self):
        """renewal_date drives the expiry job and the renewal reminders: a year after APPROVAL would end
        the membership before the period that starts at the anchor is over."""
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        membership = frappe.get_doc("Membership", frappe.db.get_value("Member", result["member"], "current_membership_plan"))
        self.assertEqual(getdate(membership.renewal_date), getdate(add_months(anchor, 12)))

    def test_the_scheduler_waits_for_the_anchor_then_invoices_the_period_that_begins_there(self):
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor)
        _application, result = self._apply_and_approve(door, template)
        schedule = self._fixed_schedule(result["member"])

        self.assertFalse(schedule.should_generate_for_cutoff_period(add_days(anchor, -1)), "cutoff before the anchor")
        self.assertTrue(schedule.should_generate_for_cutoff_period(add_days(anchor, 30)), "cutoff past the anchor")
        invoice = schedule.generate_invoice()
        self.track_doc("Sales Invoice", invoice.name)

        self.assertEqual(getdate(invoice.custom_coverage_start_date), anchor, "never the weeks before it")
        self.assertEqual(getdate(invoice.custom_coverage_end_date), self._one_period_from(anchor))
        for row in self._fixed_invoices(result["member"]):
            self.assertGreaterEqual(getdate(row.custom_coverage_start_date), anchor)

    def test_the_next_period_chains_on_from_the_anchor_period(self):
        anchor = self._anchor_in(-45)
        door, template = self._fixed_door(anchor)
        _application, result = self._apply_and_approve(door, template)
        schedule = self._fixed_schedule(result["member"])
        member = frappe.get_doc("Member", result["member"])

        period = CoverageCalculator(schedule).calculate_next_coverage_period(member)

        self.assertTrue(period.success, period)
        self.assertEqual(getdate(period.data.start_date), add_days(self._one_period_from(anchor), 1))

    def test_approved_on_the_anchor_is_the_current_period_invoiced_now(self):
        anchor = self._anchor_in(0)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        [invoice] = self._fixed_invoices(result["member"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), anchor)
        self.assertEqual(getdate(invoice.custom_coverage_start_date), getdate(today()))

    def test_approved_the_day_before_the_anchor_bills_nothing_yet(self):
        anchor = self._anchor_in(1)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        self.assertEqual(self._fixed_invoices(result["member"]), [])
        self.assertEqual(getdate(self._fixed_schedule(result["member"]).coverage_anchor_date), anchor)

    def test_without_a_waiver_the_member_is_invoiced_from_the_previous_anchor(self):
        next_anchor = self._anchor_in(45)
        previous = getdate(add_months(next_anchor, -12))
        door, template = self._fixed_door(next_anchor, waive=0)

        _application, result = self._apply_and_approve(door, template)

        [invoice] = self._fixed_invoices(result["member"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), previous)
        self.assertEqual(getdate(invoice.custom_coverage_end_date), add_days(next_anchor, -1))

    def test_a_join_date_plan_is_unchanged(self):
        """Regression: no anchor, the invoice starts today, the renewal date is a year from approval."""
        rate = (self.membership_type.minimum_amount or 0) + 41
        template = self._plan_template("Annual", mode="Fixed", dues_rate=rate, minimum_amount=0)
        door = self._door(plans=[{"dues_template": template, "is_default": 1}])

        _application, result = self._apply_and_approve(door, template)

        [invoice] = self._fixed_invoices(result["member"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), getdate(today()))
        self.assertFalse(self._fixed_schedule(result["member"]).coverage_anchor_date)
        membership = frappe.get_doc("Membership", frappe.db.get_value("Member", result["member"], "current_membership_plan"))
        self.assertEqual(getdate(membership.renewal_date), getdate(add_months(membership.start_date, 12)))

    def test_a_join_date_plan_beside_a_fixed_one_on_the_same_door_gets_no_anchor(self):
        """Control: the anchor belongs to the plan the applicant chose, not to any plan of the door."""
        anchor = self._anchor_in(45)
        rate = (self.membership_type.minimum_amount or 0) + 41
        fixed = self._plan_template("Annual", mode="Fixed", dues_rate=rate, minimum_amount=0)
        joined = self._plan_template("Annual", mode="Fixed", dues_rate=rate + 1, minimum_amount=0)
        door = self._door(
            plans=[
                self._fixed_plan_row(fixed, anchor),
                {"dues_template": joined, "is_default": 0},
            ]
        )

        _application, result = self._apply_and_approve(door, joined)

        self.assertFalse(self._fixed_schedule(result["member"]).coverage_anchor_date)
        [invoice] = self._fixed_invoices(result["member"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), getdate(today()))

    def test_a_quit_member_rejoining_on_a_fixed_date_plan_gets_the_anchor_on_the_reused_schedule(self):
        """The writer that sets coverage_anchor_date for a rejoin (reactivate_for_rejoin, anchor = start date)
        must not win over the plan's anchor. PROBE SHORTCUT: only the Membership's commitment_end_date is
        backdated so a genuine past-dated termination can run; the termination and reapplication are real."""
        from verenigingen.tests.support.termination_request import execute_real_termination

        self.expectErrorLog("Chapter Membership Error")
        join_template = self._plan_template("Monthly", mode="Fixed", dues_rate=30, minimum_amount=0)
        join_door = self._door(plans=[{"dues_template": join_template, "is_default": 1}])
        first = self._stage_fixed_plan(join_door, join_template)
        member = self._approve_fixed(first, create_invoice=False)["member"]
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", plan, "commitment_end_date", add_days(today(), -60))
        execute_real_termination(self, member, add_days(today(), -30))
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor)

        _application, result = self._apply_and_approve(door, template)

        self.assertEqual(result["member"], member, "the rejoiner is the same Member")
        schedule = self._fixed_schedule(member)
        self.assertEqual(getdate(schedule.coverage_anchor_date), anchor, "not the rejoin's start date")
        self.assertEqual(schedule.billing_frequency, "Annual", "the reused schedule took the new plan")
        self.assertEqual(self._fixed_invoices(member), [], "nothing billed before the anchor")


class TestFixedDateRetry(FixedDateCase):
    def _break_invoicing_fixed_3450(self):
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 3450")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", company)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        return company

    def test_the_retry_covers_the_same_period_approval_would_have(self):
        anchor = self._anchor_in(-45)
        door, template = self._fixed_door(anchor)
        application = self._stage_fixed_plan(door, template)
        company = self._break_invoicing_fixed_3450()
        failed = self._approve_fixed(application)
        self.assertTrue(failed["invoice_failed"], failed)
        frappe.db.set_single_value("Verenigingen Settings", "company", company)

        with self.as_user(self.admin_user.email):
            retried = retry_application_invoice(application)

        self.assertTrue(retried["invoice"], retried)
        invoice = frappe.get_doc("Sales Invoice", retried["invoice"])
        self.assertEqual(getdate(invoice.custom_coverage_start_date), anchor, "not the membership's start date")
        self.assertEqual(getdate(invoice.custom_coverage_end_date), self._one_period_from(anchor))


class TestFixedDateTypeChange(FixedDateCase):
    def _type_change_amendment(self, member, other_type):
        membership = frappe.db.get_value("Member", member, "current_membership_plan")
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership,
                "member": member,
                "amendment_type": "Membership Type Change",
                "requested_membership_type": other_type.name,
                "requested_amount": float(self._fixed_schedule(member).dues_rate) + 3,
                "reason": "moved to another type",
                "effective_date": today(),
            }
        )
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        if amendment.status == "Pending Approval":
            amendment.approve_amendment("approved in test")
            amendment.reload()
        amendment._force_apply = True
        result = amendment.apply_amendment()
        self.assertEqual(result["status"], "success", result)
        return amendment

    def _second_type_fixed_3450(self):
        return self.factory.ensure_membership_type(
            f"Other Type {frappe.generate_hash(length=6)}", {"amount": 25.00, "billing_period": "Annual"}
        )

    def test_a_type_change_before_the_anchor_leaves_no_anchor_behind(self):
        anchor = self._anchor_in(45)
        door, template = self._fixed_door(anchor)
        _application, result = self._apply_and_approve(door, template)
        before = self._fixed_schedule(result["member"])
        self.assertEqual(getdate(before.coverage_anchor_date), anchor, "precondition: the anchor is set")

        self._type_change_amendment(result["member"], self._second_type_fixed_3450())

        after = frappe.get_doc("Membership Dues Schedule", before.name)
        self.assertEqual(after.membership_type != before.membership_type, True, "the schedule was edited in place")
        self.assertFalse(after.coverage_anchor_date)
        self.assertEqual(getdate(after.next_invoice_date), getdate(today()), "the next invoice runs from the change")
        self.assertTrue(after.should_generate_for_cutoff_period(add_days(today(), 20)), "no longer held back")

    def test_a_type_change_after_the_anchor_period_was_invoiced_changes_nothing_billing_wise(self):
        """Control: an anchor already reached is left alone (the coverage chains from the last invoice)."""
        anchor = self._anchor_in(-45)
        door, template = self._fixed_door(anchor)
        _application, result = self._apply_and_approve(door, template)
        before = self._fixed_schedule(result["member"])

        self._type_change_amendment(result["member"], self._second_type_fixed_3450())

        after = frappe.get_doc("Membership Dues Schedule", before.name)
        self.assertEqual(getdate(after.coverage_anchor_date), anchor)


class TestFixedDatePlanValidation(FixedDateCase):
    def _door_with_plan(self, **plan):
        template = self._plan_template("Annual", mode="Fixed", dues_rate=60, minimum_amount=0)
        return self._door(plans=[{"dues_template": template, "is_default": 1, **plan}])

    def test_a_fixed_date_plan_with_a_real_month_and_day_is_saved(self):
        door = self._door_with_plan(period_anchor="Fixed date", anchor_month=11, anchor_day=3, waive_final_months=2)
        self.assertEqual((door.plans[0].anchor_month, door.plans[0].anchor_day), (11, 3))

    def test_a_fixed_date_plan_needs_a_valid_month_and_day(self):
        for month, day in ((None, None), (13, 1), (0, 5), (4, 31), (2, 30), (2, 29), (6, 0)):
            with self.subTest(month=month, day=day):
                with self.assertRaises(frappe.ValidationError):
                    self._door_with_plan(period_anchor="Fixed date", anchor_month=month, anchor_day=day)

    def test_a_negative_waiver_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self._door_with_plan(period_anchor="Fixed date", anchor_month=11, anchor_day=3, waive_final_months=-1)

    def test_a_join_date_plan_defaults_to_no_anchor_and_no_waiver(self):
        door = self._door_with_plan()
        row = door.plans[0]
        self.assertEqual((row.period_anchor, row.waive_final_months), ("Join date", 0))
