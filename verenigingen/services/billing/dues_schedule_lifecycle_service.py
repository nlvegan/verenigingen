# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
DuesScheduleLifecycleService - Lifecycle management for Membership Dues Schedule.

This service handles schedule lifecycle operations including:
- Pausing schedules (with reason tracking)
- Resuming schedules (with optional date adjustment)
- Status transition validation

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatelessService base class for consistent logging and error handling
- Status transition validation with allowed transition rules
"""

from typing import TYPE_CHECKING, Optional

import frappe
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class DuesScheduleLifecycleService(StatelessService):
    """
    Service for managing the lifecycle of Membership Dues Schedule documents.

    Handles status transitions, pause/resume operations, and lifecycle validation.

    Example:
        service = get_dues_schedule_lifecycle_service()
        service.pause_schedule(schedule_doc, reason="Member requested pause")
        service.resume_schedule(schedule_doc, new_next_date="2025-02-01")
    """

    # Define allowed status transitions
    ALLOWED_TRANSITIONS = {
        "Active": ["Paused", "Cancelled"],
        "Paused": ["Active", "Cancelled"],
        "Cancelled": [],  # No transitions from cancelled
        "Test": ["Active", "Cancelled"],
    }

    def __init__(self):
        super().__init__(service_name="DuesScheduleLifecycleService")

    def pause_schedule(self, schedule_doc: "Document", reason: Optional[str] = None) -> None:
        """
        Pause a dues schedule.

        Updates the schedule status to 'Paused' and optionally records
        a reason in the notes field.

        Args:
            schedule_doc: The Membership Dues Schedule document to pause
            reason: Optional reason for pausing (recorded in notes)

        Raises:
            frappe.ValidationError: If schedule cannot be paused (invalid transition)
        """
        # Validate transition
        if schedule_doc.status not in ["Active", "Test"]:
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(
                f"Cannot pause schedule with status '{schedule_doc.status}'. "
                f"Only Active or Test schedules can be paused."
            )

        schedule_doc.status = "Paused"

        if reason:
            schedule_doc.notes = (
                f"{schedule_doc.notes}\n\nPaused on {today()}: {reason}"
                if schedule_doc.notes
                else f"Paused on {today()}: {reason}"
            )

        # Skip membership validation when pausing (allows cancellation workflow)
        schedule_doc._skip_membership_validation = True
        schedule_doc.save()

        self.logger.info(f"Schedule {schedule_doc.name} paused. Reason: {reason or 'Not specified'}")

    def resume_schedule(self, schedule_doc: "Document", new_next_date: Optional[str] = None) -> None:
        """
        Resume a paused dues schedule.

        Updates the schedule status to 'Active' and optionally sets
        a new next invoice date.

        Args:
            schedule_doc: The Membership Dues Schedule document to resume
            new_next_date: Optional new date for the next invoice

        Raises:
            frappe.ValidationError: If schedule cannot be resumed (invalid transition)
        """
        if schedule_doc.status != "Paused":
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(
                f"Cannot resume schedule with status '{schedule_doc.status}'. "
                f"Only Paused schedules can be resumed."
            )

        schedule_doc.status = "Active"

        if new_next_date:
            schedule_doc.next_invoice_date = new_next_date

        schedule_doc.notes = (
            f"{schedule_doc.notes}\n\nResumed on {today()}" if schedule_doc.notes else f"Resumed on {today()}"
        )

        schedule_doc.save()

        self.logger.info(
            f"Schedule {schedule_doc.name} resumed. " f"Next invoice date: {schedule_doc.next_invoice_date}"
        )

    def validate_status_transition(self, schedule_doc: "Document") -> None:
        """
        Validate that a status transition is allowed.

        Called during document validation to ensure only valid status
        transitions are permitted.

        Args:
            schedule_doc: The schedule document being validated

        Raises:
            InvalidStatusTransitionError: If the status transition is not allowed
        """
        if schedule_doc.is_new():
            return

        if not hasattr(schedule_doc, "_doc_before_save") or schedule_doc._doc_before_save is None:
            return

        old_status = schedule_doc._doc_before_save.status
        new_status = schedule_doc.status

        if old_status == new_status:
            return

        allowed = self.ALLOWED_TRANSITIONS.get(old_status, [])
        if new_status not in allowed:
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(
                f"Cannot transition dues schedule status from {old_status} to {new_status}. "
                f"Allowed transitions from {old_status}: {', '.join(allowed) if allowed else 'None'}"
            )

    def cancel_schedule(self, schedule_doc: "Document", reason: Optional[str] = None) -> None:
        """
        Cancel a dues schedule.

        Updates the schedule status to 'Cancelled'. This is a terminal state
        with no further transitions allowed.

        Args:
            schedule_doc: The Membership Dues Schedule document to cancel
            reason: Optional reason for cancellation (recorded in notes)

        Raises:
            frappe.ValidationError: If schedule cannot be cancelled
        """
        if schedule_doc.status == "Cancelled":
            self.logger.info(f"Schedule {schedule_doc.name} is already cancelled")
            return

        allowed_from = ["Active", "Paused", "Test"]
        if schedule_doc.status not in allowed_from:
            from verenigingen.utils.exceptions import InvalidStatusTransitionError

            raise InvalidStatusTransitionError(f"Cannot cancel schedule with status '{schedule_doc.status}'.")

        schedule_doc.status = "Cancelled"

        if reason:
            schedule_doc.notes = (
                f"{schedule_doc.notes}\n\nCancelled on {today()}: {reason}"
                if schedule_doc.notes
                else f"Cancelled on {today()}: {reason}"
            )

        schedule_doc._skip_membership_validation = True
        schedule_doc.save()

        self.logger.info(f"Schedule {schedule_doc.name} cancelled. Reason: {reason or 'Not specified'}")


def get_dues_schedule_lifecycle_service() -> DuesScheduleLifecycleService:
    """Get singleton instance of DuesScheduleLifecycleService."""
    return DuesScheduleLifecycleService()
