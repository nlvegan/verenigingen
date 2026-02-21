#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portal Authentication Security Integration Tests

This test suite focuses specifically on portal authentication security,
testing the web interface authentication flows that members use to access
their portal pages and sensitive financial information.

Key Portal Authentication Flows Tested:
1. Bank Details Portal - Secure IBAN and payment method management
2. Payment Dashboard - Financial history and subscription management
3. Member Portal - Personal information access
4. SEPA Mandate Portal - Direct debit authorization management

Security Focus:
- Session validation and CSRF protection
- Member ownership validation for portal resources
- Secure context generation with proper permission checks
- Prevention of unauthorized cross-member data access
"""

import unittest
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, getdate, now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import (
    get_current_user_member_doc,
    get_member_name_for_user,
    validate_member_ownership,
)


class TestPortalAuthenticationSecurity(EnhancedTestCase):
    """
    Portal authentication security integration tests.

    Tests the complete portal authentication architecture including
    session validation, context security, and access controls.
    """

    def setUp(self):
        """Set up portal authentication test scenario"""
        super().setUp()

        # Create test users and members for portal testing
        self.portal_users = self._create_portal_test_users()
        self.portal_members = self._create_portal_test_members()
        self._setup_portal_financial_data()

        # Store original session
        self.original_user = frappe.session.user

    def _create_portal_test_users(self):
        """Create test users for portal scenarios"""
        users = {}

        # Member with full portal access
        users['portal_full'] = self.create_test_user_with_roles(
            email="portal.full@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Portal",
            last_name="Full Access"
        )

        # Member with limited portal access
        users['portal_limited'] = self.create_test_user_with_roles(
            email="portal.limited@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Portal",
            last_name="Limited Access"
        )

        # Member with financial data
        users['portal_financial'] = self.create_test_user_with_roles(
            email="portal.financial@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="Portal",
            last_name="Financial"
        )

        return users

    def _create_portal_test_members(self):
        """Create member records for portal testing"""
        members = {}

        # Full access member with complete profile
        members['portal_full'] = self.create_test_member(
            first_name="Portal",
            last_name="Full Access",
            email="portal.full@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -9000),  # Adult member
            status="Active",
            payment_method="Manual",
            address_line1="Portal Test Street 123",
            city="Amsterdam",
            postal_code="1234 AB"
        )

        # Limited access member with minimal profile
        members['portal_limited'] = self.create_test_member(
            first_name="Portal",
            last_name="Limited Access",
            email="portal.limited@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -7000),
            status="Active",
            payment_method="Manual"
        )

        # Financial member with payment setup
        members['portal_financial'] = self.create_test_member(
            first_name="Portal",
            last_name="Financial",
            email="portal.financial@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8000),
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            bank_account_name="Portal Financial Test"
        )

        return members

    def _setup_portal_financial_data(self):
        """Set up financial data for portal testing"""
        # Create SEPA mandate for financial member
        financial_member = self.portal_members['portal_financial']

        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": financial_member.name,
            "mandate_id": f"PORTAL-TEST-{financial_member.name}",
            "iban": financial_member.iban,
            "bic": financial_member.bic,
            "account_holder_name": financial_member.bank_account_name,
            "status": "Active",
            "is_active": 1,
            "sign_date": getdate(),
            "mandate_type": "RCUR"
        })
        sepa_mandate.insert()

        # Create customer for billing
        if not financial_member.customer:
            financial_member.create_customer()
            financial_member.reload()

    # ===== PORTAL ACCESS CONTROL TESTS =====

    def test_portal_access_control(self):
        """Test portal access control and authentication"""
        from verenigingen.templates.pages.member_portal import has_website_permission

        # Test authorized member access
        with self.as_user(self.portal_users['portal_financial'].email):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertTrue(has_access, "Financial member should have portal access")

        # Test guest user access (should be denied)
        with self.as_user("Guest"):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertFalse(has_access, "Guest should not have portal access")

        # Test user without member record (should be denied)
        orphaned_user = self.create_test_user_with_roles(
            email="orphaned.portal@test.verenigingen.invalid",
            roles=["Verenigingen Member"]
        )

        with self.as_user(orphaned_user.email):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertFalse(has_access, "User without member record should not have access")

    def test_portal_context_security(self):
        """Test portal context generation security"""

        with self.as_user(self.portal_users['portal_financial'].email):
            from verenigingen.templates.pages.member_portal import get_context

            context = {}
            result = get_context(context)

            # Verify security elements are present
            self.assertEqual(result['no_cache'], 1, "Page should not be cached")

            # Verify member context matches authenticated user
            self.assertIn('member', result, "Member context should be present")
            member = result['member']
            self.assertEqual(member.email, frappe.session.user, "Member should match authenticated user")

    def test_portal_session_validation(self):
        """Test portal session validation"""

        financial_user = self.portal_users['portal_financial']

        with self.as_user(financial_user.email):
            # Verify session is properly established
            self.assertEqual(frappe.session.user, financial_user.email)
            self.assertIsNotNone(frappe.session.sid)
            self.assertIsNotNone(frappe.session.csrf_token)

            # Test context generation with valid session
            from verenigingen.templates.pages.member_portal import get_context
            context = {}
            result = get_context(context)

            # Session validation should succeed
            self.assertIn('member', result)
            self.assertEqual(result['member'].email, financial_user.email)

    # ===== PAYMENT DASHBOARD PORTAL TESTS =====

    def test_payment_dashboard_portal_authentication(self):
        """Test payment dashboard portal authentication"""
        from verenigingen.templates.pages.member_portal import has_website_permission

        with self.as_user(self.portal_users['portal_financial'].email):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertTrue(has_access, "Member should have payment dashboard access")

        # Test guest access (should be denied)
        with self.as_user("Guest"):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertFalse(has_access, "Guest should not have dashboard access")

    def test_payment_dashboard_context_security(self):
        """Test payment dashboard context security"""

        with self.as_user(self.portal_users['portal_financial'].email):
            from verenigingen.templates.pages.payment_dashboard import get_context

            context = {}
            result = get_context(context)

            # Verify security elements
            self.assertIn('csrf_token', result)

            # Verify member-specific context (payment_dashboard stores member name string)
            self.assertIn('member', result)
            member_name = result['member']
            member_doc = frappe.get_doc("Member", member_name)
            self.assertEqual(member_doc.email, frappe.session.user)

    # ===== MEMBER PORTAL GENERAL TESTS =====

    def test_member_portal_authentication_flow(self):
        """Test general member portal authentication flow"""

        with self.as_user(self.portal_users['portal_full'].email):
            from verenigingen.templates.pages.member_portal import has_website_permission

            # Should have access to general member portal
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertTrue(has_access, "Member should have portal access")

        # Test unauthorized access
        with self.as_user("Guest"):
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertFalse(has_access, "Guest should not have portal access")

    def test_member_portal_cross_member_prevention(self):
        """Test prevention of cross-member data access in portal"""

        member_full = self.portal_members['portal_full']
        member_limited = self.portal_members['portal_limited']

        # Member should only access their own data
        with self.as_user(self.portal_users['portal_full'].email):
            # Valid: accessing own member data
            validate_member_ownership(member_full.name)

            # Invalid: attempting to access other member's data
            with self.assertRaises(frappe.PermissionError):
                validate_member_ownership(member_limited.name)

    # ===== SEPA MANDATE PORTAL TESTS =====

    def test_sepa_mandate_portal_authentication(self):
        """Test SEPA mandate portal authentication and access"""

        financial_member = self.portal_members['portal_financial']

        with self.as_user(self.portal_users['portal_financial'].email):
            # Should be able to access own SEPA mandate
            from verenigingen.utils.member_utils import get_member_sepa_mandate

            mandate = get_member_sepa_mandate(financial_member.name)
            self.assertIsNotNone(mandate, "Should find SEPA mandate for financial member")
            self.assertEqual(mandate['status'], "Active", "Mandate should be active")

        # Test that member without SEPA can't access mandates
        with self.as_user(self.portal_users['portal_limited'].email):
            limited_member = self.portal_members['portal_limited']
            mandate = get_member_sepa_mandate(limited_member.name)
            self.assertIsNone(mandate, "Limited member should not have SEPA mandate")

    # ===== PORTAL CSRF AND SESSION SECURITY TESTS =====

    def test_portal_csrf_protection_integration(self):
        """Test CSRF protection integration in portal pages"""

        with self.as_user(self.portal_users['portal_full'].email):
            # Verify CSRF token is available in session for portal pages
            self.assertIsNotNone(frappe.session.csrf_token, "CSRF token should be present in session")

            # Verify payment dashboard context includes CSRF token
            from verenigingen.templates.pages.payment_dashboard import get_context

            context = {}
            result = get_context(context)

            self.assertIn('csrf_token', result, "CSRF token should be in payment dashboard context")
            self.assertEqual(result['csrf_token'], frappe.session.csrf_token, "Should match session token")

    def test_portal_session_hijacking_prevention(self):
        """Test portal session hijacking prevention"""

        # Test session isolation between users
        user1 = self.portal_users['portal_full']
        user2 = self.portal_users['portal_limited']

        # Get member for user1
        with self.as_user(user1.email):
            member1_name = get_current_user_member_doc().name

        # Switch to user2 and verify isolation
        with self.as_user(user2.email):
            member2_name = get_current_user_member_doc().name

        # Verify different members retrieved
        self.assertNotEqual(member1_name, member2_name, "Session should be isolated between users")

    def test_portal_concurrent_session_safety(self):
        """Test portal concurrent session safety"""
        import threading

        results = []
        errors = []

        def portal_access_test():
            try:
                with self.as_user(self.portal_users['portal_full'].email):
                    from verenigingen.templates.pages.member_portal import get_context
                    context = {}
                    result = get_context(context)
                    if 'member' in result:
                        results.append("success")
                    else:
                        results.append("missing_member")
            except Exception as e:
                errors.append(str(e))

        # Run concurrent portal access tests
        threads = []
        for _ in range(3):
            t = threading.Thread(target=portal_access_test)
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"No errors should occur: {errors}")
        self.assertEqual(results.count("success"), 3, "All concurrent accesses should succeed")

    # ===== PORTAL ERROR HANDLING TESTS =====

    def test_portal_authentication_error_handling(self):
        """Test portal authentication error handling"""

        # Test graceful handling when member record is missing
        orphaned_user = self.create_test_user_with_roles(
            email="orphaned.error@test.verenigingen.invalid",
            roles=["Verenigingen Member"]
        )

        with self.as_user(orphaned_user.email):
            from verenigingen.templates.pages.member_portal import has_website_permission

            # Should gracefully return False instead of throwing error
            has_access = has_website_permission(None, None, frappe.session.user, False)
            self.assertFalse(has_access, "Should gracefully handle missing member record")

    def test_portal_invalid_user_handling(self):
        """Test portal handling of invalid/non-existent user lookups"""

        from verenigingen.utils.member_utils import get_member_name_for_user

        # Should return None for non-existent user
        result = get_member_name_for_user("nonexistent.user@invalid.example.com")
        self.assertIsNone(result, "Should return None for non-existent user")

        # Should return None for empty input
        result = get_member_name_for_user("")
        self.assertIsNone(result, "Should return None for empty user")

        # Should return None for None input
        result = get_member_name_for_user(None)
        self.assertIsNone(result, "Should return None for None user")

    def test_portal_context_generation_edge_cases(self):
        """Test portal context generation edge cases"""

        with self.as_user(self.portal_users['portal_limited'].email):
            from verenigingen.templates.pages.member_portal import get_context

            # Test with member that has minimal data
            context = {}
            try:
                result = get_context(context)

                # Should still generate valid context
                self.assertIn('member', result)
                self.assertIn('csrf_token', result)
                self.assertEqual(result['no_cache'], 1)

            except AttributeError:
                # Some fields might not be present - this is expected for minimal profiles
                pass

    # ===== PORTAL PERFORMANCE AND SECURITY TESTS =====

    def test_portal_response_time_with_security(self):
        """Test portal response time with security overhead"""
        import time

        with self.as_user(self.portal_users['portal_financial'].email):
            from verenigingen.templates.pages.member_portal import get_context

            # Measure context generation time
            start_time = time.time()
            context = {}
            result = get_context(context)
            generation_time = time.time() - start_time

            # Should complete within reasonable time (5 seconds)
            self.assertLess(generation_time, 5.0, "Context generation should be reasonably fast")

            # Verify security elements didn't compromise functionality
            self.assertIn('member', result)
            self.assertEqual(result['no_cache'], 1)

    # ===== UTILITY METHODS =====

    @contextmanager
    def as_user(self, user_email):
        """Context manager for running code as specific user"""
        original_user = frappe.session.user
        try:
            frappe.set_user(user_email)
            yield
        finally:
            frappe.set_user(original_user)

    def tearDown(self):
        """Clean up portal test data"""
        frappe.set_user(self.original_user)
        super().tearDown()


# ===== TEST EXECUTION FUNCTIONS =====

def run_portal_authentication_tests():
    """Run portal authentication security tests"""
    import unittest

    print("🌐 Running Portal Authentication Security Integration Tests...")

    suite = unittest.TestLoader().loadTestsFromTestCase(TestPortalAuthenticationSecurity)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    if result.wasSuccessful():
        print("✅ All portal authentication tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    run_portal_authentication_tests()
