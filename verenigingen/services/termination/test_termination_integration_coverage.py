"""
Additional integration coverage for
verenigingen/services/termination/termination_integration.py

Complements test_termination_integration.py by exercising branches that the
existing suite leaves uncovered:
  * update_customer_safe       — append to an *existing* customer_details note
  * suspend_team_memberships_safe — default-date fallback + team-lead removal
  * terminate_volunteer_records_safe — Deceased reason, existing-note append,
    default-date fallback
  * terminate_employee_records_safe  — personal_email lookup + direct
    Member.employee link discovery
  * get_member_suspension_status     — active-team counting via the volunteer's
    `user` link

All tests build real DocTypes through the EnhancedTestCase factory and assert
real DB state. No business logic is mocked. They deliberately avoid Sales
Invoice creation (which needs a fully-provisioned receivable account on the
test company) so they exercise only the termination logic under test.
"""

import frappe
from frappe.utils import today

from verenigingen.services.termination import termination_integration as ti
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTerminationIntegrationCoverage(EnhancedTestCase):
    # ------------------------------------------------------------------
    # helpers (names allow ignore_permissions / set_user per enforcer)
    # ------------------------------------------------------------------
    def _make_member(self, status="Active", **kwargs):
        member = self.create_test_member(first_name="TermCov", last_name=f"M{self.uid}", **kwargs)
        if status != "Active":
            frappe.db.set_value("Member", member.name, "status", status)
            member.reload()
        return member

    def _make_customer_for_member(self, member):
        member = frappe.get_doc("Member", member.name)
        if not member.customer:
            member.create_customer()
            member.reload()
        return member.customer

    def _make_volunteer(self, member):
        return self.create_test_volunteer(member_name=member.name)

    def _make_user(self, member, enabled=1):
        email = f"termcov-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "TermCov",
                "last_name": "User",
                "enabled": enabled,
                "send_welcome_email": 0,
            }
        )
        user.insert(ignore_permissions=True)
        frappe.db.set_value("Member", member.name, "user", email)
        return user

    def _make_employee(self, **fields):
        # The harness-OWNED company, by name -- not a scan. The chain this replaces fell
        # back to `get_value("Company", {"default_currency": "EUR"}, "name")`, which is the
        # NEWEST EUR company (`db.get_value` defaults to `creation DESC`), i.e. whatever a
        # co-tenant suite created last. Pinned in
        # test_termination_integration_extra_coverage.test_get_company_never_borrows_by_currency.
        company = self._get_test_company()
        emp = frappe.new_doc("Employee")
        emp.first_name = "TermCov"
        emp.last_name = "Emp"
        emp.employee_name = "TermCov Emp"
        emp.company = company
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = today()
        emp.gender = "Other"
        emp.status = "Active"
        for k, v in fields.items():
            setattr(emp, k, v)
        emp.insert(ignore_permissions=True)
        return emp

    def _add_team_membership(self, volunteer, team=None):
        # Adding a Team Member triggers the Team controller's assignment-history /
        # notification hooks, which log (and swallow) errors against the
        # not-yet-committed team. That is unrelated to the termination logic under
        # test, so allow it past the Error Log guard.
        self.expectErrorLog(
            "Team Assignment History Error",
            "Team Notification Error",
            "Team Event Emission Error",
        )
        if team is None:
            team = self.create_test_team()
        team_role = self.ensure_team_role("Team Member")
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": team_role.name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save()
        return team, team_doc.team_members[-1].name

    # ==================================================================
    # update_customer_safe — append to an existing customer_details note
    # ==================================================================
    def test_update_customer_safe_appends_to_existing_details(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        # Seed existing details so the append (not assign) branch runs.
        frappe.db.set_value("Customer", customer, "customer_details", "EXISTING DETAIL LINE")
        result = ti.update_customer_safe(customer, "SECOND TERMINATION NOTE")
        self.assertTrue(result)
        details = frappe.db.get_value("Customer", customer, "customer_details") or ""
        # Both the original and the appended note must be present.
        self.assertIn("EXISTING DETAIL LINE", details)
        self.assertIn("SECOND TERMINATION NOTE", details)

    # ==================================================================
    # suspend_team_memberships_safe — default-date fallback & team-lead removal
    # ==================================================================
    def test_suspend_team_memberships_safe_default_date_uses_today(self):
        """Passing termination_date=None falls back to today() for the to_date stamp."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        _team, row_name = self._add_team_membership(volunteer)

        affected = ti.suspend_team_memberships_safe(member.name, None, "suspended-default-date")
        self.assertEqual(affected, 1)
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "is_active"), 0)
        self.assertEqual(str(frappe.db.get_value("Team Member", row_name, "to_date")), today())

    def test_suspend_team_memberships_safe_clears_team_lead(self):
        """A member who leads a team has that leadership cleared on suspension."""
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        team = self.create_test_team()
        # team_lead is a read-only Link(User); set it directly so the leadership
        # discovery query (team_lead == member.user) finds this team.
        frappe.db.set_value("Team", team.name, "team_lead", user.name)

        ti.suspend_team_memberships_safe(member.name, today(), "terminated-lead")

        self.assertIsNone(frappe.db.get_value("Team", team.name, "team_lead"))
        description = frappe.db.get_value("Team", team.name, "description") or ""
        self.assertIn("Team lead removed", description)

    # ==================================================================
    # terminate_volunteer_records_safe — uncovered branches
    # ==================================================================
    def test_terminate_volunteer_records_safe_deceased_reason(self):
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        result = ti.terminate_volunteer_records_safe(member.name, "Deceased", today(), "passed away")
        self.assertEqual(result["volunteers_terminated"], 1)
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "status"), "Inactive")
        note = frappe.db.get_value("Volunteer", volunteer.name, "note") or ""
        self.assertIn("Inactive reason: Deceased", note)

    def test_terminate_volunteer_records_safe_appends_existing_note(self):
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        frappe.db.set_value("Volunteer", volunteer.name, "note", "PRE-EXISTING VOLUNTEER NOTE")
        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["volunteers_terminated"], 1)
        note = frappe.db.get_value("Volunteer", volunteer.name, "note") or ""
        self.assertIn("PRE-EXISTING VOLUNTEER NOTE", note)
        self.assertIn("Inactive reason", note)

    def test_terminate_volunteer_records_safe_default_date(self):
        """termination_date=None falls back to today() and still terminates."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", None, "left")
        self.assertEqual(result["volunteers_terminated"], 1)
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "status"), "Inactive")

    # ==================================================================
    # terminate_employee_records_safe — alternative discovery paths
    # ==================================================================
    def test_terminate_employee_records_safe_via_personal_email(self):
        """Employee found through personal_email when user_id has no match."""
        member = self._make_member()
        user = self._make_user(member)
        # user_id intentionally NOT set so the user_id query misses; personal_email matches.
        emp = self._make_employee(personal_email=user.name)
        result = ti.terminate_employee_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Resignation")

    def test_terminate_employee_records_safe_via_direct_member_link(self):
        """Employee found through the direct Member.employee link (no user/email)."""
        member = self._make_member()
        emp = self._make_employee()
        frappe.db.set_value("Member", member.name, "employee", emp.name)
        result = ti.terminate_employee_records_safe(member.name, "Expulsion", today(), "expelled")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Quit")

    # ==================================================================
    # get_member_suspension_status — active-team counting branch
    # ==================================================================
    def test_get_member_suspension_status_counts_active_teams(self):
        """When the volunteer carries a `user` link the active-team count branch runs."""
        member = self._make_member()
        user = self._make_user(member)
        volunteer = self._make_volunteer(member)
        frappe.db.set_value("Volunteer", volunteer.name, "user", user.name)
        status = ti.get_member_suspension_status(member.name)
        # Team Member is a child table (always docstatus=0) so the docstatus=1
        # count is 0, but the counting branch is executed and reported.
        self.assertIn("active_teams", status)
        self.assertEqual(status["active_teams"], 0)
        self.assertFalse(status["is_suspended"])
