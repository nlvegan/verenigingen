"""
Tests for the multi-item expense claim portal page
(verenigingen.templates.pages.volunteer.expense_claim_new).

get_context():
- raises PermissionError for Guest (require_login)
- resolves the volunteer via the current user's member record
- sets show_form=False + error_message when the user has no volunteer record
- sets show_form=True + context.volunteer on the happy path
- always seeds theme_settings and expense_stats so the template never errors
"""

import frappe

from verenigingen.templates.pages.volunteer import expense_claim_new
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestExpenseClaimNewPage(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.user_email = f"ecn-{frappe.generate_hash()[:8]}@test.invalid"
        self.member = self._make_member_with_user(self.user_email)
        self.volunteer = self.create_test_volunteer(member=self.member.name, volunteer_name="ECN Volunteer")

    def _make_member_with_user(self, email):
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Ecn",
                    "last_name": "User",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        member = self.create_test_member(
            first_name="Ecn", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)
        return member

    def test_guest_is_rejected(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                expense_claim_new.get_context(ctx)

    def test_no_volunteer_record_hides_form(self):
        other_email = f"ecn-novol-{frappe.generate_hash()[:8]}@test.invalid"
        self._make_member_with_user(other_email)
        with self.as_user(other_email):
            ctx = frappe._dict()
            expense_claim_new.get_context(ctx)
        self.assertFalse(ctx.show_form)
        self.assertIn("No volunteer record found", ctx.error_message)
        # Defaults are still seeded so the template renders
        self.assertIn("theme_settings", ctx)
        self.assertEqual(ctx.expense_stats["pending_count"], 0)

    def test_happy_path_shows_form_with_volunteer(self):
        with self.as_user(self.user_email):
            ctx = frappe._dict()
            expense_claim_new.get_context(ctx)
        self.assertTrue(ctx.show_form)
        self.assertEqual(ctx.volunteer.name, self.volunteer.name)
        self.assertEqual(ctx.title, "Submit Expense Claim")
        self.assertIn("theme_settings", ctx)
        self.assertEqual(ctx.expense_stats["total_submitted"], 0.0)
