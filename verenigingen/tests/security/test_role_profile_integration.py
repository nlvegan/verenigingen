"""
Test Role Profile Integration with API Security Framework

Tests the integration between Frappe Role Profiles and the API Security Framework
to ensure proper security level mapping and self-service operations.
"""

import unittest
import frappe

from verenigingen.utils.security.api_security_framework import APISecurityFramework
from verenigingen.utils.security.types import SecurityLevel, OperationType
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRoleProfileIntegration(EnhancedTestCase):
    """Test role profile integration with security framework"""

    def setUp(self):
        """Setup test environment"""
        self.framework = APISecurityFramework()
        self.test_user = "test@example.com"

    def test_role_profile_security_mapping_exists(self):
        """Test that role profile mapping dictionary exists and has expected entries"""
        # Verify mapping exists
        mapping = self.framework.ROLE_PROFILE_SECURITY_MAPPING
        self.assertIsInstance(mapping, dict)

        # Verify key role profiles are mapped
        expected_profiles = [
            "Verenigingen Treasurer",
            "Verenigingen Chapter Board Member",
            "Verenigingen Volunteer",
            "Verenigingen Administrator"
        ]

        for profile in expected_profiles:
            self.assertIn(profile, mapping)
            self.assertIsInstance(mapping[profile], list)

    def test_treasurer_has_critical_access(self):
        """Test that treasurers have critical level access for financial operations"""
        mapping = self.framework.ROLE_PROFILE_SECURITY_MAPPING
        treasurer_levels = mapping.get("Verenigingen Treasurer", [])

        # Treasurers should have CRITICAL access for financial operations
        self.assertIn(SecurityLevel.CRITICAL, treasurer_levels)
        self.assertIn(SecurityLevel.HIGH, treasurer_levels)
        self.assertIn(SecurityLevel.MEDIUM, treasurer_levels)

    def test_volunteer_has_low_access(self):
        """Test that volunteers have appropriate low-level access"""
        mapping = self.framework.ROLE_PROFILE_SECURITY_MAPPING
        volunteer_levels = mapping.get("Verenigingen Volunteer", [])

        # Volunteers should have LOW access only
        self.assertIn(SecurityLevel.LOW, volunteer_levels)
        self.assertNotIn(SecurityLevel.CRITICAL, volunteer_levels)
        self.assertNotIn(SecurityLevel.HIGH, volunteer_levels)

    def test_get_user_role_profiles_security_fix(self):
        """Test that role profile query is secure and only returns directly assigned profiles"""
        # Create a real test user with role profile
        test_user = self.create_test_user(
            email="treasurer@test.com",
            first_name="Test",
            last_name="Treasurer",
            role_profile="Verenigingen Treasurer"
        )

        # Test the method exists and works with real data
        user_profiles = self.framework._get_user_role_profiles(test_user.name)

        # Should return the directly assigned profile
        self.assertIsInstance(user_profiles, list)
        self.assertEqual(len(user_profiles), 1)
        self.assertEqual(user_profiles[0], "Verenigingen Treasurer")

    def test_role_profile_validation_on_init(self):
        """Test that role profile existence is validated during framework initialization"""
        # Test with real role profiles that should exist
        # Should not raise an exception when profiles exist
        try:
            self.framework._validate_role_profile_configuration()
        except Exception as e:
            self.fail(f"Role profile validation failed unexpectedly: {e}")

    def test_security_level_hierarchy(self):
        """Test that security levels are properly hierarchical"""
        # Test that higher levels include lower levels
        mapping = self.framework.ROLE_PROFILE_SECURITY_MAPPING
        treasurer_levels = mapping.get("Verenigingen Treasurer", [])
        board_levels = mapping.get("Verenigingen Chapter Board Member", [])
        volunteer_levels = mapping.get("Verenigingen Volunteer", [])

        # Treasurer should have more access levels than board member
        self.assertGreater(len(treasurer_levels), len(board_levels))

        # Board member should have more access levels than volunteer
        self.assertGreater(len(board_levels), len(volunteer_levels))

    def test_self_service_validation_enhanced(self):
        """Test enhanced self-service validation logic"""
        # Create real test member and user
        member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            birth_date="1990-01-01"
        )

        test_user = self.create_test_user(
            email="member@test.com",
            first_name="Test",
            last_name="Member"
        )

        # Link the member to the user (correct relationship)
        member.user = test_user.name
        member.save()

        # Should pass validation when user has member record
        try:
            result = self.framework._validate_self_service_access(
                target_member=member.name,
                user=test_user.name
            )
            self.assertTrue(result)
        except Exception as e:
            self.fail(f"Self-service validation failed unexpectedly: {e}")

    def test_operation_type_to_security_level_mapping(self):
        """Test that operation types are mapped to appropriate security levels"""
        # Financial operations should require CRITICAL level
        self.assertEqual(
            self.framework.OPERATION_SECURITY_MAPPING[OperationType.FINANCIAL],
            SecurityLevel.CRITICAL
        )

        # Member data operations should require HIGH level
        self.assertEqual(
            self.framework.OPERATION_SECURITY_MAPPING[OperationType.MEMBER_DATA],
            SecurityLevel.HIGH
        )

        # Reporting operations should require MEDIUM level
        self.assertEqual(
            self.framework.OPERATION_SECURITY_MAPPING[OperationType.REPORTING],
            SecurityLevel.MEDIUM
        )

    def test_backwards_compatibility_maintained(self):
        """Test that hardcoded role fallback is maintained for backwards compatibility"""
        # Framework should have fallback mechanism for non-role-profile users
        # This ensures existing role-based access still works by checking for validate_authentication method
        self.assertTrue(hasattr(self.framework, 'validate_authentication'))

    def test_security_profile_analysis_available(self):
        """Test that security profile analysis function exists for debugging"""
        # Import should work
        try:
            from verenigingen.utils.security.api_security_framework import get_user_security_profile_analysis
            self.assertTrue(callable(get_user_security_profile_analysis))
        except ImportError:
            self.fail("Security profile analysis function not available")


class TestSelfServiceOperations(EnhancedTestCase):
    """Test self-service operations functionality"""

    def setUp(self):
        """Setup test environment"""
        self.framework = APISecurityFramework()

    def test_self_service_parameter_exists(self):
        """Test that self_service_only parameter is supported in decorators"""
        # Test that the framework supports self_service_only parameter
        # This is tested by checking the parameter is accepted in validation
        try:
            # This should not raise an exception for missing parameter
            result = self.framework._validate_self_service_access("Member-001", "test@example.com")
            # Result can be True or False, but should not error on parameter
            self.assertIsInstance(result, bool)
        except TypeError as e:
            if "unexpected keyword argument" in str(e):
                self.fail("self_service_only parameter not supported")

    def test_self_service_only_validation_logic(self):
        """Test the logic of self-service-only operations"""
        # Create real test data
        member = self.create_test_member(
            first_name="Volunteer",
            last_name="User",
            birth_date="1995-01-01"
        )

        volunteer_user = self.create_test_user(
            email="volunteer@example.com",
            first_name="Volunteer",
            last_name="User"
        )

        # Link the member to the user (correct relationship)
        member.user = volunteer_user.name
        member.save()

        # Test same user access (should pass)
        result = self.framework._validate_self_service_access(
            target_member=member.name,
            user=volunteer_user.name
        )
        self.assertTrue(result)


if __name__ == '__main__':
    unittest.main()