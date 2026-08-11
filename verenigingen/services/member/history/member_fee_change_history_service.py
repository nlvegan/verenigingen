# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberFeeChangeHistoryService - Fee change history child table management

This service handles direct management of the fee_change_history child table
on Member records, providing:
- Adding new fee change entries with deduplication
- Updating existing fee change entries
- History size management (50 entry limit)
- Integration with secure_document_operation for updates

Extracted from member.py:
- add_fee_change_to_history() - lines 1869-1942 (73 LOC)
- update_fee_change_in_history() - lines 1943-2002 (59 LOC)

Total: ~132 LOC of business logic in service layer

Architecture:
- Static methods that operate on Member documents
- Direct child table manipulation with append()
- Deduplication by dues_schedule and amendment_request
- Secure updates with permission validation
- History size limits to prevent unbounded growth

Security:
- Uses secure_document_operation for update operations
- Requires Member:write permission
- Allows system user for automated financial tracking
- Bypasses link_validation for problematic chapter references

Dependencies:
- secure_operations - For secure child table updates
- Member DocType - fee_change_history child table
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberFeeChangeHistoryService(StatelessService):
    """
    Service for managing fee change history child table on Member records.

    This service handles:
    - Adding new fee change entries incrementally
    - Updating existing entries by schedule or amendment
    - Deduplication to prevent duplicate history entries
    - History size management (50 entry limit)
    - Secure updates with permission validation
    """

    # Valid billing frequencies for fee change history
    VALID_BILLING_FREQUENCIES = ["Daily", "Weekly", "Monthly", "Quarterly", "Semi-Annual", "Annual", "Custom"]

    def __init__(self) -> None:
        """Initialize the fee change history service."""
        super().__init__(service_name="MemberFeeChangeHistoryService")

    def _validate_billing_frequency(self, frequency: Optional[str] = None) -> str:
        """
        Validate and normalize billing frequency.

        Args:
            frequency: Billing frequency from schedule_data (may be invalid)

        Returns:
            str: Validated frequency or "Custom" if invalid

        Example:
            >>> MemberFeeChangeHistoryService._validate_billing_frequency("Monthly")
            "Monthly"
            >>> MemberFeeChangeHistoryService._validate_billing_frequency("InvalidValue")
            "Custom"
            >>> MemberFeeChangeHistoryService._validate_billing_frequency(None)
            "Custom"
        """
        if frequency and frequency in self.VALID_BILLING_FREQUENCIES:
            return frequency
        return "Custom"

    def add_fee_change_to_history(self, member_doc: "Document", schedule_data: Dict[str, Any]) -> None:
        """
        Add a single fee change to history incrementally.

        Adds a new entry to the fee_change_history child table, or updates an existing
        entry if a matching dues_schedule or amendment_request is found.

        Args:
            member_doc: Member document instance
            schedule_data: Dictionary with keys:
                - change_date: Date of the change (optional, defaults to creation or now)
                - name or schedule_name: Schedule document name
                - dues_rate or new_dues_rate: New rate amount
                - old_dues_rate: Previous rate (default 0)
                - billing_frequency: Billing frequency (validated against allowed values)
                - change_type: Type of change (default "Schedule Created")
                - reason: Reason for change (optional)
                - changed_by: User who made change (default current user)
                - amendment_request: Amendment request reference (optional)

        Returns:
            None - Modifies member_doc.fee_change_history in place.
                   Caller MUST save document after calling this method.
                   No automatic save to prevent multiple saves during batch operations.

        Security:
            - No direct save operation - caller is responsible for saving
            - This prevents multiple saves when refreshing history
            - Uses Frappe append() for proper child table handling

        Business Logic:
            - Deduplicates by dues_schedule or amendment_request
            - Validates billing_frequency against allowed values
            - Limits history to 50 most recent entries
            - Updates existing entries or appends new ones
        """
        try:
            # Check if entry already exists for this schedule or amendment
            existing_idx = None
            for idx, row in enumerate(member_doc.fee_change_history or []):
                row_schedule = getattr(row, "dues_schedule", None)
                row_amendment = getattr(row, "amendment_request", None)

                # Match by dues schedule
                if row_schedule and (
                    row_schedule == schedule_data.get("schedule_name")
                    or row_schedule == schedule_data.get("name")
                ):
                    existing_idx = idx
                    break

                # Match by amendment request
                if row_amendment and row_amendment == schedule_data.get("amendment_request"):
                    existing_idx = idx
                    break

            # Validate billing frequency - use "Custom" for unsupported frequencies
            billing_freq = self._validate_billing_frequency(schedule_data.get("billing_frequency"))

            # Build entry data with all required fields
            entry_data = {
                "change_date": schedule_data.get("change_date")
                or schedule_data.get("creation")
                or now_datetime(),
                "dues_schedule": schedule_data.get("name") or schedule_data.get("schedule_name"),
                "billing_frequency": billing_freq,
                "old_dues_rate": schedule_data.get("old_dues_rate", 0),
                "new_dues_rate": schedule_data.get("dues_rate") or schedule_data.get("new_dues_rate"),
                "change_type": schedule_data.get("change_type", "Schedule Created"),
                "reason": schedule_data.get("reason")
                or f"Dues schedule: {schedule_data.get('schedule_name') or schedule_data.get('name')}",
                "changed_by": schedule_data.get("changed_by") or frappe.session.user or "Administrator",
            }

            # Add amendment request if provided
            if schedule_data.get("amendment_request"):
                entry_data["amendment_request"] = schedule_data.get("amendment_request")

            if existing_idx is not None:
                # Update existing entry with new values
                for key, value in entry_data.items():
                    if value is not None:
                        setattr(member_doc.fee_change_history[existing_idx], key, value)
            else:
                # Add new entry using append method (Frappe converts dict to child doc)
                member_doc.append("fee_change_history", entry_data)

                # Keep only 50 most recent entries to prevent unlimited growth
                if len(member_doc.fee_change_history) > 50:
                    # Remove oldest entries (at the end)
                    member_doc.fee_change_history = member_doc.fee_change_history[:50]

            # NOTE: Don't save here - caller is responsible for saving after all updates
            # This prevents multiple saves when refreshing history

        except Exception as e:
            self.logger.error(f"Error adding fee change to history for member {member_doc.name}: {str(e)}")
            # Ensure method closure
            return

    def update_fee_change_in_history(self, member_doc: "Document", schedule_data: Dict[str, Any]) -> None:
        """
        Update an existing fee change in history.

        Finds an existing fee change entry by schedule name and updates it with new data.
        If no matching entry is found, adds a new entry instead.

        Args:
            member_doc: Member document instance
            schedule_data: Dictionary with keys:
                - name or schedule_name: Schedule document name to match
                - change_date: Date of the change (optional, defaults to now)
                - dues_rate or new_dues_rate: New rate amount
                - old_dues_rate: Previous rate (optional, preserves existing if not provided)
                - billing_frequency: Billing frequency (validated against allowed values)
                - change_type: Type of change (default "Fee Adjustment")
                - reason: Reason for change (optional)
                - changed_by: User who made change (default current user)

        Returns:
            None - Modifies member_doc.fee_change_history in place.
                   Automatically saves document using secure_document_operation.
                   Do NOT save document after calling - already saved internally.

        Security:
            - Uses secure_document_operation for child table updates
            - Requires Member:write permission
            - Allows system user for automated financial data tracking
            - Bypasses link_validation for problematic chapter references

        Business Logic:
            - Searches for matching entry by dues_schedule field
            - Updates existing entry or adds new one if not found
            - Saves document after update using secure operations
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        if not hasattr(member_doc, "fee_change_history") or not member_doc.fee_change_history:
            # If no history exists, just add it
            self.add_fee_change_to_history(member_doc, schedule_data)
            return

        try:
            # Find the schedule in fee change history
            found = False
            schedule_name = schedule_data.get("name") or schedule_data.get("schedule_name")

            for _idx, row in enumerate(member_doc.fee_change_history):
                if row.dues_schedule == schedule_name:
                    found = True
                    # Update the entry with new data
                    billing_freq = self._validate_billing_frequency(schedule_data.get("billing_frequency"))

                    # Update fields
                    row.change_date = schedule_data.get("change_date") or now_datetime()
                    row.billing_frequency = billing_freq
                    row.old_dues_rate = schedule_data.get("old_dues_rate", row.old_dues_rate)
                    row.new_dues_rate = schedule_data.get("dues_rate") or schedule_data.get("new_dues_rate")
                    row.change_type = schedule_data.get("change_type", "Fee Adjustment")
                    row.reason = schedule_data.get("reason") or f"Updated: {schedule_name}"
                    row.changed_by = schedule_data.get("changed_by") or frappe.session.user or "Administrator"
                    break

            if not found:
                # Entry not in history, add it
                self.add_fee_change_to_history(member_doc, schedule_data)
            else:
                # CORRECTED SECURE VERSION: Use secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="update_child_table",
                    doc=member_doc,
                    justification=f"Update fee change in history for member {member_doc.name}",
                    required_permissions=["Member:write"],
                    allow_system_user=True,  # Allow system user for automated financial data tracking
                    bypass_validations=["link_validation"],  # Allow bypass of problematic chapter references
                )

                if not result.success:
                    self.logger.error(
                        f"Failed to update fee change in history for member {member_doc.name}: {'; '.join(result.errors)}"
                    )
                    return

        except Exception as e:
            self.logger.error(f"Error updating fee change in history for member {member_doc.name}: {str(e)}")


def get_member_fee_change_history_service() -> MemberFeeChangeHistoryService:
    """Get singleton instance of MemberFeeChangeHistoryService"""
    return MemberFeeChangeHistoryService()
