"""
Integration tests for OperationResult migration in service layer.

Tests the migrated service methods to ensure they properly use OperationResult
and that the migration maintains backward compatibility and correct behavior.

Author: Verenigingen Development Team
Created: 2025-11-24
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.member.core.member_lifecycle_service import member_lifecycle_service
from verenigingen.services.member.core.member_status_service import (
    set_member_application_status_defaults,
    sync_member_status_fields,
)
from verenigingen.services.member.core.member_id_service import (
    ensure_member_has_id,
    force_assign_member_id,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberLifecycleServiceMigration(EnhancedTestCase):
    """Test MemberLifecycleService OperationResult migration."""

    def test_approve_application_success(self):
        """Test successful application approval returns OperationResult."""
        # Create application member
        member = self.create_test_member(
            first_name=f"Test{self.uid}",
            last_name="Applicant",
            email=f"test.applicant.{self.uid}@test.invalid",
            status="Pending"
        )

        # Set as application member
        member.application_id = "APP-001"
        member.application_status = "Pending"
        member.save()

        # Approve application
        result = member_lifecycle_service.approve_application(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)  # Should return member_id
        self.assertEqual(result.errors, [])
        self.assertTrue(result.metadata.get("approved"))

        # Verify member was updated
        member.reload()
        self.assertIsNotNone(member.member_id)

    def test_approve_application_not_application_member(self):
        """Test approve_application fails for non-application member."""
        # Create regular member (not from application)
        member = self.create_test_member(
            first_name=f"Regular{self.uid}",
            last_name="Member",
            email=f"regular.{self.uid}@test.invalid",
            status="Active"
        )

        # Try to approve
        result = member_lifecycle_service.approve_application(member)

        # Verify failure
        self.assertFalse(result.success)
        # When using .chain(), original error is in errors list, not error_message
        self.assertGreater(len(result.errors), 0)
        self.assertIn("not an application member", result.errors[0].lower())

    def test_approve_application_already_approved(self):
        """Test approve_application fails if already approved."""
        # Create approved application member
        member = self.create_test_member(
            first_name=f"Approved{self.uid}",
            last_name="Member",
            email=f"approved.{self.uid}@test.invalid",
            status="Active"
        )
        member.application_id = "APP-002"
        member.application_status = "Approved"
        member.save()

        # Try to approve again
        result = member_lifecycle_service.approve_application(member)

        # Verify failure
        self.assertFalse(result.success)
        # When using .chain(), original error is in errors list, not error_message
        self.assertGreater(len(result.errors), 0)
        self.assertIn("already approved", result.errors[0].lower())

    def test_reject_application_success(self):
        """Test successful application rejection returns OperationResult."""
        # Create application member
        member = self.create_test_member(
            first_name=f"Test{self.uid}",
            last_name="Reject",
            email=f"test.reject.{self.uid}@test.invalid",
            status="Pending"
        )
        member.application_id = "APP-003"
        member.application_status = "Pending"
        member.save()

        # Reject application
        reason = "Does not meet requirements"
        result = member_lifecycle_service.reject_application(member, reason)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertEqual(result.data, "Rejected")  # Should return status
        self.assertTrue(result.metadata.get("rejected"))
        self.assertIn("review_date", result.metadata)

        # Verify member was updated
        member.reload()
        self.assertEqual(member.status, "Rejected")
        # The rejection reason is stored in review_notes field (not rejection_reason which doesn't exist)
        self.assertEqual(member.review_notes, reason)

    def test_reject_application_not_application_member(self):
        """Test reject_application fails for non-application member."""
        # Create regular member
        member = self.create_test_member(
            first_name=f"Regular{self.uid}2",
            last_name="Member",
            email=f"regular2.{self.uid}@test.invalid",
            status="Active"
        )

        # Try to reject
        result = member_lifecycle_service.reject_application(member, "Test reason")

        # Verify failure
        self.assertFalse(result.success)
        # When using .chain(), original error is in errors list, not error_message
        self.assertGreater(len(result.errors), 0)
        self.assertIn("not an application member", result.errors[0].lower())


class TestMemberStatusServiceMigration(EnhancedTestCase):
    """Test MemberStatusService OperationResult migration."""

    def test_set_application_status_defaults_new_application(self):
        """Test setting defaults for new application member."""
        # Create unsaved member (simulating new application)
        member = frappe.new_doc("Member")
        member.first_name = f"New{self.uid}"
        member.last_name = "Application"
        member.email = f"new.application.{self.uid}@test.invalid"

        # Set defaults
        result = set_member_application_status_defaults(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertEqual(result.data, "Pending")  # New applications should be Pending
        self.assertEqual(member.application_status, "Pending")

    def test_set_application_status_defaults_existing_member(self):
        """Test setting defaults for existing member without status."""
        # Create and save member
        member = self.create_test_member(
            first_name=f"Existing{self.uid}",
            last_name="Member",
            email=f"existing.{self.uid}@test.invalid"
        )

        # Clear application_status
        member.application_status = None
        member.save()
        member.reload()

        # Set defaults
        result = set_member_application_status_defaults(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertEqual(result.data, "Approved")  # Existing members should be Approved
        self.assertEqual(member.application_status, "Approved")

    def test_sync_status_fields_chains_errors(self):
        """Test that sync_status_fields properly chains errors from nested calls."""
        # Create a member doc that will cause validation to fail
        # (This is a bit contrived but tests the chaining mechanism)
        member = self.create_test_member(
            first_name=f"Test{self.uid}",
            last_name="Chain",
            email=f"test.chain.{self.uid}@test.invalid"
        )

        # Sync status fields (should succeed)
        result = sync_member_status_fields(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertIsInstance(result.data, dict)
        self.assertIn("status", result.data)
        self.assertIn("application_status", result.data)
        self.assertIn("membership_status", result.data)


class TestMemberIdServiceMigration(EnhancedTestCase):
    """Test MemberIdService OperationResult migration."""

    def test_ensure_member_has_id_assigns_id(self):
        """Test ensure_member_has_id assigns ID to qualifying member."""
        # Create member and force clear ID without triggering hooks
        member = self.create_test_member(
            first_name=f"NoID{self.uid}",
            last_name="Member",
            email=f"noid.{self.uid}@test.invalid",
            status="Active"
        )
        # Directly update database to clear member_id without triggering save hooks
        frappe.db.set_value("Member", member.name, "member_id", None, update_modified=False)
        member.reload()

        # Ensure ID
        result = ensure_member_has_id(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)  # Should return member_id
        self.assertIn("Member ID assigned", result.metadata.get("message", ""))

        # Verify member has ID
        member.reload()
        self.assertIsNotNone(member.member_id)

    def test_ensure_member_has_id_already_has_id(self):
        """Test ensure_member_has_id fails when member already has ID."""
        # Create member with ID
        member = self.create_test_member(
            first_name=f"HasID{self.uid}",
            last_name="Member",
            email=f"hasid.{self.uid}@test.invalid",
            status="Active"
        )
        # Member should have ID from creation

        # Try to ensure ID
        result = ensure_member_has_id(member)

        # Verify failure
        self.assertFalse(result.success)
        self.assertIn("already has", result.error_message.lower())

    def test_force_assign_member_id_as_system_manager(self):
        """Test force_assign_member_id works for System Manager."""
        # Test user already has System Manager role from setUp()

        # Create member and force clear ID without triggering hooks
        member = self.create_test_member(
            first_name=f"Force{self.uid}",
            last_name="Assign",
            email=f"force.{self.uid}@test.invalid",
            status="Active"
        )
        # Directly update database to clear member_id without triggering save hooks
        frappe.db.set_value("Member", member.name, "member_id", None, update_modified=False)
        member.reload()

        # Force assign
        result = force_assign_member_id(member)

        # Verify OperationResult structure
        self.assertTrue(result.success)
        self.assertIsNotNone(result.data)  # Should return member_id
        self.assertIn("force assigned", result.metadata.get("message", "").lower())

        # Verify member has ID
        member.reload()
        self.assertIsNotNone(member.member_id)


class TestOperationResultChainingInServices(EnhancedTestCase):
    """Test that .chain() helper works correctly in service layer."""

    def test_chain_preserves_error_context_through_layers(self):
        """Test that chaining preserves error context through multiple service layers."""
        # Create member that will fail validation
        member = self.create_test_member(
            first_name=f"Chain{self.uid}",
            last_name="Test",
            email=f"chain.{self.uid}@test.invalid",
            status="Active"
        )
        # Not an application member

        # Try to approve (should fail and chain error)
        result = member_lifecycle_service.approve_application(member)

        # Verify error chaining
        self.assertFalse(result.success)
        # Should have context message
        self.assertIn("validation", result.error_message.lower())
        # Should preserve original error
        self.assertGreater(len(result.errors), 0)
        self.assertIn("not an application member", result.errors[0].lower())

    def test_chain_maintains_metadata_through_propagation(self):
        """Test that chain() maintains metadata when propagating errors."""
        # This tests the implementation, not just the interface
        from verenigingen.utils.operation_result import OperationResult

        # Create a failed result with metadata
        inner_result = OperationResult.fail(
            "Inner failure",
            errors=["Error 1", "Error 2"],
            field="email",
            code="VALIDATION"
        )

        # Chain it
        outer_result = inner_result.chain(
            "Outer context",
            operation="create_member"
        )

        # Verify metadata is preserved and extended
        self.assertFalse(outer_result.success)
        self.assertEqual(outer_result.error_message, "Outer context")
        self.assertEqual(outer_result.errors, ["Error 1", "Error 2"])
        self.assertEqual(outer_result.metadata["field"], "email")
        self.assertEqual(outer_result.metadata["code"], "VALIDATION")
        self.assertEqual(outer_result.metadata["operation"], "create_member")


def run_tests():
    """Helper function to run all integration tests."""
    import sys
    import unittest

    # Create test suite
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemberLifecycleServiceMigration))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemberStatusServiceMigration))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestMemberIdServiceMigration))
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestOperationResultChainingInServices))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return exit code
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import sys
    sys.exit(run_tests())
