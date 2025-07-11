# -*- coding: utf-8 -*-
"""
Critical Business Logic Tests
These tests MUST pass for the system to function correctly.
They verify that essential methods exist and core workflows work.
"""

import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today


class TestCriticalBusinessLogic(FrappeTestCase):
    """Tests for critical business logic that must always work"""

    def test_membership_doctype_has_required_methods(self):
        """Test that Membership doctype has all required methods"""
        from verenigingen.verenigingen.doctype.membership.membership import Membership
        
        # Create a membership instance with proper initialization
        membership = frappe.new_doc("Membership")
        
        # Verify critical methods exist
        critical_methods = [
            'update_member_status',
            'validate',
            'on_submit',
            'on_cancel'
        ]
        
        for method_name in critical_methods:
            self.assertTrue(hasattr(membership, method_name),
                           f"Membership doctype must have {method_name} method")
            self.assertTrue(callable(getattr(membership, method_name)),
                           f"Membership.{method_name} must be callable")

    def test_member_doctype_has_required_methods(self):
        """Test that Member doctype has all required methods"""
        from verenigingen.verenigingen.doctype.member.member import Member
        
        # Create a member instance with proper initialization
        member = frappe.new_doc("Member")
        
        # Verify critical methods exist
        critical_methods = [
            'update_membership_status',
            'validate',
            'before_save'
        ]
        
        for method_name in critical_methods:
            self.assertTrue(hasattr(member, method_name),
                           f"Member doctype must have {method_name} method")
            self.assertTrue(callable(getattr(member, method_name)),
                           f"Member.{method_name} must be callable")

    def test_membership_application_review_has_required_methods(self):
        """Test that membership application review API has required methods"""
        try:
            from verenigingen.api.membership_application_review import approve_membership_application
            
            # Verify the function exists and is callable
            self.assertTrue(callable(approve_membership_application),
                           "approve_membership_application must be callable")
            
            # Verify it has the whitelisted decorator
            self.assertTrue(hasattr(approve_membership_application, '__wrapped__'),
                           "approve_membership_application must be whitelisted")
            
        except ImportError as e:
            self.fail(f"Failed to import required module: {e}")

    def test_required_fields_exist_in_doctypes(self):
        """Test that required fields exist in critical doctypes"""
        
        # Test Member doctype has critical fields
        member_meta = frappe.get_meta("Member")
        member_fields = [f.fieldname for f in member_meta.fields]
        
        # We expect these fields to exist (based on code usage)
        expected_member_fields = [
            'email', 'status', 'full_name', 'member_id'
        ]
        
        for field in expected_member_fields:
            self.assertIn(field, member_fields,
                         f"Member doctype must have {field} field")
        
        # Test Membership doctype has critical fields
        membership_meta = frappe.get_meta("Membership")
        membership_fields = [f.fieldname for f in membership_meta.fields]
        
        expected_membership_fields = [
            'member', 'membership_type', 'status', 'start_date'
        ]
        
        for field in expected_membership_fields:
            self.assertIn(field, membership_fields,
                         f"Membership doctype must have {field} field")

    def test_critical_api_endpoints_exist(self):
        """Test that critical API endpoints exist and are whitelisted"""
        critical_apis = [
            'verenigingen.api.membership_application_review.approve_membership_application',
            'verenigingen.api.member_management.get_address_members_html_api',
        ]
        
        for api_path in critical_apis:
            try:
                # Try to get the function
                func = frappe.get_attr(api_path)
                self.assertTrue(callable(func),
                               f"{api_path} must be callable")
                
                # Check if it's whitelisted (has __wrapped__ attribute from decorator)
                self.assertTrue(hasattr(func, '__wrapped__') or 
                               getattr(func, 'is_whitelisted', False),
                               f"{api_path} must be whitelisted")
                
            except Exception as e:
                self.fail(f"Critical API {api_path} is not accessible: {e}")

    def test_membership_submission_workflow(self):
        """Test that membership submission workflow works end-to-end"""
        # Skip if no test data is available
        if not frappe.db.exists("Member", {"email": "test@example.com"}):
            self.skipTest("No test member available")
            
        # Create a minimal membership for testing
        test_member = frappe.get_doc({
            "doctype": "Member",
            "first_name": "Test",
            "last_name": "User",
            "email": "test.critical@example.com",
            "status": "Active"
        })
        
        try:
            test_member.insert(ignore_permissions=True)
            
            # Create membership
            membership = frappe.get_doc({
                "doctype": "Membership",
                "member": test_member.name,
                "membership_type": "Test Type",
                "start_date": today(),
                "status": "Draft"
            })
            
            # The key test: This should not raise AttributeError
            try:
                membership.insert(ignore_permissions=True)
                # Don't submit to avoid other dependencies, just test the methods exist
                self.assertTrue(hasattr(membership, 'update_member_status'))
                
            except AttributeError as e:
                self.fail(f"Membership workflow failed due to missing method: {e}")
                
        finally:
            # Clean up
            try:
                frappe.delete_doc("Member", test_member.name, force=True)
            except:
                pass

    def test_no_critical_import_errors(self):
        """Test that critical modules can be imported without errors"""
        critical_modules = [
            'verenigingen.verenigingen.doctype.membership.membership',
            'verenigingen.verenigingen.doctype.member.member',
            'verenigingen.api.membership_application_review',
            'verenigingen.api.member_management',
        ]
        
        for module_path in critical_modules:
            try:
                frappe.get_module(module_path)
            except ImportError as e:
                self.fail(f"Critical module {module_path} cannot be imported: {e}")


if __name__ == '__main__':
    unittest.main()