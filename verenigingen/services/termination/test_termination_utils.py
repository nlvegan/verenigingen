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
        # The harness-OWNED company, by name -- not a scan. The chain this replaces fell
        # back to `get_value("Company", {"default_currency": "EUR"}, "name")`, which is the
        # NEWEST EUR company (`db.get_value` defaults to `creation DESC`), i.e. whatever a
        # co-tenant suite created last. Pinned in
        # test_termination_integration_extra_coverage.test_get_company_never_borrows_by_currency.
        company = self._get_test_company()
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

    def test_validate_readiness_counts_onboarding_and_new_volunteers(self):
        """Full activation leaves an Onboarding volunteer holding the Volunteer profile (#1612)."""
        for status in ("Onboarding", "New"):
            member = self._make_member()
            self.create_test_volunteer(member_name=member.name, status=status)
            result = tu.validate_termination_readiness(member.name)
            self.assertEqual(result["impact"]["volunteer_records"], 1, status)

        inactive = self._make_member()
        self.create_test_volunteer(member_name=inactive.name, status="Inactive")
        self.assertEqual(
            tu.validate_termination_readiness(inactive.name)["impact"]["volunteer_records"], 0, "control"
        )

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

    def test_audit_compliance_same_fullname_different_members_not_duplicate(self):
        """Two DIFFERENT members that share the same full_name, each with one
        active request, must NOT be flagged as duplicates.

        This is the strongest discriminator for the GROUP BY fix: grouping on
        member_name (full_name) would wrongly collapse them into one group of 2
        and flag a duplicate; grouping on the `member` ID keeps them separate.
        """
        m1 = self._make_member()
        m2 = self._make_member()
        # The factory uniquifies names, so force an identical full_name (the
        # field the OLD audit wrongly grouped on) onto both distinct members.
        shared_full_name = f"Shared Name {frappe.generate_hash(length=6)}"
        frappe.db.set_value("Member", m1.name, "full_name", shared_full_name)
        frappe.db.set_value("Member", m2.name, "full_name", shared_full_name)
        self.assertNotEqual(m1.name, m2.name)
        self._make_termination_request(m1, status="Pending")
        self._make_termination_request(m2, status="Pending")
        result = tu.audit_termination_compliance()
        # OLD code grouped by member_name (the now-shared full_name) and would
        # emit a duplicate issue mentioning that name. NEW code groups by the
        # member ID and must not. Check both the IDs and the shared name so the
        # assertion fails against the OLD grouping regardless of which field the
        # message echoes.
        self.assertFalse(
            any(
                "active termination" in issue
                and (m1.name in issue or m2.name in issue or shared_full_name in issue)
                for issue in result["compliance_issues"]
            ),
            "distinct members sharing a full_name must not be flagged as duplicates",
        )

    # ==================================================================
    # audit_termination_compliance: Quit member with no Executed request (#1777)
    # ==================================================================
    def _execute_termination_through_service(self, member):
        """Terminate `member` through the real TerminationExecutionService."""
        from unittest.mock import patch

        from verenigingen.services.termination import TerminationExecutionService

        req = self._make_termination_request(
            member, status="Approved", approved_by=frappe.session.user, approval_date=frappe.utils.now()
        )
        req.submit()
        # Same transaction patching as test_termination_execution_service: execute() commits.
        with patch("frappe.db.begin"), patch("frappe.db.commit"), patch("frappe.db.rollback"):
            TerminationExecutionService().execute(req)
        return req

    def _quit_integrity_error_logs(self, member_name):
        return frappe.get_all(
            "Error Log",
            filters={
                "method": "Quit Member Without Executed Termination",
                "error": ["like", f"%{member_name}%"],
            },
            pluck="name",
        )

    def test_audit_flags_quit_member_without_executed_termination(self):
        """A Quit member with no Executed request is reported; one terminated through
        the real service is not.

        The flagged state is built with a DIRECT status write: no flow that goes through
        the termination service produces it (execute() sets Quit and the Executed request
        together). The real producers are outside it: a hand edit of Member.status, and the
        CSV import, which sets Quit for 'opgezegd' rows with `_skip_status_validation`.
        """
        self.expectErrorLog("Quit Member Without Executed Termination")
        terminated = self._make_member()
        self._execute_termination_through_service(terminated)
        self.assertEqual(frappe.db.get_value("Member", terminated.name, "status"), "Quit")

        orphan = self._make_member()
        frappe.db.set_value("Member", orphan.name, "status", "Quit")  # probe shortcut, see docstring

        result = tu.audit_termination_compliance()

        self.assertGreaterEqual(result["quit_without_termination"], 1)
        self.assertTrue(any(orphan.name in i for i in result["data_integrity_issues"]))
        self.assertFalse(any(terminated.name in i for i in result["data_integrity_issues"]))
        self.assertTrue(self._quit_integrity_error_logs(orphan.name), "operator gets an Error Log row")
        self.assertFalse(self._quit_integrity_error_logs(terminated.name))

    def test_audit_quit_member_with_only_unexecuted_request_is_flagged(self):
        """Control: a Quit member whose request is Approved (not Executed) still counts."""
        self.expectErrorLog("Quit Member Without Executed Termination")
        member = self._make_member()
        self._make_termination_request(member, status="Approved")
        frappe.db.set_value("Member", member.name, "status", "Quit")  # probe shortcut
        result = tu.audit_termination_compliance()
        self.assertTrue(any(member.name in i for i in result["data_integrity_issues"]))

    def test_audit_non_quit_member_without_termination_not_flagged(self):
        """Control: only status Quit is in scope (Active/Inactive members have no request)."""
        member = self._make_member()
        result = tu.audit_termination_compliance()
        self.assertFalse(any(member.name in i for i in result["data_integrity_issues"]))

    def test_quit_only_finding_reaches_the_admin_alert(self):
        """A run whose ONLY finding is a Quit member without a termination notifies admins.

        Real spy on the notification boundary (wraps the real function, so the notification
        still runs): `total_issues > 0` alone does not send, the notify condition must name
        this finding. Needs a site with no orphaned/stale requests, else the other branch
        notifies and this proves nothing -- asserted below.
        """
        from unittest.mock import patch  # Mock justified: spy on the notification boundary

        from verenigingen.utils import notification_helpers

        self.expectErrorLog("Quit Member Without Executed Termination")
        member = self._make_member()
        frappe.db.set_value("Member", member.name, "status", "Quit")  # probe shortcut
        with patch.object(
            notification_helpers, "notify_administrators", wraps=notification_helpers.notify_administrators
        ) as spy:
            result = tu.audit_termination_compliance()
        self.assertEqual(result["orphaned_records"], 0, "site must have no other trigger")
        self.assertLessEqual(result["stale_requests"], 5, "site must have no other trigger")
        spy.assert_called_once()
        self.assertIn("Quit Without Executed Termination", spy.call_args.kwargs["message"])

    def test_quit_check_failure_does_not_skip_other_findings(self):
        """An exception inside the Quit check is logged and the audit still returns its results."""
        from unittest.mock import patch  # Mock justified: force a DB failure inside the new check

        self.expectErrorLog("Quit Member Integrity Check Error")
        with patch.object(
            tu, "get_quit_members_without_executed_termination", side_effect=RuntimeError("boom")
        ):
            result = tu.audit_termination_compliance()
        self.assertNotIn("error", result)
        self.assertIn("orphaned_records", result)

    def test_quit_finding_error_log_is_capped(self):
        """The Error Log message lists at most QUIT_FINDING_LIST_CAP names plus the total."""
        from unittest.mock import patch  # Mock justified: avoid creating 50+ members

        self.expectErrorLog("Quit Member Without Executed Termination")
        names = [f"FAKE-{i:04d}" for i in range(tu.QUIT_FINDING_LIST_CAP + 7)]
        with patch.object(tu, "get_quit_members_without_executed_termination", return_value=names):
            tu.audit_termination_compliance()
        row = frappe.get_all(
            "Error Log",
            filters={"method": "Quit Member Without Executed Termination", "error": ["like", "%FAKE-0000%"]},
            fields=["error"],
            limit=1,
            order_by="creation desc",
        )[0]
        self.assertIn(str(len(names)), row.error)
        self.assertIn(names[tu.QUIT_FINDING_LIST_CAP - 1], row.error)
        self.assertNotIn(names[tu.QUIT_FINDING_LIST_CAP], row.error)
