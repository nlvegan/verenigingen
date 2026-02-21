# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Unit tests for Field Sync Service

Tests field synchronization testing utility.
Focus on OperationResult pattern with type-safe error handling.

Migration Status: ✅ COMPLETE (2025-11-24)
- All tests use OperationResult API
- Proper assertions for .success, .data, .error_message
- Type-safe test patterns
"""

import frappe
from frappe.utils import random_string
from verenigingen.services.field_sync_service import test_sync_relationship
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestFieldSyncService(EnhancedTestCase):
    """Unit tests for Field Sync Service"""

    def setUp(self):
        super().setUp()
        # Set user to Administrator for permissions
        frappe.set_user("Administrator")

    def test_test_sync_relationship_returns_operation_result(self):
        """Test that test_sync_relationship returns OperationResult"""
        unique_email = f"sync.test.{random_string(8).lower()}@example.com"

        # Create member with user
        member = self.create_test_member(
            first_name="Sync",
            last_name="Test",
            email=unique_email
        )

        # Create user for member
        user = frappe.new_doc("User")
        user.email = unique_email
        user.first_name = "Sync"
        user.last_name = "Test"
        user.send_welcome_email = 0
        user.user_type = "System User"
        user.insert()

        # Link user to member
        frappe.db.set_value("Member", member.name, "user", user.name)
        member.reload()

        # Test sync relationship
        result = test_sync_relationship(
            source_doctype="Member",
            source_name=member.name,
            target_doctype="User",
            field_to_test="first_name",
            test_value="Updated"
        )

        # OperationResult pattern
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.success)

    def test_test_sync_relationship_with_no_config_returns_failed_result(self):
        """Test sync relationship with no config returns failed OperationResult"""
        result = test_sync_relationship(
            source_doctype="InvalidDocType",
            source_name="Invalid-001",
            target_doctype="AnotherInvalidDocType",
            field_to_test="some_field",
            test_value="test"
        )

        # OperationResult pattern - should fail gracefully
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("No sync config", result.error_message)

    def test_test_sync_relationship_with_no_target_returns_failed_result(self):
        """Test sync relationship when target not found returns failed OperationResult"""
        unique_email = f"notarget.test.{random_string(8).lower()}@example.com"

        # Create member without user
        member = self.create_test_member(
            first_name="NoTarget",
            last_name="Test",
            email=unique_email
        )

        result = test_sync_relationship(
            source_doctype="Member",
            source_name=member.name,
            target_doctype="User",
            field_to_test="first_name",
            test_value="Updated"
        )

        # OperationResult pattern - should fail because no user linked
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error_message)
        self.assertIn("No related", result.error_message)

    def test_test_sync_relationship_never_throws_exceptions(self):
        """Test that sync relationship testing never throws exceptions"""
        # Test with various invalid inputs
        invalid_tests = [
            ("", "", "", "", ""),
            ("Invalid", "Invalid", "Invalid", "field", "value"),
            ("Member", "NON-EXISTENT", "User", "first_name", "test"),
        ]

        for source_dt, source_name, target_dt, field, value in invalid_tests:
            result = test_sync_relationship(source_dt, source_name, target_dt, field, value)
            self.assertIsNotNone(result, f"Returned None for inputs: {source_dt}, {source_name}")
            # Should be OperationResult with success attribute
            self.assertIsNotNone(result.success)

    def test_test_sync_relationship_result_contains_metadata(self):
        """Test that sync test result contains expected metadata"""
        unique_email = f"metadata.sync.{random_string(8).lower()}@example.com"

        # Create member with user
        member = self.create_test_member(
            first_name="Metadata",
            last_name="Test",
            email=unique_email
        )

        # Create user
        user = frappe.new_doc("User")
        user.email = unique_email
        user.first_name = "Metadata"
        user.last_name = "Test"
        user.send_welcome_email = 0
        user.user_type = "System User"
        user.insert()

        # Link user to member
        frappe.db.set_value("Member", member.name, "user", user.name)
        member.reload()

        # Test sync
        result = test_sync_relationship(
            source_doctype="Member",
            source_name=member.name,
            target_doctype="User",
            field_to_test="first_name",
            test_value="NewName"
        )

        # Check metadata fields (regardless of success/failure)
        if result.success:
            expected_fields = ["source_field", "target_field", "test_value", "actual_value", "target_document"]
            for field in expected_fields:
                self.assertIn(field, result.data, f"Missing expected field in data: {field}")
        else:
            # On failure, metadata should be in metadata dict
            expected_fields = ["source_field", "target_field", "test_value", "actual_value", "target_document"]
            for field in expected_fields:
                self.assertTrue(
                    field in result.data or field in result.metadata,
                    f"Missing expected field: {field}"
                )


def run_tests():
    """Helper function to run tests from console"""
    frappe.flags.in_test = True
    import unittest
    suite = unittest.TestLoader().loadTestsFromTestCase(TestFieldSyncService)
    unittest.TextTestRunner(verbosity=2).run(suite)
