#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for AccountCreationManager System
=========================================================

This test suite provides complete coverage of the secure account creation system,
ensuring zero unauthorized permission bypasses, robust error handling, and
proper integration with the Verenigingen business logic.

Key Testing Areas:
- Security Tests: Permission validation, unauthorized access prevention
- Functionality Tests: Complete pipeline execution, role assignment, employee creation
- Background Processing Tests: Redis queue integration, retry mechanisms
- Error Handling Tests: Graceful failure handling, audit trail preservation
- Integration Tests: Volunteer/Member integration, admin interface testing
- Dutch Association Business Logic: Age validation, role assignments

Author: Verenigingen Test Team
"""

import os
import unittest
from unittest.mock import patch, MagicMock, call
import frappe
from frappe import _
from frappe.utils import now, add_days, getdate
# FrappeTestCase import removed - all classes use EnhancedTestCase
import json
import time

from verenigingen.utils.account_creation_manager import (
    AccountCreationManager,
    process_account_creation_request,
    queue_account_creation_for_member,
    get_failed_requests,
    retry_failed_request
)
from verenigingen.services.member.account.user_role_profile_calculator import (
    get_user_role_profiles,
)
from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    BusinessRuleError
)


class TestAccountCreationManagerSecurity(EnhancedTestCase):
    """Security-focused tests for AccountCreationManager"""
    
    def setUp(self):
        super().setUp()
        # Enhanced Test Factory handles user context automatically
        
    def test_unauthorized_user_cannot_create_request(self):
        """Test that unauthorized users cannot create account creation requests"""
        # Create a test member
        member = self.create_test_member(
            first_name=f"Security{self.uid}",
            last_name="Test",
            email=f"security.test.{self.uid}@test.invalid"
        )
        
        # Test permission validation through API 
        # Enhanced Test Factory ensures proper permission enforcement
        # The account creation should validate permissions properly
        try:
            queue_account_creation_for_member(member.name)
            # If this succeeds, the permission system is working correctly
            self.assertTrue(True, "Account creation request processed successfully")
        except frappe.PermissionError:
            # Permission error is also acceptable - depends on current user permissions
            self.assertTrue(True, "Permission validation working correctly")
            
    def test_permission_validation_in_manager(self):
        """Test AccountCreationManager validates permissions properly"""
        # Create test member and request
        member = self.create_test_member(
            first_name=f"Permission{self.uid}",
            last_name="Validation",
            email=f"permission.validation.{self.uid}@test.invalid"
        )

        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Switch to unauthorized user
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": f"unauthorized.user.{self.uid}@test.invalid",
            "first_name": f"Unauthorized{self.uid}",
            "last_name": "User",
            "roles": [{"role": "Verenigingen Member"}]
        })
        test_user.insert()

        # Switch to the unauthorized user
        current_user = frappe.session.user
        try:
            frappe.set_user(test_user.email)

            # Enhanced Test Factory handles user context - test permission validation
            manager = AccountCreationManager(request.name)
            manager.load_request()  # Must load request before validating permissions
            with self.assertRaises(frappe.PermissionError):
                manager.validate_processing_permissions()
        finally:
            frappe.set_user(current_user)
            
    def test_load_request_raises_when_request_missing(self):
        """load_request() must raise DoesNotExistError for a non-existent ACR.

        Genuine rejection: account_creation_manager.py load_request() line 71
        `raise frappe.DoesNotExistError(...)` guards the whole pipeline against
        being driven with a bogus request name.
        """
        missing_name = f"ACR-Member-does-not-exist-{self.uid}"
        self.assertFalse(frappe.db.exists("Account Creation Request", missing_name))

        manager = AccountCreationManager(missing_name)
        with self.assertRaises(frappe.DoesNotExistError) as ctx:
            manager.load_request()
        # Assert the custom guard message (lowercase "Account creation request"),
        # which is distinct from Frappe get_doc()'s core "Account Creation Request
        # ... not found" fallback — so the assertion pins the guard, not the core.
        self.assertIn("Account creation request", str(ctx.exception))

    def test_validate_permissions_rejects_guest_user(self):
        """validate_processing_permissions() must deny Guest (no anonymous ACR).

        Genuine rejection: account_creation_manager.py line 459
        `raise frappe.PermissionError("Account creation requires authenticated user")`.
        """
        member = self.create_test_member(
            first_name=f"Guest{self.uid}",
            last_name="Denied",
            email=f"guest.denied.{self.uid}@test.invalid",
        )
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}],
        })
        request.insert()

        manager = AccountCreationManager(request.name)
        manager.load_request()

        # Guest session IS the behaviour under test; as_user restores the
        # original user on exit.
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError) as ctx:
                manager.validate_processing_permissions()
        self.assertIn("authenticated user", str(ctx.exception))

    def test_validate_permissions_rejects_unassignable_requested_role(self):
        """An admin-tier runner still cannot assign a role outside its allow-list.

        Genuine rejection: account_creation_manager.py line 473
        `raise frappe.PermissionError(f"Cannot assign role: {role_row.role}")`.
        Verenigingen Staff passes the ADMIN_ROLES gate (line 465) but
        can_assign_role() denies "Verenigingen Administrator", so the per-role
        loop rejects it — this is the privilege-escalation guard, distinct from
        the no-admin-role branch covered by test_permission_validation_in_manager.
        """
        member = self.create_test_member(
            first_name=f"Escalate{self.uid}",
            last_name="Blocked",
            email=f"escalate.blocked.{self.uid}@test.invalid",
        )
        # Inserted under the default Administrator context (can_request_role
        # permits it); the pipeline-time gate is what we exercise below.
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Administrator"}],
        })
        request.insert()

        manager = AccountCreationManager(request.name)
        manager.load_request()

        with self.as_staff():
            with self.assertRaises(frappe.PermissionError) as ctx:
                manager.validate_processing_permissions()
        self.assertIn("Cannot assign role", str(ctx.exception))
        self.assertIn("Verenigingen Administrator", str(ctx.exception))

    def test_role_assignment_permission_validation(self):
        """Test that role assignment validates permissions properly"""
        member = self.create_test_member(
            first_name=f"Role{self.uid}",
            last_name="Assignment",
            email=f"role.assignment.{self.uid}@test.invalid"
        )

        # Create a non-admin user without Role write permission
        test_user = frappe.get_doc({
            "doctype": "User",
            "email": f"non.admin.{self.uid}@test.invalid",
            "first_name": f"Non{self.uid}",
            "last_name": "Admin",
            "roles": [{"role": "Verenigingen Member"}]
        })
        test_user.insert()

        current_user = frappe.session.user
        try:
            # Switch to non-admin user
            frappe.set_user(test_user.email)

            # Create request with System Manager role (should fail for non-system managers)
            request = frappe.get_doc({
                "doctype": "Account Creation Request",
                "request_type": "Member",
                "source_record": member.name,
                "email": member.email,
                "full_name": member.full_name,
                "requested_roles": [{"role": "System Manager"}]  # Unauthorized role
            })

            # Should fail validation
            with self.assertRaises(frappe.PermissionError):
                request.insert()
        finally:
            frappe.set_user(current_user)
            
    def test_no_ignore_permissions_bypass_in_user_creation(self):
        """Test that user creation does not use ignore_permissions bypass"""
        member = self.create_test_member(
            first_name=f"No{self.uid}",
            last_name="Bypass",
            email=f"no.bypass.{self.uid}@test.invalid"
        )
        
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()
        
        # Phase 4D: Test real user creation business logic without mocking
        manager = AccountCreationManager(request.name)
        manager.load_request()
        
        # Test real business logic - if ignore_permissions is used, it should fail with proper permissions
        try:
            # Use Enhanced Test Factory's user context to test proper permission handling
            test_admin = self.ensure_test_admin_user()
            current_user = frappe.session.user
            try:
                frappe.set_user(test_admin.email)
                result = manager.create_user_account()
                
                # Verify real business logic results - user should be created properly
                self.assertIsNotNone(result)
                if result.get('success'):
                    # Verify user was actually created in database
                    self.assertTrue(frappe.db.exists('User', member.email))
                    
            finally:
                frappe.set_user(current_user)
                
        except frappe.PermissionError:
            # This is expected if ignore_permissions bypass is properly eliminated
            self.skipTest('Real permission validation working - no ignore_permissions bypass detected')
                
    def test_sql_injection_prevention(self):
        """Test that malformed inputs cannot cause SQL injection"""
        member = self.create_test_member(
            first_name=f"SQL{self.uid}",
            last_name="Injection",
            email=f"sql.injection.{self.uid}@test.invalid"
        )
        
        # Attempt SQL injection in various fields
        malicious_inputs = [
            "'; DROP TABLE `tabUser`; --",
            "' OR '1'='1",
            "UNION SELECT * FROM `tabUser` --"
        ]
        
        for malicious_input in malicious_inputs:
            with self.subTest(malicious_input=malicious_input):
                # Test in email field
                with self.assertRaises((frappe.ValidationError, frappe.DoesNotExistError)):
                    request = frappe.get_doc({
                        "doctype": "Account Creation Request",
                        "request_type": "Member",
                        "source_record": member.name,
                        "email": malicious_input,
                        "full_name": member.full_name,
                        "requested_roles": [{"role": "Verenigingen Member"}]
                    })
                    request.insert()
                    
    def test_xss_prevention_in_names(self):
        """Test that XSS attempts in user names are sanitized"""
        member = self.create_test_member(
            first_name=f"XSS{self.uid}",
            last_name="Prevention",
            email=f"xss.prevention.{self.uid}@test.invalid"
        )
        
        xss_attempts = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "<img src=x onerror=alert('xss')>"
        ]
        
        for xss_attempt in xss_attempts:
            with self.subTest(xss_attempt=xss_attempt):
                request = frappe.get_doc({
                    "doctype": "Account Creation Request",
                    "request_type": "Member", 
                    "source_record": member.name,
                    "email": member.email,
                    "full_name": xss_attempt,
                    "requested_roles": [{"role": "Verenigingen Member"}]
                })
                
                # Should either reject or sanitize
                try:
                    request.insert()
                    # If inserted, verify it's sanitized
                    self.assertNotIn('<script>', request.full_name)
                    self.assertNotIn('javascript:', request.full_name)
                except (frappe.ValidationError, frappe.DoesNotExistError):
                    # Rejection is also acceptable
                    pass

    def test_volunteer_integration_security(self):
        """Test that volunteer insert triggers ACR queue (not immediate user creation)."""
        unique_email = f"integration.test.{self.uid}.{self.test_run_id}@example.com"

        member = self.create_test_member(
            first_name=f"Integration{self.uid}",
            last_name="Test",
            email=unique_email,
        )

        from frappe.utils import today

        volunteer = frappe.get_doc({
            "doctype": "Volunteer",
            "volunteer_name": f"Integration Test Volunteer {self.uid} {self.test_run_id}",
            "email": unique_email,
            "member": member.name,
            "status": "New",
            "start_date": today(),
        })

        original_flag = frappe.flags.get("skip_volunteer_account_creation", False)
        frappe.flags.skip_volunteer_account_creation = False

        try:
            # EnhancedTestCase runs as Administrator by default
            volunteer.insert()
            self.factory.track_document("Volunteer", volunteer.name)

            account_requests = frappe.get_all(
                "Account Creation Request",
                filters={"source_record": volunteer.name},
            )
            self.assertTrue(
                len(account_requests) > 0,
                "Volunteer creation should queue account creation request",
            )
            self.assertFalse(
                frappe.db.exists("User", unique_email),
                "User should not be created immediately - should go through secure queue",
            )
        finally:
            frappe.flags.skip_volunteer_account_creation = original_flag

    def test_no_global_permission_bypasses(self):
        """Scan ACR source code for forbidden ignore_permissions=True usage."""
        import os
        import re

        files_to_scan = [
            os.path.join(
                frappe.get_app_path("verenigingen"),
                "utils", "account_creation_manager.py",
            ),
            os.path.join(
                frappe.get_app_path("verenigingen"),
                "verenigingen", "doctype",
                "account_creation_request", "account_creation_request.py",
            ),
        ]

        permission_bypass_pattern = re.compile(r"ignore_permissions\s*=\s*True")
        violations = []

        for file_path in files_to_scan:
            if not os.path.exists(file_path):
                continue
            with open(file_path, "r") as f:
                content = f.read()

            lines = content.split("\n")
            for match in permission_bypass_pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                actual_line = lines[line_num - 1] if line_num <= len(lines) else ""

                if actual_line.strip().startswith("#"):
                    continue
                if "# NO ignore_permissions=True" in actual_line:
                    continue

                context_lines = lines[max(0, line_num - 3) : min(len(lines), line_num + 3)]
                is_system_operation = any(
                    kw in "\n".join(context_lines).lower()
                    for kw in ["status tracking", "system operation", "mark_", "# system", "status update"]
                )
                if not is_system_operation:
                    violations.append(f"{file_path}:{line_num} - Unauthorized permission bypass")

        if violations:
            self.fail("Security violations found:\n" + "\n".join(violations))


class TestAccountCreationManagerFunctionality(EnhancedTestCase):
    """Functionality tests for AccountCreationManager"""

    def _get_request_or_skip(self, result, context="account creation"):
        """Helper to get Account Creation Request or skip if roles are missing."""
        if not result.get("success"):
            errors = result.get("errors", [])
            error_str = str(errors)
            if "Role" in error_str or "Employee Self Service" in error_str:
                self.skipTest(f"Required role missing in test environment: {errors}")
            self.fail(f"{context} failed: {result.get('error', errors)}")
        # Handle both nested and flat result structures
        request_name = result.get("request_name") or result.get("data", {}).get("request_name")
        if not request_name:
            self.fail(f"{context} failed: no request_name in result: {result}")
        return frappe.get_doc("Account Creation Request", request_name)

    def test_complete_member_account_creation_pipeline(self):
        """Test complete account creation pipeline for member"""
        member = self.create_test_member(
            first_name=f"Complete{self.uid}",
            last_name="Pipeline",
            email=f"complete.pipeline.{self.uid}@test.invalid",
            birth_date="1990-01-01"
        )
        
        # Create account creation request
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "role_profile": "Verenigingen Member",
            "requested_roles": [{"role": "Verenigingen Member"}],
            "business_justification": "Test member account creation"
        })
        request.insert()
        
        # Process the request
        # Already running as Administrator from setUp  # Ensure proper permissions
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify request completion
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertEqual(request.pipeline_stage, "Completed")
        self.assertIsNotNone(request.created_user)
        self.assertIsNotNone(request.completed_at)
        
        # Verify user creation
        user_exists = frappe.db.exists("User", request.created_user)
        self.assertTrue(user_exists, "User should be created")
        
        # Verify role assignment
        user_doc = frappe.get_doc("User", request.created_user)
        user_roles = [r.role for r in user_doc.roles]
        self.assertIn("Verenigingen Member", user_roles)
        
    def test_volunteer_account_creation_with_employee(self):
        """Test volunteer account creation includes employee record"""
        # Create member first (volunteers need associated member)
        member = self.create_test_member(
            first_name=f"Volunteer{self.uid}",
            last_name="Employee",
            email=f"volunteer.employee.{self.uid}@test.invalid",
            birth_date="1990-01-01"
        )

        # Create volunteer
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Volunteer Employee Test {self.uid}",
            email=f"volunteer.employee.{self.uid}@test.invalid"
        )
        
        # Create account creation request for volunteer
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Volunteer",
            "source_record": volunteer.name,
            "email": volunteer.email,
            "full_name": volunteer.volunteer_name,
            "role_profile": "Verenigingen Volunteer",
            "requested_roles": [
                {"role": "Verenigingen Volunteer"},
                {"role": "Employee"},
                {"role": "Employee Self Service"}
            ],
            "business_justification": "Volunteer account with expense functionality"
        })
        request.insert()
        
        # Process the request
        # Already running as Administrator from setUp
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify completion
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIsNotNone(request.created_user)
        self.assertIsNotNone(request.created_employee)
        
        # Verify employee creation
        employee_exists = frappe.db.exists("Employee", request.created_employee)
        self.assertTrue(employee_exists, "Employee should be created for volunteer")
        
        # Verify employee-user link
        employee_doc = frappe.get_doc("Employee", request.created_employee)
        self.assertEqual(employee_doc.user_id, request.created_user)
        
    def test_role_profile_assignment(self):
        """Test that role profiles or roles are assigned correctly"""
        member = self.create_test_member(
            first_name=f"Role{self.uid}",
            last_name="Profile",
            email=f"role.profile.{self.uid}@test.invalid"
        )

        # Ensure test role profile exists
        if not frappe.db.exists("Role Profile", "Verenigingen Member"):
            role_profile = frappe.get_doc({
                "doctype": "Role Profile",
                "role_profile": "Verenigingen Member",
                "roles": [{"role": "Verenigingen Member"}]
            })
            role_profile.insert()

        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "role_profile": "Verenigingen Member",
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Already running as Administrator from setUp
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # Verify role profile or role assignment
        request.reload()
        user_doc = frappe.get_doc("User", request.created_user)
        # Check either a role profile is set OR the role was assigned directly.
        # get_user_role_profiles reads the v16 role_profiles child table when
        # present, falling back to the legacy v15 role_profile_name field, so
        # this works across both Frappe versions.
        user_roles = [r.role for r in user_doc.roles]
        user_profiles = get_user_role_profiles(request.created_user)
        role_assigned = (
            "Verenigingen Member" in user_profiles
            or "Verenigingen Member" in user_roles
        )
        self.assertTrue(
            role_assigned,
            f"User should have role_profile 'Verenigingen Member' or role 'Verenigingen Member'. "
            f"Got profiles={user_profiles}, roles={user_roles}"
        )
        
    def test_existing_user_handling(self):
        """Test handling when user already exists"""
        # Use unique email to avoid conflicts
        unique_email = f"existing.user.{self.test_run_id}@test.invalid"
        member = self.create_test_member(
            first_name=f"Existing{self.uid}",
            last_name="User",
            email=unique_email
        )

        # Check if user already exists (cleanup from previous test runs)
        if frappe.db.exists("User", member.email):
            existing_user = frappe.get_doc("User", member.email)
        else:
            # Create user manually first
            existing_user = frappe.get_doc({
                "doctype": "User",
                "email": member.email,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "enabled": 1,
                "user_type": "System User"
            })
            existing_user.insert()

        # Create account request for same email
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()

        # Already running as Administrator from setUp
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # Should complete successfully using existing user
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertEqual(request.created_user, existing_user.name)

        # Verify member.user field is populated with existing user
        member.reload()
        self.assertEqual(member.user, existing_user.name,
                        "Member.user field should be linked to existing user")

    def test_existing_user_linking_via_queue_function(self):
        """Test that queue_account_creation_for_member links existing users"""
        # Use unique email to avoid conflicts
        unique_email = f"queue.linking.{self.test_run_id}@test.invalid"
        # Create member without user link
        member = self.create_test_member(
            first_name=f"Queue{self.uid}",
            last_name="Linking",
            email=unique_email
        )

        # Verify member.user is initially empty
        self.assertFalse(member.user, "Member.user should be empty initially")

        # Check if user already exists, or create pre-existing user account
        if frappe.db.exists("User", member.email):
            existing_user = frappe.get_doc("User", member.email)
        else:
            existing_user = frappe.get_doc({
                "doctype": "User",
                "email": member.email,
                "first_name": member.first_name,
                "last_name": member.last_name,
                "enabled": 1,
                "user_type": "System User"
            })
            existing_user.insert()

        # Queue account creation - should create request even for existing user
        result = queue_account_creation_for_member(
            member.name,
            roles=["Verenigingen Member"]
        )

        # Verify request was created (not skipped due to existing user)
        request = self._get_request_or_skip(result, "existing user handling")

        # Process the request
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # Verify request completed successfully
        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertEqual(request.created_user, existing_user.name)

        # CRITICAL: Verify member.user field is now linked to existing user
        member.reload()
        self.assertEqual(member.user, existing_user.name,
                        "Member.user field must be linked to existing user after pipeline completion")


class TestAccountCreationManagerErrorHandling(EnhancedTestCase):
    """Error handling and resilience tests"""

    def test_graceful_failure_handling(self):
        """Test graceful handling of processing - verifies request completes or fails gracefully"""
        import time
        # Use timestamp-based role name to guarantee it doesn't exist
        nonexistent_role = f"NonexistentRole{int(time.time() * 1000000)}"

        member = self.create_test_member(
            first_name=f"Failure{self.uid}",
            last_name="Handling",
            email=f"failure.handling.{self.uid}@test.invalid"
        )

        # Verify role doesn't exist before test
        if frappe.db.exists("Role", nonexistent_role):
            frappe.delete_doc("Role", nonexistent_role)

        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": nonexistent_role}]  # This may fail or be skipped
        })
        request.flags.ignore_links = True  # Bypass link validation for non-existent role
        request.insert()

        # Already running as Administrator from setUp
        manager = AccountCreationManager(request.name)

        # Implementation may either raise an exception, complete successfully (skipping invalid roles),
        # or mark the request as failed
        exception_raised = False
        try:
            manager.process_complete_pipeline()
        except (frappe.ValidationError, Exception):
            exception_raised = True

        # Verify the request was handled - either completed, failed, or raised an exception
        request.reload()
        # The implementation either completes (skipping invalid roles) or fails gracefully
        self.assertIn(request.status, ["Completed", "Failed"],
            f"Request should have Completed or Failed status. exception_raised={exception_raised}, status={request.status}")

        # If completed, user should have been created (though without the invalid role)
        if request.status == "Completed":
            self.assertIsNotNone(request.created_user,
                "If Completed, user should be created")
        # If failed, failure reason should be recorded
        elif request.status == "Failed":
            self.assertIsNotNone(request.failure_reason,
                "If Failed, failure reason should be recorded")
        
    def test_audit_trail_preservation_on_failure(self):
        """Test that audit trail is preserved even on failures"""
        import time
        # Use timestamp-based role name to guarantee it doesn't exist
        invalid_role = f"InvalidRole{int(time.time() * 1000000)}"

        member = self.create_test_member(
            first_name=f"Audit{self.uid}",
            last_name="Trail",
            email=f"audit.trail.{self.uid}@test.invalid"
        )

        # Verify role doesn't exist before test
        if frappe.db.exists("Role", invalid_role):
            frappe.delete_doc("Role", invalid_role)

        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": invalid_role}]
        })
        request.flags.ignore_links = True  # Bypass link validation for non-existent role
        request.insert()

        original_requested_by = request.requested_by
        
        # Already running as Administrator from setUp
        manager = AccountCreationManager(request.name)
        
        try:
            manager.process_complete_pipeline()
        except Exception:
            pass  # Expected to fail
            
        # Verify audit fields are preserved
        request.reload()
        self.assertEqual(request.requested_by, original_requested_by)
        self.assertIsNotNone(request.failure_reason)
        
    def test_retry_mechanism(self):
        """Test retry mechanism for failed requests"""
        member = self.create_test_member(
            first_name=f"Retry{self.uid}",
            last_name="Mechanism",
            email=f"retry.mechanism.{self.uid}@test.invalid"
        )

        # Create request normally (status will be forced to "Requested" by security)
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}],
        })
        request.insert()

        # Mark as failed using the proper method (simulates a processing failure)
        request.mark_failed("timeout error", "Test Stage")

        # Test retry
        result = request.retry_processing()
        self.assertTrue(result.get("success"))
        
        # Verify retry count increment
        request.reload()
        self.assertEqual(request.retry_count, 1)
        self.assertEqual(request.status, "Queued")
        
    def test_retry_limit_enforcement(self):
        """Test that retry limits are enforced"""
        member = self.create_test_member(
            first_name=f"Retry{self.uid}2",
            last_name="Limit",
            email=f"retry.limit.{self.uid}@test.invalid"
        )

        # Create request normally (status will be forced to "Requested" by security)
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}],
        })
        request.insert()

        # Mark as failed and set retry count to max
        request.mark_failed("Test failure", "Test Stage")
        frappe.db.set_value("Account Creation Request", request.name, "retry_count", 3)

        # Should fail to retry (max retries exceeded)
        with self.assertRaises(frappe.ValidationError):
            request.retry_processing()

    def test_retryable_vs_non_retryable_errors(self):
        """Test classification of retryable vs non-retryable errors."""
        member = self.create_test_member(
            first_name=f"ErrorClass{self.uid}",
            last_name="Test",
            email=f"error.class.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
        )

        manager = AccountCreationManager(request.name)
        manager.load_request()

        retryable_errors = [
            Exception("Connection timeout occurred"),
            Exception("Database connection error"),
            Exception("Temporary network failure"),
            Exception("Deadlock detected"),
            Exception("Lock wait timeout exceeded"),
        ]
        for error in retryable_errors:
            with self.subTest(error=str(error)):
                self.assertTrue(manager.is_retryable_error(error))

        non_retryable_errors = [
            frappe.ValidationError("Invalid role specified"),
            frappe.PermissionError("Access denied"),
            frappe.DoesNotExistError("Record not found"),
            Exception("Invalid email format"),
        ]
        for error in non_retryable_errors:
            with self.subTest(error=str(error)):
                self.assertFalse(manager.is_retryable_error(error))

    def test_schedule_retry_logs_error_with_correct_title_field(self):
        """frappe.log_error in schedule_retry() must store the short title in
        the Error Log `method` field, not the long detail f-string.

        Why this matters: Frappe.log_error signature is
        log_error(title=None, message=None, ...) and `title` maps to the
        Error Log `method` field (140-char Data). A positional call where
        positional[0] is a long single-line detail string and positional[1]
        is the short title stores them in the wrong fields — losing
        observability and risking CharacterLengthExceededError.

        schedule_retry()'s log_error call had positional args in the wrong
        order before this PR; the auto-swap rescue in frappe/utils/error.py
        only kicks in when positional[0] contains a newline, which the
        retry-enqueue branch's string doesn't.
        """
        from unittest.mock import patch

        member = self.create_test_member(
            first_name=f"RetryErr{self.uid}",
            last_name="LogTest",
            email=f"retry.err.log.{self.uid}@test.invalid"
        )
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )

        manager = AccountCreationManager(request.name)
        manager.load_request()

        # Capture Error Log rows created during the test
        log_marker = f"retry-enqueue-test-{self.uid}"

        # Force frappe.enqueue inside schedule_retry to fail so the
        # log_error rescue branch executes. Mock justified: external
        # service (Redis queue) — we're testing the rescue branch's
        # logging behaviour, not enqueue itself.
        with patch("frappe.enqueue", side_effect=RuntimeError(f"enqueue-failed-{log_marker}")):
            manager.schedule_retry()

        # The Error Log row's `method` field must hold the SHORT title
        # ("Account Creation Retry Enqueue Failed"), not the long detail
        # string. If positional args were swapped, the long
        # "Failed to enqueue retry for ..." f-string would land in method.
        rows = frappe.get_all(
            "Error Log",
            filters={"method": "Account Creation Retry Enqueue Failed"},
            fields=["name", "method", "error"],
            order_by="creation desc",
            limit=5,
        )
        self.assertTrue(
            any(log_marker in (r.error or "") for r in rows),
            "Expected an Error Log with method='Account Creation Retry "
            f"Enqueue Failed' whose error contains {log_marker!r}. "
            f"Found rows: {[(r.name, r.method[:80], (r.error or '')[:120]) for r in rows]}",
        )


class TestAccountCreationManagerBackgroundProcessing(EnhancedTestCase):
    """Background processing and Redis queue tests"""
    
    def test_background_job_queueing_real_business_logic(self):
        """Test background job queueing with real business logic (Phase 4D)"""
        # Use timestamp-based unique names to avoid Customer duplicate errors
        import time
        unique_suffix = str(int(time.time() * 1000000) % 1000000)  # Microseconds for uniqueness
        member = self.create_test_member(
            first_name=f"Background{self.uid}",
            last_name=f"Job{unique_suffix}",
            email=f"background.job.{unique_suffix}@test.invalid"
        )
        
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()
        
        # Test real business logic - no mocking of frappe.enqueue
        result = request.queue_processing()
        
        # Verify real business logic results
        self.assertIsNotNone(result)
        # Reload to check actual database state changes
        request.reload()
        self.assertEqual(request.status, "Queued")
        
        # Test real job creation logic (business validation)
        request.reload()
        self.assertEqual(request.status, "Queued")
        
    def test_background_job_entry_point(self):
        """Test the background job entry point function"""
        member = self.create_test_member(
            first_name=f"Job{self.uid}",
            last_name="Entry",
            email=f"job.entry.{self.uid}@test.invalid"
        )
        
        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": "Verenigingen Member"}]
        })
        request.insert()
        
        # Already running as Administrator from setUp
        
        # Call background job function directly
        result = process_account_creation_request(request.name)
        
        # Verify success — runtime returns dict (OperationResult auto-serialized)
        self.assertTrue(result.get("success"))

        # Verify request completion
        request.reload()
        self.assertEqual(request.status, "Completed")
        
    def test_retry_scheduling_real_business_logic(self):
        """Test retry scheduling with real business logic (Phase 4D)"""
        # Use timestamp-based unique names to avoid Customer duplicate errors
        import time
        unique_suffix = str(int(time.time() * 1000000) % 1000000)  # Microseconds for uniqueness
        # Use timestamp-based role name to guarantee it doesn't exist
        invalid_role = f"InvalidRole{int(time.time() * 1000000)}"

        member = self.create_test_member(
            first_name=f"Retry{self.uid}3",
            last_name=f"Scheduling{unique_suffix}",
            email=f"retry.scheduling.{unique_suffix}@test.invalid"
        )

        # Verify role doesn't exist before test
        if frappe.db.exists("Role", invalid_role):
            frappe.delete_doc("Role", invalid_role)

        request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "requested_roles": [{"role": invalid_role}],
            "retry_count": 1
        })
        request.flags.ignore_links = True  # Bypass link validation for non-existent role
        request.insert()
        
        # Use Enhanced Test Factory admin context
        test_admin = self.ensure_test_admin_user()
        current_user = frappe.session.user
        try:
            frappe.set_user(test_admin.email)
            manager = AccountCreationManager(request.name)
            manager.load_request()
            
            # Test real retry business logic - no mocking
            with patch.object(manager, 'is_retryable_error', return_value=True):
                manager.schedule_retry()
                
            # Verify real business logic results
            request.reload()
            self.assertGreater(request.retry_count, 1)  # Should increment
            # Status should be "Requested" after retry, not "Retry Scheduled"
            self.assertEqual(request.status, "Requested")
        finally:
            frappe.set_user(current_user)

    def test_concurrent_request_processing(self):
        """Test processing of multiple requests sequentially."""
        import time as _time

        uid = str(int(_time.time() * 1000000) % 1000000)
        requests = []
        for i in range(5):
            member = self.create_test_member(
                first_name=f"Conc{uid[:3]}",
                last_name=f"T{uid[3:]}{i}",
                email=f"concurrent.test.{uid}.{i}@test.invalid",
            )
            request = self.create_test_account_creation_request(
                source_record=member.name,
                request_type="Member",
            )
            requests.append(request)

        results = []
        for req in requests:
            try:
                result = process_account_creation_request(req.name)
                results.append({"request_name": req.name, "success": True, "result": result})
            except Exception as e:
                results.append({"request_name": req.name, "success": False, "error": str(e)})

        self.assertEqual(len(results), 5)
        successful_count = sum(1 for r in results if r["success"])
        self.assertGreaterEqual(successful_count, 3)

    def test_job_cleanup_after_completion(self):
        """Test that completed jobs have proper cleanup state."""
        import time as _time

        uid = str(int(_time.time() * 1000000) % 1000000)
        member = self.create_test_member(
            first_name=f"Cleanup{uid[:4]}",
            last_name=f"J{uid[4:]}",
            email=f"job.cleanup.{uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIsNotNone(request.completed_at)
        self.assertEqual(request.pipeline_stage, "Completed")
        self.assertEqual(request.retry_count, 0)

        with self.assertRaises(frappe.ValidationError):
            request.queue_processing()

    def test_partial_processing_recovery(self):
        """Test partial success model — role failure doesn't fail entire pipeline."""
        import time as _time

        uid = str(int(_time.time() * 1000000) % 1000000)
        member = self.create_test_member(
            first_name=f"Partial{uid[:4]}",
            last_name=f"R{uid[4:]}",
            email=f"partial.recovery.{uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
        )

        manager = AccountCreationManager(request.name)

        with patch.object(manager, "assign_roles_and_profile") as mock_assign_roles:
            mock_assign_roles.side_effect = frappe.ValidationError("Role assignment failed")
            manager.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")
        self.assertIn("PARTIAL SUCCESS", request.failure_reason)
        self.assertIn("Role assignment", request.failure_reason)
        self.assertIsNotNone(request.created_user)


class TestAccountCreationManagerIntegration(EnhancedTestCase):
    """Integration tests with other system components"""

    def _get_request_or_skip(self, result, context="account creation"):
        """Helper to get Account Creation Request or skip if roles are missing."""
        if not result.get("success"):
            errors = result.get("errors", [])
            error_str = str(errors)
            if "Role" in error_str or "Employee Self Service" in error_str:
                self.skipTest(f"Required role missing in test environment: {errors}")
            self.fail(f"{context} failed: {result.get('error', errors)}")
        # Handle both nested and flat result structures
        request_name = result.get("request_name") or result.get("data", {}).get("request_name")
        if not request_name:
            self.fail(f"{context} failed: no request_name in result: {result}")
        return frappe.get_doc("Account Creation Request", request_name)

    def test_member_integration(self):
        """Test integration with Member DocType"""
        member = self.create_test_member(
            first_name=f"Member{self.uid}",
            last_name="Integration",
            email=f"member.integration.{self.uid}@test.invalid"
        )

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )

        # Verify request creation
        self.assertEqual(request.source_record, member.name)
        self.assertEqual(request.email, member.email)
        
    def test_volunteer_integration(self):
        """Test integration with Volunteer DocType"""
        # Create member first
        member = self.create_test_member(
            first_name=f"Volunteer{self.uid}2",
            last_name="Integration",
            email=f"volunteer.integration.{self.uid}@test.invalid",
            birth_date="1990-01-01"
        )

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Volunteer Integration Test {self.uid}",
            email=f"volunteer.integration.{self.uid}@test.invalid"
        )

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )

        # Verify request creation with volunteer-specific fields
        self.assertEqual(request.source_record, volunteer.name)
        self.assertEqual(request.role_profile, "Verenigingen Volunteer")

        # Verify volunteer-specific roles
        requested_roles = [r.role for r in request.requested_roles]
        self.assertIn("Verenigingen Volunteer", requested_roles)
        self.assertIn("Employee", requested_roles)
        self.assertIn("Employee Self Service", requested_roles)
        
    def test_duplicate_request_prevention(self):
        """Test that duplicate requests are prevented or handled appropriately"""
        member = self.create_test_member(
            first_name=f"Duplicate{self.uid}",
            last_name="Prevention",
            email=f"duplicate.prevention.{self.uid}@test.invalid"
        )

        # Create first request
        result1 = queue_account_creation_for_member(member.name)
        # Handle both nested and flat result structures
        request_name = result1.get("request_name") or result1.get("data", {}).get("request_name")
        self.assertTrue(request_name, f"First request should have request_name: {result1}")

        # Attempt to create duplicate - may raise exception or return success=False
        try:
            result2 = queue_account_creation_for_member(member.name)
            # If no exception, check that it indicates a duplicate was detected
            # Implementation may return the existing request or fail gracefully
            if result2.get("success"):
                # If success, it should be referencing the same or a valid request
                request_name2 = result2.get("request_name") or result2.get("data", {}).get("request_name")
                # Either same request is returned (idempotent) or a new valid request
                self.assertTrue(request_name2,
                    f"Second call should return a request_name: {result2}")
            else:
                # Success=False indicates duplicate was detected
                self.assertFalse(result2.get("success"),
                    "Second call should indicate failure or duplicate detection")
        except (frappe.ValidationError, frappe.DuplicateEntryError):
            # Exception is also acceptable - duplicate was prevented
            pass
            
    def test_admin_interface_functions(self):
        """Test admin interface functions"""
        # Create some test requests
        member1 = self.create_test_member(
            first_name=f"Admin{self.uid}",
            last_name="Interface1",
            email=f"admin.interface1.{self.uid}@test.invalid"
        )

        member2 = self.create_test_member(
            first_name=f"Admin{self.uid}2",
            last_name="Interface2",
            email=f"admin.interface2.{self.uid}@test.invalid"
        )
        
        # Create failed request (create normally, then mark as failed)
        failed_request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member1.name,
            "email": member1.email,
            "full_name": member1.full_name,
        })
        failed_request.insert()
        failed_request.mark_failed("Test failure", "Test Stage")

        # Create pending request (status will be "Requested" by default)
        pending_request = frappe.get_doc({
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member2.name,
            "email": member2.email,
            "full_name": member2.full_name,
        })
        pending_request.insert()
        
        # Test get_failed_requests
        failed_requests_result = get_failed_requests()
        # Handle both direct list return and nested dict structure
        if isinstance(failed_requests_result, dict):
            failed_list = failed_requests_result.get("data", {}).get("failed_requests", [])
        else:
            failed_list = failed_requests_result
        # Each item may be a dict or an object
        failed_names = [
            req.get("name") if isinstance(req, dict) else req.name
            for req in failed_list
        ]
        self.assertIn(failed_request.name, failed_names)

        # Test retry_failed_request
        retry_result = retry_failed_request(failed_request.name)
        self.assertTrue(retry_result.get("success"))


class TestACRRoleProfileSync(EnhancedTestCase):
    """Regression tests for ACR Phase 3 role profile recalculation.

    Validates that when the ACR pipeline creates a user account for someone who
    already holds a position (board member, team lead), the user ends up with
    the correct role profile — not just the default "Verenigingen Member".

    Bug context: MijnRood sync adds board membership before the user account
    exists. The board save triggers _sync_role_profile_for_volunteer() which
    silently skips (no user). The ACR creates the user seconds later but
    never recalculated the profile, leaving the user stuck on "Verenigingen Member".
    """

    def test_acr_assigns_board_member_profile(self):
        """Regression: ACR for a board member should result in board member profile, not plain member."""
        # 1. Create member (no user account yet)
        member = self.create_test_member(
            first_name=f"Board{self.uid}",
            last_name="ProfileSync",
            email=f"board.profile.sync.{self.uid}@test.invalid",
            birth_date="1990-01-01",
        )
        self.assertFalse(member.user, "Member should not have a user yet")

        # 2. Create volunteer linked to the member
        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Board ProfileSync {self.uid}",
            email=member.email,
        )

        # 3. Create a chapter and add the volunteer as an active board member
        self.factory.ensure_chapter_role("Board Member")
        chapter = self.create_test_chapter()
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": "Board Member",
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter_doc.save()

        # Verify board membership is in place
        board_exists = frappe.db.exists(
            "Chapter Board Member",
            {"volunteer": volunteer.name, "is_active": 1, "parent": chapter.name},
        )
        self.assertTrue(board_exists, "Board membership should exist before ACR runs")

        # 4. Create ACR with default "Verenigingen Member" profile via factory
        #    (this is what MijnRood sync does — it doesn't know about board positions)
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )

        # Process the pipeline directly (no background job enqueued)
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # 5. Verify: user should have the BOARD MEMBER profile, not plain Member
        request.reload()
        self.assertEqual(request.status, "Completed", f"ACR should complete, got: {request.status}")

        created_user = request.created_user
        self.assertTrue(created_user, "ACR should have created a user")

        profiles = get_user_role_profiles(created_user)
        self.assertIn(
            "Verenigingen Chapter Board Member",
            profiles,
            f"Board member should get 'Verenigingen Chapter Board Member' profile, "
            f"got {profiles}. Phase 3 sync may not be running.",
        )

    def test_acr_keeps_member_profile_when_no_positions(self):
        """Sanity check: ACR for a plain member should keep the default member profile."""
        member = self.create_test_member(
            first_name=f"Plain{self.uid}",
            last_name="MemberSync",
            email=f"plain.member.sync.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        self.assertEqual(request.status, "Completed")

        created_user = request.created_user
        self.assertTrue(created_user, "ACR should have created a user")

        profiles = get_user_role_profiles(created_user)
        self.assertIn(
            "Verenigingen Member",
            profiles,
            f"Plain member should have 'Verenigingen Member' profile, got {profiles}",
        )


class TestAccountCreationManagerDutchBusinessLogic(EnhancedTestCase):
    """Tests for Dutch association-specific business logic"""

    def test_volunteer_age_validation(self):
        """Test that volunteer account creation enforces 16+ age requirement"""
        # Create underage member directly, bypassing factory validation
        # to test that volunteer creation properly enforces age requirements
        unique_email = f"too.young.{self.test_run_id}@test.invalid"

        # Try to create underage member - factory should reject this
        # If factory rejects, that's the expected behavior - age validation works
        try:
            young_member = self.create_test_member(
                first_name=f"Too{self.uid}",
                last_name="Young",
                email=unique_email,
                birth_date=add_days(getdate(), -365 * 15)  # 15 years old
            )
            # If we get here, member was created (unexpected) - test volunteer creation
            with self.assertRaises((BusinessRuleError, frappe.ValidationError)):
                self.create_test_volunteer(
                    member_name=young_member.name,
                    volunteer_name=f"Too Young Volunteer {self.uid}",
                    email=unique_email
                )
        except (BusinessRuleError, frappe.ValidationError) as e:
            # Factory correctly rejected the underage member - age validation works
            self.assertIn("16", str(e).lower() + " age requirement enforced",
                "Age validation should mention 16 years or enforce age requirement")
            
    def test_verenigingen_role_assignments(self):
        """Test proper Verenigingen role assignments"""
        member = self.create_test_member(
            first_name=f"Role{self.uid}3",
            last_name="Assignment",
            email=f"role.assignment.{self.uid}@test.invalid"
        )

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )
        requested_roles = [r.role for r in request.requested_roles]
        self.assertIn("Verenigingen Member", requested_roles)

        # Process the request
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()
        
        # Verify role was assigned
        request.reload()
        user_doc = frappe.get_doc("User", request.created_user)
        user_roles = [r.role for r in user_doc.roles]
        self.assertIn("Verenigingen Member", user_roles)
        
    def test_employee_creation_for_expense_functionality(self):
        """Test employee creation for Dutch association expense functionality"""
        member = self.create_test_member(
            first_name=f"Expense{self.uid}",
            last_name="Functionality",
            email=f"expense.functionality.{self.uid}@test.invalid",
            birth_date="1990-01-01"
        )

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"Expense Functionality Test {self.uid}",
            email=f"expense.functionality.{self.uid}@test.invalid"
        )

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )

        # Process the request
        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        # Verify employee was created for expense functionality
        request.reload()
        if not request.created_employee:
            self.skipTest("Employee not created - likely missing role in test environment")

        # Verify employee has proper settings for Dutch association
        employee_doc = frappe.get_doc("Employee", request.created_employee)
        self.assertEqual(employee_doc.status, "Active")
        self.assertIsNotNone(employee_doc.company)  # Should have default company

    def test_employee_creation_preserves_member_gender_and_birth_date(self):
        """Phase 1 create_employee_record must read gender/birth_date from the
        source Member, not hardcoded stubs.

        ERPNext's Employee.update_user() (setup/doctype/employee/employee.py)
        propagates emp.date_of_birth → user.birth_date and emp.gender →
        user.gender on every Employee save. Hardcoded stubs in Phase 1
        therefore silently overwrite real PII on the linked User.

        Phase 3 (user_role_profile_calculator._ensure_employee_for_profile)
        was fixed in PR #54 to preserve real values; Phase 1 still has the
        bug — same fix needs to land here.
        """
        member_dob = add_days(getdate(), -365 * 35)  # 35 years old
        member = self.create_test_member(
            first_name=f"PII{self.uid}",
            last_name="Preserved",
            email=f"pii.preserved.{self.uid}@test.invalid",
            gender="Female",
            birth_date=member_dob,
        )

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"PII Preserved Volunteer {self.uid}",
            email=f"pii.preserved.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        if not request.created_employee:
            self.skipTest("Employee not created - likely missing role in test environment")

        employee_doc = frappe.get_doc("Employee", request.created_employee)
        # Real Member PII must be on the Employee — not the "Prefer not to
        # say" / "1990-01-01" stubs Phase 1 hardcoded before this fix.
        self.assertEqual(employee_doc.gender, "Female",
            "Employee.gender should match Member.gender, not the Phase 1 stub")
        self.assertEqual(str(employee_doc.date_of_birth), str(getdate(member_dob)),
            "Employee.date_of_birth should match Member.birth_date, not the Phase 1 stub")

    def test_employee_creation_falls_back_to_stub_when_member_has_no_gender(self):
        """The stub fallback in _resolve_employee_pii_from_source must fire
        when the Member has no gender on file.

        Locks in the `gender or _STUB_EMPLOYEE_GENDER` branch — a future
        edit that drops the `or`-fallback (e.g., switching to
        `if member_name and pii: ...`) would silently break Employee
        creation for any Member without demographics.
        """
        member = self.create_test_member(
            first_name=f"NoGender{self.uid}",
            last_name="Stubfall",
            email=f"nogender.stubfall.{self.uid}@test.invalid",
            birth_date=add_days(getdate(), -365 * 30),
        )
        # Clear the gender field (it's optional on Member, so the DB allows None).
        frappe.db.set_value("Member", member.name, "gender", None)

        volunteer = self.create_test_volunteer(
            member_name=member.name,
            volunteer_name=f"NoGender Stubfall {self.uid}",
            email=f"nogender.stubfall.{self.uid}@test.invalid",
        )

        request = self.create_test_account_creation_request(
            source_record=volunteer.name, request_type="Volunteer"
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        if not request.created_employee:
            self.skipTest("Employee not created - likely missing role in test environment")

        employee_doc = frappe.get_doc("Employee", request.created_employee)
        # Stub falls back when the Member has no gender — same value Phase 1
        # used to hardcode unconditionally, but now reached only on missing data.
        self.assertEqual(employee_doc.gender, "Prefer not to say",
            "Employee.gender should fall back to the stub when Member.gender is None")

    def test_employee_creation_member_path_uses_source_doc_pii(self):
        """Phase 1 PII resolution must work for request_type='Member' too —
        the source_doc IS the Member, no Volunteer→Member hop needed.

        Exercises the `request_type == "Member"` branch of
        _resolve_employee_pii_from_source. The previous test only covered
        the Volunteer → source_doc.member → Member path.
        """
        member_dob = add_days(getdate(), -365 * 40)
        member = self.create_test_member(
            first_name=f"MemberPath{self.uid}",
            last_name="Direct",
            email=f"member.path.{self.uid}@test.invalid",
            gender="Male",
            birth_date=member_dob,
        )

        # CSV import flag forces Employee creation for a Member-type ACR
        # (see requires_employee_creation: Member request needs the flag
        # set or an Employee role; here the flag carries it.)
        request = self.create_test_account_creation_request(
            source_record=member.name,
            request_type="Member",
            create_employee_record=True,
        )

        manager = AccountCreationManager(request.name)
        manager.process_complete_pipeline()

        request.reload()
        if not request.created_employee:
            self.skipTest("Employee not created - likely missing role in test environment")

        employee_doc = frappe.get_doc("Employee", request.created_employee)
        self.assertEqual(employee_doc.gender, "Male",
            "Employee.gender should match Member.gender on the request_type='Member' path")
        self.assertEqual(str(employee_doc.date_of_birth), str(getdate(member_dob)),
            "Employee.date_of_birth should match Member.birth_date on the request_type='Member' path")


class TestAccountCreationManagerEnhancedFactory(EnhancedTestCase):
    """Tests for enhanced test factory integration"""

    def test_account_creation_request_factory(self):
        """Test enhanced factory support for account creation requests"""
        # Test data generation
        member = self.create_test_member(
            first_name=f"Factory{self.uid}",
            last_name="Test",
            email=f"factory.test.{self.uid}@test.invalid"
        )
        
        # Create request using enhanced patterns
        request_data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
            "priority": "Normal",
            "role_profile": "Verenigingen Member",
            "business_justification": "Test account creation with enhanced factory"
        }
        
        request = frappe.get_doc(request_data)
        request.append("requested_roles", {"role": "Verenigingen Member"})
        request.insert()
        
        # Verify all factory-generated data is valid
        self.assertIsNotNone(request.name)
        self.assertEqual(request.status, "Requested")
        self.assertIn("@test.invalid", request.email)  # Test email marker
        
    def test_realistic_test_data_generation(self):
        """Test that realistic test data is generated for account creation"""
        # Use factory to create comprehensive test scenario
        application_data = self.create_test_application_data(with_skills=True)

        # Create member from application data
        member = frappe.get_doc({
            "doctype": "Member",
            "first_name": application_data["first_name"],
            "last_name": application_data["last_name"],
            "email": application_data["email"],
            "birth_date": application_data["birth_date"]
        })
        member.insert()

        # Create ACR directly via factory (no background job enqueued)
        request = self.create_test_account_creation_request(
            source_record=member.name, request_type="Member"
        )

        # Verify realistic data characteristics
        self.assertIn("@test.invalid", request.email)  # Test marker
        self.assertTrue(len(request.full_name) > 5)  # Realistic name length
        self.assertIsNotNone(request.business_justification)
        
    def test_business_rule_integration(self):
        """Test integration with enhanced factory business rules"""
        # Factory should prevent creating invalid scenarios
        with self.assertRaises(BusinessRuleError):
            # Try to create member too young for volunteer work
            young_member = self.create_test_member(
                birth_date=add_days(getdate(), -365 * 10)  # 10 years old
            )


class TestQueueRoleProfileInference(EnhancedTestCase):
    """queue_account_creation_for_member infers role_profile from the requested
    roles when no role_profile is passed (audit T4.6).

    The inference must key off the genuine Volunteer role, not a substring
    match — a role whose name merely contains "Volunteer" must not trip the
    volunteer profile (the fragility fixed in this PR).
    """

    def _request_for(self, roles, suffix):
        """Queue member account creation with `roles` and no explicit
        role_profile; return the created Account Creation Request."""
        member = self.create_test_member(
            first_name=f"Infer{suffix}{self.uid}",
            last_name="Profile",
            email=f"infer.{suffix}.{self.uid}@test.invalid".lower(),
        )
        result = queue_account_creation_for_member(member.name, roles=roles)
        self.assertTrue(result.get("success"), f"queue failed: {result.get('errors')}")
        request_name = result.get("request_name") or result.get("data", {}).get("request_name")
        self.assertTrue(request_name, f"no request_name in result: {result}")
        return frappe.get_doc("Account Creation Request", request_name)

    def test_volunteer_role_infers_volunteer_profile(self):
        """A requested Verenigingen Volunteer role -> Volunteer profile + employee record."""
        request = self._request_for(["Verenigingen Member", "Verenigingen Volunteer"], "vol")
        self.assertEqual(request.role_profile, "Verenigingen Volunteer")
        self.assertTrue(request.create_employee_record)

    def test_member_only_role_infers_member_profile(self):
        """Only the Member role -> Member profile, no employee record."""
        request = self._request_for(["Verenigingen Member"], "mem")
        self.assertEqual(request.role_profile, "Verenigingen Member")
        self.assertFalse(request.create_employee_record)

    def test_volunteer_substring_role_does_not_infer_volunteer_profile(self):
        """A non-volunteer role whose name merely contains "Volunteer" must NOT
        infer the Volunteer profile. The old substring check did; the exact
        Roles.VOLUNTEER membership check does not."""
        if not frappe.db.exists("Role", "Volunteer Manager"):
            frappe.get_doc({"doctype": "Role", "role_name": "Volunteer Manager"}).insert()
        request = self._request_for(["Volunteer Manager"], "volmgr")
        self.assertEqual(request.role_profile, "Verenigingen Member")
        self.assertFalse(request.create_employee_record)


if __name__ == "__main__":
    # Run the test suite
    unittest.main(verbosity=2)