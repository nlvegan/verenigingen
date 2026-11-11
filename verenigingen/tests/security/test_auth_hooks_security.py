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
from unittest.mock import patch
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen import auth_hooks


class TestAuthHooksSecurity(EnhancedTestCase):
    """Test authentication hooks for security vulnerabilities and session issues"""

    def setUp(self):
        """Set up test data for authentication tests"""
        super().setUp()
        self.original_user = frappe.session.user
        # Set Administrator for authentication security testing
        frappe.set_user("Administrator")

        # Create the member first. The factory uniquifies the email for test
        # isolation, so we read the resulting email back and build the member's
        # User account with that SAME email - the self-service auth path resolves
        # a user's member by matching Member.email to the user, so they must align.
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Member",
            email="test.member@example.com",
        )

        # The member user must hold a real member role (not Guest) so it passes
        # the self-service (LOW) auth tier; ownership is then enforced by email.
        self.test_member_user = self.create_test_user(
            email=self.test_member.email,
            roles=["Verenigingen Member"],
            first_name="Test",
            last_name="Member"
        )

        # Link the user back onto the member record.
        self.test_member.db_set("user", self.test_member_user.name)
        self.test_member.reload()

        self.test_volunteer_user = self.create_test_user(
            email="test.volunteer@example.com",
            roles=["Verenigingen Volunteer"],
            first_name="Test",
            last_name="Volunteer"
        )

        self.test_admin_user = self.create_test_user(
            email="test.admin@example.com",
            roles=["System Manager"],  # Standard admin role
            first_name="Test",
            last_name="Admin"
        )

    def tearDown(self):
        """Clean up after authentication tests"""
        frappe.set_user(self.original_user)
        super().tearDown()

    # ===== RACE CONDITION TESTS =====

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

    # ===== ROLE CHECKING SECURITY TESTS =====

    def test_has_member_role_true_for_verenigingen_member(self):
        """Regression: a user holding the real "Verenigingen Member" role must be
        recognized. The check previously tested the phantom "Member" role (which
        does not exist on the site), so it returned False for every real member
        and the role-based portal redirect never fired."""
        result = auth_hooks.has_member_role(self.test_member_user.name)
        self.assertTrue(result, "Verenigingen Member user should be recognized as a member")

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

    def _set_request_path(self, path):
        """Set a minimal request object on frappe.local with the given path.

        Returns the previous value so the caller can restore it. We set the
        attribute directly rather than patching it, because frappe.local.request
        is often unset in the test runner context and unittest.mock.patch then
        fails in get_original().
        """
        previous = getattr(frappe.local, "request", None)

        class _Req:
            pass

        req = _Req()
        req.path = path
        frappe.local.request = req  # Mock justified: Infrastructure - simulated request path
        return previous

    def test_before_request_with_none_user(self):
        """The portal-access hook must handle the Guest user without raising."""
        frappe.set_user("Guest")
        previous = self._set_request_path("/app/Member")
        try:
            # enforce_member_portal_access is the real before-request hook
            # (the old before_request/validate_session_before_request was removed).
            auth_hooks.enforce_member_portal_access()
            self.assertTrue(True, "enforce_member_portal_access handled Guest user")
        except Exception as e:
            self.fail(f"enforce_member_portal_access should handle Guest user: {e}")
        finally:
            frappe.local.request = previous  # Mock justified: Infrastructure - restore

    def test_before_request_database_failure(self):
        """The portal-access hook must swallow database failures, not crash the request."""
        frappe.set_user(self.test_member_user.name)
        previous = self._set_request_path("/app/Member")
        # Mock justified: Infrastructure - simulating a DB outage inside the hook,
        # not the boundary under test (the hook's own resilience).
        with patch('frappe.get_roles', side_effect=Exception("Database error")):
            try:
                auth_hooks.enforce_member_portal_access()
                self.assertTrue(True, "enforce_member_portal_access handled database error")
            except Exception as e:
                self.fail(f"enforce_member_portal_access should handle database errors: {e}")
            finally:
                frappe.local.request = previous  # Mock justified: Infrastructure - restore

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
            # Cleanup handled by tearDown method
            pass

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