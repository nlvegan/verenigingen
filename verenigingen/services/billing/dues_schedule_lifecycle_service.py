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

    # Define allowed status transitions.
    # Grace Period / Suspended are the SEPA payment-failure dunning states
    # (sepa_batch_processor.handle_failed_payment): Active -> Grace Period on a
    # failed collection, Grace Period -> Suspended after repeated failures, and
    # either can recover to Active or be Cancelled.
    ALLOWED_TRANSITIONS = {
        # "Payment Plan Active" pauses regular billing while a Payment Plan covers
        # the dues (see PaymentPlan.update_dues_schedule_for_payment_plan); it
        # returns to Active (or is Cancelled) when the plan ends.
        "Active": ["Paused", "Cancelled", "Grace Period", "Suspended", "Payment Plan Active"],
        "Paused": ["Active", "Cancelled"],
        "Cancelled": [],  # No transitions from cancelled
        "Test": ["Active", "Cancelled"],
        "Grace Period": ["Active", "Suspended", "Cancelled"],
        "Suspended": ["Active", "Cancelled"],
        "Payment Plan Active": ["Active", "Cancelled"],
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

    def reactivate_for_rejoin(self, schedule_doc: "Document", membership_name: str, start_date) -> None:
        """
        Reuse a schedule that a voluntary termination cancelled for the member's new membership.

        Cancelled is otherwise terminal, so this is the one sanctioned way out of it: it sets
        the flag that lets the caller's save() pass validate_status_transition. The caller must
        already have applied the new template/amount (the next invoice date depends on the
        frequency) and must save the document.

        The months between the old membership and the rejoin are never billed: the coverage
        anchor makes the coverage sequence restart on ``start_date`` (see
        CoverageCalculator.get_latest_coverage_end_date), and the tracking fields describing the
        OLD membership's last invoice are cleared so nothing reads them as this one's.

        Args:
            schedule_doc: The Cancelled Membership Dues Schedule (not saved here)
            membership_name: The new Membership the schedule now belongs to
            start_date: The new membership's start date
        """
        schedule_doc.flags.rejoin_reactivation = True
        schedule_doc.status = "Active"
        schedule_doc.membership = membership_name
        schedule_doc.end_date = None
        schedule_doc.coverage_anchor_date = start_date
        schedule_doc.last_invoice_date = None
        schedule_doc.last_generated_invoice = None
        schedule_doc.last_invoice_coverage_start = None
        schedule_doc.last_invoice_coverage_end = None
        schedule_doc.next_invoice_date = schedule_doc.calculate_next_invoice_date(from_date=start_date)

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

        if (
            old_status == "Cancelled"
            and new_status == "Active"
            and schedule_doc.flags.get("rejoin_reactivation")
        ):
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
