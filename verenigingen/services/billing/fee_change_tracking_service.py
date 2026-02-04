# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
FeeChangeTrackingService - Fee change history management for dues schedules.

This service handles recording fee changes on member records including:
- Recording schedule fee changes
- Updating member dues rate
- Tracking change types (new schedule, fee adjustment, etc.)
- Amendment request linking

Extracted from membership_dues_schedule.py to reduce controller size
and improve testability.

Architecture:
- StatelessService base class for consistent logging and error handling
- Uses Member's record_fee_change() method for actual recording
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class FeeChangeTrackingService(StatelessService):
    """
    Service for tracking fee changes on membership dues schedules.

    Records fee changes to member's payment history and keeps member
    dues_rate field in sync with schedule.

    Example:
        service = get_fee_change_tracking_service()
        service.record_fee_change(schedule_doc, "Fee Adjustment", 10.0, 15.0)
        service.update_member_dues_rate(schedule_doc)
    """

    def __init__(self):
        super().__init__(service_name="FeeChangeTrackingService")

    def record_fee_change(
        self,
        schedule_doc: "Document",
        change_type: str,
        old_rate: float,
        new_rate: float,
    ) -> None:
        """
        Record a fee change using the centralized record_fee_change method.

        Creates a fee change record with deduplication on the member's
        payment history.

        Args:
            schedule_doc: The dues schedule document
            change_type: Type of change (e.g., "New Schedule", "Fee Adjustment")
            old_rate: Previous dues rate
            new_rate: New dues rate
        """
        if not schedule_doc.member:
            self.logger.warning(
                f"Cannot record fee change for schedule {schedule_doc.name}: no member assigned"
            )
            return

        try:
            member_doc = frappe.get_doc("Member", schedule_doc.member)

            # Determine reason based on context
            reason = (
                schedule_doc.custom_amount_reason
                if schedule_doc.uses_custom_amount
                else f"{change_type} - {schedule_doc.schedule_name or schedule_doc.name}"
            )

            # Check if this change is from an amendment
            amendment_request = self._get_amendment_request(schedule_doc.name)

            # Build change data in the format expected by record_fee_change
            change_data = {
                "change_date": frappe.utils.now_datetime(),
                "old_amount": old_rate or 0,
                "new_amount": new_rate,
                "reason": reason,
                "changed_by": frappe.session.user or "Administrator",
                "dues_schedule_name": schedule_doc.name,
                "dues_schedule_action": change_type.lower().replace(" ", "_"),
                "billing_frequency": schedule_doc.billing_frequency,
                "change_type": change_type,
            }

            # Add amendment reference if available
            if amendment_request:
                change_data["amendment_request_name"] = amendment_request

            # Use the centralized method with automatic deduplication
            member_doc.record_fee_change(change_data)

            self.logger.info(
                f"Recorded fee change for member {schedule_doc.member}: "
                f"{change_type} ({old_rate} -> {new_rate})"
            )

        except Exception as e:
            # Shorten error message to avoid database field length limits
            error_msg = f"Fee change recording error for {schedule_doc.name}: {str(e)[:80]}"
            self.logger.error(error_msg)
            frappe.log_error(error_msg, "Fee Change Recording")

    def _get_amendment_request(self, schedule_name: str) -> Optional[str]:
        """
        Get amendment request linked to this schedule.

        Args:
            schedule_name: Name of the dues schedule

        Returns:
            Amendment request name if found, None otherwise
        """
        if frappe.db.exists("Contribution Amendment Request", {"new_dues_schedule": schedule_name}):
            return frappe.db.get_value(
                "Contribution Amendment Request",
                {"new_dues_schedule": schedule_name},
                "name",
            )
        return None

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

        Checks for changes in dues rate, status, and billing frequency
        and records appropriate fee changes.

        Args:
            schedule_doc: The updated dues schedule document
        """
        if schedule_doc.is_template or not schedule_doc.member:
            return

        # Skip fee change recording if explicitly requested (e.g., during amendment application
        # where the fee change is recorded separately with full context)
        if getattr(schedule_doc.flags, "skip_fee_change_recording", False):
            self.logger.info(
                f"Skipping fee change recording for schedule {schedule_doc.name} - "
                "flag skip_fee_change_recording is set (amendment application)"
            )
            # Still update member dues rate even when skipping recording
            self.update_member_dues_rate(schedule_doc)
            return

        # Need old document for comparison
        if not hasattr(schedule_doc, "_doc_before_save") or schedule_doc._doc_before_save is None:
            return

        old_doc = schedule_doc._doc_before_save

        # Check for dues rate change
        if old_doc.dues_rate != schedule_doc.dues_rate:
            self.record_fee_change(schedule_doc, "Fee Adjustment", old_doc.dues_rate, schedule_doc.dues_rate)
            self.update_member_dues_rate(schedule_doc)

        # Check for status change
        if old_doc.status != schedule_doc.status:
            if schedule_doc.status == "Cancelled":
                self.record_fee_change(
                    schedule_doc,
                    "Schedule Cancelled",
                    schedule_doc.dues_rate,
                    schedule_doc.dues_rate,
                )
            elif old_doc.status == "Paused" and schedule_doc.status == "Active":
                self.record_fee_change(
                    schedule_doc,
                    "Schedule Resumed",
                    schedule_doc.dues_rate,
                    schedule_doc.dues_rate,
                )

        # Check for billing frequency change
        if old_doc.billing_frequency != schedule_doc.billing_frequency:
            self.record_fee_change(
                schedule_doc,
                "Billing Frequency Change",
                schedule_doc.dues_rate,
                schedule_doc.dues_rate,
            )

    def handle_new_schedule(self, schedule_doc: "Document") -> None:
        """
        Handle fee tracking when a new schedule is created.

        Records the initial fee for the new schedule.

        Args:
            schedule_doc: The newly created dues schedule document
        """
        if schedule_doc.is_template or not schedule_doc.member:
            return

        self.record_fee_change(schedule_doc, "New Schedule", 0, schedule_doc.dues_rate)
        self.update_member_dues_rate(schedule_doc)


def get_fee_change_tracking_service() -> FeeChangeTrackingService:
    """Get singleton instance of FeeChangeTrackingService."""
    return FeeChangeTrackingService()
