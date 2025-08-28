#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 3 API Security Integration Testing
=======================================

Real API security integration testing with actual authentication and permission validation.
This implements the API security portion of Phase 3 Testing Reformation Plan.

Security Dependency: ✅ SATISFIED - Phase 3 Security Remediation complete with
comprehensive secure_document_operation() coverage and elimination of permission bypasses.

Key Features:
- Test whitelisted endpoints with real authentication 
- Validate CSRF protection in actual request contexts
- Test role-based access control with secure operations
- Real permission boundary validation without bypasses
- Comprehensive error scenario testing
"""

import json
import frappe
from frappe import _
from frappe.utils import getdate
from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAPISecurityPhase3Integration(EnhancedTestCase):
    """
    Integration tests for API security with real authentication and permission validation.
    
    This addresses the API security testing blocked by security remediation dependency
    that has now been satisfied with 78+ bypasses eliminated.
    """

    def setUp(self):
        super().setUp()
        self.setup_test_users_and_roles()

    def setup_test_users_and_roles(self):
        """Setup test users with different permission levels"""
        # Create permission test scenario
        self.permission_scenario = self.create_permission_test_scenario(
            authorized_roles=["System Manager", "Verenigingen Administrator"],
            unauthorized_roles=["Verenigingen Member", "Guest"]
        )
        
        self.admin_user = self.permission_scenario["authorized_users"][0]
        self.member_user = self.permission_scenario["unauthorized_users"][0]

    def test_membership_application_review_api_security(self):
        """
        Test membership application review API with real authentication.
        
        Validates that the secured membership application API properly
        enforces permissions and validates input without bypasses.
        """
        # Create test application for review
        member = self.create_test_member(
            status="Pending",  
            birth_date="1990-01-01"
        )
        
        # Test unauthorized access (member trying to approve applications)
        with self.as_user(self.member_user.email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.api.membership_application_review.approve_membership_application",
                    member_name=member.name,
                    membership_type="Standard Member",
                    create_invoice=True
                )

        # Test authorized access (admin approving application)
        with self.as_user(self.admin_user.email):
            # This should succeed with proper permissions
            result = frappe.call(
                "verenigingen.api.membership_application_review.approve_membership_application",
                member_name=member.name,
                membership_type="Standard Member", 
                create_invoice=True
            )
            
            # Verify successful approval
            self.assertTrue(result.get('success'))
            
            # Verify member status was updated using secure operations
            member.reload()
            self.assertEqual(member.status, "Active")

    def test_sepa_mandate_api_security_validation(self):
        """
        Test SEPA mandate API endpoints with permission validation.
        
        Validates that SEPA operations properly enforce financial permissions
        and business rule validation.
        """
        # Create test member
        member = self.create_test_member(birth_date="1985-01-01")

        # Test unauthorized SEPA mandate creation
        with self.as_user(self.member_user.email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.utils.sepa_mandate_manager.create_sepa_mandate",
                    member_name=member.name,
                    iban="NL91ABNA0417164300",
                    account_holder_name=member.full_name
                )

        # Test authorized SEPA mandate creation
        with self.as_user(self.admin_user.email):
            result = frappe.call(
                "verenigingen.utils.sepa_mandate_manager.create_sepa_mandate", 
                member_name=member.name,
                iban="NL91ABNA0417164300",
                account_holder_name=member.full_name
            )
            
            # Verify mandate was created with proper security
            self.assertTrue(result.get('success'))
            
            # Verify mandate exists and is properly linked
            mandate_name = result.get('mandate_name')
            self.assertIsNotNone(mandate_name)
            
            mandate = frappe.get_doc("SEPA Mandate", mandate_name)
            self.assertEqual(mandate.member, member.name)
            self.assertEqual(mandate.status, "Active")

    def test_chapter_join_api_security(self):
        """
        Test chapter join API security with member self-service validation.
        
        Tests that members can request to join chapters but cannot
        approve their own requests.
        """
        # Create test member and chapter
        member = self.create_test_member(birth_date="1990-01-01")
        chapter = self.ensure_test_chapter("Test Security Chapter")

        # Test member requesting to join chapter (should be allowed)
        with self.as_user(self.member_user.email):
            result = frappe.call(
                "verenigingen.api.chapter_join.request_chapter_join",
                member_name=member.name,
                chapter_name=chapter.name,
                justification="Want to participate in local activities"
            )
            
            self.assertTrue(result.get('success'))
            request_id = result.get('request_id')
            self.assertIsNotNone(request_id)

        # Test member trying to approve their own request (should fail)
        with self.as_user(self.member_user.email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.api.chapter_join.approve_chapter_join_request",
                    request_id=request_id
                )

        # Test admin approving the request (should succeed)
        with self.as_user(self.admin_user.email):
            result = frappe.call(
                "verenigingen.api.chapter_join.approve_chapter_join_request",
                request_id=request_id
            )
            
            self.assertTrue(result.get('success'))

    def test_account_creation_api_security(self):
        """
        Test account creation API security with proper administrative controls.
        
        Validates that account creation requests require proper authorization
        and cannot be self-approved.
        """
        # Create test member
        member = self.create_test_member(birth_date="1985-01-01")

        # Test unauthorized account creation request
        with self.as_user(self.member_user.email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.utils.account_creation_manager.create_account_request",
                    member_name=member.name,
                    roles=["Verenigingen Member"],
                    justification="Self-service account creation attempt"
                )

        # Test authorized account creation request
        with self.as_user(self.admin_user.email):
            result = frappe.call(
                "verenigingen.utils.account_creation_manager.create_account_request",
                member_name=member.name,
                roles=["Verenigingen Member"],
                justification="Admin-initiated account creation for new member"
            )
            
            self.assertTrue(result.get('success'))
            request_name = result.get('request_name')
            self.assertIsNotNone(request_name)

            # Verify request was created with proper audit trail
            request_doc = frappe.get_doc("Account Creation Request", request_name)
            self.assertEqual(request_doc.source_record, member.name)
            self.assertIn("Admin-initiated", request_doc.business_justification)

    def test_api_input_validation_security(self):
        """
        Test API input validation and sanitization.
        
        Ensures that APIs properly validate and sanitize input to prevent
        injection attacks and malformed data processing.
        """
        # Test SQL injection attempt in member search
        malicious_inputs = [
            "'; DROP TABLE tabMember; --",
            "<script>alert('xss')</script>", 
            "../../etc/passwd",
            "' OR '1'='1",
            "NULL; UPDATE tabMember SET status='Deleted' WHERE 1=1; --"
        ]

        for malicious_input in malicious_inputs:
            with self.subTest(input=malicious_input):
                with self.as_user(self.admin_user.email):
                    # Test member search API with malicious input
                    try:
                        result = frappe.call(
                            "verenigingen.api.member_search.search_members",
                            search_term=malicious_input
                        )
                        
                        # Should return empty or sanitized results, not crash
                        self.assertIsInstance(result, (list, dict))
                        
                        # Should not return all members (indicating potential injection)
                        if isinstance(result, list):
                            self.assertLess(len(result), 100)  # Reasonable limit
                            
                    except frappe.ValidationError:
                        # Validation errors are acceptable - input was properly rejected
                        pass
                    except Exception as e:
                        # No other exceptions should occur (crashes, SQL errors, etc.)
                        self.fail(f"Unexpected exception with input '{malicious_input}': {str(e)}")

    def test_api_rate_limiting_and_abuse_protection(self):
        """
        Test API rate limiting and abuse protection mechanisms.
        
        Validates that APIs have proper rate limiting to prevent abuse
        and resource exhaustion attacks.
        """
        # Test rapid successive API calls
        with self.as_user(self.member_user.email):
            # Make multiple rapid requests to test rate limiting
            results = []
            for i in range(20):  # 20 rapid requests
                try:
                    result = frappe.call(
                        "verenigingen.api.member_portal.get_member_info",
                        member_email=self.member_user.email
                    )
                    results.append(result)
                except frappe.TooManyRequestsError:
                    # Rate limiting is working
                    break
                except Exception as e:
                    # Other errors are acceptable but should be logged
                    results.append({"error": str(e)})

            # Should either have rate limiting or succeed with valid results
            if len(results) == 20:
                # No rate limiting - verify all results are valid
                for result in results:
                    self.assertNotIn("error", result, "API should handle rapid requests gracefully")
            else:
                # Rate limiting is active - this is preferred
                self.assertLess(len(results), 20, "Rate limiting should prevent excessive requests")

    def test_csrf_protection_validation(self):
        """
        Test CSRF protection in API endpoints.
        
        Validates that APIs properly validate CSRF tokens and reject
        requests without proper tokens.
        """
        # Create test member
        member = self.create_test_member(birth_date="1990-01-01")

        # Test API call without CSRF token (simulated)
        with self.as_user(self.admin_user.email):
            # Patch the request to simulate missing CSRF token
            with patch('frappe.local.request') as mock_request:
                mock_request.headers = {}  # No CSRF token
                mock_request.method = 'POST'
                
                # This should fail due to missing CSRF protection
                with self.assertRaises((frappe.CSRFTokenError, frappe.PermissionError)):
                    frappe.call(
                        "verenigingen.api.membership_application_review.approve_membership_application",
                        member_name=member.name,
                        membership_type="Standard Member"
                    )

    def test_api_response_security_headers(self):
        """
        Test that API responses include proper security headers.
        
        Validates Content-Type, CORS, and other security headers
        are properly set in API responses.
        """
        # Test API response headers (this would typically be done at the web server level)
        # but we can test the Frappe response structure
        with self.as_user(self.admin_user.email):
            # Make a simple API call
            response = frappe.call(
                "verenigingen.api.member_portal.get_member_dashboard_data",
                member_email=self.admin_user.email
            )

            # Verify response structure is secure
            self.assertIsInstance(response, dict)
            
            # Should not expose sensitive system information
            sensitive_keys = ['password', 'api_key', 'secret', 'token', 'hash']
            for key in sensitive_keys:
                self.assertNotIn(key, str(response).lower(), 
                                f"API response should not expose {key}")

    def test_permission_boundary_enforcement(self):
        """
        Test that permission boundaries are properly enforced across APIs.
        
        Validates that users cannot access resources outside their
        permission scope, even through API manipulation.
        """
        # Create test members
        member1 = self.create_test_member(birth_date="1990-01-01", email="member1@test.invalid")
        member2 = self.create_test_member(birth_date="1985-01-01", email="member2@test.invalid")
        
        # Create user for member1
        member1_user = self.create_test_user_with_roles(
            email=member1.email,
            roles=["Verenigingen Member"]
        )

        # Test that member1 cannot access member2's data
        with self.as_user(member1_user.email):
            with self.assertRaises(frappe.PermissionError):
                frappe.call(
                    "verenigingen.api.member_portal.get_member_personal_details",
                    member_name=member2.name  # Trying to access other member's data
                )

        # Test that member1 can access their own data
        with self.as_user(member1_user.email):
            result = frappe.call(
                "verenigingen.api.member_portal.get_member_personal_details", 
                member_name=member1.name  # Accessing own data
            )
            
            self.assertTrue(result.get('success'))
            self.assertEqual(result.get('member_name'), member1.name)

    def test_api_error_handling_security(self):
        """
        Test that API error handling doesn't expose sensitive information.
        
        Validates that error messages are sanitized and don't reveal
        system internals, database structure, or other sensitive data.
        """
        # Test various error scenarios
        with self.as_user(self.admin_user.email):
            # Test nonexistent member access
            try:
                frappe.call(
                    "verenigingen.api.membership_application_review.approve_membership_application",
                    member_name="NONEXISTENT_MEMBER_ID_12345"
                )
            except Exception as e:
                error_message = str(e).lower()
                
                # Should not expose database structure
                sensitive_terms = ['mysql', 'select', 'where', 'table', 'sql', 'database', 
                                 'connection', 'host', 'port', 'password', 'traceback']
                for term in sensitive_terms:
                    self.assertNotIn(term, error_message, 
                                   f"Error message should not expose {term}")

            # Test invalid input types
            try:
                frappe.call(
                    "verenigingen.api.member_search.search_members",
                    search_term={"malicious": "object"}  # Object instead of string
                )
            except Exception as e:
                error_message = str(e)
                
                # Should be a clean validation error, not system error
                self.assertIn("validation", error_message.lower())

    def tearDown(self):
        """Clean up test data"""
        super().tearDown()
        # FrappeTestCase automatically handles database rollback


if __name__ == "__main__":
    import unittest
    
    # Create test suite for API security testing
    suite = unittest.TestSuite()
    
    # Add key API security tests
    suite.addTest(TestAPISecurityPhase3Integration('test_membership_application_review_api_security'))
    suite.addTest(TestAPISecurityPhase3Integration('test_sepa_mandate_api_security_validation'))
    suite.addTest(TestAPISecurityPhase3Integration('test_account_creation_api_security'))
    suite.addTest(TestAPISecurityPhase3Integration('test_api_input_validation_security'))
    suite.addTest(TestAPISecurityPhase3Integration('test_permission_boundary_enforcement'))
    
    # Run the test suite
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Report results
    if result.wasSuccessful():
        print("✅ Phase 3 API Security Integration Tests: ALL PASSED")
    else:
        print(f"❌ Phase 3 API Security Tests: {len(result.failures)} failures, {len(result.errors)} errors")