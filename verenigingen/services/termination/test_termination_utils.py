"""
Integration coverage for verenigingen/services/termination/termination_utils.py

These are the whitelisted readiness / reporting / audit helpers that drive the
termination dashboard and scheduler. Each helper is defensive: on a bad member
name or other error it returns a documented dict (often with an "error" key)
rather than raising. Tests build real Member/Membership/SEPA Mandate/Chapter/
Volunteer/Employee/Termination Request docs via the ORM and assert real DB-derived
counts, never asserting magic numbers that aren't traceable to created data.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.termination import termination_utils as tu
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTerminationUtils(EnhancedTestCase):
    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
    def _make_member(self, **kwargs):
        return self.create_test_member(first_name="TermUtil", last_name=f"M{self.uid}", **kwargs)

    def _make_customer_for_member(self, member):
        member = frappe.get_doc("Member", member.name)
        if not member.customer:
            member.create_customer()
            member.reload()
        return member.customer

    def _make_user(self, member, enabled=1):
        email = f"termutil-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "TermUtil",
                "last_name": "User",
                "enabled": enabled,
                "send_welcome_email": 0,
            }
        )
        user.insert()
        frappe.db.set_value("Member", member.name, "user", email)
        return user

    def _make_employee(self, user_email):
        company = (
            frappe.db.get_single_value("Verenigingen Settings", "company")
            or frappe.db.get_value("Company", {"default_currency": "EUR"}, "name")
            or frappe.db.get_value("Company", {}, "name")
        )
        emp = frappe.new_doc("Employee")
        emp.first_name = "TermUtil"
        emp.last_name = "Emp"
        emp.employee_name = "TermUtil Emp"
        emp.user_id = user_email
        emp.company = company
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = today()
        emp.gender = "Other"
        emp.status = "Active"
        emp.insert()
        return emp

    def _make_termination_request(self, member, status="Draft", termination_type="Voluntary", **kwargs):
        doc = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member.name,
                "termination_type": termination_type,
                "status": status,
                "request_date": today(),
                "termination_date": today(),
                "termination_reason": "test reason",
                **kwargs,
            }
        )
        doc.insert()
        return doc

    # ==================================================================
    # validate_termination_readiness
    # ==================================================================
    def test_validate_readiness_clean_member_is_ready(self):
        member = self._make_member()
        result = tu.validate_termination_readiness(member.name)
        self.assertTrue(result["ready"])
        self.assertEqual(result["blockers"], [])
        # impact dict always present with documented keys
        for key in ("active_memberships", "sepa_mandates", "board_positions", "outstanding_invoices"):
            self.assertIn(key, result["impact"])

    def test_validate_readiness_counts_active_membership(self):
        member = self._make_member()
        self.create_test_membership(member_name=member.name)
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["active_memberships"], 1)

    def test_validate_readiness_counts_sepa_mandate(self):
        member = self._make_member()
        self.create_test_sepa_mandate(member_name=member.name)
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["sepa_mandates"], 1)

    def test_validate_readiness_mollie_mandate_flag(self):
        member = self._make_member()
        frappe.db.set_value("Member", member.name, "mollie_mandate_id", "mdt_test_123")
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["mollie_mandates"], 1)

    def test_validate_readiness_no_mollie_mandate_is_zero(self):
        member = self._make_member()
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["mollie_mandates"], 0)

    def test_validate_readiness_counts_board_position(self):
        member = self._make_member()
        volunteer = self.create_test_volunteer(member_name=member.name)
        chapter = self.create_test_chapter(
            chapter_name=f"TU Chapter {frappe.generate_hash(length=6)}",
            region="Test Region TU",
        )
        chapter = frappe.get_doc("Chapter", chapter.name)
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": f"TU Role {frappe.generate_hash(length=6)}",
                "permissions_level": "Basic",
                "is_active": 1,
            }
        )
        role.insert()
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role.name,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save()
        result = tu.validate_termination_readiness(member.name)
        self.assertGreaterEqual(result["impact"]["board_positions"], 1)
        self.assertTrue(any("board position" in w for w in result["warnings"]))

    def test_validate_readiness_counts_outstanding_invoice(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        invoice = self.create_test_sales_invoice(customer)
        invoice.submit()
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["outstanding_invoices"], 1)

    def test_validate_readiness_existing_request_blocks(self):
        member = self._make_member()
        self._make_termination_request(member, status="Pending")
        result = tu.validate_termination_readiness(member.name)
        self.assertFalse(result["ready"])
        self.assertTrue(any("pending termination" in b for b in result["blockers"]))

    def test_validate_readiness_counts_active_volunteer(self):
        member = self._make_member()
        self.create_test_volunteer(member_name=member.name, status="Active")
        result = tu.validate_termination_readiness(member.name)
        self.assertEqual(result["impact"]["volunteer_records"], 1)
        self.assertTrue(any("volunteer record" in w for w in result["warnings"]))

    def test_validate_readiness_counts_employee_via_user_id(self):
        member = self._make_member()
        user = self._make_user(member)
        self._make_employee(user.name)
        result = tu.validate_termination_readiness(member.name)
        self.assertTrue(result["impact"]["user_account"])
        self.assertGreaterEqual(result["impact"]["employee_records"], 1)
        self.assertTrue(any("employee record" in w for w in result["warnings"]))

    def test_validate_readiness_missing_member_returns_error(self):
        result = tu.validate_termination_readiness("NONEXISTENT-MEMBER-XYZ")
        self.assertFalse(result["ready"])
        self.assertIn("error", result)

    # ==================================================================
    # get_termination_impact_summary
    # ==================================================================
    def test_impact_summary_includes_membership_category(self):
        member = self._make_member()
        self.create_test_membership(member_name=member.name)
        summary = tu.get_termination_impact_summary(member.name)
        self.assertEqual(summary["member_name"], frappe.db.get_value("Member", member.name, "full_name"))
        categories = {c["category"]: c for c in summary["categories"]}
        self.assertIn("Memberships", categories)
        self.assertEqual(categories["Memberships"]["count"], 1)
        self.assertEqual(categories["Memberships"]["action"], "Will be cancelled")

    def test_impact_summary_sepa_category(self):
        member = self._make_member()
        self.create_test_sepa_mandate(member_name=member.name)
        summary = tu.get_termination_impact_summary(member.name)
        categories = {c["category"]: c for c in summary["categories"]}
        self.assertIn("SEPA Mandates", categories)

    def test_impact_summary_clean_member_empty_categories(self):
        member = self._make_member()
        summary = tu.get_termination_impact_summary(member.name)
        self.assertEqual(summary["categories"], [])
        self.assertTrue(summary["ready_for_termination"])

    def test_impact_summary_missing_member_returns_error(self):
        summary = tu.get_termination_impact_summary("NONEXISTENT-MEMBER-XYZ")
        # readiness returns {"ready": False, "error": ...}; summary derives from it
        # and full_name lookup is None for a nonexistent member.
        self.assertIn("member_name", summary)
        self.assertIsNone(summary["member_name"])

    # ==================================================================
    # get_termination_statistics
    # ==================================================================
    def test_statistics_shape(self):
        stats = tu.get_termination_statistics()
        for key in ("total_requests", "pending_requests", "executed_requests", "this_month", "by_type"):
            self.assertIn(key, stats)
        self.assertIsInstance(stats["by_type"], dict)

    def test_statistics_counts_new_pending_request(self):
        member = self._make_member()
        before = tu.get_termination_statistics()
        self._make_termination_request(member, status="Pending", termination_type="Voluntary")
        after = tu.get_termination_statistics()
        self.assertEqual(after["pending_requests"], before["pending_requests"] + 1)
        self.assertEqual(after["total_requests"], before["total_requests"] + 1)
        self.assertGreaterEqual(after["by_type"].get("Voluntary", 0), 1)

    # ==================================================================
    # process_overdue_termination_requests
    # ==================================================================
    def test_process_overdue_no_overdue_returns_zero(self):
        # A fresh Pending request (request_date today) is not overdue (>7 days).
        member = self._make_member()
        self._make_termination_request(member, status="Pending")
        result = tu.process_overdue_termination_requests()
        self.assertIn("processed", result)
        # Our just-created request must not be counted as overdue.
        self.assertEqual(result["processed"], self._count_overdue_pending())

    def _count_overdue_pending(self):
        return frappe.db.count(
            "Membership Termination Request",
            {"status": "Pending", "request_date": ["<", add_days(today(), -7)]},
        )

    def test_process_overdue_counts_old_pending(self):
        member = self._make_member()
        req = self._make_termination_request(member, status="Pending")
        # Backdate the request_date to make it overdue (>7 days).
        frappe.db.set_value(
            "Membership Termination Request", req.name, "request_date", add_days(today(), -10)
        )
        result = tu.process_overdue_termination_requests()
        self.assertGreaterEqual(result["processed"], 1)

    # ==================================================================
    # generate_weekly_termination_report
    # ==================================================================
    def test_weekly_report_with_recent_request(self):
        member = self._make_member()
        self._make_termination_request(member, status="Pending", termination_type="Voluntary")
        report = tu.generate_weekly_termination_report()
        # report contains aggregated structure (not the "no requests" message)
        self.assertIn("total_requests", report)
        self.assertGreaterEqual(report["total_requests"], 1)
        self.assertIn("Voluntary", report["by_type"])
        self.assertIn("Pending", report["by_status"])
        self.assertGreaterEqual(report["pending_count"], 1)

    def test_weekly_report_counts_executed(self):
        member = self._make_member()
        # Executed requests need execution fields; insert as Pending then set status.
        req = self._make_termination_request(member, status="Pending")
        frappe.db.set_value("Membership Termination Request", req.name, "status", "Executed")
        report = tu.generate_weekly_termination_report()
        self.assertGreaterEqual(report["executed_count"], 1)

    # ==================================================================
    # audit_termination_compliance
    # ==================================================================
    def test_audit_compliance_clean_shape(self):
        result = tu.audit_termination_compliance()
        for key in ("orphaned_records", "stale_requests", "compliance_issues", "data_integrity_issues"):
            self.assertIn(key, result)

    def test_audit_compliance_valid_request_not_flagged_orphaned(self):
        """Regression: a request for an EXISTING member must not be reported as
        orphaned.

        The audit previously joined `mtr.member_name` (a Data field fetched from
        member.full_name) against `tabMember.name` (the ID). Since a person's
        name never equals the Member ID, every request was flagged orphaned. The
        join must use the `member` Link field. Asserts our valid request's name
        does not appear in any data_integrity_issue.
        """
        member = self._make_member()
        req = self._make_termination_request(member, status="Pending")
        result = tu.audit_termination_compliance()
        self.assertFalse(
            any(req.name in issue for issue in result["data_integrity_issues"]),
            "a request for an existing member must not be flagged as orphaned",
        )

    def test_audit_compliance_flags_stale_approved_request(self):
        member = self._make_member()
        req = self._make_termination_request(member, status="Approved")
        frappe.db.set_value(
            "Membership Termination Request", req.name, "request_date", add_days(today(), -40)
        )
        result = tu.audit_termination_compliance()
        self.assertGreaterEqual(result["stale_requests"], 1)
        self.assertTrue(
            any(req.name in issue for issue in result["compliance_issues"]),
            "stale request should be reported by name in compliance_issues",
        )

    def test_audit_compliance_flags_duplicate_active_requests(self):
        member = self._make_member()
        self._make_termination_request(member, status="Draft")
        self._make_termination_request(member, status="Pending")
        result = tu.audit_termination_compliance()
        self.assertTrue(
            any(
                member.name in issue and "active termination" in issue
                for issue in result["compliance_issues"]
            ),
            "member with 2 active requests should be flagged as duplicate",
        )
