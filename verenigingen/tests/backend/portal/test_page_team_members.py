"""
Tests for the team members portal page
(verenigingen.templates.pages.team_members).

get_context() (reads the team from frappe.form_dict):
- raises PermissionError for Guest (validate_user_logged_in)
- raises DoesNotExistError when the logged-in user has no Member record
- with no `team` param: shows the team selector + available_teams
- with a `team` param: enforces access (team member / same-chapter / admin),
  otherwise raises PermissionError; on success exposes context.team_members
- _get_available_teams_for_user is exercised too.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages import team_members
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTeamMembersPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"team-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Team Page Volunteer"
        )
        # A team the volunteer is an active member of.
        self.team = self.create_test_team(team_name="Members Page Team")
        self.team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "volunteer_name": self.volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        self.team.save()

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Team",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Team", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def _ctx_with_team(self, email, team):
        with self.as_user(email):
            ctx = frappe._dict()
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({"team": team} if team is not None else {})
            try:
                team_members.get_context(ctx)
            finally:
                frappe.form_dict = original
        return ctx

    # ---- get_context branches ------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            original = frappe.form_dict
            frappe.form_dict = frappe._dict({})
            try:
                with self.assertRaises(frappe.PermissionError):
                    team_members.get_context(ctx)
            finally:
                frappe.form_dict = original

    def test_user_without_member_record_raises(self):
        nomember = f"team-nomember-{frappe.generate_hash()[:8]}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": nomember,
                "first_name": "No",
                "last_name": "Member",
                "send_welcome_email": 0,
            }
        ).insert()
        with self.assertRaises(frappe.DoesNotExistError):
            self._ctx_with_team(nomember, None)

    def test_no_team_param_shows_selector(self):
        ctx = self._ctx_with_team(self.user_email, None)
        self.assertTrue(ctx.show_team_selector)
        self.assertTrue(any(t.name == self.team.name for t in ctx.available_teams))

    def test_team_member_can_view_members(self):
        ctx = self._ctx_with_team(self.user_email, self.team.name)
        self.assertEqual(ctx.team.name, self.team.name)
        self.assertTrue(any(tm.volunteer == self.volunteer.name for tm in ctx.team_members))
        # display_name falls back to the fetched volunteer_name
        viewed = next(tm for tm in ctx.team_members if tm.volunteer == self.volunteer.name)
        self.assertEqual(viewed.display_name, self.volunteer.volunteer_name)
        self.assertEqual(ctx.current_user_volunteer, self.volunteer.name)

    def test_outsider_is_denied(self):
        """A member who is neither on the team nor in its chapter is blocked."""
        outsider = f"team-outsider-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(outsider)
        with self.assertRaises(frappe.PermissionError):
            self._ctx_with_team(outsider, self.team.name)

    def test_invalid_team_raises(self):
        with self.assertRaises(Exception):
            self._ctx_with_team(self.user_email, "Nonexistent-Team-XYZ")

    # ---- _get_available_teams_for_user ---------------------------------

    def test_available_teams_for_member(self):
        teams = team_members._get_available_teams_for_user(self.user_email, self.member.name)
        self.assertTrue(any(t.name == self.team.name for t in teams))
