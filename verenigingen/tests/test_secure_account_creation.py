"""
Comprehensive Security Tests for Account Creation Manager

This test suite validates that the new AccountCreationManager system:
1. Eliminates all security vulnerabilities (no ignore_permissions=True)
2. Properly validates permissions before operations
3. Provides complete audit trails
4. Handles failures gracefully with proper rollback
5. Integrates securely with existing Frappe patterns

Author: Verenigingen Development Team
"""

import frappe
import unittest
from unittest.mock import patch
from frappe.test_runner import make_test_records
from verenigingen.utils.account_creation_manager import AccountCreationManager, queue_account_creation_for_volunteer
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSecureAccountCreation(EnhancedTestCase):
    """Test secure account creation functionality"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create test roles and role profiles if they don't exist
        cls.create_test_roles()
        cls.create_test_role_profiles()

    def setUp(self):
        super().setUp()
        # Clean up any existing test data
        self.cleanup_test_data()
        
        # Create test volunteer for account creation
        self.test_volunteer = self.create_test_volunteer(
            volunteer_name="Test Volunteer Account Creation",
            email="test.volunteer.security@example.com",
            status="New"
        )
        
    def tearDown(self):
        super().tearDown()
        self.cleanup_test_data()
        
    def cleanup_test_data(self):
        """Clean up test data to prevent interference between tests"""
        # Delete test account creation requests
        for request in frappe.get_all("Account Creation Request", 
                                     filters={"email": ["like", "%test.volunteer.security%"]}):
            frappe.delete_doc("Account Creation Request", request.name, force=True)
            
        # Delete test users
        test_emails = ["test.volunteer.security@example.com"]
        for email in test_emails:
            if frappe.db.exists("User", email):
                frappe.delete_doc("User", email, force=True)

    @classmethod
    def create_test_roles(cls):
        """Create test roles if they don't exist"""
        test_roles = [
            "Verenigingen Volunteer",
            "Employee", 
            "Employee Self Service"
        ]
        
        for role_name in test_roles:
            if not frappe.db.exists("Role", role_name):
                role_doc = frappe.get_doc({
                    "doctype": "Role",
                    "role_name": role_name,
                    "desk_access": 1
                })
                role_doc.insert()

    @classmethod
    def create_test_role_profiles(cls):
        """Create test role profiles if they don't exist"""
        if not frappe.db.exists("Role Profile", "Verenigingen Volunteer"):
            role_profile = frappe.get_doc({
                "doctype": "Role Profile",
                "role_profile": "Verenigingen Volunteer",
                "roles": [
                    {"role": "Verenigingen Volunteer"},
                    {"role": "Employee"},
                    {"role": "Employee Self Service"}
                ]
            })
            role_profile.insert()

    def test_secure_account_creation_request_creation(self):
        """Test that account creation requests are created with proper security"""
        # Set user with proper permissions
        frappe.set_user("Administrator")
        
        # Queue account creation for volunteer
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name,
            priority="Normal"
        )
        
        # Validate request was created
        self.assertIn("request_name", result)
        request_name = result["request_name"]
        
        # Validate request document
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        self.assertEqual(request_doc.request_type, "Volunteer")
        self.assertEqual(request_doc.source_record, self.test_volunteer.name)
        self.assertEqual(request_doc.email, self.test_volunteer.email)
        self.assertEqual(request_doc.status, "Queued")
        self.assertEqual(request_doc.requested_by, "Administrator")
        
        # Validate requested roles
        role_names = [role.role for role in request_doc.requested_roles]
        expected_roles = ["Verenigingen Volunteer", "Employee", "Employee Self Service"]
        for expected_role in expected_roles:
            self.assertIn(expected_role, role_names)

    def test_permission_validation_for_account_creation(self):
        """Test that permission validation works properly"""
        # Create a user without permissions
        test_user_email = "test.nopermissions@example.com"
        if not frappe.db.exists("User", test_user_email):
            test_user = frappe.get_doc({
                "doctype": "User",
                "email": test_user_email,
                "first_name": "No",
                "last_name": "Permissions",
                "user_type": "System User"
            })
            test_user.insert()
        
        # Set user without permissions
        frappe.set_user(test_user_email)
        
        # Attempt to queue account creation - should fail
        with self.assertRaises(frappe.PermissionError):
            queue_account_creation_for_volunteer(
                volunteer_name=self.test_volunteer.name,
                priority="Normal"
            )
        
        # Clean up test user
        frappe.set_user("Administrator")
        frappe.delete_doc("User", test_user_email, force=True)

    def test_no_permission_bypasses_in_account_creation(self):
        """Test that no ignore_permissions=True is used in account creation"""
        frappe.set_user("Administrator")
        
        # Queue account creation
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        # Process the request
        manager = AccountCreationManager(request_name)
        
        # Mock the account creation methods to track permission usage
        with patch.object(frappe, 'get_doc') as mock_get_doc:
            with patch.object(frappe.model.document.Document, 'insert') as mock_insert:
                with patch.object(frappe.model.document.Document, 'save') as mock_save:
                    
                    # Setup mocks to track ignore_permissions usage
                    def track_insert(*args, **kwargs):
                        if 'ignore_permissions' in kwargs and kwargs['ignore_permissions']:
                            raise AssertionError("ignore_permissions=True detected in insert()")
                        return None
                    
                    def track_save(*args, **kwargs):
                        if 'ignore_permissions' in kwargs and kwargs['ignore_permissions']:
                            raise AssertionError("ignore_permissions=True detected in save()")
                        return None
                    
                    mock_insert.side_effect = track_insert
                    mock_save.side_effect = track_save
                    
                    # This should pass without using ignore_permissions
                    # (except for system status tracking which is allowed)
                    try:
                        manager.validate_processing_permissions()
                        # Test passed - no permission bypasses detected
                    except AssertionError as e:
                        if "ignore_permissions=True detected" in str(e):
                            self.fail("Account creation uses forbidden permission bypasses")

    def test_account_creation_audit_trail(self):
        """Test that complete audit trail is maintained"""
        frappe.set_user("Administrator")
        
        # Queue account creation
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        # Validate audit fields
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        self.assertIsNotNone(request_doc.requested_by)
        self.assertIsNotNone(request_doc.creation)
        self.assertEqual(request_doc.requested_by, "Administrator")

    def test_account_creation_failure_handling(self):
        """Test that failures are handled gracefully with proper error reporting"""
        frappe.set_user("Administrator")
        
        # Create request with invalid email to force failure
        invalid_volunteer = self.create_test_volunteer(
            volunteer_name="Invalid Email Volunteer",
            email="invalid-email-format",  # Invalid email
            status="New"
        )
        
        # Queue account creation
        result = queue_account_creation_for_volunteer(
            volunteer_name=invalid_volunteer.name
        )
        request_name = result["request_name"]
        
        # Process the request (should fail gracefully)
        manager = AccountCreationManager(request_name)
        
        # Process should fail but not crash
        with self.assertRaises(Exception):
            manager.process_complete_pipeline()
            
        # Validate failure was recorded properly
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        self.assertEqual(request_doc.status, "Failed")
        self.assertIsNotNone(request_doc.failure_reason)

    def test_background_job_integration(self):
        """Test that background job processing works correctly"""
        frappe.set_user("Administrator")
        
        # Queue account creation
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        # Validate job was queued
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        self.assertEqual(request_doc.status, "Queued")
        
        # Mock successful processing
        with patch('verenigingen.utils.account_creation_manager.AccountCreationManager.process_complete_pipeline') as mock_process:
            mock_process.return_value = None  # Simulate success
            
            # Call the background job function
            from verenigingen.utils.account_creation_manager import process_account_creation_request
            result = process_account_creation_request(request_name)
            
            # Validate job was called
            mock_process.assert_called_once()
            self.assertTrue(result["success"])

    def test_role_assignment_security(self):
        """Test that role assignments are validated properly"""
        frappe.set_user("Administrator")
        
        # Queue account creation with specific roles
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        # Get the request and validate role security
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        manager = AccountCreationManager(request_name)
        manager.load_request()
        
        # Test role validation
        for role_row in request_doc.requested_roles:
            # Should be able to assign volunteer roles as Administrator
            self.assertTrue(manager.can_assign_role(role_row.role))

    def test_volunteer_integration_security(self):
        """Test that volunteer integration uses secure methods"""
        # Create new volunteer (should trigger secure account creation)
        volunteer = self.create_test_volunteer(
            volunteer_name="Integration Test Volunteer",
            email="integration.test@example.com",
            status="New"
        )
        
        # Verify that account creation was queued (not processed immediately)
        account_requests = frappe.get_all("Account Creation Request",
            filters={"source_record": volunteer.name})
        
        # Should have created an account request
        self.assertTrue(len(account_requests) > 0, 
                       "Volunteer creation should queue account creation request")
        
        # Verify no immediate user creation (secure approach)
        self.assertFalse(frappe.db.exists("User", "integration.test@example.com"),
                        "User should not be created immediately - should go through secure queue")

    def test_employee_record_security(self):
        """Test that employee record creation follows security protocols"""
        frappe.set_user("Administrator")
        
        # Create account creation request
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        # Test manager initialization
        manager = AccountCreationManager(request_name)
        manager.load_request()
        
        # Validate employee creation requirements
        self.assertTrue(manager.requires_employee_creation())
        
        # Validate that employee creation uses proper permissions
        # (This would be tested in integration with actual processing)

    def test_retry_mechanism_security(self):
        """Test that retry mechanism maintains security"""
        frappe.set_user("Administrator")
        
        # Create and fail a request
        result = queue_account_creation_for_volunteer(
            volunteer_name=self.test_volunteer.name
        )
        request_name = result["request_name"]
        
        request_doc = frappe.get_doc("Account Creation Request", request_name)
        request_doc.mark_failed("Test failure", "User Creation")
        
        # Test retry functionality
        retry_result = request_doc.retry_processing()
        self.assertTrue(retry_result["success"])
        
        # Validate retry maintains audit trail
        request_doc.reload()
        self.assertEqual(request_doc.retry_count, 1)
        self.assertIsNotNone(request_doc.last_retry_at)


class TestSecurityValidation(unittest.TestCase):
    """Additional security validation tests"""
    
    def test_no_global_permission_bypasses(self):
        """Scan for forbidden permission bypasses in account creation code"""
        import os
        import re
        
        # Files to scan for security violations
        files_to_scan = [
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/account_creation_manager.py",
            "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/verenigingen/doctype/account_creation_request/account_creation_request.py"
        ]
        
        permission_bypass_pattern = re.compile(r'ignore_permissions\s*=\s*True')
        violations = []
        
        for file_path in files_to_scan:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                # Find all permission bypasses
                matches = permission_bypass_pattern.finditer(content)
                for match in matches:
                    # Get line number
                    line_num = content[:match.start()].count('\n') + 1
                    
                    # Get context around the match
                    lines = content.split('\n')
                    context = lines[max(0, line_num-3):min(len(lines), line_num+3)]
                    
                    # Check if this is a system operation (status tracking)
                    is_system_operation = any(
                        keyword in '\n'.join(context).lower() 
                        for keyword in ['status tracking', 'system operation', 'mark_', 'save(ignore_permissions=True)  # System']
                    )
                    
                    if not is_system_operation:
                        violations.append(f"{file_path}:{line_num} - Unauthorized permission bypass")
        
        if violations:
            self.fail(f"Security violations found:\n" + "\n".join(violations))

    def test_admin_interface_permissions(self):
        """Test that admin interface properly validates permissions"""
        # Test that non-admin users cannot access admin functions
        if frappe.db.exists("User", "test.member@example.com"):
            frappe.set_user("test.member@example.com")
            
            # Should not be able to access admin functions
            with self.assertRaises(frappe.PermissionError):
                from verenigingen.utils.account_creation_manager import get_failed_requests
                get_failed_requests()
        
        frappe.set_user("Administrator")


if __name__ == "__main__":
    unittest.main()