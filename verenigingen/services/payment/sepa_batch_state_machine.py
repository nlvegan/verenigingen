"""
SEPA Batch State Machine Service

Enforces valid status transitions for Direct Debit Batches. The state machine
prevents invalid workflow transitions and ensures audit trail integrity by
requiring appropriate roles for privileged transitions.

State Machine Overview:
    Draft -> Pending Approval -> Approved -> Exported -> Uploaded -> Acknowledged -> Processed
                      |                         |           |
                  (reject)                  Rejected    Rejected
                      v                         |
                    Draft                       v
                                          (retry from Draft)

    Cancelled (terminal - reachable from Draft, Pending Approval, Approved, Exported)

Valid Transitions:
    - Draft: Pending Approval, Cancelled
    - Pending Approval: Approved, Draft (rejection), Cancelled
    - Approved: Exported, Draft (corrections), Cancelled
    - Exported: Uploaded, Cancelled
    - Uploaded: Acknowledged, Rejected
    - Acknowledged: Processed, Rejected
    - Processed: (terminal - no transitions)
    - Rejected: Draft (retry)
    - Cancelled: (terminal - no transitions)

Role Requirements:
    - Pending Approval -> Approved: Accounts Manager
    - Approved -> Exported: Accounts User
    - Exported -> Uploaded: Accounts Manager

Usage:
    from verenigingen.services.payment.sepa_batch_state_machine import (
        get_sepa_batch_state_machine,
        TransitionResult,
    )

    machine = get_sepa_batch_state_machine()

    # Check if transition is allowed
    result = machine.can_transition("Draft", "Pending Approval", user=None)
    if result.allowed:
        print("Transition allowed")

    # Get list of valid next states
    next_states = machine.get_allowed_transitions("Draft")

    # Validate and execute transition on a specific batch
    result = machine.execute_transition(
        batch_name="BATCH-25-01-0001",
        to_state="Pending Approval",
        user="admin@example.com",
        comment="Submitting for first approval"
    )

Author: Verenigingen Development Team
"""

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService


@dataclass
class TransitionResult:
    """
    Result of a state transition check or execution.

    Attributes:
        allowed: True if the transition is permitted
        reason: Human-readable explanation (especially when not allowed)
        required_role: The role required for this transition (if applicable)
    """

    allowed: bool
    reason: str = ""
    required_role: Optional[str] = None


# Type aliases for clarity
State = str
StateSet = Set[State]


class SEPABatchStateMachine(StatelessService):
    """
    State machine for Direct Debit Batch workflow enforcement.

    This service validates and enforces status transitions for SEPA Direct Debit
    Batches, ensuring that:
    - Only valid transitions are allowed
    - Privileged transitions require appropriate roles
    - An audit trail is maintained for all state changes

    The state machine is designed to support a two-person approval workflow and
    integration with bank processing systems.
    """

    # Valid transitions: from_state -> {set of allowed to_states}
    TRANSITIONS: Dict[State, StateSet] = {
        "Draft": {"Pending Approval", "Cancelled"},
        "Pending Approval": {"Approved", "Draft", "Cancelled"},
        "Approved": {"Exported", "Draft", "Cancelled"},
        "Exported": {"Uploaded", "Cancelled"},
        "Uploaded": {"Acknowledged", "Rejected"},
        "Acknowledged": {"Processed", "Rejected"},
        "Processed": set(),  # Terminal state
        "Rejected": {"Draft"},  # Can retry
        "Cancelled": set(),  # Terminal state
    }

    # Role requirements for specific transitions: (from_state, to_state) -> required_role
    TRANSITION_ROLES: Dict[Tuple[State, State], str] = {
        ("Pending Approval", "Approved"): "Accounts Manager",
        ("Approved", "Exported"): "Accounts User",
        ("Exported", "Uploaded"): "Accounts Manager",
    }

    # All valid states for validation
    VALID_STATES: FrozenSet[State] = frozenset(TRANSITIONS.keys())

    # Terminal states (no outgoing transitions)
    TERMINAL_STATES: FrozenSet[State] = frozenset({"Processed", "Cancelled"})

    def __init__(self):
        """Initialize the SEPABatchStateMachine service."""
        super().__init__(service_name="SEPABatchStateMachine")

    def _is_valid_state(self, state: State) -> bool:
        """
        Check if a state is valid.

        Args:
            state: The state to validate

        Returns:
            True if the state is a valid state in the state machine
        """
        return state in self.VALID_STATES

    def _get_required_role(self, from_state: State, to_state: State) -> Optional[str]:
        """
        Get the required role for a transition.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            Role name if required, None otherwise
        """
        return self.TRANSITION_ROLES.get((from_state, to_state))

    def _user_has_role(self, user: str, role: str) -> bool:
        """
        Check if a user has the specified role.

        Args:
            user: User ID to check
            role: Role name to check for

        Returns:
            True if user has the role
        """
        user_roles = frappe.get_roles(user)
        return role in user_roles

    def can_transition(
        self, from_state: State, to_state: State, user: Optional[str] = None
    ) -> TransitionResult:
        """
        Check if a transition from one state to another is allowed.

        This method validates:
        1. Both states are valid states in the state machine
        2. The transition is defined in the TRANSITIONS map
        3. If a role is required, the user has that role

        Args:
            from_state: Current state of the batch
            to_state: Target state to transition to
            user: User attempting the transition (optional)

        Returns:
            TransitionResult indicating whether the transition is allowed
        """
        # Validate from_state
        if not self._is_valid_state(from_state):
            return TransitionResult(
                allowed=False,
                reason=_("Invalid current state: {0}").format(from_state),
            )

        # Validate to_state
        if not self._is_valid_state(to_state):
            return TransitionResult(
                allowed=False,
                reason=_("Invalid target state: {0}").format(to_state),
            )

        # Check if transition is defined
        allowed_states = self.TRANSITIONS.get(from_state, set())
        if to_state not in allowed_states:
            return TransitionResult(
                allowed=False,
                reason=_("Transition from {0} to {1} is not allowed").format(from_state, to_state),
            )

        # Check role requirement
        required_role = self._get_required_role(from_state, to_state)
        if required_role:
            if user is None:
                # No user specified, indicate the required role
                return TransitionResult(
                    allowed=False,
                    reason=_("This transition requires the {0} role").format(required_role),
                    required_role=required_role,
                )

            if not self._user_has_role(user, required_role):
                return TransitionResult(
                    allowed=False,
                    reason=_("User {0} lacks the required {1} role").format(user, required_role),
                    required_role=required_role,
                )

        # Transition is allowed
        return TransitionResult(
            allowed=True,
            reason=_("Transition from {0} to {1} is allowed").format(from_state, to_state),
        )

    def get_allowed_transitions(self, from_state: State) -> List[State]:
        """
        Get the list of states that can be transitioned to from the given state.

        Args:
            from_state: Current state

        Returns:
            List of valid target states (empty list for terminal states)
        """
        if not self._is_valid_state(from_state):
            self.logger.warning(f"get_allowed_transitions called with invalid state: {from_state}")
            return []

        return list(self.TRANSITIONS.get(from_state, set()))

    def validate_transition(
        self,
        batch_name: str,
        to_state: State,
        user: Optional[str] = None,
    ) -> TransitionResult:
        """
        Validate a transition for a specific batch document.

        This method looks up the current state of the batch and validates
        whether the requested transition is allowed.

        Args:
            batch_name: Name/ID of the Direct Debit Batch
            to_state: Target state to transition to
            user: User attempting the transition

        Returns:
            TransitionResult indicating whether the transition is allowed
        """
        # Get current state from database
        current_state = frappe.get_value(
            "Direct Debit Batch",
            batch_name,
            "status",
        )

        if current_state is None:
            return TransitionResult(
                allowed=False,
                reason=_("Batch {0} not found").format(batch_name),
            )

        return self.can_transition(current_state, to_state, user)

    def execute_transition(
        self,
        batch_name: str,
        to_state: State,
        user: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> TransitionResult:
        """
        Execute a state transition on a batch document.

        This method:
        1. Validates the transition is allowed
        2. Updates the batch status
        3. Adds a comment to the audit trail

        Args:
            batch_name: Name/ID of the Direct Debit Batch
            to_state: Target state to transition to
            user: User performing the transition
            comment: Optional comment for the audit trail

        Returns:
            TransitionResult indicating whether the transition succeeded
        """
        # First validate the transition
        validation_result = self.validate_transition(batch_name, to_state, user)
        if not validation_result.allowed:
            return validation_result

        try:
            # Get the batch document
            batch_doc = frappe.get_doc("Direct Debit Batch", batch_name)
            from_state = batch_doc.status

            # Update the status
            batch_doc.status = to_state
            batch_doc.save(ignore_permissions=True)

            # Add audit comment
            audit_comment = self._build_audit_comment(from_state, to_state, user, comment)
            batch_doc.add_comment("Info", audit_comment)

            self.logger.info(
                f"Batch {batch_name} transitioned from {from_state} to {to_state} " f"by {user or 'system'}"
            )

            return TransitionResult(
                allowed=True,
                reason=_("Batch {0} transitioned to {1}").format(batch_name, to_state),
            )

        except Exception as e:
            self.logger.error(f"Failed to execute transition for {batch_name}: {e}")
            return TransitionResult(
                allowed=False,
                reason=_("Failed to execute transition: {0}").format(str(e)),
            )

    def _build_audit_comment(
        self,
        from_state: State,
        to_state: State,
        user: Optional[str],
        comment: Optional[str],
    ) -> str:
        """
        Build an audit trail comment for a state transition.

        Args:
            from_state: Previous state
            to_state: New state
            user: User who performed the transition
            comment: User-provided comment

        Returns:
            Formatted audit comment string
        """
        parts = [
            _("Status changed from {0} to {1}").format(from_state, to_state),
        ]

        if user:
            parts.append(_("by {0}").format(user))

        if comment:
            parts.append(f"\n{comment}")

        return " ".join(parts)

    def is_terminal_state(self, state: State) -> bool:
        """
        Check if a state is a terminal state (no outgoing transitions).

        Args:
            state: State to check

        Returns:
            True if the state is terminal
        """
        return state in self.TERMINAL_STATES

    def get_all_states(self) -> List[State]:
        """
        Get all valid states in the state machine.

        Returns:
            List of all state names
        """
        return list(self.VALID_STATES)

    def get_path_to_processed(self, from_state: State) -> Optional[List[State]]:
        """
        Get the shortest path from a state to Processed (happy path).

        This is useful for showing users what steps remain in the workflow.

        Args:
            from_state: Starting state

        Returns:
            List of states from from_state to Processed (inclusive),
            or None if no path exists
        """
        if from_state == "Processed":
            return ["Processed"]

        if from_state in self.TERMINAL_STATES and from_state != "Processed":
            return None  # Cannot reach Processed from Cancelled

        # Define the happy path order
        happy_path = [
            "Draft",
            "Pending Approval",
            "Approved",
            "Exported",
            "Uploaded",
            "Acknowledged",
            "Processed",
        ]

        try:
            start_idx = happy_path.index(from_state)
            return happy_path[start_idx:]
        except ValueError:
            # State is Rejected, which can go to Draft
            if from_state == "Rejected":
                return ["Rejected", "Draft"] + happy_path
            return None


# Module-level singleton instance
_sepa_batch_state_machine_instance: Optional[SEPABatchStateMachine] = None


def get_sepa_batch_state_machine() -> SEPABatchStateMachine:
    """
    Get the SEPABatchStateMachine service instance.

    Returns a singleton instance for efficiency.

    Returns:
        SEPABatchStateMachine service instance
    """
    global _sepa_batch_state_machine_instance
    if _sepa_batch_state_machine_instance is None:
        _sepa_batch_state_machine_instance = SEPABatchStateMachine()
    return _sepa_batch_state_machine_instance


__all__ = [
    "SEPABatchStateMachine",
    "TransitionResult",
    "get_sepa_batch_state_machine",
]
