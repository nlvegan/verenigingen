# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for DuesSchedulePermissionService.

Tests permission management including:
- Permission result structure
- Role-based access control
- Template permission rules

Uses real users and roles for security testing compliance.
"""

from unittest.mock import MagicMock

import frappe

from verenigingen.services.billing.dues_schedule_permission_service import (
    DuesSchedulePermissionService,
    PermissionResult,
    get_dues_schedule_permission_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPermissionResult(EnhancedTestCase):
    """Test suite for PermissionResult class."""

    def test_permission_result_allowed(self):
        """Test PermissionResult when allowed."""
        result = PermissionResult(allowed=True, reason="Access granted", permission_level="admin")

        self.assertTrue(result.allowed)
        self.assertTrue(result.success)
        self.assertEqual(result.reason, "Access granted")
        self.assertEqual(result.permission_level, "admin")
        self.assertIsNone(result.error_message)
        self.assertTrue(bool(result))

    def test_permission_result_denied(self):
        """Test PermissionResult when denied."""
        result = PermissionResult(allowed=False, reason="Access denied")

        self.assertFalse(result.allowed)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "Access denied")
        self.assertEqual(result.permission_level, "none")
        self.assertEqual(result.error_message, "Access denied")
        self.assertFalse(bool(result))


class TestDuesSchedulePermissionService(EnhancedTestCase):
    """Test suite for DuesSchedulePermissionService."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_permission_service()

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        service = DuesSchedulePermissionService()
        self.assertEqual(service.service_name, "DuesSchedulePermissionService")
        self.assertIsNotNone(service.logger)

    def test_get_permission_service_returns_instance(self):
        """Test that factory function returns service instance."""
        service = get_dues_schedule_permission_service()
        self.assertIsInstance(service, DuesSchedulePermissionService)


class TestValidatePermissionsWithRealUsers(EnhancedTestCase):
    """Test suite for validate_permissions with real user/role assignments."""

    def setUp(self):
        """Set up test fixtures including test users with roles."""
        super().setUp()
        self.service = get_dues_schedule_permission_service()

        # Create test users with specific roles using factory method
        self.admin_user_email = f"veradmin.{frappe.generate_hash(length=6)}@test.com"
        self.admin_user = self.create_test_user_with_roles(
            email=self.admin_user_email,
            roles=["Verenigingen Administrator"],
            first_name="Ver",
            last_name="Admin",
        )

        self.staff_user_email = f"verstaff.{frappe.generate_hash(length=6)}@test.com"
        self.staff_user = self.create_test_user_with_roles(
            email=self.staff_user_email,
            roles=["Verenigingen Staff"],
            first_name="Ver",
            last_name="Staff",
        )

    def test_system_manager_has_access(self):
        """Test that System Manager role grants full access."""
        # Administrator user has System Manager role by default
        admin_user = "Administrator"

        # Create a mock schedule to test permissions against
        mock_schedule = MagicMock()
        mock_schedule._ignore_permissions = False
        mock_schedule.is_new.return_value = True
        mock_schedule.has_value_changed.return_value = False

        result = self.service.validate_permissions(mock_schedule, user=admin_user)

        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "admin")

    def test_verenigingen_administrator_has_access(self):
        """Test that Verenigingen Administrator role grants full access."""
        mock_schedule = MagicMock()
        mock_schedule._ignore_permissions = False
        mock_schedule.is_new.return_value = True
        mock_schedule.has_value_changed.return_value = False

        result = self.service.validate_permissions(mock_schedule, user=self.admin_user_email)

        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "admin")

    def test_template_edit_requires_admin(self):
        """Test that template editing requires Verenigingen Administrator."""
        mock_schedule = MagicMock()
        mock_schedule._ignore_permissions = False
        mock_schedule.is_new.return_value = False
        mock_schedule.has_value_changed.return_value = False
        mock_schedule.is_template = True

        # Staff user should NOT be able to edit templates
        result = self.service.validate_permissions(mock_schedule, user=self.staff_user_email)

        self.assertFalse(result.allowed)
        self.assertIn("template", result.reason.lower())


class TestCheckDocumentPermissionWithRealUsers(EnhancedTestCase):
    """Test suite for check_document_permission with real users."""

    def setUp(self):
        """Set up test fixtures including test user."""
        super().setUp()
        self.service = get_dues_schedule_permission_service()

        # Create a minimal test user using factory method
        self.test_user_email = f"minuser.{frappe.generate_hash(length=6)}@test.com"
        self.test_user = self.create_test_user_with_roles(
            email=self.test_user_email,
            roles=[],  # No special roles
            first_name="Min",
            last_name="User",
        )

    def test_system_manager_document_access(self):
        """Test that System Manager can access any document."""
        # Administrator has System Manager role
        mock_doc = MagicMock()
        mock_doc.name = "Test-Schedule"

        result = self.service.check_document_permission(mock_doc, user="Administrator")

        self.assertTrue(result)

    def test_template_visible_to_authenticated_user(self):
        """Test that templates are visible to authenticated users."""
        mock_doc = MagicMock()
        mock_doc.name = "Template-Test"
        mock_doc.is_template = True

        result = self.service.check_document_permission(mock_doc, user=self.test_user_email)

        self.assertTrue(result)

    def test_member_can_access_own_schedule(self):
        """Test that members can access their own schedules."""
        # Create a test member with a linked user
        test_member = self.create_test_member(
            first_name="OwnSchedule",
            last_name="Test",
            email=f"ownschedule.test.{frappe.generate_hash(length=6)}@test.com",
        )

        # Ensure member has a user account
        if not test_member.user:
            test_member.create_user()
            test_member.reload()

        # Verify user is created
        self.assertIsNotNone(test_member.user, "Test member must have a linked user")

        # Create a mock doc that represents the member's schedule
        mock_doc = MagicMock()
        mock_doc.name = "Schedule-001"
        mock_doc.is_template = False
        mock_doc.member = test_member.name

        # The member's linked user should be able to access
        result = self.service.check_document_permission(
            mock_doc, user=test_member.user, permission_type="read"
        )

        self.assertTrue(result)

    def test_other_user_cannot_access_member_schedule(self):
        """Test that other users cannot access a member's schedule."""
        # Create a test member (the schedule owner)
        owner_member = self.create_test_member(
            first_name="ScheduleOwner",
            last_name="Test",
            email=f"scheduleowner.test.{frappe.generate_hash(length=6)}@test.com",
        )

        # Create another test member (the unauthorized accessor)
        other_member = self.create_test_member(
            first_name="OtherUser",
            last_name="Test",
            email=f"otheruser.test.{frappe.generate_hash(length=6)}@test.com",
        )

        # Ensure both members have user accounts created
        if not owner_member.user:
            owner_member.create_user()
            owner_member.reload()
        if not other_member.user:
            other_member.create_user()
            other_member.reload()

        # Verify users are created
        self.assertIsNotNone(other_member.user, "Other member must have a linked user")

        # Create a mock doc that represents the owner's schedule
        mock_doc = MagicMock()
        mock_doc.name = "Schedule-001"
        mock_doc.is_template = False
        mock_doc.member = owner_member.name

        # The other user should NOT be able to access
        result = self.service.check_document_permission(
            mock_doc, user=other_member.user, permission_type="read"
        )

        self.assertFalse(result)


class TestMemberEditValidation(EnhancedTestCase):
    """Test suite for member self-edit validation."""

    def setUp(self):
        """Set up test fixtures."""
        super().setUp()
        self.service = get_dues_schedule_permission_service()

    def test_new_schedule_allowed(self):
        """Test that new schedule creation is allowed for members."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = True

        result = self.service.validate_member_edit(mock_schedule)

        self.assertTrue(result.allowed)
        self.assertEqual(result.permission_level, "member")

    def test_allowed_field_changes(self):
        """Test that members can change allowed fields."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False

        # Set up meta with fields
        mock_field = MagicMock()
        mock_field.fieldname = "notes"
        mock_field.label = "Notes"
        mock_schedule.meta.fields = [mock_field]

        # notes is in allowed list, so has_value_changed doesn't matter
        mock_schedule.has_value_changed.return_value = True

        result = self.service.validate_member_edit(mock_schedule)

        self.assertTrue(result.allowed)

    def test_disallowed_field_changes(self):
        """Test that members cannot change restricted fields."""
        mock_schedule = MagicMock()
        mock_schedule.is_new.return_value = False

        # Set up meta with a restricted field
        mock_field = MagicMock()
        mock_field.fieldname = "billing_frequency"  # Not in allowed list
        mock_field.label = "Billing Frequency"
        mock_schedule.meta.fields = [mock_field]

        mock_schedule.has_value_changed.return_value = True

        result = self.service.validate_member_edit(mock_schedule)

        self.assertFalse(result.allowed)
        self.assertIn("Billing Frequency", result.reason)
