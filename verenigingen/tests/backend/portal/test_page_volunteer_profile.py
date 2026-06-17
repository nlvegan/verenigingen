"""
Tests for the volunteer profile portal page
(verenigingen.templates.pages.volunteer.profile).

get_context() resolves the volunteer from frappe.session.user and must:
- raise PermissionError for Guest (require_login)
- set context.error_message when there is no volunteer record
- populate context.volunteer, volunteer_profile and organizations otherwise.
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import profile
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerProfilePage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"vol-prof-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Profile Volunteer"
        )

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Prof",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Prof", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                profile.get_context(ctx)

    def test_no_volunteer_record_sets_error_message(self):
        other_email = f"prof-novol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            ctx = frappe._dict()
            profile.get_context(ctx)
        self.assertIn("No volunteer record found", ctx.error_message)
        self.assertNotIn("volunteer", ctx)

    def test_happy_path_populates_profile_and_organizations(self):
        with self.as_user(self.user_email):
            ctx = frappe._dict()
            profile.get_context(ctx)
        self.assertEqual(ctx.volunteer["name"], self.volunteer.name)
        self.assertEqual(ctx.volunteer_profile["name"], self.volunteer.name)
        self.assertEqual(ctx.volunteer_profile["email"], self.member.email)
        self.assertIn("chapters", ctx.organizations)
        self.assertIn("teams", ctx.organizations)
        self.assertEqual(ctx.title, "Volunteer Profile")
        self.assertTrue(ctx.show_sidebar)

    def test_get_user_volunteer_record_resolves_by_member(self):
        with self.as_user(self.user_email):
            rec = profile.get_user_volunteer_record()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], self.volunteer.name)

    def test_get_volunteer_profile_member_info(self):
        prof = profile.get_volunteer_profile(self.volunteer.name)
        self.assertEqual(prof["name"], self.volunteer.name)
        self.assertIsNotNone(prof["member_info"])
        self.assertEqual(prof["member_info"]["full_name"], self.member.full_name)
        self.assertIsInstance(prof["skills"], list)

    def test_get_volunteer_organizations_includes_team(self):
        team = self.create_test_team(team_name="Profile Team")
        team.append(
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
        team.save()

        orgs = profile.get_volunteer_organizations(self.volunteer.name)
        self.assertIn(team.name, [t["name"] for t in orgs["teams"]])
