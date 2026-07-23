# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberFeeChangeService - Fee override change detection and recording

This service handles fee override changes on Member records, including:
- Detecting when membership fees are manually overridden
- Permission validation for fee changes
- Delegating fee change recording to FeeChangeRecordingService

NOTE: The record_fee_change() method is now a thin wrapper that delegates
to FeeChangeRecordingService.record(). The new service provides smart
deduplication based on actual change data (member + amounts + time window)
rather than caller-provided entry IDs.

Architecture:
- Static methods that operate on Member documents
- Permission-validated fee override handling
- Deferred change processing pattern
- Delegates recording to FeeChangeRecordingService

Security:
- Explicit permission validation for fee overrides
- CSV import bypass for bulk operations
- Audit trail with fee_override_date and fee_override_by fields
- No permission bypasses

Dependencies:
- FeeChangeRecordingService - For centralized fee change recording
- MemberFeeValidationService - For fee override validation
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.financial.member_fee_validation_service import (
    get_member_fee_validation_service,
)

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberFeeChangeService(StatelessService):
    """
    Service for managing fee override changes on Member records.

    This service handles:
    - Detecting fee override changes with database comparison
    - Permission validation for fee changes
    - Recording changes to history
    - CSV import bypass for bulk operations
    """

    def __init__(self) -> None:
        """Initialize the member fee change service."""
        super().__init__(service_name="MemberFeeChangeService")

    def handle_fee_override_changes(self, member_doc: "Document") -> None:
        """
        Handle changes to membership fee override using amendment system with better atomicity.

        Detects changes to the dues_rate field by comparing current values with database
        values. Validates permissions, override amount, and reason on a detected change.

        Args:
            member_doc: Member document instance

        Returns:
            None - Sets audit fields on member_doc when an override is added.

        Security:
            - Requires fee override permissions via validate_fee_override_permissions()
            - Validates override amount and reason
            - Skips for CSV imports and bulk operations

        Business Logic:
            - Skips for new documents (no change tracking on creation)
            - Skips for CSV imports and system updates
            - Compares current vs database values to detect actual changes
            - Sets audit fields (fee_override_date, fee_override_by)
            - Validates the new override amount and reason on change
        """
        # Skip all fee override handling for CSV imports and bulk operations
        csv_flag = getattr(member_doc, "_csv_import", False)
        system_flag = getattr(member_doc, "_system_update", False)
        # Check if member is part of an active bulk import (persists across saves)
        in_bulk_import = (
            hasattr(frappe.local, "bulk_import_members")
            and member_doc.name in frappe.local.bulk_import_members
        )

        if csv_flag or system_flag or in_bulk_import:
            return

        # Check permissions for fee override changes
        get_member_fee_validation_service().validate_fee_override_permissions(member_doc)

        # Skip fee override change tracking for new member applications
        # Applications should set initial fee amounts without triggering change tracking
        if not member_doc.name or member_doc.is_new():
            # For new documents, validate and set audit fields but no change tracking
            if member_doc.dues_rate:
                # Validate fee override using dedicated validation service (Phase 2D-2)
                get_member_fee_validation_service().validate_fee_override_amount(member_doc.dues_rate)
                get_member_fee_validation_service().validate_fee_override_reason(member_doc)

                # For CSV imports, create audit log entry instead of requiring override fields
                if getattr(member_doc, "_csv_import", False) and member_doc.dues_rate:
                    self.logger.info(
                        f"CSV Import: Member {member_doc.name or 'NEW'} imported with dues_rate {member_doc.dues_rate}"
                    )

                # Set audit fields for new members (but no change tracking)
                if not getattr(member_doc, "fee_override_date", None):
                    setattr(member_doc, "fee_override_date", today())
                if not getattr(member_doc, "fee_override_by", None):
                    setattr(member_doc, "fee_override_by", frappe.session.user)
            return

        # Get current and old values for existing documents
        new_amount = member_doc.dues_rate
        old_amount = None

        try:
            # Use Frappe's built-in change tracking instead of DB query for better performance
            # get_doc_before_save() returns the document state before current changes
            doc_before_save = member_doc.get_doc_before_save()
            if doc_before_save:
                old_amount = doc_before_save.get("dues_rate")
            else:
                # Fallback to DB query only if get_doc_before_save() unavailable
                # (this can happen in some edge cases like background jobs)
                db_result = frappe.db.get_value("Member", member_doc.name, "dues_rate")
                old_amount = db_result if db_result is not None else None

            # Check if values are actually different
            if old_amount == new_amount:
                return  # No change detected

            # If we reach here, there's an actual change to process
            self.logger.info(
                f"Processing fee override change for member {member_doc.name}: {old_amount} -> {new_amount}"
            )

            # Set audit fields when adding or changing override
            if new_amount and not old_amount:
                member_doc.fee_override_date = today()
                member_doc.fee_override_by = frappe.session.user

            # Validate fee override using dedicated validation service (Phase 2D-2)
            if new_amount:
                get_member_fee_validation_service().validate_fee_override_amount(new_amount)
                get_member_fee_validation_service().validate_fee_override_reason(member_doc)

        except Exception as e:
            # Log error for administrators
            self.logger.error(f"Fee override tracking failed for member {member_doc.name}: {str(e)}")
            # Notify user that audit tracking failed
            frappe.msgprint(
                frappe._("Fee change saved but audit tracking failed. Please contact administrator."),
                indicator="orange",
                alert=True,
            )
            # Don't fail the save operation - allow document to save even if tracking fails
            return

    def record_fee_change(self, member_doc: "Document", change_data: Dict[str, Any]) -> Any:
        """
        Record fee change via the centralized FeeChangeRecordingService.

        DEPRECATED: This method is maintained for backwards compatibility.
        New code should use FeeChangeRecordingService.record() directly.

        The new service provides smart deduplication based on actual change data
        (member + amounts + time window) rather than caller-provided entry IDs.

        Args:
            member_doc: Member document instance
            change_data: Dictionary with keys:
                - change_date: Date of the change (ignored, service uses now)
                - old_amount: Previous dues rate
                - new_amount: New dues rate
                - change_type: Type of change (default "Fee Adjustment")
                - reason: Reason for change
                - changed_by: User who made the change
                - dues_schedule_name: Optional schedule name
                - billing_frequency: Optional billing frequency
                - amendment_request_name: Optional amendment request reference

        Returns:
            RecordingResult from FeeChangeRecordingService.record()
        """
        from verenigingen.services.member.financial.fee_change_recording_service import (
            get_fee_change_recording_service,
        )

        return get_fee_change_recording_service().record(
            member=member_doc,
            old_amount=change_data.get("old_amount", 0),
            new_amount=change_data.get("new_amount", 0),
            change_type=change_data.get("change_type", "Fee Adjustment"),
            reason=change_data.get("reason", ""),
            amendment_request=change_data.get("amendment_request_name"),
            dues_schedule=change_data.get("dues_schedule_name"),
            billing_frequency=change_data.get("billing_frequency"),
            changed_by=change_data.get("changed_by"),
        )


def get_member_fee_change_service() -> MemberFeeChangeService:
    """Get singleton instance of MemberFeeChangeService"""
    return MemberFeeChangeService()
