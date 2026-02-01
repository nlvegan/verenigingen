"""
SEPA Batch Approval Service

Implements the two-person (four-eyes) approval workflow for Direct Debit Batches.
This service ensures that:
1. The person who creates/submits a batch cannot approve it (four-eyes principle)
2. Only users with the Accounts Manager role can approve batches
3. Approval metadata (who approved, when) is recorded for audit trail
4. Rejection returns the batch to Draft state for corrections

This is a standard financial control mechanism to prevent fraud and errors.

State Machine Integration:
    This service uses the SEPABatchStateMachine to validate and execute state transitions.
    - Approval: Pending Approval -> Approved
    - Rejection: Pending Approval -> Draft

Usage:
    from verenigingen.services.payment.sepa_batch_approval_service import (
        get_sepa_batch_approval_service,
        ApprovalCheckResult,
    )

    service = get_sepa_batch_approval_service()

    # Check if approval is allowed
    check = service.can_approve(
        batch_name="BATCH-25-01-0001",
        submitted_by="creator@example.com",
        approver="manager@example.com"
    )
    if check.allowed:
        result = service.approve_batch("BATCH-25-01-0001", "manager@example.com")

Author: Verenigingen Development Team
"""

from dataclasses import dataclass
from typing import Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.payment.sepa_batch_state_machine import get_sepa_batch_state_machine
from verenigingen.utils.operation_result import OperationResult


@dataclass
class ApprovalCheckResult:
    """
    Result of an approval eligibility check.

    Attributes:
        allowed: True if the approval is permitted
        reason: Human-readable explanation (especially when not allowed)
    """

    allowed: bool
    reason: str = ""


class SEPABatchApprovalService(StatelessService):
    """
    Service for managing two-person approval workflow for SEPA batches.

    This service enforces the four-eyes principle and role-based access control
    for batch approvals, which is a standard financial control mechanism.

    Attributes:
        APPROVAL_ROLE: The role required to approve batches
    """

    APPROVAL_ROLE = "Accounts Manager"

    def __init__(self):
        """Initialize the SEPABatchApprovalService."""
        super().__init__(service_name="SEPABatchApprovalService")
        self._state_machine = get_sepa_batch_state_machine()

    def can_approve(
        self,
        batch_name: str,
        submitted_by: str,
        approver: str,
    ) -> ApprovalCheckResult:
        """
        Check if an approver can approve a batch.

        This method validates:
        1. Four-eyes rule: submitted_by != approver
        2. Role requirement: approver must have APPROVAL_ROLE

        Args:
            batch_name: Name of the batch (used for logging, not validation)
            submitted_by: User who submitted the batch for approval
            approver: User attempting to approve

        Returns:
            ApprovalCheckResult indicating whether approval is allowed
        """
        # Rule 1: Four-eyes principle - creator cannot approve their own batch
        if submitted_by == approver:
            return ApprovalCheckResult(
                allowed=False,
                reason=_("Creator cannot approve their own batch (four-eyes principle)"),
            )

        # Rule 2: Approver must have the required role
        if not self._user_has_approval_role(approver):
            return ApprovalCheckResult(
                allowed=False,
                reason=_("Approver must have the {0} role").format(self.APPROVAL_ROLE),
            )

        return ApprovalCheckResult(
            allowed=True,
            reason=_("Approval allowed"),
        )

    def _user_has_approval_role(self, user: str) -> bool:
        """
        Check if a user has the approval role.

        Args:
            user: User ID to check

        Returns:
            True if user has the APPROVAL_ROLE
        """
        user_roles = frappe.get_roles(user)
        return self.APPROVAL_ROLE in user_roles

    def _get_batch_info(self, batch_name: str) -> Optional[dict]:
        """
        Get batch status and owner information.

        Args:
            batch_name: Name of the batch

        Returns:
            Dictionary with status and owner, or None if batch not found
        """
        result = frappe.get_value(
            "Direct Debit Batch",
            batch_name,
            ["status", "owner"],
            as_dict=True,
        )
        return result

    def approve_batch(
        self,
        batch_name: str,
        approver: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> OperationResult[str]:
        """
        Approve a batch after validating approval eligibility.

        This method:
        1. Validates the batch is in "Pending Approval" state
        2. Checks the four-eyes rule and role requirements
        3. Uses the state machine to transition to "Approved"
        4. Records approved_by and approved_on fields

        Args:
            batch_name: Name of the batch to approve
            approver: User approving the batch (defaults to current user)
            comment: Optional comment for the audit trail

        Returns:
            OperationResult with batch name on success, error message on failure
        """
        # Default to current user if approver not specified
        approver = approver or frappe.session.user

        # Get batch info
        batch_info = self._get_batch_info(batch_name)
        if not batch_info:
            return OperationResult.fail(
                _("Batch {0} not found").format(batch_name),
                error_code="BATCH_NOT_FOUND",
                http_status=404,
            )

        # Validate batch is in correct state
        if batch_info.get("status") != "Pending Approval":
            return OperationResult.fail(
                _("Batch must be in 'Pending Approval' state to approve. Current state: {0}").format(
                    batch_info.get("status")
                ),
                error_code="INVALID_STATE",
                http_status=400,
            )

        # Get the submitter (owner of the batch)
        submitted_by = batch_info.get("owner")

        # Validate approval eligibility
        check_result = self.can_approve(batch_name, submitted_by, approver)
        if not check_result.allowed:
            return OperationResult.fail(
                check_result.reason,
                error_code="APPROVAL_DENIED",
                http_status=403,
            )

        # Use state machine to transition
        transition_result = self._state_machine.execute_transition(
            batch_name=batch_name,
            to_state="Approved",
            user=approver,
            comment=comment,
        )

        if not transition_result.allowed:
            return OperationResult.fail(
                transition_result.reason,
                error_code="TRANSITION_FAILED",
                http_status=400,
            )

        # Record approval metadata with explicit transaction control
        frappe.db.begin()
        try:
            # Capture timestamp once and reuse
            approval_time = now_datetime()

            # Record approval metadata in a single operation
            frappe.db.set_value(
                "Direct Debit Batch",
                batch_name,
                {
                    "approved_by": approver,
                    "approved_on": approval_time,
                },
                update_modified=True,
            )

            frappe.db.commit()

            self.logger.info(f"Batch {batch_name} approved by {approver}")

            return OperationResult.ok(
                batch_name,
                approved_by=approver,
                approved_on=approval_time,
            )

        except Exception as e:
            frappe.db.rollback()
            self.logger.error(f"Failed to record approval metadata for {batch_name}: {e}")
            return OperationResult.from_exception(
                e,
                message=_("Failed to record approval: {0}").format(str(e)),
                error_code="APPROVAL_RECORD_FAILED",
            )

    def reject_batch(
        self,
        batch_name: str,
        rejector: Optional[str] = None,
        reason: str = "",
    ) -> OperationResult[str]:
        """
        Reject a batch and return it to Draft state.

        This method:
        1. Validates the batch is in "Pending Approval" state
        2. Validates a reason is provided
        3. Uses the state machine to transition to "Draft"
        4. Adds a rejection comment for audit trail

        Args:
            batch_name: Name of the batch to reject
            rejector: User rejecting the batch (defaults to current user)
            reason: Required reason for rejection

        Returns:
            OperationResult with batch name on success, error message on failure
        """
        # Default to current user if rejector not specified
        rejector = rejector or frappe.session.user

        # Validate reason is provided
        if not reason or not reason.strip():
            return OperationResult.fail(
                _("Rejection reason is required"),
                error_code="REASON_REQUIRED",
                http_status=400,
            )

        # Get batch info
        batch_info = self._get_batch_info(batch_name)
        if not batch_info:
            return OperationResult.fail(
                _("Batch {0} not found").format(batch_name),
                error_code="BATCH_NOT_FOUND",
                http_status=404,
            )

        # Validate batch is in correct state
        if batch_info.get("status") != "Pending Approval":
            return OperationResult.fail(
                _("Batch must be in 'Pending Approval' state to reject. Current state: {0}").format(
                    batch_info.get("status")
                ),
                error_code="INVALID_STATE",
                http_status=400,
            )

        # Use state machine to transition back to Draft
        rejection_comment = _("Rejected by {0}: {1}").format(rejector, reason)
        transition_result = self._state_machine.execute_transition(
            batch_name=batch_name,
            to_state="Draft",
            user=rejector,
            comment=rejection_comment,
        )

        if not transition_result.allowed:
            return OperationResult.fail(
                transition_result.reason,
                error_code="TRANSITION_FAILED",
                http_status=400,
            )

        # Add rejection comment to batch
        try:
            batch_doc = frappe.get_doc("Direct Debit Batch", batch_name)
            batch_doc.add_comment("Info", rejection_comment)

            self.logger.info(f"Batch {batch_name} rejected by {rejector}: {reason}")

            return OperationResult.ok(
                batch_name,
                rejected_by=rejector,
                reason=reason,
            )

        except Exception as e:
            self.logger.error(f"Failed to add rejection comment for {batch_name}: {e}")
            return OperationResult.from_exception(
                e,
                message=_("Failed to record rejection: {0}").format(str(e)),
                error_code="REJECTION_RECORD_FAILED",
            )


# Module-level singleton instance
_sepa_batch_approval_service_instance: Optional[SEPABatchApprovalService] = None


def get_sepa_batch_approval_service() -> SEPABatchApprovalService:
    """
    Get the SEPABatchApprovalService instance.

    Returns a singleton instance for efficiency.

    Returns:
        SEPABatchApprovalService instance
    """
    global _sepa_batch_approval_service_instance
    if _sepa_batch_approval_service_instance is None:
        _sepa_batch_approval_service_instance = SEPABatchApprovalService()
    return _sepa_batch_approval_service_instance


__all__ = [
    "SEPABatchApprovalService",
    "ApprovalCheckResult",
    "get_sepa_batch_approval_service",
]
