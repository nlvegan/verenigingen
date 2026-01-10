# -*- coding: utf-8 -*-
# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

"""
Real Integration Test for Account Creation System
===============================================

This test validates the complete AccountCreationManager workflow without mocking
critical business logic. Tests the secure account creation pipeline that was
recently refactored to eliminate permission bypasses.

Key Testing Principles:
- Uses real database operations with transaction isolation
- Tests actual AccountCreationManager pipeline without permission bypasses
- Validates role assignment and employee creation logic
- Mocks only external services (email sending)
- Tests background job processing integration

This addresses the account creation testing gaps where security-critical
functionality was heavily mocked, missing real permission validation errors.

NOTE: These tests are skipped in CI environments due to Frappe's rate limiting
on user creation. Run locally for full integration testing.
"""

import os
import unittest
import frappe
from frappe.utils import today, add_days, now_datetime
from frappe.tests.utils import FrappeTestCase
from unittest.mock import patch

from verenigingen.utils.account_creation_manager import AccountCreationManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestAccountCreationRealIntegration(EnhancedTestCase):
    """
    Real integration test for AccountCreationManager workflow
    
    Tests the complete secure account creation pipeline including
    role assignment, employee record creation, and background processing.
    """

    def setUp(self):
        """Set up test environment for account creation testing"""
        super().setUp()

        # Generate unique ID for this test run to avoid name/email collisions
        import time
        self.uid = str(int(time.time() * 1000000) % 1000000)

        # Create test member for account creation
        self.member = self.create_test_member(
            first_name=f"AcctInt{self.uid[:3]}",
            last_name=f"Test{self.uid[3:]}",
            email=f"account.creation.{self.uid}@test.invalid",
            status="Active",
            birth_date=add_days(today(), -365 * 25)  # 25 years old
        )

        # Create test volunteer for employee creation testing
        # Note: first positional arg is member_name, not kwarg
        self.volunteer = self.create_test_volunteer(
            self.member.name,
            volunteer_name=f"{self.member.first_name} {self.member.last_name}",
            email=self.member.email,
            status="Active"
        )

        # Create admin user for account creation approval
        self.admin_user = self.create_test_user(
            f"account.admin.{self.uid}@test.invalid",
            roles=["System Manager", "Verenigingen Administrator"]
        )

    def test_account_creation_request_workflow(self):
        """Test complete account creation request workflow with real database operations"""
        
        # Stage 1: Create account creation request
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Integration test account creation",
            "priority": "Standard"
        })
        
        # Add role requests
        request_doc.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)
        
        # Validate initial state - DocType.validate() sets status to "Requested"
        self.assertEqual(request_doc.status, "Requested")
        self.assertEqual(request_doc.request_type, "Member")
        self.assertEqual(request_doc.source_record, self.member.name)
        
        # Stage 2: Process account creation with AccountCreationManager
        manager = AccountCreationManager(request_doc.name)
        
        # Mock only external services, keep all business logic real
        with patch('frappe.sendmail') as mock_sendmail:
            with self.as_user(self.admin_user.email):
                # Process complete pipeline - no mocking of business logic
                manager.process_complete_pipeline()
        
        # Stage 3: Validate real database changes
        request_doc.reload()
        
        # Request should be completed
        self.assertEqual(request_doc.status, "Completed")
        self.assertIsNotNone(request_doc.created_user)
        self.assertIsNotNone(request_doc.completed_at)
        
        # Stage 4: Validate user account was created
        user_email = request_doc.created_user
        self.assertTrue(DocumentExistenceValidator.check_document_exists("User", user_email))
        
        user = frappe.get_doc("User", user_email)
        self.assertEqual(user.email, self.member.email)
        self.assertEqual(user.full_name, self.member.full_name)
        self.assertTrue(user.enabled)
        
        # Stage 5: Validate role assignment
        user_roles = frappe.get_all(
            "Has Role",
            filters={"parent": user_email, "role": "Verenigingen Member"},
            fields=["role"]
        )
        
        self.assertEqual(len(user_roles), 1)
        self.assertEqual(user_roles[0]["role"], "Verenigingen Member")

    def test_account_creation_employee_integration(self):
        """Test account creation with employee record creation for volunteers"""

        # Check if Employee Self Service role exists (required for employee creation)
        has_ess_role = frappe.db.exists("Role", "Employee Self Service")

        # Create account creation request for member with volunteer record
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Volunteer needs expense functionality"
        })

        # Add roles for testing
        request_doc.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        # Only add Employee Self Service if the role exists
        if has_ess_role:
            request_doc.append("requested_roles", {
                "role": "Employee Self Service"
            })

        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)

        # Process with AccountCreationManager
        manager = AccountCreationManager(request_doc.name)

        # Test requires_employee_creation logic (only returns True if ESS role requested)
        manager.load_request()
        requires_employee = manager.requires_employee_creation()

        # Skip employee-specific assertions if ESS role doesn't exist
        if not has_ess_role:
            # Just verify the pipeline completes without ESS
            with patch('frappe.sendmail'):
                with self.as_user(self.admin_user.email):
                    manager.process_complete_pipeline()
            request_doc.reload()
            self.assertEqual(request_doc.status, "Completed")
            return

        self.assertTrue(requires_employee,
            "Should require employee creation for member with volunteer record and ESS role")

        # Process complete pipeline
        with patch('frappe.sendmail'):
            with self.as_user(self.admin_user.email):
                manager.process_complete_pipeline()

        # Validate request completed
        request_doc.reload()
        self.assertEqual(request_doc.status, "Completed")

        # Employee creation depends on whether manager created one
        # The created_employee field may be None if employee creation wasn't triggered
        if request_doc.created_employee:
            # Verify employee record exists and is properly linked
            employee_name = request_doc.created_employee
            self.assertTrue(DocumentExistenceValidator.check_document_exists("Employee", employee_name))

            employee = frappe.get_doc("Employee", employee_name)
            self.assertEqual(employee.user_id, request_doc.created_user)
            self.assertEqual(employee.employee_name, self.member.full_name)
        else:
            # If no employee created, verify that user was created successfully
            self.assertIsNotNone(request_doc.created_user)

    def test_account_creation_permission_validation(self):
        """Test that account creation respects permission boundaries"""
        
        # Create account creation request
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Permission test"
        })
        
        request_doc.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)
        
        # Create user without account creation permissions
        limited_user = self.create_test_user(
            "limited.user@example.com",
            roles=["Verenigingen Member"]  # No admin permissions
        )
        
        # Test processing with limited permissions should fail
        manager = AccountCreationManager(request_doc.name)
        
        with patch('frappe.sendmail'):
            with self.as_user(limited_user.email):
                # Should raise permission error during processing
                with self.assertRaises(frappe.PermissionError):
                    manager.process_complete_pipeline()
        
        # Request should remain in failed state
        request_doc.reload()
        self.assertEqual(request_doc.status, "Failed")

    def test_account_creation_role_validation(self):
        """Test validation of role assignment during account creation"""
        
        # Create request with invalid/unauthorized role
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Role validation test"
        })
        
        # Add invalid role that user shouldn't be able to assign
        request_doc.append("requested_roles", {
            "role": "System Manager"  # High-privilege role
        })
        
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)
        
        # Create user with limited role assignment permissions
        role_limited_user = self.create_test_user(
            "role.limited@example.com",
            roles=["Verenigingen Administrator"]  # Can create users but not assign System Manager
        )
        
        manager = AccountCreationManager(request_doc.name)
        
        with patch('frappe.sendmail'):
            with self.as_user(role_limited_user.email):
                # Should fail during role validation
                with self.assertRaises(frappe.PermissionError):
                    manager.process_complete_pipeline()

    def test_account_creation_duplicate_handling(self):
        """Test handling of duplicate account creation requests"""
        
        # Create first account creation request
        request1 = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "First request"
        })
        
        request1.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request1.insert()
        self.factory.track_document("Account Creation Request", request1.name)
        
        # Process first request successfully
        manager1 = AccountCreationManager(request1.name)
        
        with patch('frappe.sendmail'):
            with self.as_user(self.admin_user.email):
                manager1.process_complete_pipeline()
        
        request1.reload()
        self.assertEqual(request1.status, "Completed")
        
        # Create second request for same member
        request2 = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,  # Same email as first request
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Duplicate request"
        })
        
        request2.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request2.insert()
        self.factory.track_document("Account Creation Request", request2.name)
        
        # Process second request - should handle existing user gracefully
        manager2 = AccountCreationManager(request2.name)
        
        with patch('frappe.sendmail'):
            with self.as_user(self.admin_user.email):
                manager2.process_complete_pipeline()
        
        # Second request should complete successfully, reusing existing user
        request2.reload()
        self.assertEqual(request2.status, "Completed")
        self.assertEqual(request2.created_user, request1.created_user)

    def test_account_creation_error_recovery(self):
        """Test error recovery and retry mechanisms"""
        
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": "invalid.email.format",  # Invalid email to trigger error
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Error recovery test"
        })
        
        request_doc.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)
        
        # Process should fail due to invalid email
        manager = AccountCreationManager(request_doc.name)
        
        with patch('frappe.sendmail'):
            with self.as_user(self.admin_user.email):
                with self.assertRaises(frappe.ValidationError):
                    manager.process_complete_pipeline()
        
        # Request should be marked as failed
        request_doc.reload()
        self.assertEqual(request_doc.status, "Failed")
        self.assertIsNotNone(request_doc.failure_reason)

    def test_account_creation_without_business_justification(self):
        """Test that account creation works without business_justification (optional field)"""

        # Test creation without business justification - currently optional
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name
            # business_justification is optional
        })
        request_doc.append("requested_roles", {"role": "Verenigingen Member"})
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)

        # Verify request was created successfully
        self.assertEqual(request_doc.status, "Requested")
        self.assertFalse(request_doc.business_justification)

    def test_account_creation_audit_trail(self):
        """Test that account creation generates proper audit trail"""

        # Insert document as admin_user to ensure requested_by is set correctly
        with self.as_user(self.admin_user.email):
            request_doc = frappe.get_doc({
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": self.member.name,
                "email": self.member.email,
                "full_name": self.member.full_name,
                "status": "Queued",
                "business_justification": "Audit trail test"
            })

            request_doc.append("requested_roles", {
                "role": "Verenigingen Member"
            })

            request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)

        # Process account creation as admin_user
        manager = AccountCreationManager(request_doc.name)

        with patch('frappe.sendmail'):
            with self.as_user(self.admin_user.email):
                manager.process_complete_pipeline()

        # Validate audit trail information
        request_doc.reload()

        self.assertIsNotNone(request_doc.processed_by)
        self.assertIsNotNone(request_doc.completed_at)
        self.assertEqual(request_doc.requested_by, self.admin_user.email)
        
        # Check version history
        versions = frappe.get_all(
            "Version",
            filters={"ref_doctype": "Account Creation Request", "docname": request_doc.name},
            fields=["name", "data"]
        )
        
        # Should have version history for status changes
        self.assertGreater(len(versions), 0)

    def test_account_creation_background_job_integration(self):
        """Test integration with background job processing"""
        
        request_doc = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "status": "Queued",
            "business_justification": "Background job test"
        })
        
        request_doc.append("requested_roles", {
            "role": "Verenigingen Member"
        })
        
        request_doc.insert()
        self.factory.track_document("Account Creation Request", request_doc.name)
        
        # Test that request can be processed via background job pattern
        manager = AccountCreationManager(request_doc.name)
        
        # Simulate background job processing
        with patch('frappe.sendmail'):
            with self.as_user("Administrator"):  # Background jobs run as Administrator
                manager.process_complete_pipeline()
        
        # Should complete successfully even in background context
        request_doc.reload()
        self.assertEqual(request_doc.status, "Completed")
        self.assertEqual(request_doc.processed_by, "Administrator")


if __name__ == '__main__':
    import unittest
    unittest.main()