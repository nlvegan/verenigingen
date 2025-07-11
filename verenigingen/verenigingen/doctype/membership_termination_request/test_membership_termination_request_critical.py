# -*- coding: utf-8 -*-
"""
Critical Business Logic Tests for Membership Termination Request
These tests verify that essential methods exist and core termination workflows work.
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today


class TestMembershipTerminationRequestCritical(FrappeTestCase):
    """Critical tests for Membership Termination Request doctype"""

    def test_required_methods_exist(self):
        """Test that all critical methods exist"""
        termination_request = frappe.new_doc("Membership Termination Request")

        # Verify critical methods exist
        critical_methods = [
            "validate",
            "set_defaults",
            "before_save",
            "after_insert",
            "on_update_after_submit",
            "on_submit",
            "handle_status_change",
            "execute_termination_internal",
            "execute_system_updates_safely",
            "add_audit_entry",
        ]

        for method_name in critical_methods:
            self.assertTrue(
                hasattr(termination_request, method_name),
                f"MembershipTerminationRequest must have {method_name} method",
            )
            self.assertTrue(
                callable(getattr(termination_request, method_name)),
                f"MembershipTerminationRequest.{method_name} must be callable",
            )

    def test_termination_integration_module_exists(self):
        """Test that termination integration utilities exist"""
        try:
            from verenigingen.utils.termination_integration import (
                cancel_membership_safe,
                cancel_sepa_mandate_safe,
                cancel_subscription_safe,
                deactivate_user_account_safe,
                end_board_positions_safe,
                suspend_team_memberships_safe,
                terminate_employee_records_safe,
                terminate_volunteer_records_safe,
            )

            # Verify all integration methods are callable
            integration_methods = [
                cancel_membership_safe,
                cancel_sepa_mandate_safe,
                cancel_subscription_safe,
                deactivate_user_account_safe,
                end_board_positions_safe,
                suspend_team_memberships_safe,
                terminate_employee_records_safe,
                terminate_volunteer_records_safe,
            ]

            for method in integration_methods:
                self.assertTrue(
                    callable(method), f"Termination integration method {method.__name__} must be callable"
                )

        except ImportError as e:
            self.fail(f"Failed to import termination integration utilities: {e}")

    def test_required_fields_exist(self):
        """Test that required fields exist in doctype"""
        meta = frappe.get_meta("Membership Termination Request")
        field_names = [f.fieldname for f in meta.fields]

        # Critical fields that should exist
        required_fields = [
            "member",
            "status",
            "termination_type",
            "request_date",
            "requested_by",
            "execution_date",
            "executed_by",
            "termination_reason",
        ]

        for field in required_fields:
            self.assertIn(field, field_names, f"Membership Termination Request must have {field} field")

    def test_document_creation_workflow(self):
        """Test basic document creation workflow"""
        # Skip if no test member available
        if not frappe.db.exists("Member", {"email": "test@example.com"}):
            self.skipTest("No test member available")

        # Create a test member for termination
        test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Termination",
                "email": "test.termination@example.com",
                "status": "Active",
            }
        )

        try:
            test_member.insert(ignore_permissions=True)

            # Create termination request
            termination_request = frappe.get_doc(
                {
                    "doctype": "Membership Termination Request",
                    "member": test_member.name,
                    "termination_type": "Voluntary",
                    "termination_reason": "Test termination",
                    "request_date": today(),
                }
            )

            # Test document creation (should not raise exceptions)
            termination_request.insert(ignore_permissions=True)

            # Verify defaults were set
            self.assertEqual(termination_request.status, "Pending")
            self.assertIsNotNone(termination_request.requested_by)
            self.assertIsNotNone(termination_request.request_date)

        finally:
            # Clean up
            try:
                if frappe.db.exists("Membership Termination Request", termination_request.name):
                    frappe.delete_doc("Membership Termination Request", termination_request.name, force=True)
                frappe.delete_doc("Member", test_member.name, force=True)
            except:
                pass

    def test_audit_trail_functionality(self):
        """Test that audit trail methods work"""
        termination_request = frappe.new_doc("Membership Termination Request")

        # Test add_audit_entry method exists and is callable
        self.assertTrue(hasattr(termination_request, "add_audit_entry"))

        # Test method doesn't crash when called
        try:
            # This should not raise an exception
            termination_request.add_audit_entry("Test Entry", "Test Details")
        except Exception as e:
            self.fail(f"add_audit_entry method should not raise exception: {e}")

    def test_status_validation(self):
        """Test status field validation"""
        meta = frappe.get_meta("Membership Termination Request")
        status_field = None

        for field in meta.fields:
            if field.fieldname == "status":
                status_field = field
                break

        self.assertIsNotNone(status_field, "Status field must exist")

        # Verify it's a Select field with proper options
        self.assertEqual(status_field.fieldtype, "Select")
        self.assertIsNotNone(status_field.options)

        # Check that key statuses are available
        status_options = status_field.options.split("\n") if status_field.options else []
        expected_statuses = ["Pending", "Approved", "Executed", "Cancelled"]

        for status in expected_statuses:
            self.assertIn(status, status_options, f"Status field must include '{status}' option")

    def test_no_critical_import_errors(self):
        """Test that the doctype module can be imported without errors"""
        try:
            from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_request import (
                MembershipTerminationRequest,
            )

            # Verify it's the correct class
            self.assertTrue(issubclass(MembershipTerminationRequest, frappe.model.document.Document))

        except ImportError as e:
            self.fail(f"Failed to import MembershipTerminationRequest: {e}")

    def test_termination_type_validation(self):
        """Test termination type field validation"""
        meta = frappe.get_meta("Membership Termination Request")
        termination_type_field = None

        for field in meta.fields:
            if field.fieldname == "termination_type":
                termination_type_field = field
                break

        self.assertIsNotNone(termination_type_field, "Termination type field must exist")

        # Verify it has proper options
        if termination_type_field.fieldtype == "Select":
            self.assertIsNotNone(termination_type_field.options)

            # Check for common termination types
            type_options = (
                termination_type_field.options.split("\n") if termination_type_field.options else []
            )
            expected_types = ["Voluntary", "Administrative"]

            for term_type in expected_types:
                self.assertIn(
                    term_type, type_options, f"Termination type field should include '{term_type}' option"
                )


if __name__ == "__main__":
    unittest.main()
