"""
Unit Tests for Extracted Security Modules

Tests for the Phase 3 refactoring that extracted:
- FrappeWhitelistAdapter (from api_security_framework.py)
- SelfServiceAccessController (from api_security_framework.py)

These tests verify the modules work correctly in isolation and
that the singleton patterns function properly.
"""

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.utils.error_handling import PermissionError as VPermissionError


@contextmanager
def set_user_context(user):
    """Context manager to temporarily set Frappe user.

    This is the proper way to mock user context in Frappe tests,
    rather than patching frappe.session.user directly.
    """
    original_user = frappe.session.user
    try:
        frappe.set_user(user)
        yield
    finally:
        frappe.set_user(original_user)


class TestFrappeWhitelistAdapter(FrappeTestCase):
    """Tests for FrappeWhitelistAdapter module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def test_singleton_pattern(self):
        """Test that get_frappe_whitelist_adapter returns singleton."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            get_frappe_whitelist_adapter,
        )

        adapter1 = get_frappe_whitelist_adapter()
        adapter2 = get_frappe_whitelist_adapter()

        self.assertIs(adapter1, adapter2, "Should return same singleton instance")

    def test_preserve_whitelist_attribute_direct(self):
        """Test preserving __func_is_whitelisted__ from direct attribute."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
        )

        adapter = FrappeWhitelistAdapter()

        # Create mock functions
        def mock_func():
            pass

        mock_func.__func_is_whitelisted__ = True

        wrapper = MagicMock()
        adapter.preserve_whitelist_attribute(wrapper, mock_func)

        self.assertTrue(
            getattr(wrapper, "__func_is_whitelisted__", False),
            "Should preserve __func_is_whitelisted__ attribute",
        )

    def test_preserve_whitelist_attribute_from_allow_guest(self):
        """Test setting __func_is_whitelisted__ from allow_guest attribute."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
        )

        adapter = FrappeWhitelistAdapter()

        def mock_func():
            pass

        mock_func.allow_guest = True

        wrapper = MagicMock()
        # Remove __func_is_whitelisted__ if exists
        if hasattr(wrapper, "__func_is_whitelisted__"):
            delattr(wrapper, "__func_is_whitelisted__")

        adapter.preserve_whitelist_attribute(wrapper, mock_func)

        self.assertTrue(
            getattr(wrapper, "__func_is_whitelisted__", False),
            "Should set __func_is_whitelisted__ from allow_guest",
        )

    def test_preserve_common_attributes(self):
        """Test preserving common Frappe attributes."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
        )

        adapter = FrappeWhitelistAdapter()

        def mock_func():
            pass

        mock_func.allow_guest = True
        mock_func._original_func_name = "original_name"

        class MockWrapper:
            pass

        wrapper = MockWrapper()
        adapter.preserve_common_attributes(wrapper, mock_func)

        self.assertTrue(
            getattr(wrapper, "allow_guest", False), "Should preserve allow_guest"
        )
        self.assertEqual(
            getattr(wrapper, "_original_func_name", None),
            "original_name",
            "Should preserve _original_func_name",
        )

    def test_is_inner_whitelisted_from_attribute(self):
        """Test checking if function is whitelisted via attribute."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
        )

        adapter = FrappeWhitelistAdapter()

        def mock_func():
            pass

        mock_func.__func_is_whitelisted__ = True

        # Ensure frappe.whitelisted exists
        if not hasattr(frappe, "whitelisted"):
            frappe.whitelisted = set()

        self.assertTrue(
            adapter.is_inner_whitelisted(mock_func),
            "Should detect whitelisted via attribute",
        )

    def test_get_allowed_http_methods_none(self):
        """Test getting HTTP methods when none are registered."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
        )

        adapter = FrappeWhitelistAdapter()

        def mock_func():
            pass

        result = adapter.get_allowed_http_methods(mock_func)

        # If frappe doesn't have the registry, should return None
        if not hasattr(frappe, "allowed_http_methods_for_whitelisted_func"):
            self.assertIsNone(result)
        else:
            # If registry exists but func not in it, should be None
            self.assertIsNone(result)


class TestSelfServiceAccessController(FrappeTestCase):
    """Tests for SelfServiceAccessController module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # SelfServiceAccessController.get_user_member() resolves a user's member
        # by matching Member.email to the user, so we need a real member whose
        # email is known and unique. Create one deterministically rather than
        # depending on pre-existing data (which is absent on a fresh test site).
        cls.test_user_email = f"selfservice.module.{frappe.generate_hash(length=8)}@example.com"

        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "SelfService",
            "last_name": "ModuleTest",
            "email": cls.test_user_email,
            "birth_date": "1990-01-01",
        })
        member.insert(ignore_permissions=True)
        frappe.db.commit()
        cls.test_member_name = member.name

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "test_member_name", None) and frappe.db.exists("Member", cls.test_member_name):
            frappe.delete_doc("Member", cls.test_member_name, force=True, ignore_permissions=True)
            frappe.db.commit()
        super().tearDownClass()

    def test_singleton_pattern(self):
        """Test that get_self_service_controller returns singleton."""
        from verenigingen.utils.security.self_service_access_controller import (
            get_self_service_controller,
        )

        controller1 = get_self_service_controller()
        controller2 = get_self_service_controller()

        self.assertIs(controller1, controller2, "Should return same singleton instance")

    def test_system_user_bypass(self):
        """Test that Administrator bypasses validation.

        This tests the security boundary behavior where system users
        are exempt from self-service restrictions.
        """
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Use proper context to simulate Administrator context
        with set_user_context("Administrator"):
            result = controller.validate_access(member="some_other_member")
            self.assertTrue(result, "Administrator should bypass validation")

    def test_guest_user_bypass(self):
        """Test that Guest bypasses validation.

        Guest users bypass self-service validation because they don't
        have member records - access control is handled elsewhere.
        """
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Use proper context to simulate Guest context
        with set_user_context("Guest"):
            result = controller.validate_access(member="some_member")
            self.assertTrue(result, "Guest should bypass validation")

    def test_get_user_member(self):
        """Test getting member record for user."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Test with our test user
        member_name = controller.get_user_member(self.test_user_email)

        self.assertEqual(
            member_name, self.test_member_name, "Should find member for test user"
        )

    def test_get_user_member_not_found(self):
        """Test getting member for non-existent user."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        member_name = controller.get_user_member("nonexistent@example.com")

        self.assertIsNone(member_name, "Should return None for non-existent user")

    def test_validate_access_own_data(self):
        """Test that user can access their own data.

        Uses mocking to simulate a user with a valid member record
        accessing their own data.
        """
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Find a real member to use in test
        test_member = frappe.db.get_value(
            "Member", {"email": ["like", "%@%"]}, ["name", "email"], as_dict=True
        )
        if not test_member:
            self.skipTest("No members in database for testing")
            return

        # Mock the get_user_member method to return the test member
        # This simulates a user with a member record accessing their own data
        with patch.object(controller, "get_user_member", return_value=test_member.name):
            # User accessing their own member data should be allowed
            result = controller.validate_access(member=test_member.name)
            self.assertTrue(result, "User should be able to access own data")

    def test_validate_access_other_data_denied(self):
        """Test that user cannot access another user's data.

        Uses mocking to simulate a user attempting to access data
        belonging to a different member.
        """
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Find a real member to use in test
        test_member = frappe.db.get_value(
            "Member", {"email": ["like", "%@%"]}, ["name", "email"], as_dict=True
        )
        if not test_member:
            self.skipTest("No members in database for testing")
            return

        # Mock the session user to be a non-admin user (Administrator bypasses validation)
        # and mock get_user_member to return the test member
        # Mock justified: Infrastructure - external dependency, not the boundary under test
        with patch("frappe.session") as mock_session:
            mock_session.user = "test_user@example.com"
            with patch.object(controller, "get_user_member", return_value=test_member.name):
                # Create a different member name to try to access
                other_member = "MEMBER-SOMEONE-ELSE-FAKE"

                with self.assertRaises(VPermissionError) as context:
                    controller.validate_access(member=other_member)

                self.assertIn(
                    "Access denied",
                    str(context.exception),
                    "Should deny access to other user's data",
                )

    def test_implicit_self_service_with_member_record(self):
        """Test implicit self-service when user has member record.

        Tests that users with valid member records can perform implicit
        self-service operations (no explicit member target specified).
        """
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Find a real member to use in test
        test_member = frappe.db.get_value(
            "Member", {"email": ["like", "%@%"]}, ["name", "email"], as_dict=True
        )
        if not test_member:
            self.skipTest("No members in database for testing")
            return

        # Mock the get_user_member method to return the test member
        # This simulates a user with a member record doing implicit self-service
        with patch.object(controller, "get_user_member", return_value=test_member.name):
            # No explicit member target - implicit self-service
            result = controller.validate_access()
            self.assertTrue(result, "Implicit self-service should work with member record")

    def test_validate_request_content_clean(self):
        """Test content validation with no violations."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Provide audit logger mock to avoid logging failures
        controller._audit_logger = MagicMock()

        # Use a test member name
        test_member = "MY-MEMBER-001"

        # Content referencing user's own member
        result = controller.validate_request_content(
            test_member,
            data={"member": test_member, "amount": 100},
        )

        self.assertTrue(result, "Should pass with own member reference")

    def test_validate_request_content_violation(self):
        """Test content validation catches unauthorized member reference."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Mock audit logger to avoid actual logging
        mock_audit_logger = MagicMock()
        controller._audit_logger = mock_audit_logger

        # Use a test member name
        test_member = "MY-MEMBER-001"

        # Content referencing another member (tampering attempt)
        with self.assertRaises(VPermissionError) as context:
            controller.validate_request_content(
                test_member,
                data={"member": "MEMBER-SOMEONE-ELSE", "amount": 100},
            )

        self.assertIn(
            "Access denied",
            str(context.exception),
            "Should deny access when tampering detected",
        )

        # Verify audit was logged
        mock_audit_logger.log_event.assert_called_once()

    def test_nested_content_inspection(self):
        """Test that nested member references are caught."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        controller = SelfServiceAccessController()

        # Mock audit logger
        controller._audit_logger = MagicMock()

        # Use a test member name
        test_member = "MY-MEMBER-001"

        # Nested tampering attempt
        with self.assertRaises(VPermissionError):
            controller.validate_request_content(
                test_member,
                items=[
                    {"member_id": "MEMBER-SOMEONE-ELSE", "quantity": 1},
                ],
            )

    def test_injectable_dependencies(self):
        """Test that dependencies can be injected."""
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
        )

        mock_audit_logger = MagicMock()
        mock_get_client_ip = MagicMock(return_value="192.168.1.1")

        controller = SelfServiceAccessController(
            audit_logger=mock_audit_logger,
            get_client_ip=mock_get_client_ip,
        )

        # Verify dependencies are used
        self.assertEqual(controller._audit_logger, mock_audit_logger)
        self.assertEqual(controller._get_client_ip(), "192.168.1.1")


class TestSecurityModuleIntegration(FrappeTestCase):
    """Integration tests for security modules working together."""

    def test_framework_uses_self_service_controller(self):
        """Test that APISecurityFramework delegates to SelfServiceAccessController."""
        from verenigingen.utils.security.api_security_framework import (
            get_security_framework,
        )

        framework = get_security_framework()

        # Framework should have self_service_controller
        self.assertIsNotNone(
            framework.self_service_controller,
            "Framework should have self_service_controller",
        )

        # The delegation methods should exist
        self.assertTrue(
            hasattr(framework, "_validate_self_service_access"),
            "Framework should have _validate_self_service_access method",
        )
        self.assertTrue(
            hasattr(framework, "_validate_self_service_request_content"),
            "Framework should have _validate_self_service_request_content method",
        )

    def test_framework_uses_whitelist_adapter(self):
        """Test that APISecurityFramework uses FrappeWhitelistAdapter."""
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            get_frappe_whitelist_adapter,
        )

        # The adapter should be importable and functional
        adapter = get_frappe_whitelist_adapter()
        self.assertIsNotNone(adapter, "Whitelist adapter should be accessible")

        # Adapter should have the register_wrapper method
        self.assertTrue(
            hasattr(adapter, "register_wrapper"),
            "Adapter should have register_wrapper method",
        )

    def test_all_exports_available(self):
        """Test that all new classes/functions are importable from their defining submodules.

        The package `__init__.py` deliberately does not re-export these (see
        verenigingen/utils/security/__init__.py and issue #396) -- import from
        the submodule that defines each name instead.
        """
        from verenigingen.utils.security.frappe_whitelist_adapter import (
            FrappeWhitelistAdapter,
            get_frappe_whitelist_adapter,
        )
        from verenigingen.utils.security.self_service_access_controller import (
            SelfServiceAccessController,
            get_self_service_controller,
        )

        # All should be importable
        self.assertIsNotNone(FrappeWhitelistAdapter)
        self.assertIsNotNone(SelfServiceAccessController)
        self.assertIsNotNone(get_frappe_whitelist_adapter)
        self.assertIsNotNone(get_self_service_controller)


if __name__ == "__main__":
    unittest.main()
