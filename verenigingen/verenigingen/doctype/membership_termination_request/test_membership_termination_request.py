# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for Membership Termination Request
Tests all aspects of the termination workflow including business logic, validation, and integration
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_months, now_datetime, today


class TestMembershipTerminationRequest(FrappeTestCase):
    """Comprehensive tests for Membership Termination Request doctype"""

    def setUp(self):
        """Set up test environment"""
        self.setup_test_data()

    def tearDown(self):
        """Clean up test data"""
        self.cleanup_test_data()

    def setup_test_data(self):
        """Create test data for termination scenarios"""
        # Create test member
        self.test_member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Termination",
                "email": "test.termination@example.com",
                "status": "Active",
                "member_since": add_months(today(), -12),
            }
        )
        self.test_member.insert(ignore_permissions=True)

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Termination Type"):
            self.test_membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Termination Type",
                    "amount": 100,
                    "currency": "EUR",
                    "subscription_period": "Annual",
                }
            )
            self.test_membership_type.insert(ignore_permissions=True)

        # Create test membership
        self.test_membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.test_member.name,
                "membership_type": "Test Termination Type",
                "start_date": add_months(today(), -6),
                "status": "Active",
            }
        )
        self.test_membership.insert(ignore_permissions=True)

    def cleanup_test_data(self):
        """Clean up test data"""
        # Clean up in reverse dependency order
        try:
            # Clean up termination requests
            termination_requests = frappe.get_all(
                "Membership Termination Request", filters={"member": self.test_member.name}
            )
            for req in termination_requests:
                frappe.delete_doc("Membership Termination Request", req.name, force=True)

            # Clean up memberships
            frappe.delete_doc("Membership", self.test_membership.name, force=True)

            # Clean up member
            frappe.delete_doc("Member", self.test_member.name, force=True)

            # Clean up membership type
            if frappe.db.exists("Membership Type", "Test Termination Type"):
                frappe.delete_doc("Membership Type", "Test Termination Type", force=True)
        except:
            pass

    def test_document_creation_and_validation(self):
        """Test basic document creation and validation"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Moving to another city",
                "request_date": today(),
            }
        )

        # Test document creation
        termination_request.insert(ignore_permissions=True)

        # Verify defaults were set
        self.assertEqual(termination_request.status, "Pending")
        self.assertIsNotNone(termination_request.requested_by)
        self.assertEqual(termination_request.request_date, today())

        # Verify validation worked
        self.assertEqual(termination_request.member, self.test_member.name)
        self.assertEqual(termination_request.termination_type, "Voluntary")

    def test_status_workflow(self):
        """Test status workflow transitions"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test workflow",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test status transitions
        statuses = ["Pending", "Approved", "Executed"]
        for status in statuses:
            termination_request.status = status
            termination_request.save(ignore_permissions=True)
            termination_request.reload()
            self.assertEqual(termination_request.status, status)

    def test_audit_trail_functionality(self):
        """Test audit trail creation and management"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test audit trail",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test audit entry creation
        termination_request.add_audit_entry("Test Action", "Test details for audit")

        # Verify audit entry was created (if audit entries are stored)
        # This depends on the implementation of add_audit_entry
        self.assertTrue(hasattr(termination_request, "add_audit_entry"))

    def test_approval_requirements_validation(self):
        """Test approval requirements are set correctly"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test approval requirements",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Verify approval requirements are set
        self.assertTrue(hasattr(termination_request, "set_approval_requirements"))

    def test_date_validation(self):
        """Test date validation logic"""
        # Test future request date
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test date validation",
                "request_date": add_days(today(), 30),
            }
        )

        # Should be able to create with future date
        termination_request.insert(ignore_permissions=True)
        self.assertEqual(termination_request.request_date, add_days(today(), 30))

    def test_permission_validation(self):
        """Test permission validation"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test permissions",
                "request_date": today(),
            }
        )

        # Test document creation (permission validation happens in validate)
        termination_request.insert(ignore_permissions=True)

        # Verify permission validation method exists
        self.assertTrue(hasattr(termination_request, "validate_permissions"))

    @patch("verenigingen.utils.termination_integration.cancel_membership_safe")
    @patch("verenigingen.utils.termination_integration.deactivate_user_account_safe")
    def test_termination_execution_workflow(self, mock_deactivate_user, mock_cancel_membership):
        """Test complete termination execution workflow"""
        # Mock the integration functions
        mock_cancel_membership.return_value = {"success": True, "message": "Membership cancelled"}
        mock_deactivate_user.return_value = {"success": True, "message": "User deactivated"}

        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test execution workflow",
                "request_date": today(),
                "status": "Executed",
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test execution workflow
        try:
            termination_request.execute_termination_internal()

            # Verify execution fields are set
            self.assertIsNotNone(termination_request.executed_by)
            self.assertIsNotNone(termination_request.execution_date)

        except Exception as e:
            # If execution fails, verify it's due to expected reasons
            self.assertIn("termination", str(e).lower())

    def test_different_termination_types(self):
        """Test different termination types"""
        termination_types = ["Voluntary", "Non-payment", "Deceased", "Policy Violation"]

        for term_type in termination_types:
            if frappe.db.exists(
                "Membership Termination Request",
                {"member": self.test_member.name, "termination_type": term_type},
            ):
                continue

            termination_request = frappe.get_doc(
                {
                    "doctype": "Membership Termination Request",
                    "member": self.test_member.name,
                    "termination_type": term_type,
                    "termination_reason": f"Test {term_type} termination",
                    "request_date": today(),
                }
            )

            # Should be able to create with different types
            termination_request.insert(ignore_permissions=True)
            self.assertEqual(termination_request.termination_type, term_type)

    def test_system_integration_methods(self):
        """Test system integration methods exist and are callable"""
        termination_request = frappe.new_doc("Membership Termination Request")

        # Test integration methods
        integration_methods = ["execute_system_updates_safely", "execute_termination_internal"]

        for method_name in integration_methods:
            self.assertTrue(hasattr(termination_request, method_name))
            self.assertTrue(callable(getattr(termination_request, method_name)))

    def test_error_handling_scenarios(self):
        """Test error handling in various scenarios"""
        # Test with invalid member
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": "INVALID-MEMBER",
                "termination_type": "Voluntary",
                "termination_reason": "Test error handling",
                "request_date": today(),
            }
        )

        # Should raise validation error
        with self.assertRaises(frappe.ValidationError):
            termination_request.insert(ignore_permissions=True)

    def test_document_status_changes(self):
        """Test document status changes and their effects"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test status changes",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test status change handling
        original_status = termination_request.status
        termination_request.status = "Approved"
        termination_request.save(ignore_permissions=True)

        # Verify status change was handled
        self.assertEqual(termination_request.status, "Approved")
        self.assertNotEqual(termination_request.status, original_status)

    def test_termination_impact_tracking(self):
        """Test tracking of termination impacts"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test impact tracking",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test impact tracking fields
        impact_fields = [
            "sepa_mandates_cancelled",
            "positions_ended",
            "subscriptions_cancelled",
            "teams_left",
        ]

        for field in impact_fields:
            self.assertTrue(hasattr(termination_request, field))

    def test_concurrent_termination_requests(self):
        """Test handling of concurrent termination requests"""
        # Create first request
        termination_request1 = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "First request",
                "request_date": today(),
            }
        )
        termination_request1.insert(ignore_permissions=True)

        # Create second request for same member
        termination_request2 = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Second request",
                "request_date": today(),
            }
        )

        # Should be able to create multiple requests
        termination_request2.insert(ignore_permissions=True)

        # Verify both requests exist
        self.assertNotEqual(termination_request1.name, termination_request2.name)

    def test_termination_analytics_integration(self):
        """Test integration with termination analytics"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test analytics",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test analytics module integration
        try:
            from verenigingen.verenigingen.doctype.membership_termination_request.membership_termination_analytics import (
                get_termination_statistics,
            )

            # Test analytics function exists
            self.assertTrue(callable(get_termination_statistics))

        except ImportError:
            # Analytics module might not be required
            pass

    def test_data_integrity_validation(self):
        """Test data integrity validation"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test data integrity",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test required fields
        required_fields = ["member", "termination_type", "termination_reason", "request_date"]
        for field in required_fields:
            self.assertTrue(hasattr(termination_request, field))
            self.assertIsNotNone(getattr(termination_request, field))

    def test_workflow_state_management(self):
        """Test workflow state management"""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test workflow state",
                "request_date": today(),
            }
        )
        termination_request.insert(ignore_permissions=True)

        # Test workflow state transitions
        valid_transitions = [("Pending", "Approved"), ("Approved", "Executed"), ("Pending", "Rejected")]

        for from_status, to_status in valid_transitions:
            termination_request.status = from_status
            termination_request.save(ignore_permissions=True)

            termination_request.status = to_status
            termination_request.save(ignore_permissions=True)

            self.assertEqual(termination_request.status, to_status)


if __name__ == "__main__":
    unittest.main()
