# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
FeeChangeTrackingService - Schedule-based fee change detection and member dues sync.

This service detects fee changes from dues schedule updates and:
1. Delegates recording to FeeChangeRecordingService (single source of truth)
2. Updates member dues_rate field to stay in sync with schedule

IMPORTANT: This service no longer records fee changes directly. All recording
goes through FeeChangeRecordingService which handles smart deduplication.
This eliminates duplicate entries when both amendment service and schedule
hooks trigger for the same change.

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.
"""

from typing import TYPE_CHECKING

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class FeeChangeTrackingService(StatelessService):
    """
    Service for detecting fee changes from dues schedules and syncing member dues_rate.

    This service:
    - Detects changes in schedule dues_rate, status, billing_frequency
    - Delegates fee change recording to FeeChangeRecordingService
    - Updates member dues_rate to match schedule

    Example:
        service = get_fee_change_tracking_service()
        service.handle_schedule_update(schedule_doc)
        service.update_member_dues_rate(schedule_doc)
    """

    def __init__(self):
        super().__init__(service_name="FeeChangeTrackingService")

    def update_member_dues_rate(self, schedule_doc: "Document") -> None:
        """
        Update the member's dues_rate field to match the schedule.

        Uses secure operations with explicit permission validation.

        Args:
            schedule_doc: The dues schedule document with the new rate
        """
        if not schedule_doc.member:
            return

        try:
            member_doc = frappe.get_doc("Member", schedule_doc.member)

            if member_doc.dues_rate == schedule_doc.dues_rate:
                return  # No change needed

            member_doc.dues_rate = schedule_doc.dues_rate

            # Use secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            result = secure_document_operation(
                operation="save",
                doc=member_doc,
                justification=f"Update member dues rate from schedule {schedule_doc.name}",
                required_permissions=["Member:write"],
            )

            if not result.success:
                self.logger.error(f"Failed to update member dues rate: {'; '.join(result.errors)}")
            else:
                self.logger.info(
                    f"Updated member {schedule_doc.member} dues rate to {schedule_doc.dues_rate}"
                )

        except Exception as e:
            self.logger.error(f"Error updating member dues rate: {str(e)}")
            frappe.log_error(
                f"Error updating member dues rate: {str(e)}",
                "Member Dues Rate Update",
            )

    def handle_schedule_update(self, schedule_doc: "Document") -> None:
        """
        Handle fee tracking when a schedule is updated.

        Detects changes in dues rate, status, and billing frequency and
        delegates recording to FeeChangeRecordingService.

        Args:
            schedule_doc: The updated dues schedule document
        """
        if schedule_doc.is_template or not schedule_doc.member:
            return

        # Need old document for comparison
        if not hasattr(schedule_doc, "_doc_before_save") or schedule_doc._doc_before_save is None:
            return

        old_doc = schedule_doc._doc_before_save

        # Import the centralized recording service
        from verenigingen.services.member.financial.fee_change_recording_service import (
            get_fee_change_recording_service,
        )

        recording_service = get_fee_change_recording_service()

        # Determine reason based on context
        reason = (
            schedule_doc.custom_amount_reason
            if schedule_doc.uses_custom_amount
            else f"Schedule update - {schedule_doc.schedule_name or schedule_doc.name}"
        )

        # Check for dues rate change
        if old_doc.dues_rate != schedule_doc.dues_rate:
            recording_service.record(
                member=schedule_doc.member,
                old_amount=old_doc.dues_rate or 0,
                new_amount=schedule_doc.dues_rate,
                change_type="Fee Adjustment",
                reason=reason,
                dues_schedule=schedule_doc.name,
                billing_frequency=schedule_doc.billing_frequency,
            )
            self.update_member_dues_rate(schedule_doc)

        # Check for status change
        if old_doc.status != schedule_doc.status:
            if schedule_doc.status == "Cancelled":
                recording_service.record(
                    member=schedule_doc.member,
                    old_amount=schedule_doc.dues_rate,
                    new_amount=0,  # Cancelled means no more dues
                    change_type="Schedule Cancelled",
                    reason=f"Schedule {schedule_doc.name} cancelled",
                    dues_schedule=schedule_doc.name,
                )
            elif old_doc.status == "Paused" and schedule_doc.status == "Active":
                recording_service.record(
                    member=schedule_doc.member,
                    old_amount=0,  # Was paused (effectively 0)
                    new_amount=schedule_doc.dues_rate,
                    change_type="Schedule Resumed",
                    reason=f"Schedule {schedule_doc.name} resumed",
                    dues_schedule=schedule_doc.name,
                )

        # Billing frequency changes are informational, not actual fee changes
        # The recording service will skip them since old_amount == new_amount

    def handle_new_schedule(self, schedule_doc: "Document") -> None:
        """
        Handle fee tracking when a new schedule is created.

        Records the initial fee for the new schedule.

        Args:
            schedule_doc: The newly created dues schedule document
        """
        if schedule_doc.is_template or not schedule_doc.member:
            return

        from verenigingen.services.member.financial.fee_change_recording_service import (
            get_fee_change_recording_service,
        )

        reason = (
            schedule_doc.custom_amount_reason
            if schedule_doc.uses_custom_amount
            else f"New schedule - {schedule_doc.schedule_name or schedule_doc.name}"
        )

        get_fee_change_recording_service().record(
            member=schedule_doc.member,
            old_amount=0,
            new_amount=schedule_doc.dues_rate,
            change_type="New Schedule",
            reason=reason,
            dues_schedule=schedule_doc.name,
            billing_frequency=schedule_doc.billing_frequency,
        )
        self.update_member_dues_rate(schedule_doc)


def get_fee_change_tracking_service() -> FeeChangeTrackingService:
    """Get singleton instance of FeeChangeTrackingService."""
    return FeeChangeTrackingService()
