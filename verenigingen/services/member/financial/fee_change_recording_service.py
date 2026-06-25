# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
FeeChangeRecordingService - Single entry point for all fee change recording.

This service centralizes fee change recording with smart deduplication based on
actual change data rather than caller-provided IDs. This eliminates the need for
coordination between multiple callers (amendment service, schedule hooks, etc.).

Deduplication Strategy:
- Reject if old_amount == new_amount (no actual change)
- Reject if member.dues_rate == new_amount (already at target)
- Reject/merge if duplicate within 60-second window (same member + amounts)

All callers provide whatever context they have (amendment reference, schedule
reference, etc.) and the service handles the rest.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Optional, Union

import frappe
from frappe.utils import flt, now_datetime

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


@dataclass
class RecordingResult:
    """Result of a fee change recording attempt."""

    status: str  # 'created', 'skipped', 'merged'
    message: str
    entry_name: Optional[str] = None


# Deduplication window in seconds
DEDUP_WINDOW_SECONDS = 60


class FeeChangeRecordingService(StatelessService):
    """
    Single entry point for all fee change recording.

    Provides smart deduplication based on actual change data, eliminating
    the need for caller coordination or flags.

    Usage:
        service = get_fee_change_recording_service()
        result = service.record(
            member="MEM-001",
            old_amount=10.0,
            new_amount=15.0,
            change_type="Fee Adjustment",
            reason="Annual increase",
            amendment_request="AMEND-001",  # optional context
        )
    """

    def __init__(self) -> None:
        """Initialize the fee change recording service."""
        super().__init__(service_name="FeeChangeRecordingService")

    def record(
        self,
        member: Union[str, "Document"],
        old_amount: float,
        new_amount: float,
        change_type: str = "Fee Adjustment",
        reason: str = "",
        amendment_request: Optional[str] = None,
        dues_schedule: Optional[str] = None,
        billing_frequency: Optional[str] = None,
        changed_by: Optional[str] = None,
    ) -> RecordingResult:
        """
        Record a fee change with smart deduplication.

        Args:
            member: Member document or name
            old_amount: Previous dues rate
            new_amount: New dues rate
            change_type: Type of change (e.g., "Fee Adjustment", "New Schedule")
            reason: Reason for the change
            amendment_request: Optional amendment request reference
            dues_schedule: Optional dues schedule reference
            billing_frequency: Optional billing frequency
            changed_by: User who made the change (defaults to current user)

        Returns:
            RecordingResult with status: 'created', 'skipped', or 'merged'
        """
        # Normalize inputs
        old_amount = flt(old_amount)
        new_amount = flt(new_amount)
        changed_by = changed_by or frappe.session.user or "Administrator"
        # `reason` is mandatory on Member Fee Change History. A None/empty reason
        # would produce an invalid child row that raises MandatoryError when the
        # member is later saved (this previously aborted amendment application).
        # Guarantee a non-empty value here for every caller.
        reason = (reason or "").strip() or change_type or "Fee change"

        # Get member document
        if isinstance(member, str):
            member_name = member
            member_doc = frappe.get_doc("Member", member_name)
        else:
            member_name = member.name
            member_doc = member

        # === Filter 1: No actual change ===
        if abs(old_amount - new_amount) < 0.01:
            self.logger.debug(
                f"Skipping fee change for {member_name}: no actual change "
                f"(old={old_amount}, new={new_amount})"
            )
            return RecordingResult(
                status="skipped",
                message="No actual change in amount",
            )

        # === Filter 2: Already at target ===
        current_rate = flt(member_doc.dues_rate or 0)
        if abs(current_rate - new_amount) < 0.01 and abs(current_rate - old_amount) > 0.01:
            # Member is already at the new rate, and it's different from old_amount
            # This suggests the change was already applied
            self.logger.debug(
                f"Skipping fee change for {member_name}: already at target rate "
                f"(current={current_rate}, new={new_amount})"
            )
            return RecordingResult(
                status="skipped",
                message="Member already at target rate",
            )

        # === Filter 3: Check for recent duplicate ===
        recent_duplicate = self._find_recent_duplicate(member_doc, old_amount, new_amount)

        if recent_duplicate:
            # Merge additional context into existing entry if we have new info
            merged = self._merge_context_if_needed(
                recent_duplicate,
                amendment_request=amendment_request,
                dues_schedule=dues_schedule,
            )
            if merged:
                # _merge_context_if_needed mutated the existing child row in
                # memory only; persist the change so the merged amendment/
                # schedule reference survives a fresh DB read (the _create_entry
                # path persists via the history manager; the merge path must too).
                from verenigingen.utils import safe_child_table_update

                persist_result = safe_child_table_update(
                    member_doc,
                    "fee_change_history",
                    justification="Merge amendment/schedule context into existing fee change entry",
                    doctype_permission="Member:write",
                )
                if not persist_result.success:
                    self.logger.error(
                        f"Failed to persist merged fee change context for {member_name}: "
                        f"{persist_result.errors}"
                    )
                    return RecordingResult(
                        status="skipped",
                        message="Failed to persist merged context",
                        entry_name=recent_duplicate.name,
                    )
                self.logger.info(f"Merged context into existing fee change entry for {member_name}")
                return RecordingResult(
                    status="merged",
                    message="Merged context into existing entry",
                    entry_name=recent_duplicate.name,
                )
            else:
                self.logger.debug(
                    f"Skipping duplicate fee change for {member_name} "
                    f"(existing entry: {recent_duplicate.name})"
                )
                return RecordingResult(
                    status="skipped",
                    message="Duplicate entry within deduplication window",
                    entry_name=recent_duplicate.name,
                )

        # === Create new entry ===
        return self._create_entry(
            member_doc=member_doc,
            old_amount=old_amount,
            new_amount=new_amount,
            change_type=change_type,
            reason=reason,
            amendment_request=amendment_request,
            dues_schedule=dues_schedule,
            billing_frequency=billing_frequency,
            changed_by=changed_by,
        )

    def _find_recent_duplicate(
        self,
        member_doc: "Document",
        old_amount: float,
        new_amount: float,
    ) -> Optional["Document"]:
        """
        Find a recent fee change entry that matches this change.

        Looks for entries within the deduplication window with matching amounts.
        """
        fee_history = member_doc.get("fee_change_history", [])
        if not fee_history:
            return None

        cutoff_time = now_datetime() - timedelta(seconds=DEDUP_WINDOW_SECONDS)

        for entry in fee_history:
            # Check if within time window
            entry_time = entry.get("change_date")
            if not entry_time:
                continue

            # Handle both datetime and string formats
            if isinstance(entry_time, str):
                from frappe.utils import get_datetime

                entry_time = get_datetime(entry_time)

            if entry_time < cutoff_time:
                continue  # Too old

            # Check if amounts match
            entry_old = flt(entry.get("old_dues_rate", 0))
            entry_new = flt(entry.get("new_dues_rate", 0))

            if abs(entry_old - old_amount) < 0.01 and abs(entry_new - new_amount) < 0.01:
                return entry

        return None

    def _merge_context_if_needed(
        self,
        entry: "Document",
        amendment_request: Optional[str] = None,
        dues_schedule: Optional[str] = None,
    ) -> bool:
        """
        Merge additional context into an existing entry if we have new info.

        Returns True if context was merged, False if nothing to merge.
        """
        merged = False

        # Add amendment reference if entry doesn't have one
        if amendment_request and not entry.get("amendment_request"):
            entry.amendment_request = amendment_request
            merged = True

        # Add schedule reference if entry doesn't have one
        if dues_schedule and not entry.get("dues_schedule"):
            entry.dues_schedule = dues_schedule
            merged = True

        return merged

    def _create_entry(
        self,
        member_doc: "Document",
        old_amount: float,
        new_amount: float,
        change_type: str,
        reason: str,
        amendment_request: Optional[str],
        dues_schedule: Optional[str],
        billing_frequency: Optional[str],
        changed_by: str,
    ) -> RecordingResult:
        """Create a new fee change history entry."""
        from verenigingen.utils.member_financial_history_manager import (
            get_fee_change_history_manager,
        )

        # Build entry data
        entry_data = {
            "change_date": now_datetime(),
            "old_dues_rate": old_amount,
            "new_dues_rate": new_amount,
            "change_type": change_type,
            "reason": reason,
            "changed_by": changed_by,
        }

        # Add optional fields if provided
        if amendment_request:
            entry_data["amendment_request"] = amendment_request
        if dues_schedule:
            entry_data["dues_schedule"] = dues_schedule
        if billing_frequency:
            entry_data["billing_frequency"] = billing_frequency

        # Use the history manager for actual storage
        # Generate a unique entry_id based on timestamp for the manager
        entry_id = f"fee_change_{now_datetime().strftime('%Y%m%d%H%M%S%f')}"

        fee_history_manager = get_fee_change_history_manager(member_doc)
        success = fee_history_manager.add_or_update_entry(
            entry_id=entry_id,
            entry_builder=lambda: entry_data,
            id_field_name="change_date",  # Use change_date for identification
        )

        if success:
            self.logger.info(
                f"Recorded fee change for {member_doc.name}: " f"{old_amount} -> {new_amount} ({change_type})"
            )
            return RecordingResult(
                status="created",
                message="Fee change recorded successfully",
            )
        else:
            self.logger.error(f"Failed to record fee change for {member_doc.name}")
            return RecordingResult(
                status="skipped",
                message="Failed to save entry",
            )


# Singleton instance
_fee_change_recording_service: Optional[FeeChangeRecordingService] = None


def get_fee_change_recording_service() -> FeeChangeRecordingService:
    """Get singleton instance of FeeChangeRecordingService."""
    global _fee_change_recording_service
    if _fee_change_recording_service is None:
        _fee_change_recording_service = FeeChangeRecordingService()
    return _fee_change_recording_service
