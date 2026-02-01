"""
Unit Tests for SEPABatchStateMachine Service

Tests the state machine that enforces valid status transitions for Direct Debit
Batches. The state machine prevents invalid workflow transitions and ensures
audit trail integrity.

State Machine Overview:
    Draft -> Pending Approval -> Approved -> Exported -> Uploaded -> Acknowledged -> Processed
                      |                         |           |
                  (reject)                  Rejected    Rejected
                      v                         |
                    Draft                       v
                                          (retry from Draft)

    Cancelled (terminal - reachable from Draft, Pending Approval, Approved, Exported)

Test Strategy:
    - Test valid transitions between states
    - Test invalid transitions are blocked
    - Test role requirements for privileged transitions
    - Test complete workflow from Draft to Processed
    - Test terminal states have no outgoing transitions

Author: Verenigingen Development Team
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.payment.sepa_batch_state_machine import (
    SEPABatchStateMachine,
    TransitionResult,
    get_sepa_batch_state_machine,
)


class TestTransitionResult(FrappeTestCase):
    """Test the TransitionResult dataclass"""

    def test_transition_result_allowed(self):
        """Test creating an allowed transition result"""
        result = TransitionResult(allowed=True)

        self.assertTrue(result.allowed)
        self.assertEqual(result.reason, "")
        self.assertIsNone(result.required_role)

    def test_transition_result_disallowed_with_reason(self):
        """Test creating a disallowed transition result with reason"""
        result = TransitionResult(
            allowed=False,
            reason="Cannot transition from Draft to Processed",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "Cannot transition from Draft to Processed")
        self.assertIsNone(result.required_role)

    def test_transition_result_with_required_role(self):
        """Test transition result indicating required role"""
        result = TransitionResult(
            allowed=False,
            reason="User lacks required role",
            required_role="Accounts Manager",
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.required_role, "Accounts Manager")


class TestSEPABatchStateMachineTransitions(FrappeTestCase):
    """Test valid and invalid state transitions"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    # ========== Valid Transition Tests ==========

    def test_valid_transition_draft_to_pending_approval(self):
        """
        Test that Draft -> Pending Approval is allowed.

        This is the first step in the approval workflow.
        """
        result = self.machine.can_transition("Draft", "Pending Approval", user=None)

        self.assertIsInstance(result, TransitionResult)
        self.assertTrue(result.allowed)

    def test_valid_transition_draft_to_cancelled(self):
        """Test that Draft -> Cancelled is allowed"""
        result = self.machine.can_transition("Draft", "Cancelled", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_pending_to_approved(self):
        """
        Test that Pending Approval -> Approved is allowed.

        Note: This transition requires Accounts Manager role.
        """
        result = self.machine.can_transition(
            "Pending Approval", "Approved", user=None
        )

        # Transition itself is valid, but may require role
        self.assertTrue(result.allowed or result.required_role == "Accounts Manager")

    def test_valid_transition_pending_to_draft(self):
        """
        Test that Pending Approval -> Draft is allowed (rejection).

        This allows a batch to be sent back for corrections.
        """
        result = self.machine.can_transition("Pending Approval", "Draft", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_pending_to_cancelled(self):
        """Test that Pending Approval -> Cancelled is allowed"""
        result = self.machine.can_transition(
            "Pending Approval", "Cancelled", user=None
        )

        self.assertTrue(result.allowed)

    def test_valid_transition_approved_to_exported(self):
        """Test that Approved -> Exported is a valid transition (requires Accounts User role)"""
        result = self.machine.can_transition("Approved", "Exported", user=None)

        # This transition requires Accounts User role
        # When no user is provided, it returns allowed=False with required_role set
        self.assertEqual(result.required_role, "Accounts User")
        # Verify it's in the valid transitions list
        self.assertIn("Exported", self.machine.get_allowed_transitions("Approved"))

    def test_valid_transition_approved_to_draft(self):
        """Test that Approved -> Draft is allowed (for corrections)"""
        result = self.machine.can_transition("Approved", "Draft", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_approved_to_cancelled(self):
        """Test that Approved -> Cancelled is allowed"""
        result = self.machine.can_transition("Approved", "Cancelled", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_exported_to_uploaded(self):
        """Test that Exported -> Uploaded is a valid transition (requires Accounts Manager role)"""
        result = self.machine.can_transition("Exported", "Uploaded", user=None)

        # This transition requires Accounts Manager role
        # When no user is provided, it returns allowed=False with required_role set
        self.assertEqual(result.required_role, "Accounts Manager")
        # Verify it's in the valid transitions list
        self.assertIn("Uploaded", self.machine.get_allowed_transitions("Exported"))

    def test_valid_transition_exported_to_cancelled(self):
        """Test that Exported -> Cancelled is allowed"""
        result = self.machine.can_transition("Exported", "Cancelled", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_uploaded_to_acknowledged(self):
        """Test that Uploaded -> Acknowledged is allowed"""
        result = self.machine.can_transition("Uploaded", "Acknowledged", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_uploaded_to_rejected(self):
        """Test that Uploaded -> Rejected is allowed (bank rejection)"""
        result = self.machine.can_transition("Uploaded", "Rejected", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_acknowledged_to_processed(self):
        """Test that Acknowledged -> Processed is allowed (final state)"""
        result = self.machine.can_transition("Acknowledged", "Processed", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_acknowledged_to_rejected(self):
        """Test that Acknowledged -> Rejected is allowed (late rejection)"""
        result = self.machine.can_transition("Acknowledged", "Rejected", user=None)

        self.assertTrue(result.allowed)

    def test_valid_transition_rejected_to_draft(self):
        """Test that Rejected -> Draft is allowed (retry)"""
        result = self.machine.can_transition("Rejected", "Draft", user=None)

        self.assertTrue(result.allowed)

    # ========== Invalid Transition Tests ==========

    def test_invalid_transition_draft_to_uploaded(self):
        """
        Test that Draft -> Uploaded is NOT allowed.

        Must go through approval workflow first.
        """
        result = self.machine.can_transition("Draft", "Uploaded", user=None)

        self.assertFalse(result.allowed)
        self.assertIn("Draft", result.reason)

    def test_invalid_transition_draft_to_processed(self):
        """Test that Draft -> Processed is NOT allowed"""
        result = self.machine.can_transition("Draft", "Processed", user=None)

        self.assertFalse(result.allowed)

    def test_invalid_transition_draft_to_acknowledged(self):
        """Test that Draft -> Acknowledged is NOT allowed"""
        result = self.machine.can_transition("Draft", "Acknowledged", user=None)

        self.assertFalse(result.allowed)

    def test_invalid_transition_uploaded_to_draft(self):
        """
        Test that Uploaded -> Draft is NOT allowed.

        Once uploaded to bank, cannot go back to draft.
        """
        result = self.machine.can_transition("Uploaded", "Draft", user=None)

        self.assertFalse(result.allowed)

    def test_invalid_transition_processed_to_any(self):
        """
        Test that Processed (terminal) cannot transition anywhere.

        Processed is a terminal state.
        """
        result = self.machine.can_transition("Processed", "Draft", user=None)
        self.assertFalse(result.allowed)

        result = self.machine.can_transition("Processed", "Cancelled", user=None)
        self.assertFalse(result.allowed)

    def test_invalid_transition_cancelled_to_any(self):
        """
        Test that Cancelled (terminal) cannot transition anywhere.

        Cancelled is a terminal state.
        """
        result = self.machine.can_transition("Cancelled", "Draft", user=None)
        self.assertFalse(result.allowed)

        result = self.machine.can_transition("Cancelled", "Pending Approval", user=None)
        self.assertFalse(result.allowed)

    def test_invalid_transition_exported_to_approved(self):
        """Test that Exported -> Approved is NOT allowed (no going back)"""
        result = self.machine.can_transition("Exported", "Approved", user=None)

        self.assertFalse(result.allowed)

    def test_invalid_transition_acknowledged_to_uploaded(self):
        """Test that Acknowledged -> Uploaded is NOT allowed (no going back)"""
        result = self.machine.can_transition("Acknowledged", "Uploaded", user=None)

        self.assertFalse(result.allowed)

    # ========== Terminal State Tests ==========

    def test_terminal_states_have_no_transitions(self):
        """
        Test that terminal states have no valid outgoing transitions.

        Terminal states: Processed, Cancelled
        """
        processed_transitions = self.machine.get_allowed_transitions("Processed")
        cancelled_transitions = self.machine.get_allowed_transitions("Cancelled")

        self.assertEqual(len(processed_transitions), 0)
        self.assertEqual(len(cancelled_transitions), 0)

    def test_processed_is_terminal(self):
        """Processed should have no outgoing transitions"""
        transitions = self.machine.get_allowed_transitions("Processed")
        self.assertEqual(transitions, [])

    def test_cancelled_is_terminal(self):
        """Cancelled should have no outgoing transitions"""
        transitions = self.machine.get_allowed_transitions("Cancelled")
        self.assertEqual(transitions, [])


class TestSEPABatchStateMachineRoleRequirements(FrappeTestCase):
    """Test role-based access control for transitions"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    def test_role_required_for_approval(self):
        """
        Test that Pending Approval -> Approved requires Accounts Manager role.

        This ensures only authorized personnel can approve batches.
        """
        # Test without user (should indicate required role)
        result = self.machine.can_transition(
            "Pending Approval", "Approved", user=None
        )

        # When user is None, the transition check should indicate the required role
        # if one exists for this transition
        if not result.allowed:
            self.assertEqual(result.required_role, "Accounts Manager")

    @patch("frappe.get_roles")
    def test_approval_allowed_with_accounts_manager_role(self, mock_get_roles):
        """Test that users with Accounts Manager role can approve"""
        mock_get_roles.return_value = ["Accounts Manager", "System Manager"]

        result = self.machine.can_transition(
            "Pending Approval", "Approved", user="test_manager@example.com"
        )

        self.assertTrue(result.allowed)

    @patch("frappe.get_roles")
    def test_approval_denied_without_accounts_manager_role(self, mock_get_roles):
        """Test that users without Accounts Manager role cannot approve"""
        mock_get_roles.return_value = ["Accounts User", "System Manager"]

        result = self.machine.can_transition(
            "Pending Approval", "Approved", user="test_user@example.com"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.required_role, "Accounts Manager")

    @patch("frappe.get_roles")
    def test_exported_to_uploaded_requires_accounts_manager(self, mock_get_roles):
        """Test that Exported -> Uploaded requires Accounts Manager"""
        mock_get_roles.return_value = ["Accounts User"]

        result = self.machine.can_transition(
            "Exported", "Uploaded", user="test_user@example.com"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.required_role, "Accounts Manager")

    @patch("frappe.get_roles")
    def test_approved_to_exported_requires_accounts_user(self, mock_get_roles):
        """Test that Approved -> Exported requires at least Accounts User"""
        mock_get_roles.return_value = ["Guest"]

        result = self.machine.can_transition(
            "Approved", "Exported", user="guest@example.com"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.required_role, "Accounts User")


class TestSEPABatchStateMachineGetAllowedTransitions(FrappeTestCase):
    """Test the get_allowed_transitions method"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    def test_get_allowed_transitions_from_draft(self):
        """Test getting allowed transitions from Draft state"""
        transitions = self.machine.get_allowed_transitions("Draft")

        self.assertIn("Pending Approval", transitions)
        self.assertIn("Cancelled", transitions)
        self.assertNotIn("Processed", transitions)
        self.assertNotIn("Uploaded", transitions)

    def test_get_allowed_transitions_from_pending_approval(self):
        """Test getting allowed transitions from Pending Approval state"""
        transitions = self.machine.get_allowed_transitions("Pending Approval")

        self.assertIn("Approved", transitions)
        self.assertIn("Draft", transitions)  # Rejection
        self.assertIn("Cancelled", transitions)

    def test_get_allowed_transitions_from_uploaded(self):
        """Test getting allowed transitions from Uploaded state"""
        transitions = self.machine.get_allowed_transitions("Uploaded")

        self.assertIn("Acknowledged", transitions)
        self.assertIn("Rejected", transitions)
        self.assertNotIn("Draft", transitions)  # Cannot go back after upload
        self.assertNotIn("Cancelled", transitions)

    def test_get_allowed_transitions_from_rejected(self):
        """Test getting allowed transitions from Rejected state"""
        transitions = self.machine.get_allowed_transitions("Rejected")

        self.assertIn("Draft", transitions)  # Can retry
        self.assertEqual(len(transitions), 1)


class TestSEPABatchStateMachineCompleteWorkflow(FrappeTestCase):
    """Test complete workflow scenarios"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    @patch("frappe.get_roles")
    def test_complete_workflow(self, mock_get_roles):
        """
        Test the complete happy path workflow from Draft to Processed.

        Draft -> Pending Approval -> Approved -> Exported ->
        Uploaded -> Acknowledged -> Processed
        """
        # Give the user all necessary roles
        mock_get_roles.return_value = ["Accounts Manager", "Accounts User"]

        # Step 1: Draft -> Pending Approval
        result = self.machine.can_transition(
            "Draft", "Pending Approval", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Draft->Pending failed: {result.reason}")

        # Step 2: Pending Approval -> Approved (requires Accounts Manager)
        result = self.machine.can_transition(
            "Pending Approval", "Approved", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Pending->Approved failed: {result.reason}")

        # Step 3: Approved -> Exported (requires Accounts User)
        result = self.machine.can_transition(
            "Approved", "Exported", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Approved->Exported failed: {result.reason}")

        # Step 4: Exported -> Uploaded (requires Accounts Manager)
        result = self.machine.can_transition(
            "Exported", "Uploaded", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Exported->Uploaded failed: {result.reason}")

        # Step 5: Uploaded -> Acknowledged
        result = self.machine.can_transition(
            "Uploaded", "Acknowledged", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Uploaded->Acknowledged failed: {result.reason}")

        # Step 6: Acknowledged -> Processed
        result = self.machine.can_transition(
            "Acknowledged", "Processed", user="admin@example.com"
        )
        self.assertTrue(result.allowed, f"Acknowledged->Processed failed: {result.reason}")

    def test_rejection_and_retry_workflow(self):
        """
        Test the rejection workflow.

        Draft -> Pending Approval -> Draft (rejected) -> Pending Approval
        """
        # Submit for approval
        result = self.machine.can_transition("Draft", "Pending Approval", user=None)
        self.assertTrue(result.allowed)

        # Reject back to Draft
        result = self.machine.can_transition("Pending Approval", "Draft", user=None)
        self.assertTrue(result.allowed)

        # Resubmit for approval
        result = self.machine.can_transition("Draft", "Pending Approval", user=None)
        self.assertTrue(result.allowed)

    def test_bank_rejection_and_retry_workflow(self):
        """
        Test the bank rejection workflow.

        ... -> Uploaded -> Rejected -> Draft (retry)
        """
        # Bank rejects
        result = self.machine.can_transition("Uploaded", "Rejected", user=None)
        self.assertTrue(result.allowed)

        # Retry from Draft
        result = self.machine.can_transition("Rejected", "Draft", user=None)
        self.assertTrue(result.allowed)

    def test_cancellation_workflow(self):
        """Test that batches can be cancelled at appropriate stages"""
        cancellable_states = ["Draft", "Pending Approval", "Approved", "Exported"]

        for state in cancellable_states:
            result = self.machine.can_transition(state, "Cancelled", user=None)
            self.assertTrue(
                result.allowed,
                f"{state} should be cancellable, but got: {result.reason}"
            )

        # Verify Uploaded, Acknowledged, Processed cannot be cancelled
        non_cancellable_states = ["Uploaded", "Acknowledged", "Processed", "Rejected"]

        for state in non_cancellable_states:
            result = self.machine.can_transition(state, "Cancelled", user=None)
            self.assertFalse(
                result.allowed,
                f"{state} should not be cancellable"
            )


class TestSEPABatchStateMachineFactory(FrappeTestCase):
    """Test the factory function"""

    def test_get_sepa_batch_state_machine_returns_instance(self):
        """Test that factory returns SEPABatchStateMachine instance"""
        machine = get_sepa_batch_state_machine()
        self.assertIsInstance(machine, SEPABatchStateMachine)

    def test_get_sepa_batch_state_machine_singleton(self):
        """Test that factory returns same instance (singleton)"""
        machine1 = get_sepa_batch_state_machine()
        machine2 = get_sepa_batch_state_machine()

        self.assertIs(machine1, machine2)


class TestSEPABatchStateMachineValidateTransition(FrappeTestCase):
    """Test validate_transition method that works with actual batch documents"""

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    @patch("frappe.get_value")
    def test_validate_transition_gets_current_state(self, mock_get_value):
        """Test that validate_transition looks up the current state from database"""
        mock_get_value.return_value = "Draft"

        result = self.machine.validate_transition(
            batch_name="BATCH-25-01-0001",
            to_state="Pending Approval",
            user=None
        )

        mock_get_value.assert_called_once()
        self.assertTrue(result.allowed)

    @patch("frappe.get_value")
    def test_validate_transition_batch_not_found(self, mock_get_value):
        """Test validation when batch does not exist"""
        mock_get_value.return_value = None

        result = self.machine.validate_transition(
            batch_name="NONEXISTENT-BATCH",
            to_state="Pending Approval",
            user=None
        )

        self.assertFalse(result.allowed)
        self.assertIn("not found", result.reason.lower())


class TestSEPABatchStateMachineExecuteTransition(FrappeTestCase):
    """Test execute_transition method that performs actual state changes

    Note: Tests for execute_transition that would require modifying documents
    are tested via validate_transition (which tests the validation logic).
    Integration tests with real documents should be added when testing the
    full workflow in test_sepa_batch_workflow.py.

    The execute_transition method:
    1. Calls validate_transition (tested via mocks in validate tests)
    2. Updates document status
    3. Adds audit comment

    We test the validation path here; document updates are tested in integration tests.
    """

    def setUp(self):
        """Set up test fixtures"""
        super().setUp()
        self.machine = get_sepa_batch_state_machine()

    @patch("frappe.get_value")
    def test_execute_transition_invalid(self, mock_get_value):
        """Test that invalid transitions are rejected before document retrieval"""
        mock_get_value.return_value = "Draft"

        result = self.machine.execute_transition(
            batch_name="BATCH-25-01-0001",
            to_state="Processed",  # Invalid from Draft
            user=None,
            comment=None
        )

        # The transition is blocked at validation, before get_doc is called
        self.assertFalse(result.allowed)
        self.assertIn("not allowed", result.reason.lower())

    @patch("frappe.get_value")
    @patch("frappe.get_roles")
    def test_execute_transition_missing_role(self, mock_get_roles, mock_get_value):
        """Test that transitions requiring roles are rejected before document retrieval"""
        mock_get_value.return_value = "Pending Approval"
        mock_get_roles.return_value = ["Guest"]

        result = self.machine.execute_transition(
            batch_name="BATCH-25-01-0001",
            to_state="Approved",  # Requires Accounts Manager
            user="guest@example.com",
            comment=None
        )

        # The transition is blocked at validation, before get_doc is called
        self.assertFalse(result.allowed)
        self.assertEqual(result.required_role, "Accounts Manager")

    @patch("frappe.get_value")
    def test_execute_transition_batch_not_found(self, mock_get_value):
        """Test that execute_transition handles missing batch gracefully"""
        mock_get_value.return_value = None

        result = self.machine.execute_transition(
            batch_name="NONEXISTENT-BATCH",
            to_state="Pending Approval",
            user=None,
            comment=None
        )

        self.assertFalse(result.allowed)
        self.assertIn("not found", result.reason.lower())
