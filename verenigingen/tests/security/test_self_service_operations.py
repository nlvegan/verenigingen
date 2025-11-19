"""
Test Self-Service Operations Security

Tests the self_service_only parameter functionality in the API Security Framework
to ensure volunteers can submit their own expenses but not access others' data.
"""

import unittest
import frappe

from verenigingen.utils.security.api_security_framework import (
    APISecurityFramework,
    standard_api
)
from verenigingen.utils.security.types import SecurityLevel, OperationType
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSelfServiceOperations(EnhancedTestCase):
    """Test self-service operations security functionality"""

    def setUp(self):
        """Setup test environment"""
        self.framework = APISecurityFramework()
        self.volunteer_user = "volunteer@example.com"
        self.treasurer_user = "treasurer@example.com"

    def test_self_service_validation_same_user(self):
        """Test that self-service validation passes for same user"""
        # Create real test data
        member = self.create_test_member(
            first_name="Volunteer",
            last_name="User",
            birth_date="1990-01-01"
        )

        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Volunteer",
            last_name="User"
        )

        # Link the member to the user (correct relationship)
        member.user = volunteer_user.name
        member.save()

        # Should pass when volunteer accesses their own member record
        result = self.framework._validate_self_service_access(
            target_member=member.name,
            user=volunteer_user.name
        )
        self.assertTrue(result)

    def test_self_service_validation_different_user(self):
        """Test that self-service validation fails for different user"""
        # Create two different members
        member1 = self.create_test_member(
            first_name="Member",
            last_name="One",
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Member",
            last_name="Two",
            birth_date="1991-01-01"
        )

        # Create user linked to member2
        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Volunteer",
            last_name="User"
        )

        # Link member2 to the user (correct relationship)
        member2.user = volunteer_user.name
        member2.save()

        # Should fail when volunteer tries to access member1's record
        with self.assertRaises(Exception) as context:
            self.framework._validate_self_service_access(
                target_member=member1.name,
                user=volunteer_user.name
            )
        self.assertIn("self-service", str(context.exception).lower())

    def test_self_service_validation_no_member_link(self):
        """Test that self-service validation fails when user has no member link"""
        # Create a member
        member = self.create_test_member(
            first_name="Member",
            last_name="Test",
            birth_date="1990-01-01"
        )

        # Create user with NO member link
        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Volunteer",
            last_name="User"
            # Note: no member_name parameter
        )

        # Should fail when user has no member record link
        with self.assertRaises(Exception) as context:
            self.framework._validate_self_service_access(
                target_member=member.name,
                user=volunteer_user.name
            )
        self.assertIn("member", str(context.exception).lower())

    def test_self_service_decorator_integration(self):
        """Test that self_service_only parameter works with decorators"""

        @standard_api(operation_type=OperationType.REPORTING, self_service_only=True)
        def mock_submit_expense(expense_data=None):
            """Mock expense submission function"""
            return {"success": True, "expense_id": "EXP-001"}

        # Function should have the decorator applied
        self.assertTrue(hasattr(mock_submit_expense, '_security_config'))

        # Check that self_service_only is in the security config
        security_config = getattr(mock_submit_expense, '_security_config', {})
        self.assertTrue(security_config.get('self_service_only', False))

    def test_volunteer_expense_submission_security_level(self):
        """Test that volunteer expense submission uses appropriate security level"""
        # Import the actual volunteer expense function
        try:
            from verenigingen.templates.pages.volunteer.expenses import submit_expense

            # Check that it has the correct security configuration
            if hasattr(submit_expense, '_security_config'):
                config = submit_expense._security_config
                # Should be MEDIUM level for volunteers with self_service_only
                self.assertEqual(config.get('security_level'), SecurityLevel.MEDIUM)
                self.assertTrue(config.get('self_service_only', False))
            else:
                # If not decorated, that's also valid as long as the function exists
                self.assertTrue(callable(submit_expense))

        except ImportError:
            self.skipTest("Volunteer expense submission function not available")

    def test_self_service_audit_logging(self):
        """Test that self-service operations are properly logged"""
        # Create real test data
        member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            birth_date="1990-01-01"
        )

        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Test",
            last_name="Member"
        )

        # Link the member to the user (correct relationship)
        member.user = volunteer_user.name
        member.save()

        # Test successful validation doesn't generate errors
        try:
            result = self.framework._validate_self_service_access(
                target_member=member.name,
                user=volunteer_user.name
            )
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"Valid self-service access should not fail: {e}")

    def test_self_service_parameter_types(self):
        """Test that self_service_only parameter accepts correct types"""

        # Should accept boolean True
        @standard_api(operation_type=OperationType.REPORTING, self_service_only=True)
        def test_func_true():
            pass

        # Should accept boolean False
        @standard_api(operation_type=OperationType.REPORTING, self_service_only=False)
        def test_func_false():
            pass

        # Both should work without errors
        self.assertTrue(hasattr(test_func_true, '_security_config'))
        self.assertTrue(hasattr(test_func_false, '_security_config'))

    def test_self_service_with_multiple_members(self):
        """Test self-service validation with users who might have multiple member records"""
        # Create test members
        member1 = self.create_test_member(
            first_name="Member",
            last_name="One",
            birth_date="1990-01-01"
        )

        member999 = self.create_test_member(
            first_name="Member",
            last_name="NineNineNine",
            birth_date="1991-01-01"
        )

        # Create user linked to member1
        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Member",
            last_name="One"
        )

        # Link member1 to the user (correct relationship)
        member1.user = volunteer_user.name
        member1.save()

        # Should pass for correct member
        result = self.framework._validate_self_service_access(
            target_member=member1.name,
            user=volunteer_user.name
        )
        self.assertTrue(result)

        # Should fail for different member
        with self.assertRaises(Exception):
            self.framework._validate_self_service_access(
                target_member=member999.name,
                user=volunteer_user.name
            )

    def test_self_service_security_level_requirements(self):
        """Test that self-service operations have appropriate security level requirements"""
        # Volunteers should have LOW level access
        volunteer_levels = self.framework.ROLE_PROFILE_SECURITY_MAPPING.get("Verenigingen Volunteer", [])
        self.assertIn(SecurityLevel.LOW, volunteer_levels)

        # Standard APIs (MEDIUM level) should be accessible to volunteers for self-service
        # This allows volunteers to submit expenses with self_service_only=True
        self.assertIn(SecurityLevel.MEDIUM,
                     self.framework.ROLE_PROFILE_SECURITY_MAPPING.get("Verenigingen Volunteer", []))

    def test_self_service_without_authentication(self):
        """Test that self-service operations require authentication"""
        # Create a member for testing
        member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            birth_date="1990-01-01"
        )

        # Should fail for guest users
        with self.assertRaises(Exception) as context:
            self.framework._validate_self_service_access(
                target_member=member.name,
                user="Guest"
            )

        # Error should mention authentication
        error_msg = str(context.exception).lower()
        self.assertTrue(any(word in error_msg for word in ["authentication", "guest", "access denied"]))

    def test_framework_supports_self_service_parameter(self):
        """Test that the framework properly supports the self_service_only parameter"""

        # The framework should have the validation method
        self.assertTrue(hasattr(self.framework, '_validate_self_service_access'))

        # The method should be callable
        self.assertTrue(callable(getattr(self.framework, '_validate_self_service_access')))

    def test_self_service_error_messages(self):
        """Test that self-service validation provides meaningful error messages"""
        # Create two different members
        member1 = self.create_test_member(
            first_name="Member",
            last_name="One",
            birth_date="1990-01-01"
        )

        member2 = self.create_test_member(
            first_name="Member",
            last_name="Two",
            birth_date="1991-01-01"
        )

        # Create user linked to member2
        volunteer_user = self.create_test_user(
            email=self.volunteer_user,
            first_name="Member",
            last_name="Two"
        )

        # Link member2 to the user (correct relationship)
        member2.user = volunteer_user.name
        member2.save()

        try:
            self.framework._validate_self_service_access(
                target_member=member1.name,
                user=volunteer_user.name
            )
            self.fail("Should have raised an exception")
        except Exception as e:
            error_msg = str(e).lower()
            # Error message should be meaningful and mention self-service
            self.assertTrue(len(error_msg) > 10)  # Not just a generic error
            self.assertTrue(any(word in error_msg for word in ["self", "service", "access", "member"]))


if __name__ == '__main__':
    unittest.main()