# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberFeeChangeService - Fee override change detection and recording

This service handles fee override changes on Member records, including:
- Detecting when membership fees are manually overridden
- Permission validation for fee changes
- Recording fee changes to history
- Deferred processing to avoid save recursion

Extracted from member.py:
- handle_fee_override_changes() - lines 1317-1410 (95 LOC)
- record_fee_change() - lines 1410-1457 (47 LOC)

Total: ~142 LOC of business logic in service layer

Architecture:
- Static methods that operate on Member documents
- Permission-validated fee override handling
- Deferred change processing pattern
- Integration with MemberFinancialHistoryManager

Security:
- Explicit permission validation for fee overrides
- CSV import bypass for bulk operations
- Audit trail with fee_override_date and fee_override_by fields
- No permission bypasses

Dependencies:
- member_financial_history_manager - For fee change history recording
- MemberFeeValidationService - For fee override validation (Phase 2D-2)
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe.utils import now, today

from verenigingen.services.member.financial.member_fee_validation_service import MemberFeeValidationService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberFeeChangeService:
    """
    Service for managing fee override changes on Member records.

    This service handles:
    - Detecting fee override changes with database comparison
    - Permission validation for fee changes
    - Recording changes to history
    - Deferred processing to avoid save recursion
    - CSV import bypass for bulk operations
    """

    @staticmethod
    def handle_fee_override_changes(member_doc: "Document") -> None:
        """
        Handle changes to membership fee override using amendment system with better atomicity.

        Detects changes to the dues_rate field by comparing current values with database
        values. Validates permissions and records changes for deferred processing.

        Args:
            member_doc: Member document instance

        Returns:
            None - Sets _pending_fee_change on member_doc for deferred processing

        Security:
            - Requires fee override permissions via validate_fee_override_permissions()
            - Validates override amount and reason
            - Skips for CSV imports and bulk operations

        Business Logic:
            - Skips for new documents (no change tracking on creation)
            - Skips for CSV imports and system updates
            - Compares current vs database values to detect actual changes
            - Sets audit fields (fee_override_date, fee_override_by)
            - Queues change for deferred processing to avoid save recursion
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
        MemberFeeValidationService.validate_fee_override_permissions(member_doc)

        # Skip fee override change tracking for new member applications
        # Applications should set initial fee amounts without triggering change tracking
        if not member_doc.name or member_doc.is_new():
            # For new documents, validate and set audit fields but no change tracking
            if member_doc.dues_rate:
                # Validate fee override using dedicated validation service (Phase 2D-2)
                MemberFeeValidationService.validate_fee_override_amount(member_doc.dues_rate)
                MemberFeeValidationService.validate_fee_override_reason(member_doc)

                # For CSV imports, create audit log entry instead of requiring override fields
                if getattr(member_doc, "_csv_import", False) and member_doc.dues_rate:
                    frappe.logger().info(
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
            frappe.logger().info(
                f"Processing fee override change for member {member_doc.name}: {old_amount} -> {new_amount}"
            )

            # Set audit fields when adding or changing override
            if new_amount and not old_amount:
                member_doc.fee_override_date = today()
                member_doc.fee_override_by = frappe.session.user

            # Validate fee override using dedicated validation service (Phase 2D-2)
            if new_amount:
                MemberFeeValidationService.validate_fee_override_amount(new_amount)
                MemberFeeValidationService.validate_fee_override_reason(member_doc)

            # Store change data for deferred processing to avoid save recursion
            member_doc._pending_fee_change = {
                "old_amount": old_amount,
                "new_amount": new_amount,
                "reason": getattr(member_doc, "fee_override_reason", None) or "No reason provided",
                "change_date": now(),
                "changed_by": frappe.session.user if frappe.session.user else "Administrator",
            }

            frappe.logger().info(f"Queued fee override change for member {member_doc.name}")

        except Exception as e:
            # Log error for administrators
            frappe.log_error(
                f"Fee override tracking failed for member {member_doc.name}: {str(e)}",
                "Fee Change Tracking Error",
            )
            # Notify user that audit tracking failed
            frappe.msgprint(
                frappe._("Fee change saved but audit tracking failed. Please contact administrator."),
                indicator="orange",
                alert=True,
            )
            # Don't fail the save operation - allow document to save even if tracking fails
            return

    @staticmethod
    def record_fee_change(member_doc: "Document", change_data: Dict[str, Any]) -> Any:
        """
        Record fee change in history using the financial history manager.

        Builds a fee change entry from change_data and adds/updates it in the member's
        fee change history using the MemberFinancialHistoryManager.

        Args:
            member_doc: Member document instance
            change_data: Dictionary with keys:
                - change_date: Date of the change
                - old_amount: Previous dues rate
                - new_amount: New dues rate
                - change_type: Type of change (default "Fee Adjustment")
                - reason: Reason for change
                - changed_by: User who made the change
                - dues_schedule_name: Optional schedule name
                - billing_frequency: Optional billing frequency
                - amendment_request_name: Optional amendment request reference

        Returns:
            Result from fee_history_manager.add_or_update_entry()

        Security:
            - Uses MemberFinancialHistoryManager for secure history updates
            - Proper deduplication with entry_id based on amendment or schedule

        Business Logic:
            - Uses amendment_request_name for true idempotency if available
            - Falls back to schedule_name + action for other changes
            - Stores actual document names in Link fields (not prefixed IDs)
            - Delegates to MemberFinancialHistoryManager for actual update
        """
        from verenigingen.utils.member_financial_history_manager import get_fee_change_history_manager

        # Use amendment request name for true idempotency, fallback to schedule+action for other changes
        amendment_name = change_data.get("amendment_request_name")
        if amendment_name:
            entry_id = f"amendment_{amendment_name}"
            id_field_name = "amendment_request"
        else:
            # For non-amendment changes: use schedule name + action type for deduplication
            # This prevents duplicate entries when same schedule action is processed multiple times
            # If no schedule name, use change_date for identification
            schedule_name = change_data.get("dues_schedule_name")
            if not schedule_name:
                schedule_name = change_data.get("change_date", "unknown")
            action = change_data.get("dues_schedule_action", "manual")
            entry_id = f"{schedule_name}_{action}"
            id_field_name = "dues_schedule"

        def build_fee_change_entry():
            entry_data = {
                "change_date": change_data["change_date"],
                "old_dues_rate": change_data["old_amount"],
                "new_dues_rate": change_data["new_amount"],
                "change_type": change_data.get("change_type", "Fee Adjustment"),
                "reason": change_data["reason"],
                "changed_by": change_data["changed_by"],
                "dues_schedule": change_data.get("dues_schedule_name", ""),
            }
            # Add billing frequency if provided
            if "billing_frequency" in change_data:
                entry_data["billing_frequency"] = change_data["billing_frequency"]
            # Add amendment request reference if available
            # CRITICAL: Store the actual amendment_name (not entry_id) in the Link field
            # Link fields require valid document names, not prefixed IDs
            # The deduplication logic uses entry_id for comparison, but storage must use document name
            if amendment_name:
                entry_data["amendment_request"] = amendment_name  # Store actual document name for Link field
            return entry_data

        fee_history_manager = get_fee_change_history_manager(member_doc)
        return fee_history_manager.add_or_update_entry(
            entry_id=entry_id,
            entry_builder=build_fee_change_entry,
            id_field_name=id_field_name,
        )


def get_member_fee_change_service() -> MemberFeeChangeService:
    """Get singleton instance of MemberFeeChangeService"""
    return MemberFeeChangeService()
