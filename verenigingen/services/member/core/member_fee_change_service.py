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
        Enforce fee-override rules while a Member is saved.

        Runs during Member validate. For a new member carrying a dues_rate it
        validates the override amount/reason and sets the audit fields; for an
        existing member it only enforces the fee-override permission gate.

        Args:
            member_doc: Member document instance

        Returns:
            None - Sets audit fields on member_doc for a new override.

        Security:
            - Requires fee override permissions via validate_fee_override_permissions()
            - Validates override amount and reason for new members
            - Skips for CSV imports and bulk operations

        Business Logic:
            - Skips for CSV imports, bulk operations, and system updates
            - New members: validate the override amount/reason and set audit fields
            - Existing members: permission gate only; dues_rate is a denormalized
              mirror of the dues-schedule rate, so genuine fee changes
              (amendments, dues-schedule edits) record history on their own paths
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

        # Existing members: the permission gate above is the only enforcement
        # that applies here. `dues_rate` is a denormalized mirror of the active
        # Membership Dues Schedule rate; genuine fee changes flow through the
        # amendment / dues-schedule paths, which record fee_change_history and
        # save with _system_update=True (skipped above).
        #
        # A former change-detection branch here re-validated the amount/reason
        # whenever an existing member's dues_rate differed on save (reachable via
        # api.member.financial_api.sync_member_dues_rate and raw REST edits). It
        # was removed as redundant: it duplicated the gate's own old-vs-new
        # detection, its amount check cannot fire on a non-negative synced rate,
        # and its reason-required check spuriously blocked denormalization syncs
        # that carry no fee_override_reason. The permission gate is retained.

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
