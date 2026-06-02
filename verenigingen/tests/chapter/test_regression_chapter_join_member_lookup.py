"""
Regression test for chapter join member lookup fixes.

Tests the fix for the bug where chapter join API was using incorrect member lookup
pattern ({"email": frappe.session.user}) instead of the proper pattern that uses
the utility function get_current_user_member_name() which queries by user field.

Issue discovered: 2025-12-12
Fix applied to: verenigingen/api/chapter_join.py
"""

import frappe
from frappe.utils import random_string

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    get_member_name_for_user,
)


class TestRegressionChapterJoinMemberLookup(VereningingenTestCase):
    """
    Regression test for chapter join member lookup bug.

    The bug occurred because the chapter join API was looking up members by:
        frappe.db.get_value("Member", {"email": frappe.session.user})

    This is incorrect because:
    - email field contains the member's contact email (e.g., "john@example.com")
    - frappe.session.user is the username (e.g., "Administrator" or "user@example.com")
    - The correct lookup is by the user field: {"user": frappe.session.user}

    The fix uses get_current_user_member_name() which properly handles both
    lookup strategies (user field primary, email field fallback).
    """

    def test_member_lookup_by_user_field(self):
        """
        Test that member lookup works when user field is set.

        This is the primary lookup pattern that should be used.
        """
        # Create a test user
        test_email = f"test.user.{random_string(8)}@example.com"
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": test_email,
            "first_name": "Test",
            "last_name": "User",
            "send_welcome_email": 0,
        })
        test_user.insert()
        self.track_doc("User", test_user.name)

        # Create a member linked to this user via user field
        member = self.create_test_member(
            first_name="Test",
            last_name="MemberUserField",
            email=f"member.contact.{random_string(8)}@example.com",  # Different from user email
        )

        # Link member to user
        member.user = test_user.name
        member.save()

        # Verify the utility function finds the member by user field
        found_member = get_member_name_for_user(test_user.name)
        self.assertEqual(found_member, member.name)

    def test_member_lookup_by_email_fallback(self):
        """
        Test that member lookup falls back to email field when user field is not set.

        This is the fallback pattern for older records.
        """
        # Create a unique email that will be used for both User and Member
        shared_email = f"shared.{random_string(8)}@example.com"

        # Create a test user
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": shared_email,
            "first_name": "Test",
            "last_name": "User",
            "send_welcome_email": 0,
        })
        test_user.insert()
        self.track_doc("User", test_user.name)

        # Create a member with email matching the user (but no user field link)
        member = self.create_test_member(
            first_name="Test",
            last_name="MemberEmailFallback",
            email=shared_email,  # Same as user email
        )

        # Explicitly clear user field to test fallback
        member.user = None
        member.save()

        # Verify the utility function finds the member by email fallback
        found_member = get_member_name_for_user(shared_email)
        self.assertEqual(found_member, member.name)

    def test_member_lookup_prefers_user_field_over_email(self):
        """
        Test that user field lookup takes precedence over email field.

        When both a member with matching user field and another with matching
        email field exist, the user field match should be returned.
        """
        test_email = f"test.precedence.{random_string(8)}@example.com"

        # Create a test user
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": test_email,
            "first_name": "Test",
            "last_name": "User",
            "send_welcome_email": 0,
        })
        test_user.insert()
        self.track_doc("User", test_user.name)

        # Create member A: email matches user email, but no user field link
        member_a = self.create_test_member(
            first_name="Test",
            last_name="MemberA",
            email=test_email,  # Matches user email
        )
        member_a.user = None
        member_a.save()

        # Create member B: different email, but user field links to test_user
        member_b = self.create_test_member(
            first_name="Test",
            last_name="MemberB",
            email=f"different.{random_string(8)}@example.com",
        )
        member_b.user = test_user.name
        member_b.save()

        # The lookup should find member_b (user field match) not member_a (email match)
        # User field is the explicit link and takes precedence over coincidental email match
        found_member = get_member_name_for_user(test_email)

        # Correct behavior: user field lookup is primary, email is fallback
        # member_b has explicit user field link, so it should be found
        self.assertEqual(found_member, member_b.name)

    def test_member_lookup_returns_none_for_nonexistent_user(self):
        """
        Test that member lookup returns None for users without member records.

        This should not raise an exception, just return None.
        """
        nonexistent_email = f"nonexistent.{random_string(8)}@example.com"

        found_member = get_member_name_for_user(nonexistent_email)
        self.assertIsNone(found_member)

    def test_member_lookup_handles_empty_input(self):
        """
        Test that member lookup handles empty/None input gracefully.
        """
        self.assertIsNone(get_member_name_for_user(""))
        self.assertIsNone(get_member_name_for_user(None))

    def test_chapter_join_api_uses_correct_lookup(self):
        """
        Integration test: Verify chapter join API uses the correct member lookup.

        This test ensures the API endpoint actually uses the utility function
        rather than the incorrect direct query.
        """
        from verenigingen.api.chapter_join import get_chapter_join_context

        # Create test chapter
        chapter = self.create_test_chapter(
            chapter_name=f"Test Chapter {random_string(8)}",
            postal_codes="1000-9999"
        )

        # Create test user and member
        test_email = f"test.api.{random_string(8)}@example.com"
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": test_email,
            "first_name": "Test",
            "last_name": "APIUser",
            "send_welcome_email": 0,
            # get_chapter_join_context is a @standard_api (MEDIUM security).
            # Per ROLE_PROFILE_SECURITY_MAPPING the Verenigingen Volunteer role
            # grants MEDIUM access; assign it so the authenticated-member path
            # is exercised rather than being rejected at the security gate.
            "roles": [{"role": "Verenigingen Volunteer"}],
        })
        test_user.insert()
        self.track_doc("User", test_user.name)

        member = self.create_test_member(
            first_name="Test",
            last_name="APIMember",
            email=f"member.api.{random_string(8)}@example.com",  # Different from user email
        )
        member.user = test_user.name
        member.save()

        # Set session user to test user
        original_user = frappe.session.user
        try:
            frappe.set_user(test_user.name)

            # Call the API
            result = get_chapter_join_context(chapter.name)

            # Verify the API found the member correctly. get_chapter_join_context
            # returns an OperationResult envelope dict: {"success", "data", ...}
            self.assertTrue(result["success"], msg=result.get("error"))
            self.assertEqual(result["data"].get("member"), member.name)
            self.assertTrue(result["data"].get("user_logged_in"))

        finally:
            frappe.set_user(original_user)
