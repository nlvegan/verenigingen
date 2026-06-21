# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for verenigingen.utils.department_hierarchy.

This module aligns the association's chapter/team/board structure with ERPNext
(HRMS) Departments so expense claims route to the right approvers. The tests
below exercise it against the real DB the way production does — creating real
Chapter / Chapter Board Member / Team / Volunteer / Department fixtures and
deriving expected department names from that data.

Transaction safety: the manager writes Departments and Users exclusively via
`secure_document_operation` (which does NOT commit) and via
`frappe.db.set_value` (also no commit), so every write rolls back with the test
transaction. We never invoke a path that commits to global state.

Covered:
- DepartmentHierarchyManager.__init__ (company guard)
- get_volunteer_department (board / team-lead / team-member / default priorities,
  national vs chapter-linked team branches)
- _ensure_department (create + idempotent return)
- _get_financial_approvers (role priority, disabled/missing user skips, empty)
- _update_department_approvers (missing dept, valid approvers, no-valid-approver)
- sync_chapter_approvers_for_chapter (missing chapter, real sync)
- update_employee_departments (employee + department existence branches)
- update_volunteer_employee_department hook
- whitelist get_volunteer_department
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.department_hierarchy import (
    DepartmentHierarchyManager,
    get_volunteer_department,
)


class TestDepartmentHierarchy(EnhancedTestCase):
    # ------------------------------------------------------------------ helpers
    def _ensure_company(self):
        """Make sure Verenigingen Settings has a company so __init__ works.

        Returns the configured company. We do not mutate-and-commit: set_value
        without commit is rolled back with the transaction, and if a company is
        already configured we leave it untouched.
        """
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if not company:
            company = frappe.db.get_value("Company", {}, "name")
            self.assertIsNotNone(company, "Need at least one Company to test department hierarchy")
            frappe.db.set_value("Verenigingen Settings", "Verenigingen Settings", "company", company)
        return company

    def _ensure_chapter_role(self, role_name):
        """Create a Chapter Role with the exact (financial) name the manager filters on."""
        if not frappe.db.exists("Chapter Role", role_name):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Financial",
                    "is_active": 1,
                }
            )
            role.insert()
            self._track_test_document("Chapter Role", role.name, priority=3)
        return role_name

    def _make_chapter(self, published=1):
        return self.factory.create_chapter(published=published, region="Test Region DH")

    def _add_board_member(self, chapter_name, volunteer_name, chapter_role, is_active=1, from_dt=None):
        chapter_doc = frappe.get_doc("Chapter", chapter_name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": chapter_role,
                "from_date": from_dt or today(),
                "is_active": is_active,
            },
        )
        chapter_doc.save()
        return chapter_doc

    def _make_team(self, chapter=None, team_type="Project Team"):
        kwargs = {"team_type": team_type}
        if chapter:
            kwargs["chapter"] = chapter
        return self.factory.create_team(**kwargs)

    def _add_team_member(self, team_name, volunteer_name, role=None):
        """Append a Team Member, setting the legacy free-text `role` Data column
        that get_volunteer_department's SQL actually filters on."""
        team = frappe.get_doc("Team", team_name)
        tm = self.factory.create_team_member(team_name, volunteer_name)
        # create_team_member sets team_role (Link) but the production SQL reads
        # the legacy `role` Data field — set it directly on the persisted row.
        if role is not None:
            team.reload()
            team.team_members[-1].role = role
            team.save()
        return tm

    # ------------------------------------------------------------------ __init__
    def test_init_uses_configured_company(self):
        company = self._ensure_company()
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.company, company)

    def test_init_throws_without_company(self):
        # Temporarily blank the company (rolled back with the transaction).
        original = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_value("Verenigingen Settings", "Verenigingen Settings", "company", "")
        frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")
        try:
            with self.assertRaises(frappe.ValidationError):
                DepartmentHierarchyManager()
        finally:
            frappe.db.set_value("Verenigingen Settings", "Verenigingen Settings", "company", original)
            frappe.clear_document_cache("Verenigingen Settings", "Verenigingen Settings")

    # ----------------------------------------------- get_volunteer_department
    def test_volunteer_department_default_no_assignments(self):
        self._ensure_company()
        vol = self.factory.create_volunteer()
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.get_volunteer_department(vol.name), "National Organization")

    def test_volunteer_department_board_position_priority(self):
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        chapter = self._make_chapter()
        vol = self.factory.create_volunteer()
        self._add_board_member(chapter.name, vol.name, "Treasurer")
        mgr = DepartmentHierarchyManager()
        # Board position wins -> "Chapter {chapter} Board"
        self.assertEqual(mgr.get_volunteer_department(vol.name), f"Chapter {chapter.name} Board")

    def test_volunteer_department_team_lead_chapter_linked(self):
        self._ensure_company()
        chapter = self._make_chapter()
        team = self._make_team(chapter=chapter.name)
        vol = self.factory.create_volunteer()
        self._add_team_member(team.name, vol.name, role="Team Lead")
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.get_volunteer_department(vol.name), f"Chapter {chapter.name} Teams")

    def test_volunteer_department_team_lead_national(self):
        self._ensure_company()
        team = self._make_team(chapter=None, team_type="Working Group")
        vol = self.factory.create_volunteer()
        self._add_team_member(team.name, vol.name, role="Team Coordinator")
        mgr = DepartmentHierarchyManager()
        expected = f"{team.team_name} ({team.team_type or 'Team'})"
        self.assertEqual(mgr.get_volunteer_department(vol.name), expected)

    def test_volunteer_department_regular_member_chapter_linked(self):
        self._ensure_company()
        chapter = self._make_chapter()
        team = self._make_team(chapter=chapter.name)
        vol = self.factory.create_volunteer()
        # Plain member (role not a leadership role) -> priority 3
        self._add_team_member(team.name, vol.name, role="Member")
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.get_volunteer_department(vol.name), f"Chapter {chapter.name} Volunteers")

    def test_volunteer_department_regular_member_national_team(self):
        self._ensure_company()
        team = self._make_team(chapter=None)
        vol = self.factory.create_volunteer()
        self._add_team_member(team.name, vol.name, role="Member")
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.get_volunteer_department(vol.name), "National Teams")

    def test_volunteer_department_inactive_board_ignored(self):
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        chapter = self._make_chapter()
        vol = self.factory.create_volunteer()
        # Inactive board member -> should fall through to default
        self._add_board_member(chapter.name, vol.name, "Treasurer", is_active=0)
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr.get_volunteer_department(vol.name), "National Organization")

    # ------------------------------------------------------- _create_team_departments
    def test_create_team_departments_interpolates_team_name(self):
        """REGRESSION (BUG 3): _create_team_departments built dept_name from a
        non-f-string literal ("{team.team_name} ({team.team_type ...})"), so the
        created Department was literally named "{team.team_name} (...)" instead
        of the real team name. That literal then never matched the correctly
        f-stringed lookup in get_volunteer_department, breaking team-department
        routing entirely.

        We create a real national (chapter-less) Team and run
        _create_team_departments, then assert a Department exists whose
        department_name is the correctly interpolated value and that the literal
        placeholder name was NOT created.

        secure_document_operation does not commit, so the created Departments
        roll back with the test transaction.
        """
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        # The "National Teams" parent must exist for the team dept to attach.
        mgr._ensure_department("National Teams", parent=None)

        team = self._make_team(chapter=None, team_type="Working Group")
        expected_name = f"{team.team_name} ({team.team_type or 'Team'})"
        literal_name = "{team.team_name} ({team.team_type or 'Team'})"

        mgr._create_team_departments()

        # The literal, un-interpolated department must NOT have been created.
        self.assertIsNone(
            frappe.db.get_value("Department", {"department_name": literal_name}, "name"),
            "literal placeholder department should never be created (missing f-prefix bug)",
        )
        # The correctly interpolated department MUST exist.
        self.assertTrue(
            frappe.db.get_value("Department", {"department_name": expected_name}, "name"),
            f"expected a Department named {expected_name!r} for the national team",
        )

    # ------------------------------------------------------- _ensure_department
    def test_ensure_department_creates_then_returns_existing(self):
        company = self._ensure_company()
        mgr = DepartmentHierarchyManager()
        dept_name = f"DH Test Dept {frappe.generate_hash(length=6)}"
        full_name = f"{dept_name} - {frappe.get_cached_value('Company', company, 'abbr')}"
        self.assertFalse(frappe.db.exists("Department", full_name))

        created = mgr._ensure_department(dept_name, parent=None)
        self.assertTrue(frappe.db.exists("Department", created.name))
        self.assertEqual(created.company, company)

        # Idempotent: second call returns the existing doc, not a duplicate
        again = mgr._ensure_department(created.department_name, parent=None)
        self.assertEqual(again.name, created.name)

    # --------------------------------------------------- _get_financial_approvers
    def test_financial_approvers_empty_when_no_board(self):
        self._ensure_company()
        chapter = self._make_chapter()
        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr._get_financial_approvers(chapter.name), [])

    def test_financial_approvers_returns_enabled_user_email(self):
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        chapter = self._make_chapter()
        # Volunteer whose linked Member has a User -> enabled email
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        member = self.factory.create_member(email=user.email)
        member.user = user.email
        member.save()
        vol = self.factory.create_volunteer(member_name=member.name, email=user.email, _exact_email=True)
        self._add_board_member(chapter.name, vol.name, "Treasurer")

        mgr = DepartmentHierarchyManager()
        approvers = mgr._get_financial_approvers(chapter.name)
        self.assertEqual(approvers, [user.email])

    def test_financial_approvers_skips_disabled_user(self):
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        chapter = self._make_chapter()
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        frappe.db.set_value("User", user.email, "enabled", 0)
        member = self.factory.create_member(email=user.email)
        member.user = user.email
        member.save()
        vol = self.factory.create_volunteer(member_name=member.name, email=user.email, _exact_email=True)
        self._add_board_member(chapter.name, vol.name, "Treasurer")

        mgr = DepartmentHierarchyManager()
        # Disabled user is skipped -> no valid approver
        self.assertEqual(mgr._get_financial_approvers(chapter.name), [])

    def test_financial_approvers_role_priority(self):
        """Treasurer outranks Board Chair regardless of insertion order."""
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        self._ensure_chapter_role("Board Chair")
        chapter = self._make_chapter()

        chair_user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        chair_member = self.factory.create_member(email=chair_user.email)
        chair_member.user = chair_user.email
        chair_member.save()
        chair_vol = self.factory.create_volunteer(
            member_name=chair_member.name, email=chair_user.email, _exact_email=True
        )

        treas_user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        treas_member = self.factory.create_member(email=treas_user.email)
        treas_member.user = treas_user.email
        treas_member.save()
        treas_vol = self.factory.create_volunteer(
            member_name=treas_member.name, email=treas_user.email, _exact_email=True
        )

        # Add chair first, treasurer second
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {"volunteer": chair_vol.name, "chapter_role": "Board Chair", "from_date": today(), "is_active": 1},
        )
        chapter_doc.append(
            "board_members",
            {"volunteer": treas_vol.name, "chapter_role": "Treasurer", "from_date": today(), "is_active": 1},
        )
        chapter_doc.save()

        mgr = DepartmentHierarchyManager()
        self.assertEqual(mgr._get_financial_approvers(chapter.name), [treas_user.email])

    # ------------------------------------------------ _update_department_approvers
    def test_update_department_approvers_missing_department_noop(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        # Non-existent department: returns without error
        mgr._update_department_approvers(
            f"Nonexistent Dept {frappe.generate_hash(length=6)}", ["x@example.invalid"]
        )

    def test_update_department_approvers_sets_valid_approvers(self):
        company = self._ensure_company()
        mgr = DepartmentHierarchyManager()
        dept = mgr._ensure_department(f"DH Approver Dept {frappe.generate_hash(length=6)}", parent=None)
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])

        mgr._update_department_approvers(dept.name, [user.email])
        dept.reload()
        approver_emails = [r.approver for r in dept.expense_approvers]
        self.assertIn(user.email, approver_emails)
        self.assertEqual(len(approver_emails), 1)

    def test_update_department_approvers_drops_unknown_user(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        dept = mgr._ensure_department(f"DH Approver Dept2 {frappe.generate_hash(length=6)}", parent=None)
        # No valid users -> approvers untouched (stays empty)
        mgr._update_department_approvers(dept.name, ["ghost-user@example.invalid"])
        dept.reload()
        self.assertEqual(len(dept.expense_approvers), 0)

    # ------------------------------------------ sync_chapter_approvers_for_chapter
    def test_sync_chapter_approvers_missing_chapter_warns(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        # Missing chapter -> logs warning and returns (no raise)
        with self.assertNoErrorLog():
            mgr.sync_chapter_approvers_for_chapter(f"No Such Chapter {frappe.generate_hash(length=6)}")

    def test_sync_chapter_approvers_updates_department(self):
        self._ensure_company()
        self._ensure_chapter_role("Treasurer")
        chapter = self._make_chapter()
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        member = self.factory.create_member(email=user.email)
        member.user = user.email
        member.save()
        vol = self.factory.create_volunteer(member_name=member.name, email=user.email, _exact_email=True)
        self._add_board_member(chapter.name, vol.name, "Treasurer")

        mgr = DepartmentHierarchyManager()
        # Pre-create the target departments so the sync has something to write to
        board_dept = mgr._ensure_department(f"Chapter {chapter.name} Board", parent=None)
        parent_dept = mgr._ensure_department(f"Chapter {chapter.name}", parent=None)

        mgr.sync_chapter_approvers_for_chapter(chapter.name)

        board_dept.reload()
        parent_dept.reload()
        self.assertIn(user.email, [r.approver for r in board_dept.expense_approvers])
        self.assertIn(user.email, [r.approver for r in parent_dept.expense_approvers])

    # -------------------------------------------- update_employee_departments
    def test_update_employee_departments_no_employee(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        # Volunteer without employee_id -> filtered out by employee_id != "" filter
        vol = self.factory.create_volunteer()
        self.assertEqual(mgr.update_employee_departments(volunteer_name=vol.name), 0)

    def test_update_employee_departments_sets_existing_department(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        # Build a national team membership so the resolved department is "National Teams"
        team = self._make_team(chapter=None)
        vol = self.factory.create_volunteer()
        self._add_team_member(team.name, vol.name, role="Member")

        # Create a real Employee and link it to the volunteer
        employee = self._make_employee()
        frappe.db.set_value("Volunteer", vol.name, "employee_id", employee.name)

        # Ensure the resolved department exists so the update path runs
        mgr._ensure_department("National Teams", parent=None)

        updated = mgr.update_employee_departments(volunteer_name=vol.name)
        self.assertEqual(updated, 1)
        self.assertEqual(
            frappe.db.get_value("Employee", employee.name, "department"),
            frappe.get_value("Department", {"department_name": "National Teams"}, "name"),
        )

    def test_update_employee_departments_skips_missing_department(self):
        self._ensure_company()
        mgr = DepartmentHierarchyManager()
        vol = self.factory.create_volunteer()  # resolves to "National Organization"
        employee = self._make_employee()
        frappe.db.set_value("Volunteer", vol.name, "employee_id", employee.name)
        # Do NOT create the "National Organization" department -> update skipped
        if frappe.db.exists("Department", {"department_name": "National Organization"}):
            self.skipTest("National Organization department already exists on this site")
        self.assertEqual(mgr.update_employee_departments(volunteer_name=vol.name), 0)

    # ----------------------------------------- update_volunteer_employee_department
    def test_hook_sets_department_when_exists(self):
        from verenigingen.utils.department_hierarchy import update_volunteer_employee_department

        self._ensure_company()
        team = self._make_team(chapter=None)
        vol = self.factory.create_volunteer()
        self._add_team_member(team.name, vol.name, role="Member")
        employee = self._make_employee()
        frappe.db.set_value("Volunteer", vol.name, "employee_id", employee.name)

        DepartmentHierarchyManager()._ensure_department("National Teams", parent=None)
        vol.reload()
        update_volunteer_employee_department(vol, "on_update")
        self.assertEqual(
            frappe.db.get_value("Employee", employee.name, "department"),
            frappe.get_value("Department", {"department_name": "National Teams"}, "name"),
        )

    def test_hook_noop_without_employee(self):
        from verenigingen.utils.department_hierarchy import update_volunteer_employee_department

        self._ensure_company()
        vol = self.factory.create_volunteer()
        vol.reload()
        # No employee_id -> early return, no raise
        update_volunteer_employee_department(vol, "on_update")

    # ----------------------------------------------- whitelist get_volunteer_department
    def test_whitelist_get_volunteer_department(self):
        self._ensure_company()
        vol = self.factory.create_volunteer()
        self.assertEqual(get_volunteer_department(vol.name), "National Organization")

    # ------------------------------------------------------------------ employee
    def _make_employee(self):
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"DHTest{frappe.generate_hash(length=5)}",
                "company": company,
                "status": "Active",
                "date_of_joining": today(),
                "gender": "Other",
                "date_of_birth": "1990-01-01",
            }
        )
        emp.insert()
        self._track_test_document("Employee", emp.name, priority=2)
        return emp
