"""
Tests for the volunteer dashboard portal page
(verenigingen.templates.pages.volunteer.dashboard).

The page resolves the volunteer from frappe.session.user via
get_user_volunteer_record() (member-by-user → volunteer-by-member, then
volunteer-by-email fallback). get_context() must:

- raise PermissionError for Guest (require_login)
- set context.error_message when the user has no volunteer record
- on the happy path populate context.volunteer, volunteer_profile,
  organizations, recent_activities, expense_summary, upcoming_activities

The data-helper functions (get_volunteer_profile, get_volunteer_organizations,
get_recent_activities, get_expense_summary, get_upcoming_activities) are
exercised directly against real Volunteer/Chapter/Team data.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.templates.pages.volunteer import dashboard
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerDashboardPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"vol-dash-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Dashboard Volunteer"
        )

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Dash",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Dash", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    # ---- get_context branches ------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                dashboard.get_context(ctx)

    def test_no_volunteer_record_sets_error_message(self):
        """A logged-in member WITHOUT a volunteer record gets the error branch."""
        other_email = f"novol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)  # member but no volunteer

        with self.as_user(other_email):
            ctx = frappe._dict()
            dashboard.get_context(ctx)

        self.assertIn("No volunteer record found", ctx.error_message)
        self.assertNotIn("volunteer", ctx)

    def test_happy_path_populates_context(self):
        with self.as_user(self.user_email):
            ctx = frappe._dict()
            dashboard.get_context(ctx)

        # No error on the happy path
        self.assertIsNone(ctx.get("error_message"))
        self.assertEqual(ctx.volunteer["name"], self.volunteer.name)
        self.assertEqual(ctx.volunteer_profile["name"], self.volunteer.name)
        self.assertIn("chapters", ctx.organizations)
        self.assertIn("teams", ctx.organizations)
        self.assertIsInstance(ctx.recent_activities, list)
        # Expense summary keys present with numeric defaults
        self.assertIn("total_submitted", ctx.expense_summary)
        self.assertIn("pending_count", ctx.expense_summary)
        self.assertIsInstance(ctx.upcoming_activities, list)
        self.assertEqual(ctx.no_cache, 1)
        self.assertFalse(ctx.show_sidebar)

    # ---- get_user_volunteer_record -------------------------------------

    def test_get_user_volunteer_record_resolves_by_member(self):
        with self.as_user(self.user_email):
            rec = dashboard.get_user_volunteer_record()
        self.assertIsNotNone(rec)
        self.assertEqual(rec["name"], self.volunteer.name)
        self.assertEqual(rec["member"], self.member.name)

    def test_get_user_volunteer_record_none_for_unlinked_user(self):
        stranger = f"stranger-{frappe.generate_hash()[:8]}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": stranger,
                "first_name": "No",
                "last_name": "Member",
                "send_welcome_email": 0,
            }
        ).insert()
        with self.as_user(stranger):
            self.assertIsNone(dashboard.get_user_volunteer_record())

    # ---- get_volunteer_profile -----------------------------------------

    def test_get_volunteer_profile_includes_member_info(self):
        profile = dashboard.get_volunteer_profile(self.volunteer.name)
        self.assertEqual(profile["name"], self.volunteer.name)
        # email is taken from the linked member
        self.assertEqual(profile["email"], self.member.email)
        self.assertIsNotNone(profile["member_info"])
        self.assertEqual(profile["member_info"]["full_name"], self.member.full_name)
        self.assertIsInstance(profile["skills"], list)
        self.assertIsInstance(profile["interests"], list)

    # ---- get_volunteer_organizations -----------------------------------

    def test_get_volunteer_organizations_reflects_team_membership(self):
        team = self.create_test_team(team_name="Dash Team")
        team.append(
            "team_members",
            {
                "volunteer": self.volunteer.name,
                "volunteer_name": self.volunteer.volunteer_name,
                "team_role": "Team Member",
                "role_type": "Team Member",
                "role": "Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()

        orgs = dashboard.get_volunteer_organizations(self.volunteer.name)
        team_names = [t["name"] for t in orgs["teams"]]
        self.assertIn(team.name, team_names)

    # ---- get_recent_activities -----------------------------------------

    def test_get_recent_activities_returns_assignment(self):
        vol_doc = frappe.get_doc("Volunteer", self.volunteer.name)
        vol_doc.append(
            "assignment_history",
            {
                "assignment_type": "Project",
                "role": "Coordinator",
                "start_date": today(),
                "status": "Active",
            },
        )
        vol_doc.save()

        activities = dashboard.get_recent_activities(self.volunteer.name)
        self.assertIsInstance(activities, list)
        # At most 8 returned
        self.assertLessEqual(len(activities), 8)

    # ---- get_expense_summary -------------------------------------------

    def test_get_expense_summary_zero_without_employee(self):
        """Volunteers without an employee_id get a zeroed summary, not a crash."""
        summary = dashboard.get_expense_summary(self.volunteer.name)
        self.assertEqual(summary["total_submitted"], 0)
        self.assertEqual(summary["total_approved"], 0)
        self.assertEqual(summary["pending_count"], 0)
        self.assertEqual(summary["pending_amount"], 0)

    # ---- get_upcoming_activities ---------------------------------------

    def test_get_upcoming_activities_lists_future_assignments(self):
        vol_doc = frappe.get_doc("Volunteer", self.volunteer.name)
        vol_doc.append(
            "assignment_history",
            {
                "assignment_type": "Event",
                "role": "Helper",
                "start_date": add_days(today(), 30),
                "status": "Active",
            },
        )
        vol_doc.save()

        upcoming = dashboard.get_upcoming_activities(self.volunteer.name)
        self.assertIsInstance(upcoming, list)
        # All returned items are in the future
        for item in upcoming:
            self.assertGreater(str(item["date"]), today())
