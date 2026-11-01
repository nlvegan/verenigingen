# -*- coding: utf-8 -*-
"""
#1773/#1774: the invoice created AT approval, driven through the real flow
(submit_application -> reject -> resubmit -> approve_membership_application).
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, flt, getdate, today

from verenigingen.api.membership_application import submit_application
from verenigingen.api.membership_application_review import (
    approve_membership_application,
    reject_membership_application,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestApprovalInvoicePeriod(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.chapter = self.factory.ensure_test_chapter(
            f"Test Chapter {run}", {"short_name": "TST", "country": "Netherlands"}
        )
        self.membership_type = self.factory.ensure_membership_type(
            f"Inv Type {run}", {"amount": 25.00, "billing_period": "Monthly"}
        )
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
        if not frappe.db.exists("Item Group", "Memberships"):
            frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Memberships",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            ).insert()
        self.membership_type.get_or_create_membership_item()
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        self.admin_user = self.create_test_user_with_roles(
            email=f"inv.admin.{frappe.generate_hash(length=6)}@example.com",
            roles=["System Manager", "Verenigingen Administrator"],
        )
        grant_matching_role_profiles(self.admin_user.email, "Verenigingen Administrator")

    def _submit_invoice_applicant(self, email, template, amount):
        result = submit_application(
            first_name="Inv",
            last_name=f"Applicant{frappe.generate_hash(length=6)}",
            email=email,
            birth_date=add_days(today(), -365 * 30),
            address_line1="123 Test Street",
            city="Amsterdam",
            postal_code="1234AB",
            country="Netherlands",
            selected_membership_type=self.membership_type.name,
            selected_chapter=self.chapter.name,
            selected_dues_schedule=template.name,
            custom_contribution_fee=amount,
            uses_custom_amount=1,
        )
        self.assertTrue(result["success"], result)
        return result["data"]["member_record"]

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

    def _approve_with_invoicing(self, member, create_invoice=True):
        with self.as_user(self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return approve_membership_application(
                    member_name=member,
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
        """Rejected, then reapplied on an Annual template under a Monthly Membership Type."""
        self.assertEqual(self.membership_type.billing_period, "Monthly", "precondition")
        email = f"inv-{frappe.generate_hash(length=8)}@example.com"
        chosen = self.minimum + 200.25
        member = self._submit_invoice_applicant(email, self.annual_template, chosen + 1)
        with self.as_user(self.admin_user.email):
            reject_membership_application(member, reason="first attempt rejected")
        self.assertEqual(self._submit_invoice_applicant(email, self.annual_template, chosen), member)
        result = self._approve_with_invoicing(member)
        self._assert_one_full_period(result, "Annual", 12, chosen)
        schedule = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member, "is_template": 0}, "billing_frequency"
        )
        self.assertEqual(schedule, "Annual", "the invoice period matches the schedule it feeds")

    def test_new_member_on_quarterly_template_is_invoiced_one_full_quarter(self):
        quarterly = self._frequency_template("Quarterly", "Quarterly")
        member = self._submit_invoice_applicant(f"inv-{frappe.generate_hash(length=8)}@example.com", quarterly, self.minimum + 70)
        self._assert_one_full_period(self._approve_with_invoicing(member), "Quarterly", 3, self.minimum + 70)

    def test_member_on_the_types_own_frequency_is_still_invoiced_that_period(self):
        """Control: a Monthly template under the Monthly type stays one month."""
        monthly = self._frequency_template("Monthly", "Monthly")
        member = self._submit_invoice_applicant(f"inv-{frappe.generate_hash(length=8)}@example.com", monthly, self.minimum + 9)
        self._assert_one_full_period(self._approve_with_invoicing(member), "Monthly", 1, self.minimum + 9)

    def test_quit_rejoiner_is_invoiced_on_the_new_schedule_period(self):
        """The #1773 case: a voluntary Quit rejoins on an Annual template.

        PROBE SHORTCUT: only the Membership's commitment_end_date is backdated so a genuine
        past-dated termination can run; the termination and the reapplication are real.
        """
        from verenigingen.tests.support.termination_request import execute_real_termination

        self.expectErrorLog("Chapter Membership Error")
        email = f"inv-{frappe.generate_hash(length=8)}@example.com"
        monthly = self._frequency_template("Monthly", "Monthly")
        member = self._submit_invoice_applicant(email, monthly, None)
        self._approve_with_invoicing(member, create_invoice=False)
        plan = frappe.db.get_value("Member", member, "current_membership_plan")
        frappe.db.set_value("Membership", plan, "commitment_end_date", add_days(today(), -60))
        execute_real_termination(self, member, add_days(today(), -30))
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Quit")
        chosen = self.minimum + 200.25
        self.assertEqual(self._submit_invoice_applicant(email, self.annual_template, chosen), member)
        self._assert_one_full_period(self._approve_with_invoicing(member), "Annual", 12, chosen)

    def test_a_failed_invoice_is_reported_and_logged_not_called_success(self):
        """Break invoicing for real (Verenigingen Settings names a company that does not exist)."""
        member = self._submit_invoice_applicant(
            f"inv-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 60
        )
        original = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 1774")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "company", original)
        self.expectErrorLog(
            "Membership Invoice Creation Failed", "Membership Invoice Security", "BTW Tax Exemption Error",
            "Secure Operation Failed"
        )
        result = self._approve_with_invoicing(member)
        self.assertIsNone(result["invoice"])
        self.assertTrue(result["invoice_failed"], result)
        self.assertNotIn("Invoice sent", result["message"])
        self.assertIn("NOT be created", result["message"])
        self.assertTrue(
            frappe.db.exists("Error Log", {"method": "Membership Invoice Creation Failed", "error": ["like", f"%{member}%"]})
        )

    def test_no_invoice_requested_is_not_reported_as_a_failure(self):
        """Control: create_invoice=False is not a failed invoice."""
        member = self._submit_invoice_applicant(
            f"inv-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 61
        )
        result = self._approve_with_invoicing(member, create_invoice=False)
        self.assertIsNone(result["invoice"])
        self.assertFalse(result["invoice_failed"])
        self.assertNotIn("NOT be created", result["message"])

    # -- callers that read invoice_failed (#1774) -----------------------------

    def _break_invoicing(self):
        """Same real break as above: Verenigingen Settings names a company that does not exist."""
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
        member = self._submit_invoice_applicant(
            f"inv-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 80
        )
        with self.as_user(board.user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                result = approve_membership_application(
                    member_name=member,
                    membership_type=self.membership_type.name,
                    chapter=self.chapter.name,
                    create_invoice=True,
                )
        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], result)
        self.assertTrue(result["invoice"])

    def _board_applicant(self):
        """A real submitted application whose Chapter Member row is Active, not Pending, so
        quick_approve_member takes its membership-application branch (not approve_member_request).
        PROBE SHORTCUT: the row's status is set directly to stand in for a chapter that
        activated it at submission."""
        member = self._submit_invoice_applicant(
            f"quick-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 83
        )
        rows = frappe.get_all(
            "Chapter Member", filters={"member": member, "parent": self.chapter.name}, pluck="name"
        )
        self.assertEqual(len(rows), 1, "precondition: submission wrote one Chapter Member row")
        frappe.db.set_value("Chapter Member", rows[0], {"status": "Active", "enabled": 1})
        return member

    def test_quick_approve_member_passes_the_invoice_failure_through(self):
        from verenigingen.api.chapter_dashboard_api import quick_approve_member

        board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Secretary"
        )
        member = self._board_applicant()
        self._break_invoicing()
        with self.as_user(board.user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                result = quick_approve_member(member, self.chapter.name)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["invoice_failed"], result)
        self.assertIn("NOT be created", result["message"])
        self.assertNotEqual(result["message"], "Member approved successfully")

    def test_quick_approve_member_with_an_invoice_is_plain_success(self):
        """Control: a working invoice keeps the plain message and invoice_failed False."""
        from verenigingen.api.chapter_dashboard_api import quick_approve_member

        board = self.create_test_board_member(
            self.chapter.name, permissions_level="Admin", role_name="Secretary"
        )
        member = self._board_applicant()
        with self.as_user(board.user):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                result = quick_approve_member(member, self.chapter.name)
        self.assertTrue(result["success"], result)
        self.assertFalse(result["invoice_failed"], result)
        self.assertEqual(result["message"], "Member approved successfully")

    def _bulk_approve(self, member):
        from verenigingen.pages.membership_applications import bulk_approve_applications

        with self.as_user(self.admin_user.email):
            # Mock justified: External Service - SMTP delivery, not business logic
            with patch("frappe.sendmail"):
                return bulk_approve_applications(
                    frappe.as_json([member]), self.membership_type.name, create_invoices=True
                )

    def test_bulk_approve_counts_invoice_failures_apart_from_clean_successes(self):
        clean = self._submit_invoice_applicant(
            f"inv-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 81
        )
        broken = self._submit_invoice_applicant(
            f"inv-{frappe.generate_hash(length=8)}@example.com", self.annual_template, self.minimum + 82
        )
        ok_result = self._bulk_approve(clean)
        self.assertEqual((ok_result["success"], ok_result["invoice_failed"]), ([clean], []))
        self._break_invoicing()
        bad_result = self._bulk_approve(broken)
        self.assertEqual((bad_result["success"], bad_result["invoice_failed"]), ([], [broken]))
        self.assertEqual(bad_result["failed"], [])
