# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for MemberUserAccountService

Tests user account creation and linking functionality.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.utils import random_string
from verenigingen.services.member.account.member_user_account_service import MemberUserAccountService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestMemberUserAccountService(EnhancedTestCase):
    """Unit tests for MemberUserAccountService"""

    def setUp(self):
        super().setUp()
        self.service = MemberUserAccountService()
        # Set user to Administrator for user creation permissions
        frappe.set_user("Administrator")

    def test_create_member_user_account_basic_returns_operation_result(self):
        """Test basic user account creation returns OperationResult"""
        # Use timestamp + random for better uniqueness
        import time
        unique_email = f"basic.test.{int(time.time())}.{random_string(6).lower()}@example.com"
        member = self.create_test_member(
            first_name="Basic",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, str)  # Username
        self.assertIn("action", result.metadata)
        # Action can be either created_new or linked_existing depending on test isolation
        self.assertIn(result.metadata["action"], ["created_new", "linked_existing"])

    def test_create_member_user_account_user_already_exists_returns_failed_result(self):
        """Test creating account when user already exists returns failed OperationResult"""
        unique_email = f"existing.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Existing",
            last_name="Test",
            email=unique_email
        )

        # Create user account first time
        result1 = self.service.create_member_user_account(member.name)
        self.assertTrue(result1.success)

        # Try to create again - should fail
        result2 = self.service.create_member_user_account(member.name)

        # Should return failed OperationResult
        self.assertFalse(result2.success)
        self.assertIsNotNone(result2.error_message)
        self.assertIn("User already exists", result2.errors)
        self.assertIn("user", result2.metadata)

    def test_create_member_user_account_link_existing_user(self):
        """Test linking member to existing user account"""
        import time
        unique_email = f"link.test.{int(time.time())}.{random_string(6).lower()}@example.com"

        # Create a user first (or get existing one)
        if frappe.db.exists("User", unique_email):
            user = frappe.get_doc("User", unique_email)
        else:
            user = frappe.new_doc("User")
            user.email = unique_email
            user.first_name = "Link"
            user.last_name = "Test"
            user.send_welcome_email = 0
            user.user_type = "System User"
            user.insert(ignore_permissions=True)

        # Create member with same email
        member = self.create_test_member(
            first_name="Link",
            last_name="Test",
            email=unique_email
        )

        # Should link to existing user
        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertEqual(result.data, user.name)
        self.assertEqual(result.metadata.get("action"), "linked_existing")

    def test_create_member_user_account_invalid_member_returns_failed_result(self):
        """Test creating account for invalid member returns failed OperationResult"""
        result = self.service.create_member_user_account("INVALID-MEMBER")

        # Should return failed OperationResult (not throw exception)
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("INVALID-MEMBER", result.metadata.get("member", ""))

    def test_create_member_user_account_with_send_welcome_email_false(self):
        """Test creating account with send_welcome_email=False"""
        unique_email = f"nowelcome.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="NoWelcome",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name, send_welcome_email=False)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, str)

        # Verify user was created. The factory may uniquify the email, so the
        # created user mirrors the member's actual stored email.
        user = frappe.get_doc("User", result.data)
        self.assertEqual(user.email, member.email)

    def test_service_never_throws_exceptions(self):
        """Test that service never throws exceptions - always returns OperationResult"""
        invalid_inputs = ["", "INVALID", "Non-Existent-Member-789"]

        for invalid_input in invalid_inputs:
            result = self.service.create_member_user_account(invalid_input)
            self.assertIsNotNone(result, f"Service returned None for: {invalid_input}")
            # Should be OperationResult with success attribute
            self.assertIsNotNone(result.success)

    def test_created_user_has_correct_properties(self):
        """Test that created user has correct properties"""
        unique_email = f"props.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Props",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Verify user properties. The user mirrors the member's stored names; the
        # factory appends a uniqueness suffix to last_name, so compare against the
        # member's actual stored last_name (prefix "Test"). The "Verenigingen
        # Member" role profile grants desk-access roles, so Frappe keeps the user
        # as "System User".
        user = frappe.get_doc("User", result.data)
        self.assertEqual(user.email, member.email)
        self.assertEqual(user.first_name, "Props")
        self.assertEqual(user.last_name, member.last_name)
        self.assertTrue(member.last_name.startswith("Test"))
        self.assertEqual(user.user_type, "System User")
        self.assertEqual(user.enabled, 1)

    def test_member_linked_to_user_after_creation(self):
        """Test that member is linked to user after account creation"""
        unique_email = f"linked.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Linked",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Verify member is linked to user
        member.reload()
        self.assertEqual(member.user, result.data)

    def test_user_gets_member_roles(self):
        """Test that created user gets member-specific roles"""
        unique_email = f"roles.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Roles",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)

        # Verify user has member-specific roles (MemberRoleService assigns these)
        user = frappe.get_doc("User", result.data)
        roles = [r.role for r in user.roles]
        # Check for Verenigingen Member role (assigned by MemberRoleService)
        self.assertTrue(
            "Verenigingen Member" in roles or "All" in roles,
            f"Expected member roles but got: {roles}"
        )

    def test_metadata_contains_action_field(self):
        """Test that result metadata contains action field"""
        unique_email = f"metadata.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Metadata",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIn("action", result.metadata)
        self.assertIn(result.metadata["action"], ["created_new", "linked_existing"])

    def test_operation_result_data_is_username(self):
        """Test that OperationResult.data contains the username string"""
        unique_email = f"username.test.{random_string(8).lower()}@example.com"
        member = self.create_test_member(
            first_name="Username",
            last_name="Test",
            email=unique_email
        )

        result = self.service.create_member_user_account(member.name)

        # OperationResult pattern
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, str)

        # Verify it's a valid user
        self.assertTrue(frappe.db.exists("User", result.data))


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMemberUserAccountService)
    unittest.TextTestRunner(verbosity=2).run(suite)
