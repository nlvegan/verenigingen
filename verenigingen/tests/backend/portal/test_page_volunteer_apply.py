"""
Tests for the volunteer application portal page
(verenigingen.templates.pages.volunteer.apply).

get_context():
- For a Guest: already_member is False and an organization_logo is provided.
- For a logged-in user who is already a Member: already_member is True,
  member_name set, and it returns early (no logo lookup needed).
"""

import frappe

from verenigingen.templates.pages.volunteer import apply
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestVolunteerApplyPage(EnhancedTestCase):
    def test_guest_gets_application_form(self):
        with self.as_user("Guest"):
            ctx = frappe._dict()
            apply.get_context(ctx)
        self.assertFalse(ctx.already_member)
        # Logo key is always populated for the guest application form
        self.assertIn("organization_logo", ctx)
        self.assertEqual(ctx.title, "Volunteer Application")
        self.assertFalse(ctx.show_sidebar)

    def test_existing_member_is_short_circuited(self):
        email = f"apply-member-{frappe.generate_hash()[:8]}@test.invalid"
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Apply",
                "last_name": "User",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        ).insert()
        member = self.create_test_member(
            first_name="Apply", last_name="Member", email=email, birth_date="1990-01-01"
        )
        member.db_set("user", email)

        with self.as_user(email):
            ctx = frappe._dict()
            apply.get_context(ctx)

        self.assertTrue(ctx.already_member)
        self.assertEqual(ctx.member_name, member.name)
        # Early return: logo lookup is skipped for existing members
        self.assertNotIn("organization_logo", ctx)
