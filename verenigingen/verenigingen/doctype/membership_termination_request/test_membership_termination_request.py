# -*- coding: utf-8 -*-
"""
Comprehensive Test Suite for Membership Termination Request
Tests all aspects of the termination workflow including business logic, validation, and integration
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipTerminationRequest(EnhancedTestCase):
    """Comprehensive tests for Membership Termination Request doctype"""

    def setUp(self):
        """Set up test environment using Enhanced Test Factory"""
        super().setUp()

        # Create test member using Enhanced Test Factory. NB: no explicit email --
        # a hardcoded address here previously caused cross-run pollution (a member
        # left in status "Quit" by a genuinely-executing termination test would
        # make the NEXT run's validate_termination_request() reject as
        # "Cannot terminate member with status: Quit"); the factory generates a
        # unique email/member per test invocation instead.
        self.test_member = self.create_test_member(
            first_name="Test",
            last_name="Termination",
            status="Active",
            member_since=add_months(today(), -12),
        )

        # Create test membership type. enforce_minimum_period is off: it defaults to 1,
        # which makes set_commitment_end_date() put commitment_end_date 12 months after
        # the membership start, and validate_commitment_period() then refuses to
        # terminate before that date. These tests are about the termination workflow,
        # not the welcome-gift commitment rule (covered by
        # tests/member/test_membership_commitment_period.py).
        if not frappe.db.exists("Membership Type", "Test Termination Type"):
            self.test_membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Termination Type",
                    "amount": 100,
                    "currency": "EUR",
                    "billing_period": "Annual",
                    "is_active": 1,
                    "enforce_minimum_period": 0,
                }
            )
            self.test_membership_type.insert()
        else:
            # Ensure the pre-existing type is active and unconstrained for membership
            # creation (a type left behind by an older run still enforces the period).
            self.test_membership_type = frappe.get_doc("Membership Type", "Test Termination Type")
            if not self.test_membership_type.is_active or self.test_membership_type.enforce_minimum_period:
                self.test_membership_type.is_active = 1
                self.test_membership_type.enforce_minimum_period = 0
                self.test_membership_type.save()

        self.test_membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": self.test_member.name,
                "membership_type": "Test Termination Type",
                "start_date": add_months(today(), -6),
                "status": "Active",
            }
        )
        self.test_membership.insert()

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
        termination_request.insert()

        # Verify defaults were set
        self.assertEqual(termination_request.status, "Draft")
        self.assertIsNotNone(termination_request.requested_by)
        self.assertEqual(termination_request.request_date, today())

        # Verify validation worked
        self.assertEqual(termination_request.member, self.test_member.name)
        self.assertEqual(termination_request.termination_type, "Voluntary")

    def test_status_change_appends_audit_trail_entry(self):
        """Each status change + save() actually persists AND appends a real
        before_save audit-trail entry (TerminationAuditService.log_document_update)
        recording the new status -- not just an in-memory field mutation.

        NB: this doctype's is_submittable=0 in the JSON is a form-layer setting
        only; nothing in production code ever calls .submit() on it (approval/
        rejection/execution all go through .save()), so on_update_after_submit /
        on_submit are unreachable via the real lifecycle -- see backlog-dead-code.md.
        Every real status transition therefore happens via plain save(), which is
        exactly what this test exercises."""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test workflow",
                "request_date": today(),
            }
        )
        termination_request.insert()
        entries_before = len(termination_request.audit_trail)

        statuses = ["Pending", "Approved", "Rejected"]
        for status in statuses:
            termination_request.status = status
            termination_request.save()
            termination_request.reload()
            self.assertEqual(termination_request.status, status)

        self.assertEqual(len(termination_request.audit_trail), entries_before + len(statuses))
        last_entry = termination_request.audit_trail[-1]
        self.assertEqual(last_entry.action, "Document Updated")
        self.assertIn("Rejected", last_entry.details)

    def test_audit_trail_functionality(self):
        """add_audit_entry() appends a real row to the audit_trail child table
        with the action/details/user it was given, not just existing as a no-op."""
        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test audit trail",
                "request_date": today(),
            }
        )
        termination_request.insert()

        entries_before = len(termination_request.audit_trail)
        termination_request.add_audit_entry("Test Action", "Test details for audit")

        self.assertEqual(len(termination_request.audit_trail), entries_before + 1)
        new_entry = termination_request.audit_trail[-1]
        self.assertEqual(new_entry.action, "Test Action")
        self.assertEqual(new_entry.details, "Test details for audit")
        self.assertEqual(new_entry.user, frappe.session.user)
        self.assertEqual(new_entry.system_action, 0)

    def test_approval_requirements_validation(self):
        """set_approval_requirements() (run from validate()) flags disciplinary
        termination types as needing secondary approval; ordinary ones don't."""
        voluntary_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test approval requirements",
                "request_date": today(),
            }
        )
        voluntary_request.insert()
        self.assertEqual(voluntary_request.requires_secondary_approval, 0)

        disciplinary_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Disciplinary Action",
                "termination_reason": "Test approval requirements",
                "request_date": today(),
                "disciplinary_documentation": "Evidence attached",
            }
        )
        disciplinary_request.insert()
        self.assertEqual(disciplinary_request.requires_secondary_approval, 1)

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
        termination_request.insert()
        self.assertEqual(termination_request.request_date, add_days(today(), 30))

    @patch("verenigingen.permissions.can_terminate_member")
    def test_permission_denied_for_member_blocks_creation(self, mock_can_terminate):
        """validate_permissions() rejects the request when the user isn't allowed
        to terminate this specific member (a genuine permission-denial path)."""
        mock_can_terminate.return_value = False

        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test permissions",
                "request_date": today(),
            }
        )

        with self.assertRaises(frappe.ValidationError) as ctx:
            termination_request.insert()
        self.assertIn("permission", str(ctx.exception).lower())

    @patch("verenigingen.services.termination.termination_integration.cancel_membership_safe")
    @patch("verenigingen.services.termination.termination_integration.deactivate_user_account_safe")
    def test_termination_execution_workflow(self, mock_deactivate_user, mock_cancel_membership):
        """execute_termination_internal() runs the real declarative system-update
        pipeline: it must start from status "Approved" (TerminationExecutionService
        rejects any other status) and, on success, flips status to "Executed" and
        records who/when. The two safe-integration boundary functions are mocked
        (they belong to CancelMembershipsOperation / DeactivateUserAccountOperation
        inside the pipeline, imported from services.termination.termination_integration
        -- NOT the deprecated verenigingen.utils.termination_integration shim, which
        the old version of this test patched and which the pipeline never imports
        from); every other effect (status flip, tracking fields) is real."""
        mock_cancel_membership.return_value = True
        mock_deactivate_user.return_value = True

        # Submit the setUp membership so CancelMembershipsOperation's active-membership
        # query (status in Active/Pending, docstatus=1) actually finds it.
        self.test_membership.submit()

        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test execution workflow",
                "request_date": today(),
                "status": "Approved",
            }
        )
        termination_request.insert()

        result = termination_request.execute_termination_internal()

        self.assertTrue(result)
        mock_cancel_membership.assert_called_once()
        mock_deactivate_user.assert_called_once()

        termination_request.reload()
        self.assertEqual(termination_request.status, "Executed")
        self.assertEqual(termination_request.executed_by, frappe.session.user)
        self.assertIsNotNone(termination_request.execution_date)
        # _update_tracking() writes real counters from the pipeline's results dict;
        # SEPA/board operations are disabled (cancel_sepa_mandates/end_board_positions
        # default falsy) and the member has no outstanding invoices, so these stay 0.
        self.assertEqual(termination_request.sepa_mandates_cancelled, 0)
        self.assertEqual(termination_request.positions_ended, 0)
        self.assertEqual(termination_request.outstanding_invoices_cancelled, 0)

    def test_different_termination_types(self):
        """Test different termination types"""
        termination_types = ["Voluntary", "Non-payment", "Deceased", "Policy Violation"]

        for term_type in termination_types:
            if frappe.db.exists(
                "Membership Termination Request",
                {"member": self.test_member.name, "termination_type": term_type},
            ):
                continue

            request_data = {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": term_type,
                "termination_reason": f"Test {term_type} termination",
                "request_date": today(),
            }

            # Disciplinary terminations require documentation
            if term_type in ["Policy Violation", "Disciplinary Action", "Expulsion"]:
                request_data["disciplinary_documentation"] = f"Documented evidence for {term_type}"

            termination_request = frappe.get_doc(request_data)

            # Should be able to create with different types
            termination_request.insert()
            self.assertEqual(termination_request.termination_type, term_type)

    @patch("verenigingen.services.termination.TerminationExecutionService")
    def test_execute_system_updates_safely_delegates_to_service(self, mock_service_cls):
        """execute_system_updates_safely() must delegate to
        TerminationExecutionService.execute_system_updates(self) rather than
        reimplementing (or silently dropping) the update logic inline."""
        mock_instance = mock_service_cls.return_value
        mock_instance.execute_system_updates.return_value = {"success": True, "actions_taken": []}

        termination_request = frappe.get_doc(
            {
                "doctype": "Membership Termination Request",
                "member": self.test_member.name,
                "termination_type": "Voluntary",
                "termination_reason": "Test delegation",
                "request_date": today(),
            }
        )
        termination_request.insert()

        result = termination_request.execute_system_updates_safely()

        mock_instance.execute_system_updates.assert_called_once_with(termination_request)
        self.assertEqual(result, {"success": True, "actions_taken": []})

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
            termination_request.insert()

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
        termination_request1.insert()

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
        termination_request2.insert()

        # Verify both requests exist
        self.assertNotEqual(termination_request1.name, termination_request2.name)


if __name__ == "__main__":
    unittest.main()
