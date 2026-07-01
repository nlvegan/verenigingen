#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Permission System Coverage Tests -- Document-level checks & role maintenance
============================================================================

Second-wave real-integration coverage for ``verenigingen/permissions.py``,
targeting the security-critical branches the existing suites
(``test_permissions_coverage``, ``test_member_permissions``,
``test_donor_permissions``) do NOT exercise:

- ``has_member_permission`` -- the Member DocType document-level check
  (admin bypass, service-account deferral, chapter-board scoping + the
  termination-request fallback, member self-access, owner fallback, and the
  no-role deny). Previously ENTIRELY uncovered.
- ``has_membership_termination_request_permission`` -- the Termination Request
  document-level check (admin, chapter-board grant + cross-chapter deny, the
  no-member and no-role deny paths, str + doc call shapes). Previously ENTIRELY
  uncovered.
- ``has_volunteer_permission`` chapter-board branch and the dangling-member /
  no-user-member guard branches (the existing suite only exercises the member
  and team-leader branches).
- ``get_team_member_permission_query`` positive path: a team member seeing
  their teammates (execution-based, in-scope visible / out-of-scope excluded).
- ``can_view_financial_info`` board-member-with-financial-permissions positive
  path (the existing suite only covers admin / self / deny).
- ``can_terminate_member`` national-board-chapter grant branch.
- ``assign_chapter_board_role`` / ``update_all_chapter_board_roles`` /
  ``_users_with_chapter_board_role`` -- the role-maintenance functions that
  add/remove the Chapter Board Member role based on active board positions.

All tests reuse the committed fixture graph from ``PermissionsCoverageBase``
(two chapters, a Financial board member of chapter A, a regular member of A, an
unrelated member of B, staff / admin / bare users) and act as real users. No
business logic is mocked -- every assertion is driven by real DocTypes and the
real permission functions.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.security.test_permissions_coverage import PermissionsCoverageBase
from verenigingen.utils.constants import Roles


def _ensure_neutral_role():
    """Idempotently ensure a permission-irrelevant Role exists, used to build a
    user that holds NONE of the member/board/staff/admin roles (a fresh User with
    an empty role list would still need at least one valid Role to save)."""
    role_name = "Verenigingen Perm Neutral"
    if not frappe.db.exists("Role", role_name):
        frappe.get_doc(
            {"doctype": "Role", "role_name": role_name, "desk_access": 1}
        ).insert(ignore_permissions=True)
    return role_name


class TestHasMemberPermission(PermissionsCoverageBase):
    """Full coverage for ``has_member_permission`` (permissions.py ~381-471)."""

    def test_admin_bypass(self):
        """Any ADMIN_ROLES holder (Verenigingen Staff is in ADMIN_ROLES) passes
        the admin bypass at the top of the function."""
        from verenigingen.permissions import has_member_permission

        # staff_user holds Verenigingen Staff which IS in ADMIN_ROLES.
        self.assertTrue(has_member_permission(self.regular_member.name, self.staff_user.name))

    def test_service_account_deferral_returns_bool(self):
        """A webhook service account defers to DocPerm and gets a concrete bool
        (never falls through to chapter logic)."""
        from verenigingen.permissions import has_member_permission

        webhook_user = self.create_test_user(
            email=f"perm-mp-webhook-{self.token}@test.com", roles=[Roles.WEBHOOK_USER]
        )
        result = has_member_permission(self.regular_member.name, webhook_user.name)
        self.assertIn(result, (True, False))

    def test_undeterminable_member_denied(self):
        """A doc from which no member name can be resolved (not a str, no .name)
        is denied."""
        from verenigingen.permissions import has_member_permission

        # An int has neither .name nor is a str -> member_name is None -> deny.
        self.assertFalse(has_member_permission(12345, self.regular_user.name))

    def test_chapter_board_sees_own_chapter_member(self):
        """A chapter board member reaches a member in their own chapter."""
        from verenigingen.permissions import has_member_permission

        self.assertTrue(has_member_permission(self.regular_member.name, self.board_user.name))

    def test_chapter_board_cross_chapter_with_termination_fallback(self):
        """A board member of chapter A must NOT reach a chapter-B member via the
        chapter path. A termination request exists for the B member so the
        termination-request fallback loop runs, but the board user has no
        termination access to a B member either, so access is still denied and
        the function falls through to the (also-failing) member/owner branch."""
        from verenigingen.permissions import has_member_permission

        # Termination request for the other-chapter member so the fallback loop
        # (permissions.py ~426-444) actually iterates.
        frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.other_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Coverage: board cross-chapter fallback",
                "request_date": today(),
                "requested_by": self.staff_user.name,
                "status": "Draft",
            }
        ).insert(ignore_permissions=True)

        self.assertFalse(has_member_permission(self.other_member.name, self.board_user.name))

    def test_member_self_access(self):
        """A regular member reaches their own Member record via the user link."""
        from verenigingen.permissions import has_member_permission

        self.assertTrue(has_member_permission(self.regular_member.name, self.regular_user.name))

    def test_member_other_record_denied_via_owner_string(self):
        """A regular member passed another member's NAME (str) fails the owner
        fallback (owner != user)."""
        from verenigingen.permissions import has_member_permission

        self.assertFalse(has_member_permission(self.other_member.name, self.regular_user.name))

    def test_member_other_record_denied_via_owner_doc(self):
        """Same deny, but exercising the doc-object owner branch (getattr owner)."""
        from verenigingen.permissions import has_member_permission

        other_doc = frappe.get_doc("Member", self.other_member.name)
        self.assertFalse(has_member_permission(other_doc, self.regular_user.name))

    def test_no_appropriate_role_denied(self):
        """A user with none of the member/board/staff/admin roles is denied even
        for a valid member record."""
        from verenigingen.permissions import has_member_permission

        no_role_user = self.create_test_user(
            email=f"perm-norole-{self.token}@test.com", roles=[_ensure_neutral_role()]
        )
        self.assertFalse(has_member_permission(self.regular_member.name, no_role_user.name))


class TestHasTerminationRequestPermission(PermissionsCoverageBase):
    """Full coverage for ``has_membership_termination_request_permission``
    (permissions.py ~1478-1523)."""

    def _make_request(self, member_name):
        return frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": member_name,
                "termination_type": "Voluntary",
                "termination_reason": "Coverage: termination request permission",
                "request_date": today(),
                "requested_by": self.staff_user.name,
                "status": "Draft",
            }
        ).insert(ignore_permissions=True)

    def test_admin_grant(self):
        from verenigingen.permissions import has_membership_termination_request_permission

        req = self._make_request(self.regular_member.name)
        self.assertTrue(
            has_membership_termination_request_permission(req.name, self.staff_user.name)
        )

    def test_board_grant_via_doc_with_member_attr(self):
        """The doc-with-.member shape (as Frappe hands to has_permission): a board
        member of the target's chapter is granted."""
        from verenigingen.permissions import has_membership_termination_request_permission

        doc = frappe._dict(member=self.regular_member.name, name="TR-doc-shape")
        self.assertTrue(
            has_membership_termination_request_permission(doc, self.board_user.name)
        )

    def test_board_grant_via_string_name(self):
        """The str shape: member is resolved from the DB, then chapter-board access
        is checked."""
        from verenigingen.permissions import has_membership_termination_request_permission

        req = self._make_request(self.regular_member.name)
        self.assertTrue(
            has_membership_termination_request_permission(req.name, self.board_user.name)
        )

    def test_board_cross_chapter_denied(self):
        """A board member of chapter A must NOT reach a termination request for a
        chapter-B member."""
        from verenigingen.permissions import has_membership_termination_request_permission

        req = self._make_request(self.other_member.name)
        self.assertFalse(
            has_membership_termination_request_permission(req.name, self.board_user.name)
        )

    def test_no_member_denied(self):
        """A request from which no member can be resolved is denied."""
        from verenigingen.permissions import has_membership_termination_request_permission

        doc = frappe._dict(member=None, name="TR-empty")
        self.assertFalse(
            has_membership_termination_request_permission(doc, self.board_user.name)
        )

    def test_non_board_role_denied(self):
        """A plain member (no board seat) is denied."""
        from verenigingen.permissions import has_membership_termination_request_permission

        req = self._make_request(self.regular_member.name)
        self.assertFalse(
            has_membership_termination_request_permission(req.name, self.regular_user.name)
        )


class TestHasVolunteerPermissionBranches(PermissionsCoverageBase):
    """Chapter-board and guard branches of ``has_volunteer_permission``
    (permissions.py ~474-568) not covered by the team-leader suite."""

    def test_admin_grant(self):
        from verenigingen.permissions import has_volunteer_permission

        vol = self.create_test_volunteer(self.regular_member.name)
        # staff_user is in VOLUNTEER_ADMIN_ROLES.
        self.assertTrue(has_volunteer_permission(vol.name, self.staff_user.name))

    def test_chapter_board_reaches_chapter_member_volunteer(self):
        """A board member of chapter A reaches the volunteer of a member in
        chapter A (the chapter-board branch, ~526-530)."""
        from verenigingen.permissions import has_volunteer_permission

        vol = self.create_test_volunteer(self.regular_member.name)
        self.assertTrue(has_volunteer_permission(vol.name, self.board_user.name))

    def test_chapter_board_denied_other_chapter_volunteer(self):
        """The board member of A must NOT reach the volunteer of a chapter-B
        member."""
        from verenigingen.permissions import has_volunteer_permission

        other_vol = self.create_test_volunteer(self.other_member.name)
        self.assertFalse(has_volunteer_permission(other_vol.name, self.board_user.name))

    def test_volunteer_without_linked_member_denied(self):
        """A volunteer whose ``member`` link is empty is denied for a non-admin
        (guard at ~508-511)."""
        from verenigingen.permissions import has_volunteer_permission

        vol = self.create_test_volunteer(self.regular_member.name)
        frappe.db.set_value("Volunteer", vol.name, "member", "")
        try:
            self.assertFalse(has_volunteer_permission(vol.name, self.regular_user.name))
        finally:
            frappe.db.set_value("Volunteer", vol.name, "member", self.regular_member.name)

    def test_acting_user_without_member_record_denied(self):
        """When the acting user has no Member record, access to any volunteer is
        denied (guard at ~514-517)."""
        from verenigingen.permissions import has_volunteer_permission

        vol = self.create_test_volunteer(self.regular_member.name)
        # bare_user holds Verenigingen Member but has NO Member record.
        self.assertFalse(has_volunteer_permission(vol.name, self.bare_user.name))

    def test_undeterminable_volunteer_denied(self):
        """A doc yielding no volunteer name is denied (~502-505)."""
        from verenigingen.permissions import has_volunteer_permission

        self.assertFalse(has_volunteer_permission(12345, self.regular_user.name))


class TestTeamMemberQueryPositive(PermissionsCoverageBase):
    """``get_team_member_permission_query`` positive path (permissions.py
    ~1788-1806): a team member sees other members of teams they belong to.

    The existing suite only exercises the 1=0 branches (no member / no
    volunteer). This builds a real team and proves execution-based scoping:
    teammate IN, outsider OUT.
    """

    def _make_team_fixture(self):
        """Build a real Team with the acting user's volunteer + a teammate as
        active members, plus an unrelated outsider volunteer. Returns
        (my_volunteer, teammate_volunteer, outsider_volunteer)."""
        my_volunteer = self.create_test_volunteer(self.regular_member.name)
        teammate_member = self.create_test_member(
            first_name="Perm", last_name="TeamMate", email=f"perm-tm-mate-{self.token}@test.com"
        )
        teammate_volunteer = self.create_test_volunteer(teammate_member.name)
        outsider_member = self.create_test_member(
            first_name="Perm", last_name="TeamOut", email=f"perm-tm-out-{self.token}@test.com"
        )
        outsider_volunteer = self.create_test_volunteer(outsider_member.name)

        role = frappe.get_doc(
            {
                "doctype": "Team Role",
                "role_name": f"Perm TMRole {self.token}",
                "permissions_level": "Basic",
                "is_team_leader": 0,
                "is_active": 1,
            }
        )
        role.insert(ignore_permissions=True)

        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Perm TMTeam {self.token}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
                "team_members": [
                    {
                        "volunteer": my_volunteer.name,
                        "team_role": role.name,
                        "from_date": today(),
                        "is_active": 1,
                        "status": "Active",
                    },
                    {
                        "volunteer": teammate_volunteer.name,
                        "team_role": role.name,
                        "from_date": today(),
                        "is_active": 1,
                        "status": "Active",
                    },
                ],
            }
        )
        team.insert(ignore_permissions=True)
        frappe.db.commit()
        return my_volunteer, teammate_volunteer, outsider_volunteer

    def test_team_member_sees_teammates_only(self):
        from verenigingen.permissions import get_team_member_permission_query

        my_volunteer, teammate_volunteer, outsider_volunteer = self._make_team_fixture()

        cond = get_team_member_permission_query(self.regular_user.name)
        self.assertTrue(cond and cond != "1=0")
        self.assertIn("tabTeam Member", cond)

        # Execution-based scoping against the real Team Member rows.
        def visible(volunteer_name):
            rows = frappe.db.sql(
                f"SELECT name FROM `tabTeam Member` WHERE volunteer = %s AND {cond}",
                volunteer_name,
            )
            return bool(rows)

        self.assertTrue(visible(my_volunteer.name), "member sees own team-member row")
        self.assertTrue(visible(teammate_volunteer.name), "member sees teammate's row")
        self.assertFalse(
            visible(outsider_volunteer.name), "member must not see a non-team volunteer"
        )


class TestFinancialInfoBoardPositive(PermissionsCoverageBase):
    """``can_view_financial_info`` board-member positive path (permissions.py
    ~1202-1230): a Financial board member of the target's chapter can view the
    member's financial info. The existing suite only covers admin / self / deny.
    """

    def test_financial_board_member_can_view(self):
        from verenigingen.permissions import can_view_financial_info

        # board_user is a Financial-level board member of chapter A; regular_member
        # is a member of chapter A. The secure permission-evaluation query resolves
        # the target's chapter and Chapter.can_view_member_payments grants access.
        self.assertTrue(
            can_view_financial_info("Member", self.regular_member.name, self.board_user.name),
            "Financial board member of the target's chapter must view financial info",
        )

    def test_non_board_member_of_other_chapter_denied(self):
        """A Financial board member of chapter A must NOT view a chapter-B
        member's financial info (proves the grant is chapter-scoped)."""
        from verenigingen.permissions import can_view_financial_info

        self.assertFalse(
            can_view_financial_info("Member", self.other_member.name, self.board_user.name),
            "board member of A must not view a B member's financial info",
        )


class TestCanTerminateNationalChapter(PermissionsCoverageBase):
    """``can_terminate_member`` national-board-chapter grant branch
    (permissions.py ~1332-1341)."""

    def test_national_board_member_can_terminate_outside_own_chapter(self):
        from verenigingen.permissions import can_terminate_member

        # Pre-condition: without a national chapter, the board user (board of A
        # only) cannot terminate a chapter-B member.
        self.assertFalse(can_terminate_member(self.other_member.name, self.board_user.name))

        # Configure chapter A (where board_user IS a board member) as the national
        # board chapter. Now the national-chapter branch grants termination of ANY
        # member, including the chapter-B member. Non-committed so it rolls back and
        # production reads it in the same transaction.
        frappe.db.set_single_value(
            "Verenigingen Settings", "national_board_chapter", self.chapter_a.name
        )
        self.assertTrue(
            can_terminate_member(self.other_member.name, self.board_user.name),
            "national board member must be able to terminate any member",
        )


class TestChapterBoardRoleMaintenance(PermissionsCoverageBase):
    """``assign_chapter_board_role`` / ``update_all_chapter_board_roles`` /
    ``_users_with_chapter_board_role`` (permissions.py ~1555-1678). These add or
    remove the Chapter Board Member role based on active board positions."""

    def _make_member_with_board_position(self):
        """Create a fresh user/member/volunteer with an active board seat in
        chapter A, WITHOUT the Chapter Board Member role (so assign can add it)."""
        user = self.create_test_user(
            email=f"perm-assign-{self.token}@test.com", roles=[Roles.VERENIGINGEN_MEMBER]
        )
        member = self.create_test_member(
            first_name="Perm",
            last_name="Assign",
            email=f"perm-assign-{self.token}@test.com",
            user=user.name,
        )
        volunteer = self.create_test_volunteer(member.name)
        position = frappe.get_doc(
            {
                "doctype": "Chapter Board Member",
                "parent": self.chapter_a.name,
                "parenttype": "Chapter",
                "parentfield": "board_members",
                "volunteer": volunteer.name,
                "chapter_role": self.financial_role.name,
                "from_date": today(),
                "is_active": 1,
            }
        )
        position.insert(ignore_permissions=True)
        return user, position

    def _has_board_role(self, user_email):
        return frappe.db.exists(
            "Has Role", {"parent": user_email, "role": Roles.CHAPTER_BOARD_MEMBER}
        )

    def test_assign_add_idempotent_and_remove(self):
        from verenigingen.permissions import assign_chapter_board_role

        user, position = self._make_member_with_board_position()

        # The board-position insert path may already have granted the role; strip it
        # so this test drives the ADD branch of assign_chapter_board_role from a clean
        # state (the function's own add/remove logic is what is under test here).
        frappe.db.delete("Has Role", {"parent": user.name, "role": Roles.CHAPTER_BOARD_MEMBER})
        self.assertFalse(self._has_board_role(user.name))

        # Add: has an active board position -> role assigned.
        self.assertTrue(assign_chapter_board_role(user.name))
        self.assertTrue(self._has_board_role(user.name), "role must be added")

        # Idempotent: already has the role -> still True, no duplicate.
        self.assertTrue(assign_chapter_board_role(user.name))
        self.assertTrue(self._has_board_role(user.name))

        # Remove: deactivate the board position -> role removed.
        frappe.db.set_value("Chapter Board Member", position.name, "is_active", 0)
        self.assertTrue(assign_chapter_board_role(user.name))
        self.assertFalse(self._has_board_role(user.name), "role must be removed")

        # No positions and no role -> nothing to do -> False.
        self.assertFalse(assign_chapter_board_role(user.name))

    def test_assign_no_member_record(self):
        from verenigingen.permissions import assign_chapter_board_role

        self.assertFalse(assign_chapter_board_role(f"perm-nobody-{self.token}@test.com"))

    def test_users_with_chapter_board_role_includes_committed_board_user(self):
        from verenigingen.permissions import _users_with_chapter_board_role

        # board_user was committed in setUp holding the Chapter Board Member role.
        users = _users_with_chapter_board_role()
        self.assertIn(self.board_user.name, users)

    def test_update_all_returns_count(self):
        from verenigingen.permissions import update_all_chapter_board_roles

        # Runs the site-wide maintenance sweep; must return a non-negative int and
        # not raise. Role writes are uncommitted -> rolled back with the test.
        result = update_all_chapter_board_roles()
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, 0)


class TestMemberQueryNoAccess(PermissionsCoverageBase):
    """``get_member_permission_query`` no-conditions-matched -> 1=0 branch
    (permissions.py ~1073-1074) and ``has_donation_permission`` dangling-donor
    guard (~784-786)."""

    def test_member_query_no_role_denied(self):
        from verenigingen.permissions import get_member_permission_query

        no_role_user = self.create_test_user(
            email=f"perm-mq-norole-{self.token}@test.com", roles=[_ensure_neutral_role()]
        )
        self.assertEqual(get_member_permission_query(no_role_user.name), "1=0")

    def test_donation_with_donor_missing_member_denied(self):
        from verenigingen.permissions import has_donation_permission

        donor = self.create_test_donor(member=self.regular_member.name)
        donation = self.create_test_donation(donor=donor.name)
        # Null out the donor's member link -> donor_member falsy -> deny.
        frappe.db.set_value("Donor", donor.name, "member", "")
        try:
            self.assertFalse(has_donation_permission(donation.name, self.regular_user.name))
        finally:
            frappe.db.set_value("Donor", donor.name, "member", self.regular_member.name)


def teardown_module():
    frappe.db.rollback()
