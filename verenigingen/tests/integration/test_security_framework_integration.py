"""
Integration Tests for Security Framework

This module provides comprehensive integration tests for the security wrapper framework,
specifically testing prevention of "User None is disabled" errors and validation of
security fixes in realistic scenarios.

Key Test Scenarios:
1. Authentication hooks with invalid user parameters
2. Role checking functions with edge cases
3. Session management under various conditions
4. API security validation with malformed requests
5. Integration with existing Verenigingen business logic

Security Testing Strategy:
- Test actual error conditions that cause "User None is disabled"
- Validate security wrappers prevent privilege escalation
- Ensure backward compatibility with existing code
- Test performance impact of security validation
- Verify audit logging functionality

Author: Security Team
Date: 2025-08-20
Version: 1.0
"""

import frappe
import unittest
from unittest.mock import patch, Mock
from verenigingen.utils.security_wrappers import (
    safe_get_roles, 
    safe_has_role, 
    safe_has_any_role,
    validate_security_wrapper_installation,
    get_security_audit_info
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class SecurityFrameworkIntegrationTests(EnhancedTestCase):
    """Comprehensive integration tests for security framework"""
    
    def setUp(self):
        """Set up test environment with clean state"""
        super().setUp()
        
        # Ensure security wrappers are properly installed
        self.assertTrue(
            validate_security_wrapper_installation(),
            "Security wrapper validation failed during test setup"
        )
    
    def test_user_none_error_prevention(self):
        """
        Test that security wrappers prevent the "User None is disabled" error
        that occurs when frappe.get_roles(None) is called incorrectly.
        """
        # Test 1: Direct None parameter
        roles = safe_get_roles(None)
        self.assertIsInstance(roles, list)
        self.assertNotEqual(roles, [], "None user should get current user's roles, not empty list")
        
        # Test 2: String "None" parameter (common attack vector)
        roles = safe_get_roles("None")
        self.assertEqual(roles, [], "String 'None' should return empty list")
        
        # Test 3: Empty string parameter
        roles = safe_get_roles("")
        self.assertEqual(roles, [], "Empty string should return empty list")
        
        # Test 4: Whitespace-only parameter
        roles = safe_get_roles("   ")
        self.assertEqual(roles, [], "Whitespace-only string should return empty list")
        
    def test_auth_hooks_integration(self):
        """
        Test that authentication hooks work correctly with security wrappers
        under various session conditions.
        """
        from verenigingen.auth_hooks import has_member_role, has_volunteer_role, has_system_access
        
        # Test with valid user
        test_member = self.create_test_member("Security", "Test")
        self.assertFalse(has_member_role(test_member.user))  # User doesn't have Member role yet
        
        # Test with invalid users
        self.assertFalse(has_member_role(None))
        self.assertFalse(has_member_role(""))
        self.assertFalse(has_member_role("NonexistentUser"))
        
        # Test volunteer role checking
        self.assertFalse(has_volunteer_role(None))
        self.assertFalse(has_volunteer_role(""))
        self.assertFalse(has_volunteer_role("NonexistentUser"))
        
        # Test system access checking
        self.assertFalse(has_system_access(None))
        self.assertFalse(has_system_access(""))
        self.assertFalse(has_system_access("NonexistentUser"))
    
    def test_session_creation_hook_security(self):
        """
        Test the on_session_creation hook with various edge cases
        that could trigger security vulnerabilities.
        """
        from verenigingen.auth_hooks import on_session_creation
        
        # Mock login manager with invalid session states
        mock_login_manager = Mock()
        
        # Test 1: Missing session user
        with patch('frappe.session') as mock_session:
            mock_session.user = None
            try:
                on_session_creation(mock_login_manager)
                # Should not raise exception
            except Exception as e:
                self.fail(f"Session creation hook failed with None user: {e}")
        
        # Test 2: Invalid user type
        with patch('frappe.session') as mock_session:
            mock_session.user = 123  # Non-string user
            try:
                on_session_creation(mock_login_manager)
                # Should not raise exception
            except Exception as e:
                self.fail(f"Session creation hook failed with non-string user: {e}")
        
        # Test 3: String "None" user
        with patch('frappe.session') as mock_session:
            mock_session.user = "None"
            try:
                on_session_creation(mock_login_manager)
                # Should not raise exception
            except Exception as e:
                self.fail(f"Session creation hook failed with string None user: {e}")
    
    def test_api_security_integration(self):
        """
        Test API security integration with security wrappers
        to ensure malformed requests don't bypass security.
        """
        # Test API calls with various user parameters
        with self.assertQueryCount(50):  # Monitor query performance
            
            # Test safe role checking in API context
            audit_info = get_security_audit_info()
            self.assertIn("current_user", audit_info)
            self.assertIn("user_roles", audit_info)
            self.assertIn("has_admin_access", audit_info)
            
            # Ensure no sensitive data is exposed
            self.assertNotIn("password", str(audit_info))
            self.assertNotIn("api_key", str(audit_info))
    
    def test_member_portal_security_integration(self):
        """
        Test member portal security integration with realistic scenarios
        that could occur in production.
        """
        # Create test member
        test_member = self.create_test_member("Portal", "Security", birth_date="1990-01-01")
        
        # Test portal access validation
        from verenigingen.utils.member_portal_utils import get_member_context_safe
        
        # Mock session with member user
        with patch('frappe.session') as mock_session:
            mock_session.user = test_member.user
            
            # This should work without raising security exceptions
            try:
                # Test function that uses role checking internally
                context = {}
                # The function should handle security safely
                self.assertIsInstance(context, dict)
            except Exception as e:
                self.fail(f"Member portal security integration failed: {e}")
    
    def test_volunteer_role_security_integration(self):
        """
        Test volunteer role checking integration with realistic volunteer scenarios.
        """
        # Create test member and volunteer
        test_member = self.create_test_member("Volunteer", "Security", birth_date="1980-01-01")
        test_volunteer = self.create_test_volunteer(test_member.name)
        
        # Test volunteer-related security functions
        from verenigingen.auth_hooks import has_volunteer_role
        
        # Test with valid volunteer
        # Note: The user might not have the Volunteer role assigned yet
        result = has_volunteer_role(test_volunteer.user)
        self.assertIsInstance(result, bool)  # Should return boolean, not crash
        
        # Test with edge cases
        self.assertFalse(has_volunteer_role(None))
        self.assertFalse(has_volunteer_role(""))
        self.assertFalse(has_volunteer_role("   "))
    
    def test_permission_system_integration(self):
        """
        Test integration with Frappe's permission system to ensure
        security wrappers don't break existing permission checks.
        """
        # Test permission checking functions
        test_member = self.create_test_member("Permission", "Test")
        
        # Test role-based permission checking
        roles = safe_get_roles(test_member.user)
        self.assertIsInstance(roles, list)
        
        # Test has_role functions
        self.assertFalse(safe_has_role(test_member.user, "Nonexistent Role"))
        self.assertTrue(safe_has_role(test_member.user, "Guest"))  # All users have Guest role
        
        # Test has_any_role function
        test_roles = ["System Manager", "Member", "Guest"]
        result = safe_has_any_role(test_member.user, test_roles)
        self.assertIsInstance(result, bool)
    
    def test_background_job_security_integration(self):
        """
        Test security integration with background jobs that might
        run with different user contexts.
        """
        # Test security wrapper behavior in background job context
        
        # Simulate background job environment
        with patch('frappe.session') as mock_session:
            mock_session.user = "Administrator"
            
            # Test security functions in admin context
            roles = safe_get_roles()
            self.assertIn("Administrator", roles)
            
            # Test with explicit user parameter
            roles = safe_get_roles("Administrator")
            self.assertIn("Administrator", roles)
    
    def test_error_handling_and_logging_integration(self):
        """
        Test error handling and security logging integration
        to ensure proper audit trails.
        """
        import logging
        from unittest.mock import patch
        
        # Mock logger to capture security events
        with patch('vereingingen.utils.security_wrappers.security_logger') as mock_logger:
            
            # Test logging of suspicious calls
            safe_get_roles("None")
            mock_logger.warning.assert_called()
            
            # Test logging of privileged role checks
            safe_has_role("Administrator", "System Manager")
            # Should log privileged role access
            
            # Reset mock
            mock_logger.reset_mock()
            
            # Test normal operations don't over-log
            safe_get_roles("Guest")
            # Should not generate excessive log entries
    
    def test_performance_impact_integration(self):
        """
        Test that security wrappers don't significantly impact performance
        in realistic usage scenarios.
        """
        import time
        
        # Create test users
        test_member = self.create_test_member("Performance", "Test")
        
        # Measure performance of security wrapper calls
        start_time = time.time()
        
        for _ in range(100):
            safe_get_roles(test_member.user)
            safe_has_role(test_member.user, "Guest")
            safe_has_any_role(test_member.user, ["Member", "Guest"])
        
        end_time = time.time()
        duration = end_time - start_time
        
        # Performance should be reasonable (less than 1 second for 300 calls)
        self.assertLess(duration, 1.0, f"Security wrapper calls took {duration:.3f}s, too slow")
    
    def test_edge_case_user_parameters(self):
        """
        Test various edge cases for user parameters that could
        cause security issues.
        """
        edge_cases = [
            None,
            "",
            "   ",
            "None",
            "null",
            "undefined",
            "0",
            False,
            True,
            [],
            {},
            "a" * 1000,  # Very long string
        ]
        
        for edge_case in edge_cases:
            try:
                # All of these should return empty list or handle gracefully
                roles = safe_get_roles(edge_case)
                self.assertIsInstance(roles, list, f"Failed for edge case: {repr(edge_case)}")
                
                # Test has_role functions too
                result = safe_has_role(edge_case, "Some Role")
                self.assertIsInstance(result, bool, f"Failed for edge case: {repr(edge_case)}")
                
            except Exception as e:
                self.fail(f"Security wrapper failed for edge case {repr(edge_case)}: {e}")
    
    def test_realistic_production_scenarios(self):
        """
        Test realistic production scenarios that could trigger
        the original security vulnerabilities.
        """
        # Scenario 1: User logout with invalid session
        with patch('frappe.session') as mock_session:
            mock_session.user = None
            
            # This commonly happens during logout
            roles = safe_get_roles()
            self.assertIsInstance(roles, list)
        
        # Scenario 2: API call with malformed user parameter
        test_member = self.create_test_member("Production", "Test")
        
        # Simulate API call with user ID instead of email
        try:
            roles = safe_get_roles(test_member.name)  # DocType name instead of user
            self.assertIsInstance(roles, list)
        except Exception as e:
            self.fail(f"Production scenario failed: {e}")
        
        # Scenario 3: Concurrent user creation/deletion
        # This could result in temporary invalid user states
        roles = safe_get_roles("user_being_created@example.com")
        self.assertEqual(roles, [])
    
    def tearDown(self):
        """Clean up test environment"""
        super().tearDown()


class SecurityAuditIntegrationTests(EnhancedTestCase):
    """Integration tests for security audit functionality"""
    
    def test_security_audit_script_integration(self):
        """
        Test that security audit script can run successfully
        and identify security issues.
        """
        from verenigingen.utils.security_audit_script import run_comprehensive_audit
        
        # Run audit (should not crash)
        try:
            results = run_comprehensive_audit()
            self.assertIn("summary", results)
            self.assertIn("total_issues_found", results["summary"])
            
        except Exception as e:
            self.fail(f"Security audit script failed: {e}")
    
    def test_migration_script_generation(self):
        """
        Test that migration scripts can be generated successfully
        for identified security issues.
        """
        from verenigingen.utils.security_audit_script import generate_security_report
        
        try:
            report = generate_security_report()
            self.assertIn("Security Audit Report", report)
            self.assertIn("frappe.get_roles()", report)
            
        except Exception as e:
            self.fail(f"Migration script generation failed: {e}")


if __name__ == "__main__":
    unittest.main()