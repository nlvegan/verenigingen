# -*- coding: utf-8 -*-
"""
#1773/#1774: the invoice created AT approval, driven through the real application-keyed flow
(submit_application as Guest -> confirm link -> [reject -> resubmit -> confirm] -> approve_application).
Staging is ApprovalCase's own real flow. No probe shortcuts except where a test says so (the quit
rejoiner backdates the Membership commitment end so a genuine past-dated termination can run).
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, flt, getdate, today

from verenigingen.tests.integration.test_application_record_approval import SUBMISSION, ApprovalCase


class TestApprovalInvoicePeriod(ApprovalCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.minimum = flt(self.membership_type.minimum_amount or 0)
        self.annual_template = self.ensure_dues_schedule_template(
            f"Inv Annual {run}",
            {
                "billing_frequency": "Annual",
                "dues_rate": self.minimum + 123,
                "suggested_amount": self.minimum + 123,
                "minimum_amount": self.minimum,
                "membership_type": self.membership_type.name,
                "contribution_mode": "Fixed",
            },
        )

    def _stage_invoice_applicant(self, template, amount, email=None):
        """ApprovalCase's real flow (Guest submit -> confirm link) with the chosen dues schedule and a
        custom amount carried through the form, as the old member-keyed helper did."""
        overrides = {"selected_dues_schedule": template.name}
        if amount is not None:
            overrides.update(custom_contribution_fee=amount, uses_custom_amount=1)
        if email:
            overrides["email"] = email
        return self._stage_and_confirm(**overrides)

    # -- helpers -------------------------------------------------------------

    def _frequency_template(self, frequency, label):
        return self.ensure_dues_schedule_template(
            f"Inv {label} {frappe.generate_hash(length=6)}",
            {
                "billing_frequency": frequency,
                "dues_rate": self.minimum + 50,
                "suggested_amount": self.minimum + 50,
                "minimum_amount": self.minimum,
                "membership_type": self.membership_type.name,
                "contribution_mode": "Fixed",
            },
        )

    def _approve_with_invoicing(self, application, create_invoice=True):
        return self._approve_as(
            application,
            membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            create_invoice=create_invoice,
        )

    def _assert_one_full_period(self, result, frequency, months, amount):
        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], result)
        invoice = frappe.get_doc("Sales Invoice", result["invoice"])
        start = getdate(invoice.custom_coverage_start_date)
        self.assertEqual(start, getdate(today()))
        # Derived from the schedule's frequency, never from the Membership Type (Monthly).
        self.assertEqual(
            getdate(invoice.custom_coverage_end_date), add_days(add_months(start, months), -1), frequency
        )
        self.assertEqual(flt(invoice.grand_total), flt(amount))
        self.assertEqual(invoice.docstatus, 1)

    def test_approver_profile_cannot_read_item_through_another_role(self):
        """Precondition for the tests below: this approver is the real Verenigingen Administrator
        profile, which can create a Sales Invoice (Accounts Manager) but holds none of the
        stock roles that read Item. Item read must come from the app's own grant (#1774)."""
        roles = set(frappe.get_roles(self.admin_user.email))
        self.assertIn("Accounts Manager", roles)
        for stock_role in ("Accounts User", "Sales User", "Stock User", "Stock Manager", "Item Manager"):
            self.assertNotIn(stock_role, roles)

    # -- #1773 / #1774: real flow -------------------------------------------

    def test_reapplicant_on_annual_template_is_invoiced_one_full_annual_period(self):
        """Rejected, then reapplied on an Annual template under a Monthly Membership Type.

        A rejected application creates no Member (reject_application touches only the application), so
        "the same Member" is asserted as: still exactly one Member for the email after approval, and it
        is the one the approval reports."""
        self.assertEqual(self.membership_type.billing_period, "Monthly", "precondition")
        chosen = self.minimum + 200.25
        first = self._stage_invoice_applicant(self.annual_template, chosen + 1)
        self._reject_as(first, reason="first attempt rejected")
        self.assertEqual(frappe.db.get_value(SUBMISSION, first, "status"), "Rejected")
        second = self._stage_invoice_applicant(self.annual_template, chosen)
        self.assertNotEqual(first, second)
        result = self._approve_with_invoicing(second)
        members = frappe.get_all("Member", {"email": self.email}, pluck="name")
        self.assertEqual(members, [result["member"]], "one Member for the email, the one approved")
        self._assert_one_full_period(result, "Annual", 12, chosen)
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": result["member"], "is_template": 0},
            "billing_frequency",
        )
        self.assertEqual(schedule, "Annual", "the invoice period matches the schedule it feeds")

    def test_new_member_on_quarterly_template_is_invoiced_one_full_quarter(self):
        quarterly = self._frequency_template("Quarterly", "Quarterly")
        application = self._stage_invoice_applicant(quarterly, self.minimum + 70)
        result = self._approve_with_invoicing(application)
        self._assert_one_full_period(result, "Quarterly", 3, self.minimum + 70)

    def test_member_on_the_types_own_frequency_is_still_invoiced_that_period(self):
        """Control: a Monthly template under the Monthly type stays one month."""
        monthly = self._frequency_template("Monthly", "Monthly")
        application = self._stage_invoice_applicant(monthly, self.minimum + 9)
        self._assert_one_full_period(self._approve_with_invoicing(application), "Monthly", 1, self.minimum + 9)

    def test_quit_rejoiner_is_invoiced_on_the_new_schedule_period(self):
        """The #1773 case: a voluntary Quit rejoins on an Annual template.

        PROBE SHORTCUT: only the Membership's commitment_end_date is backdated so a genuine
        past-dated termination can run; the termination and the reapplication are real.
        """
        from verenigingen.tests.support.termination_request import execute_real_termination

        self.expectErrorLog("Chapter Membership Error")
        monthly = self._frequency_template("Monthly", "Monthly")
        first = self._stage_invoice_applicant(monthly, None)
        member = self._approve_with_invoicing(first, create_invoice=False)["member"]
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", plan, "commitment_end_date", add_days(today(), -60))
        execute_real_termination(self, member, add_days(today(), -30))
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")
        chosen = self.minimum + 200.25
        second = self._stage_invoice_applicant(self.annual_template, chosen)
        result = self._approve_with_invoicing(second)
        self.assertEqual(result["member"], member, "the rejoiner is the same Member")
        self._assert_one_full_period(result, "Annual", 12, chosen)

    def test_a_failed_invoice_is_reported_and_logged_not_called_success(self):
        """Break invoicing for real (Verenigingen Settings names a company that does not exist)."""
        application = self._stage_invoice_applicant(self.annual_template, self.minimum + 60)
        self._break_invoicing()
        result = self._approve_with_invoicing(application)
        self.assertIsNone(result["invoice"])
        self.assertTrue(result["invoice_failed"], result)
        self.assertNotIn("Invoice sent", result["message"])
        self.assertIn("NOT be created", result["message"])
        self.assertTrue(
            frappe.db.exists(
                "Error Log",
                {"method": "Membership Invoice Creation Failed", "error": ["like", f"%{result['member']}%"]},
            )
        )

    def test_no_invoice_requested_is_not_reported_as_a_failure(self):
        """Control: create_invoice=False is not a failed invoice."""
        application = self._stage_invoice_applicant(self.annual_template, self.minimum + 61)
        result = self._approve_with_invoicing(application, create_invoice=False)
        self.assertIsNone(result["invoice"])
        self.assertFalse(result["invoice_failed"])
        self.assertNotIn("NOT be created", result["message"])

    # -- callers that read invoice_failed (#1774) -----------------------------

    def _break_invoicing(self):
        """Verenigingen Settings names a company that does not exist."""
        original = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 1774")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", original)
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )

    def test_chapter_board_approver_gets_an_invoice_with_the_dashboards_default(self):
        """M-4 control: a board approver (Accounts User + Sales User, so Item read without the
        Administrator grant) approves with create_invoice=True, the chapter dashboard default."""
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application = self._stage_invoice_applicant(self.annual_template, self.minimum + 80)
        result = self._approve_as(
            application,
            user=board.user,
            membership_type=self.membership_type.name,
            chapter=self.chapter.name,
            create_invoice=True,
        )
        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], result)
        self.assertTrue(result["invoice"])

    def _quick_approve_as_board(self, application):
        """quick_approve_application as a real board member whose role carries can_approve_members."""
        from verenigingen.api.chapter_dashboard_api import quick_approve_application

        board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Secretary"
        )
        with self.as_user(board.user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return quick_approve_application(application)

    def test_quick_approve_application_passes_the_invoice_failure_through(self):
        application = self._stage_invoice_applicant(self.annual_template, self.minimum + 83)
        self._break_invoicing()
        result = self._quick_approve_as_board(application)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["invoice_failed"], result)
        self.assertIn("NOT be created", result["message"])
        self.assertNotEqual(result["message"], "Member approved successfully")

    def test_quick_approve_application_with_an_invoice_is_plain_success(self):
        """Control: a working invoice keeps invoice_failed False and no failure message."""
        application = self._stage_invoice_applicant(self.annual_template, self.minimum + 84)
        result = self._quick_approve_as_board(application)
        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], result)
        self.assertNotIn("NOT be created", result["message"])

    def test_looped_approvals_report_invoice_failure_per_application(self):
        """There is no server bulk endpoint on this branch: the review page's JS loops over
        approve_application and reads each response's invoice_failed (pinned in the JS tests)."""
        clean = self._stage_invoice_applicant(self.annual_template, self.minimum + 81)
        ok_result = self._approve_with_invoicing(clean)
        self.assertEqual((ok_result["success"], ok_result["invoice_failed"]), (True, False))
        broken = self._stage_invoice_applicant(
            self.annual_template, self.minimum + 82, email=self._fresh_applicant_email()
        )
        self._break_invoicing()
        bad_result = self._approve_with_invoicing(broken)
        self.assertEqual((bad_result["success"], bad_result["invoice_failed"]), (True, True))
