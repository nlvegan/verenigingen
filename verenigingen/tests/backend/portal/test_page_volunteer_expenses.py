"""
Tests for the volunteer expenses portal page
(verenigingen.templates.pages.volunteer.expenses).

get_context() delegates to build_base_expense_context which:
- raises PermissionError for Guest
- sets context.error_message + safe defaults when no volunteer record exists
- otherwise populates volunteer/organizations/expense_categories/expense_stats

The whitelisted data endpoints are exercised against real Volunteer/Chapter/
Team data, covering the no-volunteer and happy-path branches:
- get_organization_options (Chapter / Team / unknown type)
- get_volunteer_expense_context
- get_expense_details (no-volunteer guard)
- submit_multiple_expenses (guest guard)
"""

import frappe
from frappe.utils import today

from verenigingen.templates.pages.volunteer import expenses
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerExpensesPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"exp-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(
            member=self.member.name, volunteer_name="Expenses Volunteer"
        )
        # Chapter the volunteer's member belongs to, and a team they are on,
        # so organization lookups return real rows.
        self.chapter = self.create_test_chapter(chapter_name=f"Exp Chapter {frappe.generate_hash()[:6]}")
        self.chapter.append(
            "members",
            {
                "member": self.member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        self.chapter.save()

        self.team = self.create_test_team(team_name="Exp Team")
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
                    "first_name": "Exp",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Exp", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    # ---- get_context ---------------------------------------------------

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                expenses.get_context(ctx)

    def test_no_volunteer_sets_error_with_safe_defaults(self):
        other_email = f"exp-novol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            ctx = frappe._dict()
            expenses.get_context(ctx)
        self.assertIn("No volunteer record found", ctx.error_message)
        self.assertIsNone(ctx.volunteer)
        self.assertEqual(ctx.organizations, {"chapters": [], "teams": []})
        self.assertEqual(ctx.expense_stats["total_count"], 0)

    def test_happy_path_populates_context(self):
        with self.as_user(self.user_email):
            ctx = frappe._dict()
            expenses.get_context(ctx)
        self.assertIsNone(ctx.get("error_message"))
        self.assertEqual(ctx.volunteer.name, self.volunteer.name)
        self.assertIn("chapters", ctx.organizations)
        self.assertIn("teams", ctx.organizations)
        self.assertIsInstance(ctx.expense_categories, list)
        self.assertEqual(ctx.title, "Volunteer Expenses")
        self.assertTrue(ctx.show_sidebar)

    # ---- get_organization_options --------------------------------------

    def test_organization_options_denied_for_plain_member(self):
        """A member-only user (no REPORTING profile) is denied by the API
        security framework before the no-volunteer branch is reached."""
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        other_email = f"exp-orgnovol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            with self.assertRaises(VPermissionError):
                expenses.get_organization_options("Chapter")

    def test_organization_options_chapter(self):
        with self.as_user(self.user_email):
            result = expenses.get_organization_options("Chapter")
        self.assertIsInstance(result, list)
        self.assertTrue(any(opt["value"] == self.chapter.name for opt in result))

    def test_organization_options_team(self):
        with self.as_user(self.user_email):
            result = expenses.get_organization_options("Team")
        self.assertIsInstance(result, list)
        self.assertTrue(any(opt["value"] == self.team.name for opt in result))

    def test_organization_options_unknown_type_returns_empty(self):
        with self.as_user(self.user_email):
            result = expenses.get_organization_options("Galaxy")
        self.assertEqual(result, [])

    # ---- get_volunteer_expense_context ---------------------------------

    def test_volunteer_expense_context_guest(self):
        with self.as_user("Guest"):
            result = expenses.get_volunteer_expense_context()
        self.assertFalse(result["success"])
        self.assertIn("log in", result["message"].lower())

    def test_volunteer_expense_context_happy_path(self):
        with self.as_user(self.user_email):
            result = expenses.get_volunteer_expense_context()
        self.assertTrue(result["success"])
        self.assertEqual(result["volunteer"], self.volunteer.name)
        self.assertIn(self.chapter.name, result["user_chapters"])
        self.assertIn(self.team.name, result["user_teams"])
        self.assertIn("approval_thresholds", result)

    def test_volunteer_expense_context_no_volunteer(self):
        other_email = f"exp-ctxnovol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            result = expenses.get_volunteer_expense_context()
        self.assertFalse(result["success"])
        self.assertIn("No volunteer record found", result["message"])

    # ---- get_expense_details -------------------------------------------

    def test_expense_details_denied_for_plain_member(self):
        """get_expense_details is MEMBER_DATA-gated; a member-only user without
        the required profile is denied by the security framework."""
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        other_email = f"exp-detnovol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            with self.assertRaises(VPermissionError):
                expenses.get_expense_details("SOMECLAIM-001")

    def test_expense_details_no_employee_denied(self):
        """Volunteer without employee_id cannot resolve an ERPNext claim."""
        with self.as_user(self.user_email):
            with self.assertRaises(frappe.ValidationError):
                expenses.get_expense_details("CLAIM-123")

    # ---- submit_multiple_expenses --------------------------------------

    def test_submit_multiple_expenses_guest(self):
        with self.as_user("Guest"):
            result = expenses.submit_multiple_expenses([])
        self.assertFalse(result["success"])
        self.assertIn("log in", result["message"].lower())
