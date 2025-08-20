"""
Authentication Hooks Security Test Suite

Tests for authentication system security, session handling, and validation
to prevent "User None is disabled" errors and session corruption.

This test suite covers:
1. Session creation safety and error conditions
2. Race conditions in database queries during session creation
3. Prevention of invalid or corrupted session states
4. Validation of edge cases in user authentication
5. Best practices for Frappe session management
"""

import unittest
import frappe
from unittest.mock import patch, MagicMock
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen import auth_hooks


class TestAuthHooksSecurity(EnhancedTestCase):
    """Test authentication hooks for security vulnerabilities and session issues"""

    def setUp(self):
        """Set up test data for authentication tests"""
        super().setUp()
        
        # Create test users with different roles
        self.test_member_user = self.create_test_user(
            email="test.member@example.com",
            first_name="Test",
            last_name="Member",
            roles=["Member"]
        )
        
        self.test_volunteer_user = self.create_test_user(
            email="test.volunteer@example.com", 
            first_name="Test",
            last_name="Volunteer",
            roles=["Volunteer"]
        )
        
        self.test_admin_user = self.create_test_user(
            email="test.admin@example.com",
            first_name="Test", 
            last_name="Admin",
            roles=["System Manager"]
        )
        
        # Create linked member record for member user
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email="test.member@example.com",
            user=self.test_member_user.name
        )

    def create_test_user(self, email, first_name, last_name, roles=None):
        """Helper to create test users with roles"""
        user = frappe.get_doc({
            "doctype": "User",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "enabled": 1,
            "new_password": "test123",
            "roles": [{"role": role} for role in (roles or [])]
        })
        user.insert(ignore_permissions=True)
        return user

    # ===== SESSION CREATION SAFETY TESTS =====

    def test_session_creation_with_none_user(self):
        """Test session creation handles None user gracefully"""
        # Mock frappe.session.user to be None
        with patch('frappe.session.user', None):
            login_manager = MagicMock()
            
            # Should not raise exception, should return early
            try:
                auth_hooks.on_session_creation(login_manager)
                self.assertTrue(True, "Function handled None user without error")
            except Exception as e:
                self.fail(f"Session creation failed with None user: {e}")

    def test_session_creation_with_empty_user(self):
        """Test session creation handles empty string user"""
        with patch('frappe.session.user', ""):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                self.assertTrue(True, "Function handled empty user without error")
            except Exception as e:
                self.fail(f"Session creation failed with empty user: {e}")

    def test_session_creation_with_invalid_login_manager(self):
        """Test session creation handles invalid login_manager"""
        with patch('frappe.session.user', 'test@example.com'):
            # Pass None as login manager
            try:
                auth_hooks.on_session_creation(None)
                self.assertTrue(True, "Function handled None login_manager")
            except Exception as e:
                self.fail(f"Session creation failed with None login_manager: {e}")

    def test_database_failure_during_session_creation(self):
        """Test session creation handles database failures gracefully"""
        with patch('frappe.session.user', 'test@example.com'):
            # Mock database failure
            with patch('frappe.db.get_value', side_effect=Exception("Database connection failed")):
                login_manager = MagicMock()
                
                try:
                    auth_hooks.on_session_creation(login_manager)
                    self.assertTrue(True, "Function handled database failure gracefully")
                except Exception as e:
                    self.fail(f"Session creation should handle database errors: {e}")

    # ===== RACE CONDITION TESTS =====

    def test_concurrent_session_creation(self):
        """Test multiple simultaneous session creation attempts"""
        import threading
        import time
        
        results = []
        errors = []
        
        def create_session():
            try:
                with patch('frappe.session.user', self.test_member_user.name):
                    login_manager = MagicMock()
                    auth_hooks.on_session_creation(login_manager)
                    results.append("success")
            except Exception as e:
                errors.append(str(e))
        
        # Start multiple threads to simulate race condition
        threads = []
        for i in range(5):
            t = threading.Thread(target=create_session)
            threads.append(t)
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join(timeout=10)
        
        # Check no errors occurred
        if errors:
            self.fail(f"Race condition caused errors: {errors}")
        
        self.assertEqual(len(results), 5, "Not all concurrent sessions completed")

    def test_user_role_check_race_condition(self):
        """Test role checking doesn't fail under concurrent access"""
        # Test multiple concurrent role checks
        def check_roles():
            try:
                result = auth_hooks.has_member_role(self.test_member_user.name)
                return result
            except Exception as e:
                return f"Error: {e}"
        
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(check_roles) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        # Check no errors occurred
        errors = [r for r in results if isinstance(r, str) and r.startswith("Error:")]
        if errors:
            self.fail(f"Concurrent role checks failed: {errors}")

    # ===== SESSION STATE VALIDATION TESTS =====

    def test_member_portal_redirect_safety(self):
        """Test member portal redirect doesn't corrupt session"""
        with patch('frappe.session.user', self.test_member_user.name):
            with patch('frappe.local.response', {}) as mock_response:
                login_manager = MagicMock()
                
                auth_hooks.on_session_creation(login_manager)
                
                # Check redirect was set safely
                self.assertIn("home_page", mock_response)
                self.assertEqual(mock_response["home_page"], "/member_portal")

    def test_session_state_integrity(self):
        """Test session state remains consistent after auth hook"""
        original_user = frappe.session.user
        
        with patch('frappe.session.user', self.test_member_user.name):
            login_manager = MagicMock()
            auth_hooks.on_session_creation(login_manager)
            
            # Session user should remain unchanged
            self.assertEqual(frappe.session.user, self.test_member_user.name)
        
        # Restore original session
        frappe.session.user = original_user

    # ===== EDGE CASE VALIDATION TESTS =====

    def test_guest_user_handling(self):
        """Test guest user is handled correctly"""
        with patch('frappe.session.user', 'Guest'):
            login_manager = MagicMock()
            
            # Should return early without processing
            auth_hooks.on_session_creation(login_manager)
            self.assertTrue(True, "Guest user handled correctly")

    def test_nonexistent_user_handling(self):
        """Test handling of user that doesn't exist"""
        with patch('frappe.session.user', 'nonexistent@user.com'):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                self.assertTrue(True, "Nonexistent user handled gracefully")
            except Exception as e:
                self.fail(f"Should handle nonexistent user: {e}")

    def test_user_with_no_roles(self):
        """Test user with no roles is handled correctly"""
        # Create user with no roles
        user_no_roles = self.create_test_user(
            email="no.roles@example.com",
            first_name="No",
            last_name="Roles",
            roles=[]
        )
        
        with patch('frappe.session.user', user_no_roles.name):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                self.assertTrue(True, "User with no roles handled correctly")
            except Exception as e:
                self.fail(f"Should handle user with no roles: {e}")

    # ===== ROLE CHECKING SECURITY TESTS =====

    def test_has_member_role_with_invalid_user(self):
        """Test has_member_role handles invalid users safely"""
        # Test with None user
        result = auth_hooks.has_member_role(None)
        self.assertFalse(result, "Should return False for None user")
        
        # Test with empty string
        result = auth_hooks.has_member_role("")
        self.assertFalse(result, "Should return False for empty user")
        
        # Test with nonexistent user  
        result = auth_hooks.has_member_role("nonexistent@user.com")
        self.assertFalse(result, "Should return False for nonexistent user")

    def test_has_volunteer_role_with_invalid_user(self):
        """Test has_volunteer_role handles invalid users safely"""
        result = auth_hooks.has_volunteer_role(None)
        self.assertFalse(result, "Should return False for None user")
        
        result = auth_hooks.has_volunteer_role("")
        self.assertFalse(result, "Should return False for empty user")

    def test_has_system_access_with_invalid_user(self):
        """Test has_system_access handles invalid users safely"""
        result = auth_hooks.has_system_access(None)
        self.assertFalse(result, "Should return False for None user")
        
        result = auth_hooks.has_system_access("")
        self.assertFalse(result, "Should return False for empty user")

    # ===== BEFORE REQUEST HOOK TESTS =====

    def test_before_request_with_none_user(self):
        """Test before_request hook handles None user"""
        with patch('frappe.session.user', None):
            with patch('frappe.local.request') as mock_request:
                mock_request.path = "/app/Member"
                
                try:
                    auth_hooks.before_request()
                    self.assertTrue(True, "before_request handled None user")
                except Exception as e:
                    self.fail(f"before_request should handle None user: {e}")

    def test_before_request_database_failure(self):
        """Test before_request handles database failures"""
        with patch('frappe.session.user', self.test_member_user.name):
            with patch('frappe.local.request') as mock_request:
                mock_request.path = "/app/Member"
                with patch('frappe.get_roles', side_effect=Exception("Database error")):
                    
                    try:
                        auth_hooks.before_request()
                        self.assertTrue(True, "before_request handled database error")
                    except Exception as e:
                        self.fail(f"before_request should handle database errors: {e}")

    # ===== API SECURITY TESTS =====

    def test_get_member_home_page_api_security(self):
        """Test API method handles session validation"""
        frappe.set_user(self.test_member_user.name)
        
        try:
            home_page = auth_hooks.get_member_home_page()
            self.assertIsNotNone(home_page, "API should return home page")
        except Exception as e:
            self.fail(f"API method failed: {e}")
        finally:
            frappe.set_user("Administrator")

    def test_get_default_home_page_with_invalid_user(self):
        """Test get_default_home_page handles invalid users"""
        result = auth_hooks.get_default_home_page(user=None)
        self.assertEqual(result, "/web", "Should return default for None user")
        
        result = auth_hooks.get_default_home_page(user="")
        self.assertEqual(result, "/web", "Should return default for empty user")


def run_auth_hooks_security_tests():
    """Run authentication hooks security tests"""
    print("🔐 Running Authentication Hooks Security Tests...")
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAuthHooksSecurity)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All authentication security tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    # Run when called directly
    run_auth_hooks_security_tests()