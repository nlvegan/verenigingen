#!/usr/bin/env python3

from verenigingen.utils.validation_utilities import DocumentExistenceValidator
# -*- coding: utf-8 -*-
"""
API Authentication with Security Decorators Integration Tests

This test suite provides comprehensive integration testing of the API security
framework decorators in realistic authentication scenarios. It validates that
the security decorators properly integrate with the member authentication system
and enforce security boundaries correctly.

Key API Authentication Patterns Tested:
1. Security decorator integration with member lookup utilities
2. Role-based access control enforcement through decorators
3. Member ownership validation in decorated API endpoints
4. Financial operation security with SEPA mandate validation
5. Multi-layer security validation (authentication + authorization + ownership)

Security Focus:
- End-to-end API security validation
- Realistic attack scenario prevention
- Performance impact of layered security
- Error handling and audit trail generation
"""

import time
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.utils import now_datetime, add_days, getdate

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import (
    get_current_user_member_name,
    get_current_user_member_doc,
    validate_member_ownership,
    get_member_sepa_mandate,
    has_mollie_subscription
)
from verenigingen.utils.security.api_security_framework import (
    SecurityLevel,
    OperationType,
    api_security_framework,
    critical_api,
    high_security_api,
    standard_api,
    utility_api,
    public_api
)


class TestAPIAuthenticationDecoratorsIntegration(EnhancedTestCase):
    """
    Integration tests for API security decorators with authentication system.
    
    Tests the complete integration of security decorators with the member
    authentication system, validating that all security layers work together.
    """

    def setUp(self):
        """Set up API authentication integration test scenario"""
        super().setUp()
        
        # Create comprehensive user-member relationships for API testing
        self.api_users = self._create_api_test_users()
        self.api_members = self._create_api_test_members()
        self._setup_api_test_data()
        
        # Store original session
        self.original_user = frappe.session.user

    def _create_api_test_users(self):
        """Create test users for API authentication scenarios"""
        users = {}
        
        # System administrator
        users['admin'] = self.create_test_user_with_roles(
            email="admin.api@test.verenigingen.invalid",
            roles=["System Manager", "Verenigingen Administrator"],
            first_name="API",
            last_name="Administrator"
        )
        
        # Association manager
        users['manager'] = self.create_test_user_with_roles(
            email="manager.api@test.verenigingen.invalid",
            roles=["Verenigingen Staff", "Verenigingen Staff"],
            first_name="API",
            last_name="Manager"
        )
        
        # Staff member
        users['staff'] = self.create_test_user_with_roles(
            email="staff.api@test.verenigingen.invalid",
            roles=["Verenigingen Staff"],
            first_name="API",
            last_name="Staff"
        )
        
        # Regular member with full profile
        users['member_full'] = self.create_test_user_with_roles(
            email="member.full.api@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="API",
            last_name="Member Full"
        )
        
        # Member with financial data access
        users['member_financial'] = self.create_test_user_with_roles(
            email="member.financial.api@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="API",
            last_name="Member Financial"
        )
        
        # Basic member with minimal access
        users['member_basic'] = self.create_test_user_with_roles(
            email="member.basic.api@test.verenigingen.invalid",
            roles=["Verenigingen Member"],
            first_name="API",
            last_name="Member Basic"
        )
        
        # Volunteer with dual access
        users['volunteer'] = self.create_test_user_with_roles(
            email="volunteer.api@test.verenigingen.invalid",
            roles=["Verenigingen Volunteer", "Verenigingen Member"],
            first_name="API",
            last_name="Volunteer"
        )
        
        return users

    def _create_api_test_members(self):
        """Create member records for API testing"""
        members = {}
        
        # Full profile member
        members['member_full'] = self.create_test_member(
            first_name="API",
            last_name="Member Full",
            email="member.full.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -9000),  # Adult
            status="Active",
            payment_method="Manual"
        )
        
        # Financial member with SEPA setup
        members['member_financial'] = self.create_test_member(
            first_name="API",
            last_name="Member Financial",
            email="member.financial.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8000),
            status="Active",
            payment_method="SEPA Direct Debit",
            iban="NL91ABNA0417164300",
            bic="ABNANL2A",
            bank_account_name="API Financial Test"
        )
        
        # Basic member
        members['member_basic'] = self.create_test_member(
            first_name="API",
            last_name="Member Basic",
            email="member.basic.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -7000),
            status="Active",
            payment_method="Manual"
        )
        
        # Volunteer member
        members['volunteer'] = self.create_test_member(
            first_name="API",
            last_name="Volunteer",
            email="volunteer.api@test.verenigingen.invalid",
            birth_date=add_days(getdate(), -8500),
            status="Active",
            payment_method="Mollie",
            mollie_customer_id="cst_api_volunteer",
            mollie_subscription_id="sub_api_volunteer", 
            subscription_status="active"
        )
        
        return members

    def _setup_api_test_data(self):
        """Set up additional test data for API testing"""
        # Create SEPA mandate for financial member
        financial_member = self.api_members['member_financial']
        
        sepa_mandate = frappe.get_doc({
            "doctype": "SEPA Mandate",
            "member": financial_member.name,
            "mandate_id": f"API-TEST-{financial_member.name}",
            "iban": financial_member.iban,
            "bic": financial_member.bic,
            "account_holder_name": financial_member.bank_account_name,
            "status": "Active",
            "is_active": 1,
            "sign_date": getdate(),
            "mandate_type": "RCUR"
        })
        sepa_mandate.insert()
        
        # Create volunteer record
        volunteer_member = self.api_members['volunteer']
        self.api_volunteer = self.create_test_volunteer(
            member_name=volunteer_member.name,
            volunteer_name=volunteer_member.full_name,
            email=volunteer_member.email,
            status="Active"
        )
        
        # Set up customer relationships for billing
        for member in self.api_members.values():
            if not member.customer:
                member.create_customer()
                member.reload()

    # ===== BASIC SECURITY DECORATOR INTEGRATION TESTS =====

    def test_public_api_decorator_integration(self):
        """Test public API decorator integration with authentication system"""
        
        @public_api(operation_type=OperationType.PUBLIC)
        def test_public_endpoint():
            return {
                "public": "access_granted",
                "user": frappe.session.user,
                "authenticated": frappe.session.user != "Guest"
            }
        
        # Test guest access (should work)
        with self.as_user("Guest"):
            result = test_public_endpoint()
            self.assertEqual(result["public"], "access_granted")
            self.assertEqual(result["user"], "Guest")
            self.assertFalse(result["authenticated"])
        
        # Test authenticated user access (should also work)
        with self.as_user(self.api_users['member_full'].email):
            result = test_public_endpoint()
            self.assertEqual(result["public"], "access_granted")
            self.assertEqual(result["user"], self.api_users['member_full'].email)
            self.assertTrue(result["authenticated"])

    def test_utility_api_decorator_integration(self):
        """Test utility API decorator integration"""
        
        @utility_api(operation_type=OperationType.UTILITY)
        def test_utility_endpoint():
            # Even utility APIs can access authentication context
            current_user = frappe.session.user
            member_name = None
            
            if current_user != "Guest":
                member_name = get_current_user_member_name()
            
            return {
                "utility": "access_granted",
                "user": current_user,
                "has_member": bool(member_name),
                "member": member_name
            }
        
        # Test with authenticated member
        with self.as_user(self.api_users['member_full'].email):
            result = test_utility_endpoint()
            self.assertEqual(result["utility"], "access_granted")
            self.assertTrue(result["has_member"])
            self.assertEqual(result["member"], self.api_members['member_full'].name)
        
        # Test with authenticated user without member record
        with self.as_user(self.api_users['admin'].email):
            result = test_utility_endpoint()
            self.assertEqual(result["utility"], "access_granted")
            self.assertFalse(result["has_member"])
            self.assertIsNone(result["member"])

    # ===== MEMBER DATA ACCESS SECURITY TESTS =====

    def test_standard_api_member_data_integration(self):
        """Test standard API decorator with member data access"""
        
        @standard_api(operation_type=OperationType.MEMBER_DATA)
        def get_member_profile():
            member_doc = get_current_user_member_doc()
            return {
                "member_name": member_doc.name,
                "full_name": member_doc.full_name,
                "email": member_doc.email,
                "status": member_doc.status
            }
        
        # Test successful access with member user
        with self.as_user(self.api_users['member_full'].email):
            result = get_member_profile()
            self.assertEqual(result["member_name"], self.api_members['member_full'].name)
            self.assertEqual(result["email"], self.api_users['member_full'].email)
        
        # Test access denied for admin without member record
        with self.as_user(self.api_users['admin'].email):
            with self.assertRaises(frappe.DoesNotExistError):
                get_member_profile()

    def test_high_security_api_member_ownership_validation(self):
        """Test high security API with member ownership validation"""
        
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def update_member_data(member_id, new_address):
            # Validate ownership before allowing update
            validate_member_ownership(member_id)
            
            member = frappe.get_doc("Member", member_id)
            old_address = member.address_line1
            member.address_line1 = new_address
            member.save()
            
            return {
                "updated": True,
                "member": member_id,
                "old_address": old_address,
                "new_address": new_address
            }
        
        member_full = self.api_members['member_full']
        member_basic = self.api_members['member_basic']
        
        # Test successful update of own member data
        with self.as_user(self.api_users['member_full'].email):
            result = update_member_data(member_full.name, "New Test Address 456")
            self.assertTrue(result["updated"])
            self.assertEqual(result["member"], member_full.name)
            self.assertEqual(result["new_address"], "New Test Address 456")
        
        # Test access denied for other member's data
        with self.as_user(self.api_users['member_full'].email):
            with self.assertRaises(frappe.PermissionError):
                update_member_data(member_basic.name, "Unauthorized Address")

    # ===== FINANCIAL OPERATION SECURITY TESTS =====

    def test_critical_api_financial_operations(self):
        """Test critical API decorator with financial operations"""
        
        @critical_api(operation_type=OperationType.FINANCIAL)
        def process_sepa_payment(member_id, amount):
            # Validate admin access and member ownership
            current_user = frappe.session.user
            user_roles = frappe.get_roles(current_user)
            
            if "System Manager" not in user_roles and "Verenigingen Administrator" not in user_roles:
                frappe.throw("Administrative access required", frappe.PermissionError)
            
            # Validate member exists and has SEPA mandate
            if not DocumentExistenceValidator.check_document_exists("Member", member_id):
                frappe.throw("Member not found", frappe.DoesNotExistError)
                
            sepa_mandate = get_member_sepa_mandate(member_id)
            if not sepa_mandate:
                frappe.throw("No active SEPA mandate found", frappe.ValidationError)
            
            return {
                "payment_processed": True,
                "member": member_id,
                "amount": amount,
                "mandate_id": sepa_mandate["mandate_id"],
                "processor": current_user
            }
        
        financial_member = self.api_members['member_financial']
        
        # Test successful financial operation with admin user
        with self.as_user(self.api_users['admin'].email):
            result = process_sepa_payment(financial_member.name, 50.0)
            self.assertTrue(result["payment_processed"])
            self.assertEqual(result["member"], financial_member.name)
            self.assertEqual(result["amount"], 50.0)
            self.assertEqual(result["processor"], self.api_users['admin'].email)
        
        # Test access denied for non-admin user
        with self.as_user(self.api_users['staff'].email):
            with self.assertRaises(Exception):  # Should be denied by decorator
                process_sepa_payment(financial_member.name, 50.0)

    def test_financial_api_mollie_integration(self):
        """Test financial API integration with Mollie subscriptions"""
        
        @high_security_api(operation_type=OperationType.FINANCIAL)
        def manage_mollie_subscription(action):
            member_doc = get_current_user_member_doc()
            
            if not has_mollie_subscription():
                frappe.throw("No active Mollie subscription found")
            
            return {
                "action": action,
                "member": member_doc.name,
                "customer_id": member_doc.mollie_customer_id,
                "subscription_id": member_doc.mollie_subscription_id,
                "status": member_doc.subscription_status
            }
        
        # Test with volunteer who has Mollie subscription
        with self.as_user(self.api_users['volunteer'].email):
            result = manage_mollie_subscription("status_check")
            self.assertEqual(result["action"], "status_check")
            self.assertEqual(result["member"], self.api_members['volunteer'].name)
            self.assertIsNotNone(result["customer_id"])
        
        # Test with member without Mollie subscription
        with self.as_user(self.api_users['member_financial'].email):
            with self.assertRaises(frappe.ValidationError):
                manage_mollie_subscription("status_check")

    # ===== ROLE-BASED ACCESS CONTROL INTEGRATION TESTS =====

    def test_api_role_matrix_integration(self):
        """Test comprehensive role-based access control matrix"""
        
        # Critical level API (Admin only)
        @critical_api(operation_type=OperationType.ADMIN)
        def admin_operation():
            return {"level": "critical", "user": frappe.session.user}
        
        # High level API (Manager+)
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def manager_operation():
            return {"level": "high", "user": frappe.session.user}
        
        # Standard level API (Staff+)
        @standard_api(operation_type=OperationType.REPORTING)
        def staff_operation():
            return {"level": "standard", "user": frappe.session.user}
        
        # Test admin access (should access all levels)
        with self.as_user(self.api_users['admin'].email):
            admin_result = admin_operation()
            self.assertEqual(admin_result["level"], "critical")
            
            manager_result = manager_operation()
            self.assertEqual(manager_result["level"], "high")
            
            staff_result = staff_operation()
            self.assertEqual(staff_result["level"], "standard")
        
        # Test manager access (should access high and standard)
        with self.as_user(self.api_users['manager'].email):
            with self.assertRaises(Exception):
                admin_operation()  # Should be denied
            
            manager_result = manager_operation()
            self.assertEqual(manager_result["level"], "high")
            
            staff_result = staff_operation()
            self.assertEqual(staff_result["level"], "standard")
        
        # Test staff access (should only access standard)
        with self.as_user(self.api_users['staff'].email):
            with self.assertRaises(Exception):
                admin_operation()  # Should be denied
            
            with self.assertRaises(Exception):
                manager_operation()  # Should be denied
            
            staff_result = staff_operation()
            self.assertEqual(staff_result["level"], "standard")

    def test_volunteer_role_integration(self):
        """Test volunteer role integration with API security"""
        
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def volunteer_profile_access():
            member_doc = get_current_user_member_doc()
            
            # Check if user is also a volunteer
            from verenigingen.utils.member_utils import get_volunteer_for_current_user
            volunteer_name = get_volunteer_for_current_user()
            
            return {
                "member": member_doc.name,
                "is_volunteer": bool(volunteer_name),
                "volunteer_name": volunteer_name,
                "roles": frappe.get_roles(frappe.session.user)
            }
        
        # Test with volunteer user
        with self.as_user(self.api_users['volunteer'].email):
            result = volunteer_profile_access()
            self.assertTrue(result["is_volunteer"])
            self.assertEqual(result["volunteer_name"], self.api_volunteer.name)
            self.assertIn("Verenigingen Volunteer", result["roles"])
            self.assertIn("Verenigingen Member", result["roles"])

    # ===== SECURITY BOUNDARY AND ATTACK PREVENTION TESTS =====

    def test_api_session_hijacking_prevention(self):
        """Test API session hijacking prevention"""
        
        @standard_api(operation_type=OperationType.MEMBER_DATA)
        def session_sensitive_operation():
            member_doc = get_current_user_member_doc()
            return {
                "session_user": frappe.session.user,
                "member_name": member_doc.name,
                "member_email": member_doc.email
            }
        
        # Test session isolation
        with self.as_user(self.api_users['member_full'].email):
            result1 = session_sensitive_operation()
            self.assertEqual(result1["session_user"], self.api_users['member_full'].email)
            self.assertEqual(result1["member_name"], self.api_members['member_full'].name)
        
        with self.as_user(self.api_users['member_basic'].email):
            result2 = session_sensitive_operation()
            self.assertEqual(result2["session_user"], self.api_users['member_basic'].email)
            self.assertEqual(result2["member_name"], self.api_members['member_basic'].name)
        
        # Verify sessions are properly isolated
        self.assertNotEqual(result1["session_user"], result2["session_user"])
        self.assertNotEqual(result1["member_name"], result2["member_name"])

    def test_api_parameter_injection_prevention(self):
        """Test API parameter injection and validation"""
        
        @high_security_api(operation_type=OperationType.MEMBER_DATA)
        def secure_member_lookup(member_id):
            # Security: validate member_id format and ownership
            if not member_id or not isinstance(member_id, str):
                frappe.throw("Invalid member ID format")
            
            validate_member_ownership(member_id)
            
            member = frappe.get_doc("Member", member_id)
            return {
                "member": member.name,
                "validated": True
            }
        
        member_full = self.api_members['member_full']
        
        # Test valid parameter
        with self.as_user(self.api_users['member_full'].email):
            result = secure_member_lookup(member_full.name)
            self.assertTrue(result["validated"])
        
        # Test invalid parameter injection attempts
        with self.as_user(self.api_users['member_full'].email):
            with self.assertRaises(frappe.ValidationError):
                secure_member_lookup("")  # Empty string
            
            with self.assertRaises(frappe.ValidationError):
                secure_member_lookup(None)  # None value

    def test_api_concurrent_access_safety(self):
        """Test API concurrent access safety with decorators"""
        import threading
        
        @standard_api(operation_type=OperationType.REPORTING)
        def concurrent_safe_operation():
            member_doc = get_current_user_member_doc()
            return {
                "user": frappe.session.user,
                "member": member_doc.name,
                "timestamp": now_datetime()
            }
        
        results = []
        errors = []
        
        def concurrent_api_call():
            try:
                with self.as_user(self.api_users['member_full'].email):
                    result = concurrent_safe_operation()
                    if result["user"] == self.api_users['member_full'].email:
                        results.append("success")
                    else:
                        results.append("session_mismatch")
            except Exception as e:
                errors.append(str(e))
        
        # Run concurrent API calls
        threads = []
        for _ in range(3):
            t = threading.Thread(target=concurrent_api_call)
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join(timeout=10)
        
        self.assertEqual(len(errors), 0, f"No errors should occur: {errors}")
        self.assertEqual(results.count("success"), 3, "All concurrent calls should succeed")

    # ===== PERFORMANCE AND MONITORING TESTS =====

    def test_security_decorator_performance_impact(self):
        """Test performance impact of security decorators"""
        
        # Baseline function without decorator
        def baseline_function():
            return {"baseline": "response"}
        
        # Function with security decorator
        @standard_api(operation_type=OperationType.REPORTING)
        def secured_function():
            return {"secured": "response"}
        
        # Measure performance with authenticated user
        with self.as_user(self.api_users['staff'].email):
            # Warm up
            baseline_function()
            secured_function()
            
            # Time baseline
            start_time = time.time()
            for _ in range(10):
                baseline_function()
            baseline_time = time.time() - start_time
            
            # Time secured function
            start_time = time.time()
            for _ in range(10):
                secured_function()
            secured_time = time.time() - start_time
            
            # Security overhead should be reasonable
            if baseline_time > 0:
                overhead_ratio = secured_time / baseline_time
                self.assertLess(overhead_ratio, 5.0, "Security overhead should be reasonable")

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
        """Clean up API test data"""
        frappe.set_user(self.original_user)
        super().tearDown()


# ===== TEST EXECUTION FUNCTIONS =====

def run_api_authentication_decorator_tests():
    """Run API authentication decorator integration tests"""
    import unittest
    
    print("🔒 Running API Authentication Decorator Integration Tests...")
    
    suite = unittest.TestLoader().loadTestsFromTestCase(TestAPIAuthenticationDecoratorsIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    if result.wasSuccessful():
        print("✅ All API authentication decorator tests passed!")
        return True
    else:
        print(f"❌ {len(result.failures)} test(s) failed, {len(result.errors)} error(s)")
        for test, traceback in result.failures + result.errors:
            print(f"\nFAILED: {test}")
            print(traceback)
        return False


if __name__ == "__main__":
    run_api_authentication_decorator_tests()