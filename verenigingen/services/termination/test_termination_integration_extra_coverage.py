"""
Extra integration coverage for
verenigingen/services/termination/termination_integration.py

Complements test_termination_integration.py and
test_termination_integration_coverage.py by exercising branches those suites
leave uncovered. Every test builds real DocTypes through the EnhancedTestCase
factory and asserts real DB side-effects (dues schedule cancelled, member
next_invoice_date cleared, draft expense claim flagged, employee relieved via
the company_email discovery path, user suspended/reactivated via the
email-fallback lookup). No business logic is mocked.

Sales Invoice paths are covered elsewhere and are intentionally avoided here
(they require a fully provisioned receivable account on the test company).
"""

import frappe
from frappe.utils import today

from verenigingen.services.termination import termination_integration as ti
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTerminationIntegrationExtraCoverage(EnhancedTestCase):
    def test_get_company_never_borrows_by_currency(self):
        """``_get_company`` must own its company, not scan for a EUR one.

        It used to read ``Verenigingen Settings.company`` and, when that was unset, fall
        back to ``get_value("Company", {"default_currency": "EUR"}, "name")`` -- which is
        not "some EUR company" but the NEWEST one (``db.get_value`` has no ``order_by``, so
        it defaults to ``creation DESC``), i.e. whatever a co-tenant suite in the shard
        created last. Measured on test_site_2, 2026-08-23: 30 EUR companies, and that
        expression returned an e_boekhouden fixture, one of which has no receivable or
        income account at all.

        The single is cleared here on purpose: ``EnhancedTestCase.setUp`` sets it (via
        ``_ensure_master_data``, which swallows its own exceptions), so on a warm site the
        borrow never fires and a pin that did not clear it would be green either way.
        Uncommitted -- the per-test rollback puts it back.
        """
        from verenigingen.tests.support.eur_company_decoy import newest_eur_company

        frappe.db.set_single_value("Verenigingen Settings", "company", None)
        with newest_eur_company() as decoy:
            resolved = self._get_company()

        self.assertEqual(resolved, self._get_test_company())
        self.assertNotEqual(resolved, decoy)

    # ------------------------------------------------------------------
    # helpers (names use allowed prefixes for ignore_permissions per enforcer)
    # ------------------------------------------------------------------
    def _make_member(self, status="Active", **kwargs):
        member = self.create_test_member(first_name="TermXtra", last_name=f"M{self.uid}", **kwargs)
        if status != "Active":
            frappe.db.set_value("Member", member.name, "status", status)
            member.reload()
        return member

    def _make_volunteer(self, member):
        return self.create_test_volunteer(member_name=member.name)

    def _make_user_with_email(self, email, enabled=1):
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "TermXtra",
                "last_name": "User",
                "enabled": enabled,
                "send_welcome_email": 0,
            }
        )
        user.insert(ignore_permissions=True)
        return user

    def _get_company(self):
        """The harness-OWNED company, resolved by name.

        Not a scan. See ``test_get_company_never_borrows_by_currency`` above for what the
        currency fallback this replaces actually resolved to. ``_get_test_company()`` is
        the same value ``EnhancedTestCase.setUp`` writes into
        ``Verenigingen Settings.company``, so this is not a behaviour change on a healthy
        run -- only on the run where that setup silently failed.
        """
        return self._get_test_company()

    def _make_employee(self, **fields):
        emp = frappe.new_doc("Employee")
        emp.first_name = "TermXtra"
        emp.last_name = "Emp"
        emp.employee_name = "TermXtra Emp"
        emp.company = self._get_company()
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = today()
        emp.gender = "Other"
        emp.status = "Active"
        for k, v in fields.items():
            setattr(emp, k, v)
        emp.insert(ignore_permissions=True)
        return emp

    def _insert_draft_expense_claim(self, employee_name, company):
        expense_acct = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        ) or frappe.db.get_value(
            "Account", {"root_type": "Expense", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available on test company")
        claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee_name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": [
                    {
                        "expense_type": "Food",
                        "amount": 12.5,
                        "sanctioned_amount": 12.5,
                        "expense_date": today(),
                        "default_account": expense_acct,
                    }
                ],
            }
        )
        claim.insert(ignore_permissions=True)
        return claim

    # ==================================================================
    # cancel_membership_safe — cascades to the linked dues schedule
    # ==================================================================
    def test_cancel_membership_safe_cancels_linked_dues_schedule(self):
        """Cancelling a membership must also cancel its active dues schedule
        (the query+cascade branch inside cancel_membership_safe)."""
        member = self._make_member()
        self.create_test_membership(member_name=member.name)
        schedule = self.create_test_dues_schedule(member.name)
        # The dues schedule is linked to the member's active membership.
        membership_name = frappe.db.get_value(
            "Membership", {"member": member.name, "status": "Active"}, "name"
        )
        self.assertTrue(membership_name)

        result = ti.cancel_membership_safe(membership_name, cancellation_reason="cascade test")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Membership", membership_name, "status"), "Cancelled")
        # The associated dues schedule must have been cancelled by the cascade.
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"),
            "Cancelled",
        )

    # ==================================================================
    # update_member_status_safe — next_invoice_date clearing + Non-payment map
    # ==================================================================
    def test_update_member_status_safe_clears_next_invoice_date(self):
        """Terminated members must not remain scheduled for invoicing."""
        member = self._make_member()
        frappe.db.set_value("Member", member.name, "next_invoice_date", today())
        member.reload()
        self.assertIsNotNone(frappe.db.get_value("Member", member.name, "next_invoice_date"))

        result = ti.update_member_status_safe(member.name, "Voluntary", today())
        self.assertTrue(result)
        self.assertIsNone(frappe.db.get_value("Member", member.name, "next_invoice_date"))

    def test_update_member_status_safe_non_payment_maps_to_quit(self):
        member = self._make_member()
        result = ti.update_member_status_safe(member.name, "Non-payment", today())
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        note = frappe.db.get_value("Member", member.name, "notes") or ""
        self.assertIn("Non-payment", note)

    def test_update_member_status_safe_includes_request_in_note(self):
        """When a termination_request is passed it is recorded in the member note."""
        member = self._make_member()
        result = ti.update_member_status_safe(
            member.name, "Administrative", today(), termination_request="TERM-REQ-XYZ"
        )
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        note = frappe.db.get_value("Member", member.name, "notes") or ""
        self.assertIn("TERM-REQ-XYZ", note)

    # ==================================================================
    # terminate_volunteer_records_safe — draft expense-claim flagging branch
    # ==================================================================
    def test_terminate_volunteer_records_safe_flags_draft_expense_claim(self):
        """A volunteer linked to an employee with a pending draft Expense Claim:
        terminating the volunteer must flag (annotate) that claim for HR review
        without rejecting it."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        company = self._get_company()
        employee = self._make_employee()
        # Link the volunteer to the employee so the expense-claim discovery runs.
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee.name)

        claim = self._insert_draft_expense_claim(employee.name, company)
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "docstatus"), 0)

        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", today(), "left org")
        self.assertEqual(result["volunteers_terminated"], 1)
        self.assertEqual(result["expense_claims_flagged"], 1)
        # The volunteer was set inactive ...
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "status"), "Inactive")
        # ... and the draft claim was annotated (not deleted / rejected).
        self.assertEqual(frappe.db.get_value("Expense Claim", claim.name, "docstatus"), 0)
        remark = frappe.db.get_value("Expense Claim", claim.name, "remark") or ""
        self.assertIn("volunteer terminated", remark.lower())

    def test_terminate_volunteer_records_safe_no_employee_link_skips_claims(self):
        """A volunteer with no employee_id must terminate but flag zero claims."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", None)
        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["volunteers_terminated"], 1)
        self.assertEqual(result["expense_claims_flagged"], 0)

    # ==================================================================
    # terminate_employee_records_safe — company_email discovery + On Leave
    # ==================================================================
    def test_terminate_employee_records_safe_via_company_email(self):
        """Employee found via company_email when user_id and personal_email miss."""
        member = self._make_member()
        member_email = frappe.db.get_value("Member", member.name, "email")
        user = self._make_user_with_email(member_email)
        frappe.db.set_value("Member", member.name, "user", user.name)
        # Only company_email matches (user_id and personal_email deliberately unset).
        emp = self._make_employee(company_email=user.name)
        result = ti.terminate_employee_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Resignation")

    def test_terminate_employee_records_safe_on_leave_employee(self):
        """An employee currently On Leave is still relieved on member termination."""
        member = self._make_member()
        member_email = frappe.db.get_value("Member", member.name, "email")
        user = self._make_user_with_email(member_email)
        frappe.db.set_value("Member", member.name, "user", user.name)
        emp = self._make_employee(user_id=user.name)
        # Move to On Leave to exercise the ["Active", "On Leave"] filter branch.
        frappe.db.set_value("Employee", emp.name, "status", "On Leave")
        result = ti.terminate_employee_records_safe(member.name, "Deceased", today(), "passed away")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Deceased")

    # ==================================================================
    # suspend_member_safe / unsuspend_member_safe — user-by-email fallback
    # ==================================================================
    def test_suspend_member_safe_finds_user_by_email_fallback(self):
        """When Member.user is unset but a User exists with the member's email,
        suspension must still disable that user account (email fallback branch)."""
        member = self._make_member()
        member_email = frappe.db.get_value("Member", member.name, "email")
        # No linked user; a User exists with the same email address.
        frappe.db.set_value("Member", member.name, "user", None)
        user = self._make_user_with_email(member_email, enabled=1)

        result = ti.suspend_member_safe(member.name, "policy", suspend_user=True, suspend_teams=False)
        self.assertTrue(result["success"])
        self.assertTrue(result["user_suspended"])
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)

    def test_unsuspend_member_safe_finds_user_by_email_fallback(self):
        """Unsuspension re-enables a user discovered via the email fallback."""
        member = self._make_member()
        member_email = frappe.db.get_value("Member", member.name, "email")
        frappe.db.set_value("Member", member.name, "user", None)
        user = self._make_user_with_email(member_email, enabled=1)

        ti.suspend_member_safe(member.name, "policy", suspend_user=True, suspend_teams=False)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)

        result = ti.unsuspend_member_safe(member.name, "appeal upheld")
        self.assertTrue(result["success"])
        self.assertTrue(result["user_unsuspended"])
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)
