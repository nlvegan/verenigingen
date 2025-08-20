"""
Critical Authentication Hooks Security Tests

Tests specifically designed to catch the "User None is disabled" session validation error
and other critical security issues in authentication hooks without complex setup.
"""

import unittest
import frappe
from unittest.mock import patch, MagicMock
from verenigingen import auth_hooks


class TestAuthHooksCriticalSecurity(unittest.TestCase):
    """Critical security tests for authentication hooks"""

    def setUp(self):
        """Minimal setup for critical tests"""
        self.original_user = frappe.session.user
        
    def tearDown(self):
        """Clean up after tests"""
        frappe.session.user = self.original_user

    # ===== CRITICAL SESSION VALIDATION TESTS =====

    def test_on_session_creation_with_none_user(self):
        """CRITICAL: Test session creation handles None user without breaking"""
        with patch('frappe.session.user', None):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                print("✅ PASS: None user handled without exception")
            except Exception as e:
                self.fail(f"❌ CRITICAL: Session creation failed with None user: {e}")

    def test_on_session_creation_with_empty_user(self):
        """CRITICAL: Test session creation handles empty string user"""
        with patch('frappe.session.user', ""):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                print("✅ PASS: Empty user handled without exception")
            except Exception as e:
                self.fail(f"❌ CRITICAL: Session creation failed with empty user: {e}")

    def test_on_session_creation_database_error(self):
        """CRITICAL: Test session creation handles database failures"""
        with patch('frappe.session.user', 'test@example.com'):
            with patch('frappe.db.get_value', side_effect=Exception("Database connection failed")):
                login_manager = MagicMock()
                
                try:
                    auth_hooks.on_session_creation(login_manager)
                    print("✅ PASS: Database error handled gracefully")
                except Exception as e:
                    self.fail(f"❌ CRITICAL: Session creation should handle DB errors: {e}")

    def test_has_member_role_with_invalid_users(self):
        """CRITICAL: Test role checking handles invalid users safely"""
        # Test with None user
        try:
            result = auth_hooks.has_member_role(None)
            self.assertFalse(result, "Should return False for None user")
            print("✅ PASS: has_member_role handles None user")
        except Exception as e:
            self.fail(f"❌ CRITICAL: has_member_role failed with None user: {e}")
        
        # Test with empty string
        try:
            result = auth_hooks.has_member_role("")
            self.assertFalse(result, "Should return False for empty user")
            print("✅ PASS: has_member_role handles empty user")
        except Exception as e:
            self.fail(f"❌ CRITICAL: has_member_role failed with empty user: {e}")

    def test_has_volunteer_role_with_invalid_users(self):
        """CRITICAL: Test volunteer role checking handles invalid users"""
        try:
            result = auth_hooks.has_volunteer_role(None)
            self.assertFalse(result, "Should return False for None user")
            print("✅ PASS: has_volunteer_role handles None user")
        except Exception as e:
            self.fail(f"❌ CRITICAL: has_volunteer_role failed with None user: {e}")

    def test_has_system_access_with_invalid_users(self):
        """CRITICAL: Test system access checking handles invalid users"""
        try:
            result = auth_hooks.has_system_access(None)
            self.assertFalse(result, "Should return False for None user")
            print("✅ PASS: has_system_access handles None user")
        except Exception as e:
            self.fail(f"❌ CRITICAL: has_system_access failed with None user: {e}")

    def test_get_default_home_page_with_none_user(self):
        """CRITICAL: Test home page function handles None user"""
        try:
            result = auth_hooks.get_default_home_page(user=None)
            self.assertIsNotNone(result, "Should return valid home page for None user")
            print(f"✅ PASS: get_default_home_page returned {result} for None user")
        except Exception as e:
            self.fail(f"❌ CRITICAL: get_default_home_page failed with None user: {e}")

    def test_before_request_with_none_user(self):
        """CRITICAL: Test before_request handles None user in session"""
        with patch('frappe.session.user', None):
            with patch('frappe.local.request') as mock_request:
                mock_request.path = "/app/Member"
                
                try:
                    auth_hooks.before_request()
                    print("✅ PASS: before_request handles None user")
                except Exception as e:
                    self.fail(f"❌ CRITICAL: before_request failed with None user: {e}")

    def test_session_creation_response_manipulation_safety(self):
        """CRITICAL: Test response manipulation doesn't corrupt session"""
        with patch('frappe.session.user', 'test@example.com'):
            with patch('frappe.local.response', {}) as mock_response:
                with patch('frappe.db.get_value', return_value='test_member'):
                    login_manager = MagicMock()
                    
                    try:
                        auth_hooks.on_session_creation(login_manager)
                        # Should set home page without corruption
                        self.assertIn("home_page", mock_response)
                        print("✅ PASS: Response manipulation handled safely")
                    except Exception as e:
                        self.fail(f"❌ CRITICAL: Response manipulation caused error: {e}")

    def test_frappe_get_roles_error_handling(self):
        """CRITICAL: Test role functions handle frappe.get_roles failures"""
        with patch('frappe.get_roles', side_effect=Exception("Role fetch failed")):
            try:
                result = auth_hooks.has_member_role('test@example.com')
                self.assertFalse(result, "Should return False when role fetch fails")
                print("✅ PASS: Role function handles get_roles failure")
            except Exception as e:
                self.fail(f"❌ CRITICAL: Role function should handle get_roles error: {e}")

    def test_guest_user_early_return(self):
        """CRITICAL: Test Guest user is handled correctly"""
        with patch('frappe.session.user', 'Guest'):
            login_manager = MagicMock()
            
            try:
                auth_hooks.on_session_creation(login_manager)
                print("✅ PASS: Guest user handled with early return")
            except Exception as e:
                self.fail(f"❌ CRITICAL: Guest user handling failed: {e}")

    def test_session_user_validation_edge_cases(self):
        """CRITICAL: Test various edge cases for session user validation"""
        edge_cases = [None, "", "None", "null", False, 0]
        
        for case in edge_cases:
            with patch('frappe.session.user', case):
                login_manager = MagicMock()
                
                try:
                    auth_hooks.on_session_creation(login_manager)
                    print(f"✅ PASS: Edge case {repr(case)} handled")
                except Exception as e:
                    self.fail(f"❌ CRITICAL: Edge case {repr(case)} failed: {e}")

    # ===== RACE CONDITION SIMULATION =====

    def test_concurrent_role_checking(self):
        """Test role checking under concurrent access doesn't fail"""
        import threading
        import time
        
        errors = []
        
        def check_roles():
            try:
                # Test with existing user to simulate real scenario
                auth_hooks.has_member_role('Administrator')
            except Exception as e:
                errors.append(str(e))
        
        # Simulate concurrent access
        threads = []
        for i in range(3):  # Reduced from 5 to avoid overwhelming
            t = threading.Thread(target=check_roles)
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join(timeout=5)
        
        if errors:
            self.fail(f"❌ CRITICAL: Concurrent role checking failed: {errors}")
        else:
            print("✅ PASS: Concurrent role checking handled safely")


def run_critical_auth_tests():
    """Run critical authentication tests"""
    print("🔥 Running CRITICAL Authentication Security Tests...")
    print("=" * 60)
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAuthHooksCriticalSecurity)
    runner = unittest.TextTestRunner(verbosity=1, stream=open('/dev/null', 'w'))
    result = runner.run(suite)
    
    print("=" * 60)
    if result.wasSuccessful():
        print("✅ ALL CRITICAL TESTS PASSED!")
        print("Authentication hooks appear secure against session corruption.")
    else:
        print(f"❌ CRITICAL FAILURES DETECTED:")
        print(f"   {len(result.failures)} test(s) failed")
        print(f"   {len(result.errors)} error(s) occurred")
        
        print("\n🚨 DETAILED FAILURE ANALYSIS:")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            # Show just the critical error message, not full traceback
            lines = traceback.split('\n')
            for line in lines:
                if 'CRITICAL' in line or 'fail(' in line:
                    print(f"   {line.strip()}")
        return False
    
    return True


if __name__ == "__main__":
    # Run when called directly
    run_critical_auth_tests()