"""
Unit Tests for SEPABatchApprovalService

Tests the two-person (four-eyes) approval workflow for SEPA Direct Debit Batches.
This service ensures that the person who creates/submits a batch cannot approve it,
which is a standard financial control mechanism.

Test Strategy:
    - Test four-eyes rule enforcement (creator cannot approve)
    - Test role requirements for approval
    - Test approval records approver and timestamp
    - Test rejection workflow returns batch to Draft
    - Test validation of batch state before approval

Note: These tests mock service-internal methods (_get_batch_info, state machine)
rather than frappe.get_doc to comply with the testing guidelines that prohibit
mocking document retrieval operations directly.

Author: Verenigingen Development Team
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.sepa_batch_approval_service import (
    ApprovalCheckResult,
    SEPABatchApprovalService,
    get_sepa_batch_approval_service,
)


class TestApprovalCheckResult(FrappeTestCase):
    """Test the ApprovalCheckResult dataclass"""

    def test_allowed_result(self):
        """Test creating an allowed approval check result"""
        result = ApprovalCheckResult(allowed=True)

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "")

    def test_disallowed_result_with_reason(self):
        """Test creating a disallowed result with reason"""
        result = ApprovalCheckResult(
            allowed=False,
            reason="Creator cannot approve their own batch",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "Creator cannot approve their own batch")


class TestSEPABatchApprovalServiceFourEyesRule(FrappeTestCase):
    """Test the four-eyes rule: creator cannot approve their own batch"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.service = get_sepa_batch_approval_service()

    def test_creator_cannot_approve_own_batch(self):
        """
        Test that the person who submitted a batch cannot approve it.

        This is the core four-eyes principle.
        """
        submitted_by = "creator@example.com"
        approver = "creator@example.com"  # Same person

        result = self.service.can_approve(
            batch_name="BATCH-25-01-0001",
            submitted_by=submitted_by,
            approver=approver,
        )

        self.assertFalse(result.allowed)
        self.assertIn("cannot approve", result.reason.lower())

    @patch("frappe.get_roles")
    def test_different_person_can_approve(self, mock_get_roles):
        """
        Test that a different person with correct role can approve.

        This validates the happy path of four-eyes approval.
        """
        mock_get_roles.return_value = ["Accounts Manager", "System Manager"]

        submitted_by = "creator@example.com"
        approver = "manager@example.com"  # Different person

        result = self.service.can_approve(
            batch_name="BATCH-25-01-0001",
            submitted_by=submitted_by,
            approver=approver,
        )

        self.assertTrue(result.allowed)


class TestSEPABatchApprovalServiceRoleRequirements(FrappeTestCase):
    """Test role-based access control for approval"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.service = get_sepa_batch_approval_service()

    @patch("frappe.get_roles")
    def test_approval_requires_accounts_manager_role(self, mock_get_roles):
        """
        Test that approvers must have the Accounts Manager role.

        Even if it is a different person, they need the right role.
        """
        mock_get_roles.return_value = ["Accounts User", "Guest"]  # No Accounts Manager

        result = self.service.can_approve(
            batch_name="BATCH-25-01-0001",
            submitted_by="creator@example.com",
            approver="user@example.com",
        )

        self.assertFalse(result.allowed)
        self.assertIn("Accounts Manager", result.reason)

    @patch("frappe.get_roles")
    def test_approval_allowed_with_accounts_manager_role(self, mock_get_roles):
        """Test that Accounts Manager role allows approval"""
        mock_get_roles.return_value = ["Accounts Manager"]

        result = self.service.can_approve(
            batch_name="BATCH-25-01-0001",
            submitted_by="creator@example.com",
            approver="manager@example.com",
        )

        self.assertTrue(result.allowed)

    @patch("frappe.get_roles")
    def test_four_eyes_checked_before_role(self, mock_get_roles):
        """
        Test that four-eyes rule is checked even if user has correct role.

        Creator should not be able to approve even with Accounts Manager role.
        """
        mock_get_roles.return_value = ["Accounts Manager", "System Manager"]

        result = self.service.can_approve(
            batch_name="BATCH-25-01-0001",
            submitted_by="manager@example.com",
            approver="manager@example.com",  # Same person, but has role
        )

        self.assertFalse(result.allowed)
        self.assertIn("cannot approve", result.reason.lower())


class TestSEPABatchApprovalServiceApproveBatch(FrappeTestCase):
    """Test the approve_batch method

    These tests mock the service's internal _get_batch_info method and the
    state machine's execute_transition method to test validation logic
    without mocking frappe.get_doc directly.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.service = get_sepa_batch_approval_service()

    def test_approval_requires_pending_approval_state(self):
        """
        Test that only batches in 'Pending Approval' state can be approved.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = {
                "status": "Draft",  # Wrong state
                "owner": "creator@example.com",
            }

            result = self.service.approve_batch(
                batch_name="BATCH-25-01-0001",
                approver="manager@example.com",
            )

            self.assertFalse(result.success)
            self.assertIn("Pending Approval", result.error_message)

    def test_approval_fails_for_creator(self):
        """
        Test that creator cannot approve their own batch.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = {
                "status": "Pending Approval",
                "owner": "manager@example.com",  # Same as approver
            }

            with patch("frappe.get_roles") as mock_get_roles:
                mock_get_roles.return_value = ["Accounts Manager"]

                result = self.service.approve_batch(
                    batch_name="BATCH-25-01-0001",
                    approver="manager@example.com",  # Creator trying to approve
                )

                self.assertFalse(result.success)
                self.assertIn("cannot approve", result.error_message.lower())

    def test_approval_fails_for_batch_not_found(self):
        """
        Test that approval fails gracefully when batch is not found.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = None  # Batch not found

            result = self.service.approve_batch(
                batch_name="NONEXISTENT-BATCH",
                approver="manager@example.com",
            )

            self.assertFalse(result.success)
            self.assertIn("not found", result.error_message.lower())

    def test_approval_fails_without_accounts_manager_role(self):
        """
        Test that approval fails when approver lacks required role.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = {
                "status": "Pending Approval",
                "owner": "creator@example.com",
            }

            with patch("frappe.get_roles") as mock_get_roles:
                mock_get_roles.return_value = ["Accounts User"]  # Missing Accounts Manager

                result = self.service.approve_batch(
                    batch_name="BATCH-25-01-0001",
                    approver="user@example.com",
                )

                self.assertFalse(result.success)
                self.assertIn("Accounts Manager", result.error_message)


class TestSEPABatchApprovalServiceRejectBatch(FrappeTestCase):
    """Test the reject_batch method

    These tests mock the service's internal _get_batch_info method
    to test validation logic without mocking frappe.get_doc directly.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.service = get_sepa_batch_approval_service()

    def test_reject_requires_reason(self):
        """
        Test that rejection requires a reason.
        """
        # This validation happens before _get_batch_info is called
        result = self.service.reject_batch(
            batch_name="BATCH-25-01-0001",
            rejector="manager@example.com",
            reason="",  # Empty reason
        )

        self.assertFalse(result.success)
        self.assertIn("reason", result.error_message.lower())

    def test_reject_requires_pending_approval_state(self):
        """
        Test that only batches in 'Pending Approval' state can be rejected.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = {
                "status": "Approved",  # Wrong state
                "owner": "creator@example.com",
            }

            result = self.service.reject_batch(
                batch_name="BATCH-25-01-0001",
                rejector="manager@example.com",
                reason="Found issues",
            )

            self.assertFalse(result.success)
            self.assertIn("Pending Approval", result.error_message)

    def test_reject_fails_for_batch_not_found(self):
        """
        Test that rejection fails gracefully when batch is not found.
        """
        with patch.object(self.service, "_get_batch_info") as mock_info:
            mock_info.return_value = None  # Batch not found

            result = self.service.reject_batch(
                batch_name="NONEXISTENT-BATCH",
                rejector="manager@example.com",
                reason="Some reason",
            )

            self.assertFalse(result.success)
            self.assertIn("not found", result.error_message.lower())


class TestSEPABatchApprovalServiceFactory(FrappeTestCase):
    """Test the factory function"""

    def test_get_service_returns_instance(self):
        """Test that factory returns SEPABatchApprovalService instance"""
        service = get_sepa_batch_approval_service()
        self.assertIsInstance(service, SEPABatchApprovalService)

    def test_get_service_singleton(self):
        """Test that factory returns same instance (singleton)"""
        service1 = get_sepa_batch_approval_service()
        service2 = get_sepa_batch_approval_service()

        self.assertIs(service1, service2)


class TestSEPABatchApprovalServiceConstants(FrappeTestCase):
    """Test service constants"""

    def test_approval_role_constant(self):
        """Test that APPROVAL_ROLE is defined correctly"""
        service = get_sepa_batch_approval_service()

        self.assertEqual(service.APPROVAL_ROLE, "Accounts Manager")


if __name__ == "__main__":
    unittest.main()
