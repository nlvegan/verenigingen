# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberHistoryUpdateService - Complete member history table management

This service provides self-contained history table update logic for members,
including donations, payments, invoices, volunteer expenses, and fee changes.

Extracted from member.py:
- incremental_update_history_tables() - orchestration (lines 2676-2759, 84 LOC)
- refresh_fee_change_history() - fee history refresh (lines 3143-3327, 185 LOC)

Architecture:
- Self-contained methods (minimal member method dependencies)
- Uses existing managers: DonationHistoryManager, HistoryIntegrityManager
- Payment history rebuild delegates to PaymentHistoryService so every
  payment_history writer routes through the single PaymentHistoryEntryBuilder
- Coordinates all history updates with proper flags and error handling
- Secure operations with permission validation for fee history updates

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
Public API methods return OperationResult[Dict[str, Any]] with type-safe error handling.
Never throw exceptions - all errors returned as OperationResult.fail().

Public API Methods:
- incremental_update_history_tables: Returns OperationResult[Dict] (history update summary)
- refresh_fee_change_history: Returns OperationResult[Dict] (fee history refresh results)

Migration Status: ✅ COMPLETE (2025-11-24)
- Both API methods migrated from dict-based to OperationResult pattern
- All secure_document_operation calls and integrity checks preserved
- Type-safe error handling with comprehensive metadata

Dependencies:
This service is fully independent with no member_doc method dependencies.

External Service Dependencies:
- DonationHistoryManager - Donation history synchronization
- HistoryIntegrityManager - Cleanup of broken expense entries
- sync_donor_history() - Donor history updates
- PaymentHistoryService - Unified invoice-based payment_history rebuild
- secure_document_operation - Secure document updates with permission validation
- cleanup_member_history - History integrity checking and cleanup

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.error_codes import log_operation_error
from verenigingen.utils.operation_result import OperationResult

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberHistoryUpdateService(StatelessService):
    """
    Service for orchestrating member history table updates.

    Inherits from StatelessService for consistent logging, metrics, and error handling.

    This service coordinates the rebuilding of all history-related child tables
    for a member, including:
    - Donation history (from Donor link)
    - Payment history (invoices, via the unified PaymentHistoryService rebuild)
    - Volunteer expense history (from Employee link)
    """

    def __init__(self) -> None:
        """Initialize the member history update service."""
        super().__init__(service_name="MemberHistoryUpdateService")

    def incremental_update_history_tables(self, member_doc: "Document") -> OperationResult[Dict[str, Any]]:
        """
        Rebuild payment history, donation history, and volunteer expense history tables.

        Performs a FULL rebuild including:
        - Sales Invoices (invoice-based payment_history, via PaymentHistoryService)
        - ALL Donations
        - ALL Volunteer Expenses

        Includes integrity checking and cleanup via HistoryIntegrityManager.

        Args:
            member_doc: Member document object

        Returns:
            OperationResult[Dict[str, Any]]: Summary of updates with:
                - volunteer_expenses (dict): {success, count, cleaned}
                - donations (dict): {success, count}
                - dues_payments (dict): {success, count}
                - invoices (dict): {success, count}
                - message (str): Human-readable summary

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - All errors logged and returned as OperationResult.fail()
            - Each step has independent error handling for accurate error attribution
        """
        changes_made = False
        has_errors = False

        results = {
            "volunteer_expenses": {"success": True, "count": 0, "cleaned": 0},
            "donations": {"success": True, "count": 0},
            "dues_payments": {"success": True, "count": 0},
            "invoices": {"success": True, "count": 0},
        }

        # STEP 1: Clean broken volunteer expense entries
        cleanup_removed, step_err = self._step_cleanup_volunteer_expenses(member_doc, results)
        if step_err:
            has_errors = True
        if cleanup_removed > 0:
            changes_made = True

        # STEP 2: Update donation history
        if self._step_sync_donation_history(member_doc, results):
            changes_made = True
        elif results["donations"].get("error"):
            has_errors = True

        # STEPS 3-5: Rebuild invoice-based payment history via the unified builder
        payment_changes, pay_err = self._step_rebuild_payment_history(member_doc, results)
        if payment_changes:
            changes_made = True
        if pay_err:
            has_errors = True

        # STEP 6: Volunteer expense history — archived (child table removed)

        # Save if needed
        if changes_made:
            save_err = self._step_save_history_changes(member_doc, results)
            if save_err:
                has_errors = True

        return self._build_history_result(results, member_doc.name, cleanup_removed, has_errors)

    def _step_cleanup_volunteer_expenses(self, member_doc: "Document", results: dict) -> tuple:
        """STEP 1: Clean broken volunteer expense entries if employee is linked.

        Returns:
            Tuple of (cleanup_removed_count, had_error)
        """
        try:
            if hasattr(member_doc, "employee") and member_doc.employee:
                from verenigingen.utils.member_history_integrity import HistoryIntegrityManager

                manager = HistoryIntegrityManager(member_doc)
                cleanup_stats = manager.cleanup_volunteer_expense_history()
                removed = cleanup_stats["removed"]
                results["volunteer_expenses"]["cleaned"] = removed
                return removed, False
        except Exception as e:
            log_operation_error("HIST_008", f"member {member_doc.name}", e)
            results["volunteer_expenses"]["success"] = False
            results["volunteer_expenses"]["error"] = f"Cleanup failed: {str(e)}"
            results["volunteer_expenses"]["error_code"] = "HIST_008"
            return 0, True
        return 0, False

    def _step_sync_donation_history(self, member_doc: "Document", results: dict) -> bool:
        """STEP 2: Update donation history if donor exists.

        Returns:
            True if changes were made
        """
        try:
            from verenigingen.utils.donor_member_reconciliation import get_donor_for_member

            donor_name = get_donor_for_member(member_doc)
            if donor_name:
                from verenigingen.utils.donation_history_manager import sync_donor_history

                original_count = len(getattr(member_doc, "donation_history", []))
                sync_donor_history(donor_name)
                member_doc.reload()
                changes = abs(len(getattr(member_doc, "donation_history", [])) - original_count)
                results["donations"]["count"] = changes
                return changes > 0
        except Exception as e:
            log_operation_error("HIST_001", f"member {member_doc.name}", e)
            results["donations"]["success"] = False
            results["donations"]["error"] = str(e)
            results["donations"]["error_code"] = "HIST_001"
        return False

    def _step_rebuild_payment_history(self, member_doc: "Document", results: dict) -> tuple:
        """STEPS 3-5: Rebuild invoice-based payment history via the unified builder.

        Delegates to PaymentHistoryService.load_payment_history_batched — the same
        invoice-only rebuild the async drain and background job use — so the
        Member-form "Rebuild Payment History" button emits rows identical to every
        other writer (Membership reference + SEPA-mandate fields).

        This replaces the former hand-rolled _update_invoice_payment_history /
        _update_dues_payment_history pair, whose invoice rows diverged from the
        builder (they never set the Membership reference_doctype/reference_name nor
        any SEPA-mandate fields) and which additionally emitted standalone
        "Membership Dues Payment" rows from custom_member Payment Entries — a
        row-type that does not occur in practice (payments reconcile against
        invoices) and is now dropped, matching the invoice-only model the other
        writers already enforce.

        The service clears and rebuilds member_doc.payment_history in place without
        saving; the orchestrator's _step_save_history_changes persists it.

        Returns:
            Tuple of (had_changes, had_errors)
        """
        # dues_payments is retained in the result contract (the Member form JS reads
        # data.dues_payments) but is always zero now that standalone dues rows are gone.
        results["dues_payments"]["count"] = 0

        if not member_doc.customer:
            return False, False

        from verenigingen.services.member.payment.payment_history_service import (
            get_payment_history_service,
        )

        rows_before = len(member_doc.payment_history or [])

        try:
            result = get_payment_history_service().load_payment_history_batched(member_doc)
        except Exception as e:
            log_operation_error("HIST_004", f"member {member_doc.name}", e)
            results["invoices"]["success"] = False
            results["invoices"]["error"] = str(e)
            results["invoices"]["error_code"] = "HIST_004"
            return False, True

        if not result.success:
            err_msg = "; ".join(result.errors) if result.errors else result.message
            results["invoices"]["success"] = False
            results["invoices"]["error"] = err_msg
            results["invoices"]["error_code"] = "HIST_004"
            return False, True

        entries_loaded = result.data.get("entries_loaded", 0)
        results["invoices"]["count"] = entries_loaded

        # The table was cleared and rebuilt: a save is warranted when rows were
        # produced OR when previously-existing rows were cleared away.
        changed = entries_loaded > 0 or rows_before > 0
        return changed, False

    def _step_save_history_changes(self, member_doc: "Document", results: dict) -> bool:
        """Save member doc with history flags. Returns True if save failed."""
        try:
            member_doc.flags.ignore_version = True
            member_doc.flags.ignore_links = True
            member_doc.flags.ignore_comment = True
            member_doc.save()
            return False
        except Exception as e:
            log_operation_error("HIST_007", f"member {member_doc.name}", e)
            for key in results:
                if results[key]["success"]:
                    results[key]["success"] = False
                    results[key]["error"] = f"Save failed: {str(e)}"
                    results[key]["error_code"] = "HIST_007"
            return True

    @staticmethod
    def _build_history_result(
        results: dict, member_name: str, cleanup_removed: int, has_errors: bool
    ) -> OperationResult:
        """Build the final OperationResult from step results."""
        message_parts = []
        if results["donations"]["count"] > 0:
            message_parts.append(f"{results['donations']['count']} donation changes")
        if results["dues_payments"]["count"] > 0:
            message_parts.append(f"{results['dues_payments']['count']} dues payment changes")
        if results["invoices"]["count"] > 0:
            message_parts.append(f"{results['invoices']['count']} invoice changes")
        if cleanup_removed > 0:
            message_parts.append(f"{cleanup_removed} broken entries cleaned")

        summary = ", ".join(message_parts) if message_parts else "No changes"

        if has_errors:
            error_messages = []
            error_codes = []
            for key, value in results.items():
                if not value["success"] and "error" in value:
                    error_messages.append(f"{key}: {value['error']}")
                    if "error_code" in value:
                        error_codes.append(value["error_code"])

            primary_error_code = error_codes[0] if error_codes else None
            return OperationResult.fail(
                f"Partial update completed with errors: {summary}",
                errors=error_messages,
                error_code=primary_error_code,
                **results,
                member=member_name,
            )

        return OperationResult.ok(
            results,
            message=f"Incremental update: {summary}",
        )

    @staticmethod
    def _process_fee_amendments(member_doc, applied_amendments, existing_entries_by_amendment):
        """Process applied amendments, adding new fee change history entries. Returns True if changes made."""
        changes_made = False
        for amendment in applied_amendments:
            if amendment.name not in existing_entries_by_amendment:
                amendment_data = {
                    "amendment_request": amendment.name,
                    "dues_rate": amendment.requested_amount,
                    "old_dues_rate": amendment.current_amount or 0,
                    "change_type": "Fee Adjustment",
                    "reason": (
                        f"Amendment: {amendment.reason}"
                        if amendment.reason
                        else f"Amendment {amendment.name}"
                    ),
                    "change_date": amendment.applied_date or amendment.effective_date,
                    "changed_by": amendment.applied_by or "Administrator",
                }
                member_doc.add_fee_change_to_history(amendment_data)
                changes_made = True
        return changes_made

    @staticmethod
    def _process_fee_schedule(member_doc, schedule, existing_entry):
        """Process a single dues schedule for fee history. Returns True if changes made."""
        schedule_label = f"Dues schedule: {schedule.schedule_name or schedule.name}"

        if existing_entry:
            needs_update = (
                existing_entry.new_dues_rate != schedule.dues_rate
                or existing_entry.billing_frequency  # ast-skip: Dues Schedule field
                != schedule.billing_frequency
                or existing_entry.reason != schedule_label  # ast-skip: Member Fee Change History field
            )
            if needs_update:
                member_doc.update_fee_change_in_history(
                    {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name,
                        "dues_rate": schedule.dues_rate,
                        "billing_frequency": schedule.billing_frequency,
                        "old_dues_rate": existing_entry.old_dues_rate,
                        "change_type": "Fee Adjustment",
                        "reason": schedule_label,
                        "change_date": frappe.utils.now_datetime(),
                        "changed_by": frappe.session.user or "Administrator",
                    }
                )
                return True
            return False

        # New entry (initial schedule creation)
        member_doc.add_fee_change_to_history(
            {
                "name": schedule.name,
                "schedule_name": schedule.schedule_name,
                "dues_rate": schedule.dues_rate,
                "billing_frequency": schedule.billing_frequency,
                "creation": schedule.creation,
                "old_dues_rate": 0,
                "change_type": "Schedule Created",
                "reason": schedule_label,
                "changed_by": frappe.session.user or "Administrator",
            }
        )
        return True

    def refresh_fee_change_history(self, member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Refresh fee change history from dues schedules and amendments with integrity checking.

        Performs a complete rebuild of the member's fee_change_history child table from
        Membership Dues Schedules and Contribution Amendment Requests.

        Args:
            member_name: Name/ID of the member document

        Returns:
            OperationResult[Dict[str, Any]]: Result with history_count, amendments_found,
                dues_schedules_found, removed_entries, cleanup_details, method, reload_doc.

        Note:
            Never throws exceptions — all errors returned as OperationResult.fail().
        """
        try:
            from verenigingen.utils.member_history_integrity import cleanup_member_history
            from verenigingen.utils.secure_operations import secure_document_operation

            member_doc = frappe.get_doc("Member", member_name, for_update=True)

            # STEP 1: Clean broken history entries
            cleanup_result = cleanup_member_history(member_doc)
            cleanup_stats = {
                "removed": cleanup_result["fee_history"]["removed"],
                "reasons": {"total": cleanup_result["fee_history"]["removed"]},
                "errors": cleanup_result["fee_history"]["errors"],
            }

            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "schedule_name", "dues_rate", "billing_frequency", "status", "creation"],
                order_by="creation",
            )

            existing_entries_by_schedule = {
                row.dues_schedule: row for row in member_doc.fee_change_history or [] if row.dues_schedule
            }
            existing_entries_by_amendment = {
                row.amendment_request: row
                for row in member_doc.fee_change_history or []
                if row.amendment_request
            }

            # STEP 2: Process applied amendments
            applied_amendments = frappe.get_all(
                "Contribution Amendment Request",
                filters={"member": member_name, "status": "Applied"},
                fields=[
                    "name",
                    "effective_date",
                    "requested_amount",
                    "current_amount",
                    "reason",
                    "applied_date",
                    "applied_by",
                ],
                order_by="effective_date, applied_date",
            )

            changes_made = self._process_fee_amendments(
                member_doc, applied_amendments, existing_entries_by_amendment
            )

            # STEP 3: Process schedules
            for schedule in dues_schedules:
                existing_entry = existing_entries_by_schedule.get(schedule.name)
                if self._process_fee_schedule(member_doc, schedule, existing_entry):
                    changes_made = True

            if cleanup_stats["removed"] > 0:
                changes_made = True

            if not changes_made:
                return OperationResult.ok(
                    {
                        "history_count": len(member_doc.fee_change_history or []),
                        "amendments_found": len(applied_amendments),
                        "dues_schedules_found": len(dues_schedules),
                        "removed_entries": 0,
                        "cleanup_details": cleanup_stats,
                        "method": "no_changes",
                    },
                    message=f"Fee change history is already up to date for {member_name}",
                )

            # Fee history updates are administrative operations that preserve audit trail
            member_doc.flags.ignore_validate_update_after_submit = True  # JUSTIFIED: Fee history update

            fee_history_result = secure_document_operation(
                operation="update_child_table",
                doc=member_doc,
                justification=f"Update fee change history for member {member_doc.name}",
                required_permissions=["Member:write"],
                allow_system_user=False,
                bypass_validations=["link_validation"],
            )

            if not fee_history_result.success:
                self.logger.error(
                    f"Fee history update failed for {member_doc.name}: {'; '.join(fee_history_result.errors)}"
                )
                frappe.throw(
                    frappe._("Failed to update fee change history: {0}").format(
                        "; ".join(fee_history_result.errors)
                    )
                )

            frappe.db.commit()

            return OperationResult.ok(
                {
                    "history_count": len(applied_amendments) + len(dues_schedules),
                    "reload_doc": True,
                    "amendments_found": len(applied_amendments),
                    "dues_schedules_found": len(dues_schedules),
                    "removed_entries": cleanup_stats["removed"],
                    "cleanup_details": cleanup_stats,
                    "method": "atomic_with_amendments",
                },
                message=(
                    f"Fee change history refreshed for {member_name} - "
                    f"{len(applied_amendments)} amendments + {len(dues_schedules)} schedules processed, "
                    f"{cleanup_stats['removed']} broken entries cleaned"
                ),
            )

        except Exception as e:
            log_operation_error("HIST_006", f"member {member_name}", e)
            error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
            return OperationResult.fail(
                f"Error: {error_msg}",
                errors=[str(e)],
                error_code="HIST_006",
                member=member_name,
            )


def get_member_history_update_service() -> MemberHistoryUpdateService:
    """Get singleton instance of MemberHistoryUpdateService"""
    return MemberHistoryUpdateService()
