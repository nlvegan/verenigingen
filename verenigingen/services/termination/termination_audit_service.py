# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
TerminationAuditService - Membership termination audit trail management

This service handles audit trail management for membership terminations with:
- Centralized audit entry creation
- Status change tracking
- Document lifecycle event logging
- System action attribution
- User action tracking

Extracted from membership_termination_request.py:
- add_audit_entry() - Lines 236-254 (19 LOC)
- handle_status_change() - Lines 68-90 (23 LOC)
- before_save() audit call - Line 53
- after_insert() audit call - Line 56
Total extraction: ~50 LOC

QCE HIGH PRIORITY FIXES (2025-11-24):
- Issue #5: Added traceback module for full error context in logging
- Issue #6: Added logging for user validation fallbacks (security)

Architecture:
- Static methods for stateless operations
- Consistent audit entry format
- Proper user handling (system vs user actions)
- Integration with document audit trail child table
- Event-based logging for compliance

Dependencies:
- frappe.session.user for user attribution
- frappe.utils.now for timestamps
- Document.append() for audit trail child table
- traceback for error context preservation

Compliance:
- All termination actions logged with timestamps
- User attribution for all changes
- System actions clearly marked
- Status transitions tracked
- Execution events recorded
- Full error context preserved for debugging
"""

import traceback
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class TerminationAuditService(StatelessService):
    """
    Service for termination audit trail management.

    This service handles:
    - Creating audit trail entries with proper user attribution
    - Tracking status changes with old/new values
    - Logging document lifecycle events
    - Recording execution events (success/failure)
    - Distinguishing system vs user actions
    """

    def __init__(self):
        """Initialize the Termination Audit Service"""
        super().__init__(service_name="TerminationAuditService")

    # ========================================================================
    # PUBLIC AUDIT METHODS
    # ========================================================================

    def add_entry(self, doc: "Document", action: str, details: str, is_system: bool = False) -> None:
        """Add an entry to the audit trail with proper user handling.

        QCE HIGH PRIORITY FIX #6 (2025-11-24):
        Now logs security warning when user validation fails and falls back to Administrator.
        This prevents silent privilege escalation and audit trail corruption.

        This creates a new audit trail entry in the document's audit_trail
        child table. System actions use "Administrator" as the user, while
        user actions use the current session user.

        Args:
            doc: MembershipTerminationRequest document
            action: Action description (e.g., "Status Changed", "Execution Failed")
            details: Detailed description of the action
            is_system: True if system-initiated action, False if user-initiated

        Examples:
            >>> TerminationAuditService().add_entry(doc, "Status Changed", "Draft → Approved")
            >>> TerminationAuditService().add_entry(doc, "System Update", "SEPA mandate cancelled", is_system=True)
        """
        # Handle system entries properly - use Administrator instead of "System"
        audit_user = frappe.session.user if not is_system else "Administrator"

        # Ensure the user exists - LOG SECURITY WARNING if fallback needed
        if not frappe.db.exists("User", audit_user):
            self.logger.warning(
                f"SECURITY: Audit user '{audit_user}' does not exist - using Administrator fallback. "
                f"Document: {doc.name}, Action: {action}, Is System: {is_system}. "
                f"This may indicate corrupted session or deleted user account."
            )
            audit_user = "Administrator"

        doc.append(
            "audit_trail",
            {
                "timestamp": now(),
                "action": action,
                "user": audit_user,
                "details": details,
                "system_action": 1 if is_system else 0,
            },
        )

    def log_status_change(
        self, doc: "Document", old_status: Optional[str] = None, new_status: Optional[str] = None
    ) -> None:
        """Log a status change in the audit trail.

        This method is called when the termination request status changes.
        It logs the transition with both old and new status values, and
        handles special status transitions (Executed, Approved, Rejected).

        Args:
            doc: MembershipTerminationRequest document
            old_status: Previous status (None if not available)
            new_status: New status (uses doc.status if not provided)

        Examples:
            >>> TerminationAuditService().log_status_change(doc, "Draft", "Pending Approval")
            >>> TerminationAuditService().log_status_change(doc)  # Uses doc.status
        """
        # Get old status from saved doc if not provided
        if old_status is None:
            old_doc = doc.get_doc_before_save() if doc.get_doc_before_save() else None
            old_status = old_doc.status if old_doc else None

        # Get new status from parameter or document
        if new_status is None:
            new_status = doc.status

        # Log the status change
        self.logger.info(f"Termination request {doc.name} status changed from {old_status} to {new_status}")

        # Add audit trail entry
        self.add_entry(
            doc, "Status Changed", f"Status changed from {old_status} to {new_status}", is_system=True
        )

        # Handle specific status transitions
        if new_status == "Executed" and old_status != "Executed":
            self.logger.info(f"Executing termination for request {doc.name}")
            # Execution is triggered by workflow - actual execution logged separately

        elif new_status == "Approved":
            self._log_approved_transition(doc)

        elif new_status == "Rejected":
            self._log_rejected_transition(doc)

    def log_document_update(self, doc: "Document") -> None:
        """Log a document update (before_save event).

        Called during document save to track modifications.

        Args:
            doc: MembershipTerminationRequest document

        Examples:
            >>> TerminationAuditService().log_document_update(doc)
        """
        self.add_entry(doc, "Document Updated", f"Status: {doc.status}")

    def log_request_created(self, doc: "Document") -> None:
        """Log request creation (after_insert event).

        Called after a new termination request is created.

        Args:
            doc: MembershipTerminationRequest document

        Examples:
            >>> TerminationAuditService().log_request_created(doc)
        """
        self.add_entry(doc, "Request Created", f"Termination type: {doc.termination_type}")

    def log_execution_complete(self, doc: "Document", results: Dict[str, Any]) -> None:
        """Log successful execution completion.

        Called after termination execution completes successfully.

        Args:
            doc: MembershipTerminationRequest document
            results: Execution results from TerminationExecutor

        Examples:
            >>> results = {"actions_taken": ["Cancel membership", "Cancel SEPA"], "errors": []}
            >>> TerminationAuditService().log_execution_complete(doc, results)
        """
        actions_count = len(results.get("actions_taken", []))
        errors_count = len(results.get("errors", []))

        if errors_count > 0:
            details = f"System updates completed with {errors_count} warnings: {actions_count} actions"
        else:
            details = f"System updates completed: {actions_count} actions"

        self.add_entry(doc, "Termination Executed", details)

        # Log individual actions
        for action in results.get("actions_taken", []):
            self.add_entry(doc, "System Update", action, is_system=True)

        # Log errors
        for error in results.get("errors", []):
            self.add_entry(doc, "System Update Error", error, is_system=True)

    def log_execution_failed(self, doc: "Document", error: Exception) -> None:
        """Log execution failure with full error context.

        QCE HIGH PRIORITY FIX #5 (2025-11-24):
        Now captures full exception traceback for debugging production failures.
        Previously only logged error message, losing valuable stack trace context.

        Called when termination execution fails, before status is reverted.

        Args:
            doc: MembershipTerminationRequest document
            error: Exception that occurred

        Examples:
            >>> try:
            >>>     execute_termination()
            >>> except Exception as e:
            >>>     TerminationAuditService().log_execution_failed(doc, e)
        """
        error_msg = str(error)
        error_type = type(error).__name__
        error_trace = traceback.format_exc()

        # Log full error context to logger (includes stack trace)
        self.logger.error(
            f"Termination execution failed for {doc.name}:\n"
            f"Error Type: {error_type}\n"
            f"Error Message: {error_msg}\n"
            f"Stack Trace:\n{error_trace}"
        )

        # Add audit entry with error type and message (not full trace - too verbose for UI)
        self.add_entry(doc, "Execution Failed", f"Error Type: {error_type}\nMessage: {error_msg}")

    # ========================================================================
    # HELPER METHODS (Private)
    # ========================================================================

    def _log_approved_transition(self, doc: "Document") -> None:
        """Log additional details when request is approved.

        Args:
            doc: MembershipTerminationRequest document
        """
        approver = doc.approved_by or "Unknown"
        self.add_entry(doc, "Request Approved", f"Approved by: {approver}", is_system=False)

    def _log_rejected_transition(self, doc: "Document") -> None:
        """Log additional details when request is rejected.

        Args:
            doc: MembershipTerminationRequest document
        """
        rejector = doc.approved_by or "Unknown"  # Same field used for rejection
        reason = doc.approver_notes or "No reason provided"  # DocType has no rejection_reason field
        self.add_entry(doc, "Request Rejected", f"Rejected by: {rejector}. Reason: {reason}", is_system=False)


def get_termination_audit_service() -> TerminationAuditService:
    """Get instance of TerminationAuditService."""
    return TerminationAuditService()
