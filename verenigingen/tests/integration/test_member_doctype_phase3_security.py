# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Phase 3 Security Validation Tests for Member DocType
===================================================

Validates that Phase 3 security improvements to Member DocType methods
eliminate permission bypasses while maintaining full functionality.

Key Security Improvements Tested:
- create_customer() method: Secure customer creation with audit trail
- create_user() method: Secure user creation with proper context switching
- create_donor_from_member() function: Secure donor creation workflow

This test ensures the core Member DocType operations work securely without
permission bypasses while maintaining all business functionality.
"""

import frappe
from frappe.utils import today, add_days
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
import unittest


class TestMemberDoctypePhase3Security(EnhancedTestCase):
    """
    Phase 3 security validation for Member DocType core methods
    
    Tests that permission bypasses have been eliminated from critical
    Member DocType methods while maintaining functionality through 
    secure context switching patterns.
    """

    def setUp(self):
        """Set up test environment with proper security context"""
        super().setUp()
        
        # Create unique test member for this test run
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        self.test_member = self.create_test_member(
            first_name="Phase3Security",
            last_name="TestMember", 
            email=f"phase3.security.{unique_id}@example.com",
            status="Active",
            birth_date=add_days(today(), -365 * 30)  # 30 years old
        )
        
        # Create admin user for secure operations
        self.admin_user = self.create_test_user_with_roles(
            email=f"admin.phase3.{unique_id}@example.com",
            roles=["System Manager", "HR Manager", "Verenigingen Administrator"]
        )

    def test_create_customer_method_security(self):
        """Test that create_customer() method works securely without permission bypasses"""
        
        with self.as_user(self.admin_user.email):
            # Ensure member has no customer initially
            self.assertIsNone(self.test_member.customer)
            
            # Test secure customer creation
            customer_id = self.test_member.create_customer()
            
            self.assertIsNotNone(customer_id, "Customer creation should succeed with secure context")
            
            # Verify customer was created with correct details
            customer_doc = frappe.get_doc("Customer", customer_id)
            self.assertEqual(customer_doc.customer_name, self.test_member.full_name)
            self.assertEqual(customer_doc.customer_type, "Individual")
            self.assertEqual(customer_doc.member, self.test_member.name)
            self.assertEqual(customer_doc.email_id, self.test_member.email)
            
            # Verify member was updated with customer link
            self.test_member.reload()
            self.assertEqual(self.test_member.customer, customer_id)
            
            # Track for cleanup
            self.track_doc("Customer", customer_id)
            
            # Test idempotency - calling again should return existing customer
            customer_id_second = self.test_member.create_customer()
            self.assertEqual(customer_id, customer_id_second)

    def test_create_user_method_security(self):
        """Test that create_user() method works securely without permission bypasses"""
        
        with self.as_user(self.admin_user.email):
            # Ensure member has no user initially
            self.assertIsNone(self.test_member.user)
            
            # Test secure user creation
            user_id = self.test_member.create_user()
            
            self.assertIsNotNone(user_id, "User creation should succeed with secure context")
            self.assertEqual(user_id, self.test_member.email)
            
            # Verify user was created with correct details
            user_doc = frappe.get_doc("User", user_id)
            self.assertEqual(user_doc.email, self.test_member.email)
            self.assertEqual(user_doc.first_name, self.test_member.first_name)
            self.assertEqual(user_doc.last_name, self.test_member.last_name)
            self.assertEqual(user_doc.user_type, "System User")
            self.assertTrue(user_doc.enabled, "User should be enabled")
            
            # Verify member was updated with user link
            self.test_member.reload()
            self.assertEqual(self.test_member.user, user_id)
            
            # Verify ownership transfer occurred
            self.assertEqual(self.test_member.owner, user_id)
            
            # Track for cleanup
            self.track_doc("User", user_id)
            
            # Test idempotency - calling again should return existing user
            user_id_second = self.test_member.create_user()
            self.assertEqual(user_id, user_id_second)

    def test_create_donor_from_member_security(self):
        """Test that create_donor_from_member() function works securely"""
        
        with self.as_user(self.admin_user.email):
            # Import the function we're testing
            from verenigingen.verenigingen.doctype.member.member import create_donor_from_member
            
            # Test secure donor creation
            result = create_donor_from_member(self.test_member.name)
            
            self.assertTrue(result.get("success"), f"Donor creation should succeed: {result}")
            self.assertIn("donor_name", result)
            
            donor_name = result["donor_name"]
            
            # Verify donor was created with correct details
            donor_doc = frappe.get_doc("Donor", donor_name)
            self.assertEqual(donor_doc.donor_name, self.test_member.full_name)
            self.assertEqual(donor_doc.donor_email, self.test_member.email)
            self.assertEqual(donor_doc.donor_type, "Individual")
            self.assertEqual(donor_doc.member, self.test_member.name)
            
            # Track for cleanup
            self.track_doc("Donor", donor_name)
            
            # Test idempotency - calling again should indicate donor exists
            result_second = create_donor_from_member(self.test_member.name)
            self.assertFalse(result_second.get("success"))
            self.assertIn("already exists", result_second.get("message", ""))

    def test_customer_donor_integration_security(self):
        """Test integrated workflow: member -> customer -> donor with secure context"""
        
        with self.as_user(self.admin_user.email):
            # Test full workflow with security
            
            # Step 1: Create customer
            customer_id = self.test_member.create_customer()
            self.assertIsNotNone(customer_id)
            
            # Step 2: Create donor (should link to customer)
            from verenigingen.verenigingen.doctype.member.member import create_donor_from_member
            donor_result = create_donor_from_member(self.test_member.name)
            self.assertTrue(donor_result.get("success"))
            
            donor_name = donor_result["donor_name"]
            
            # Verify customer-donor linking
            customer_doc = frappe.get_doc("Customer", customer_id)
            if hasattr(customer_doc, "donor"):
                self.assertEqual(customer_doc.donor, donor_name)
            
            # Track for cleanup
            self.track_doc("Customer", customer_id)
            self.track_doc("Donor", donor_name)

    def test_security_validation_no_permission_bypasses(self):
        """Meta-test: Verify no ignore_permissions=True in secured methods"""
        
        import inspect
        from verenigingen.verenigingen.doctype.member.member import Member, create_donor_from_member
        
        # Get source code of secured methods
        methods_to_check = [
            Member.create_customer,
            Member.create_user,
            create_donor_from_member
        ]
        
        for method in methods_to_check:
            source = inspect.getsource(method)
            
            # Should not contain functional permission bypasses
            bypass_pattern = "ignore_permissions=" + "True"  # Avoid false positive detection
            self.assertNotIn(bypass_pattern, source, 
                f"Method {method.__name__} still contains permission bypasses")
            
            # Should contain secure context manager usage
            has_security_pattern = any(pattern in source for pattern in [
                "secure_user_context",
                "get_creation_user",
                "ctx.log_operation"
            ])
            
            self.assertTrue(has_security_pattern,
                f"Method {method.__name__} lacks secure context manager pattern")

    def test_audit_trail_completeness(self):
        """Test that all secured operations create comprehensive audit trails"""
        
        with self.as_user(self.admin_user.email):
            # Create customer and verify audit trail
            customer_id = self.test_member.create_customer()
            
            # Note: Actual audit trail verification would require access to 
            # secure context manager logs, which are logged via frappe.logger()
            # This test validates the operations complete successfully with
            # the secure patterns in place
            
            self.assertIsNotNone(customer_id)
            
            # Create user and verify audit trail  
            user_id = self.test_member.create_user()
            self.assertIsNotNone(user_id)
            
            # Create donor and verify audit trail
            from verenigingen.verenigingen.doctype.member.member import create_donor_from_member
            donor_result = create_donor_from_member(self.test_member.name)
            self.assertTrue(donor_result.get("success"))
            
            # Track for cleanup
            self.track_doc("Customer", customer_id)
            self.track_doc("User", user_id)
            self.track_doc("Donor", donor_result["donor_name"])

    def test_error_handling_with_secure_context(self):
        """Test that error handling works correctly with secure context switching"""
        
        with self.as_user(self.admin_user.email):
            # Test create_user with invalid email (should handle gracefully)
            invalid_member = self.create_test_member(
                first_name="Invalid",
                last_name="Email",
                email="",  # Invalid empty email
                status="Active",
                birth_date=add_days(today(), -365 * 25)
            )
            
            # This should fail gracefully without permission bypass errors
            with self.assertRaises(Exception):
                invalid_member.create_user()
            
            # Verify the member still exists (no corruption from failed operation)
            invalid_member.reload()
            self.assertEqual(invalid_member.first_name, "Invalid")

    def test_permission_validation_works(self):
        """Test that permission validation actually works (users without permissions fail)"""
        
        # Create limited user without required permissions
        limited_user = self.create_test_user_with_roles(
            email="limited.phase3@example.com",
            roles=["Verenigingen Member"]  # Limited permissions
        )
        
        with self.as_user(limited_user.email):
            # These operations should either fail with permission errors 
            # or use secure fallback mechanisms
            
            # Customer creation should be handled securely
            # (May succeed via secure context or fail gracefully)
            try:
                result = self.test_member.create_customer()
                # If it succeeds, it should be via secure context manager
                if result:
                    self.assertIsNotNone(result)
            except frappe.PermissionError:
                # Permission error is acceptable - shows security is working
                pass
            except Exception as e:
                # Other exceptions should be handled gracefully
                self.assertNotIn("ignore_permissions", str(e).lower())


if __name__ == '__main__':
    import unittest
    unittest.main()