# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberHistoryUpdateService - Complete member history table management

This service provides self-contained history table update logic for members,
including donations, payments, invoices, volunteer expenses, and fee changes.

Extracted from member.py:
- incremental_update_history_tables() - orchestration (lines 2676-2759, 84 LOC)
- _update_donation_history() - uses DonationHistoryManager (14 LOC)
- _update_volunteer_expense_history() - expense claims (lines 2312-2401, 90 LOC)
- _update_dues_payment_history() - payment entries (lines 2403-2490, 88 LOC)
- _update_invoice_payment_history() - sales invoices (lines 2492-2672, 180 LOC)
- refresh_fee_change_history() - fee history refresh (lines 3143-3327, 185 LOC)

Total: ~641 LOC of business logic now in service layer

Architecture:
- Self-contained static methods (minimal member method dependencies)
- Uses existing managers: DonationHistoryManager, HistoryIntegrityManager
- Coordinates all history updates with proper flags and error handling
- Optimized queries to avoid N+1 problems
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
- MemberMembershipService - Active membership queries (extracted 2025-11-20)
- secure_document_operation - Secure document updates with permission validation
- cleanup_member_history - History integrity checking and cleanup

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.error_codes import log_operation_error
from verenigingen.utils.operation_result import OperationResult

if TYPE_CHECKING:
    from frappe.model.document import Document


@dataclass
class PaymentReferenceCache:
    """
    Cached payment reference data shared between history update methods.

    This cache is populated once per history rebuild and passed to both
    _update_dues_payment_history() and _update_invoice_payment_history()
    to avoid redundant database queries.

    Query Reduction: ~4 queries → 2 queries (50% reduction)
    """

    member_invoice_names: List[str] = field(default_factory=list)
    payment_refs_by_invoice: Dict[str, List[Any]] = field(default_factory=dict)
    payment_entries_data: Dict[str, Any] = field(default_factory=dict)
    reconciled_payment_entries: Set[str] = field(default_factory=set)


class MemberHistoryUpdateService(StatelessService):
    """
    Service for orchestrating member history table updates.

    Inherits from StatelessService for consistent logging, metrics, and error handling.

    This service coordinates the rebuilding of all history-related child tables
    for a member, including:
    - Donation history (from Donor link)
    - Dues payment history (from Payment Entries)
    - Invoice payment history (from Sales Invoices)
    - Volunteer expense history (from Employee link)
    """

    def __init__(self) -> None:
        """Initialize the member history update service."""
        super().__init__(service_name="MemberHistoryUpdateService")

    def incremental_update_history_tables(self, member_doc: "Document") -> OperationResult[Dict[str, Any]]:
        """
        Rebuild payment history, donation history, and volunteer expense history tables.

        Performs a FULL rebuild (no record limits) including:
        - ALL Sales Invoices with coverage dates
        - ALL Payment Entries (dues payments)
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

        # STEPS 3-5: Prefetch and update payment histories
        payment_changes, pay_err = self._step_prefetch_and_update_payments(member_doc, results)
        if payment_changes:
            changes_made = True
        if pay_err:
            has_errors = True

        # STEP 6: Update volunteer expense history
        try:
            expense_changes = self._update_volunteer_expense_history(member_doc)
            results["volunteer_expenses"]["count"] = expense_changes
            if expense_changes > 0:
                changes_made = True
        except Exception as e:
            log_operation_error("HIST_005", f"member {member_doc.name}", e)
            results["volunteer_expenses"]["success"] = False
            results["volunteer_expenses"]["error"] = str(e)
            results["volunteer_expenses"]["error_code"] = "HIST_005"
            has_errors = True

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

    def _step_prefetch_and_update_payments(self, member_doc: "Document", results: dict) -> tuple:
        """STEPS 3-5: Prefetch payment references, update dues and invoice histories.

        Returns:
            Tuple of (had_changes, had_errors)
        """
        changes_made = False
        has_errors = False

        # STEP 3: Prefetch payment reference data
        payment_cache = None
        try:
            payment_cache = self._prefetch_payment_references(member_doc)
        except Exception as e:
            log_operation_error("HIST_002", f"member {member_doc.name}", e)
            err_msg = f"Payment reference prefetch failed: {str(e)}"
            for key in ("dues_payments", "invoices"):
                results[key]["success"] = False
                results[key]["error"] = err_msg
                results[key]["error_code"] = "HIST_002"
            return False, True

        # STEP 4: Update dues payment history
        if results["dues_payments"]["success"]:
            try:
                dues_changes = self._update_dues_payment_history(member_doc, payment_cache)
                results["dues_payments"]["count"] = dues_changes
                if dues_changes > 0:
                    changes_made = True
            except Exception as e:
                log_operation_error("HIST_003", f"member {member_doc.name}", e)
                results["dues_payments"]["success"] = False
                results["dues_payments"]["error"] = str(e)
                results["dues_payments"]["error_code"] = "HIST_003"
                has_errors = True

        # STEP 5: Update invoice payment history
        if results["invoices"]["success"]:
            try:
                invoice_changes = self._update_invoice_payment_history(member_doc, payment_cache)
                results["invoices"]["count"] = invoice_changes
                if invoice_changes > 0:
                    changes_made = True
            except Exception as e:
                log_operation_error("HIST_004", f"member {member_doc.name}", e)
                results["invoices"]["success"] = False
                results["invoices"]["error"] = str(e)
                results["invoices"]["error_code"] = "HIST_004"
                has_errors = True

        return changes_made, has_errors

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
        if results["volunteer_expenses"]["count"] > 0:
            message_parts.append(f"{results['volunteer_expenses']['count']} expense changes")
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

    def _prefetch_payment_references(self, member_doc: "Document") -> PaymentReferenceCache:
        """
        Prefetch payment reference data used by both dues and invoice history methods.

        This method fetches all Payment Entry Reference data in bulk, avoiding
        redundant queries when updating both dues payment history and invoice
        payment history.

        Args:
            member_doc: Member document object

        Returns:
            PaymentReferenceCache: Cached data structure with:
                - member_invoice_names: List of Sales Invoice names
                - payment_refs_by_invoice: Dict mapping invoice -> payment refs
                - payment_entries_data: Dict mapping payment entry name -> data
                - reconciled_payment_entries: Set of reconciled payment entry names
        """
        cache = PaymentReferenceCache()

        if not member_doc.customer:
            return cache

        # Get all Sales Invoices for this member's customer
        cache.member_invoice_names = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member_doc.customer, "docstatus": ["!=", 2]},
            pluck="name",
        )

        if not cache.member_invoice_names:
            return cache

        # Get all payment references for these invoices in one query
        payment_refs = frappe.get_all(
            "Payment Entry Reference",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": ["in", cache.member_invoice_names],
            },
            fields=["reference_name", "parent", "allocated_amount"],
        )

        # Group by invoice and collect unique payment entry names
        all_payment_entry_names: Set[str] = set()
        for ref in payment_refs:
            if ref.reference_name not in cache.payment_refs_by_invoice:
                cache.payment_refs_by_invoice[ref.reference_name] = []
            cache.payment_refs_by_invoice[ref.reference_name].append(ref)
            all_payment_entry_names.add(ref.parent)

        # Build set of reconciled payment entries
        cache.reconciled_payment_entries = all_payment_entry_names.copy()

        # Get all unique payment entries in one query
        if all_payment_entry_names:
            payment_entries = frappe.get_all(
                "Payment Entry",
                filters={"name": ["in", list(all_payment_entry_names)], "docstatus": ["!=", 2]},
                fields=["name", "posting_date", "mode_of_payment"],
            )
            cache.payment_entries_data = {pe.name: pe for pe in payment_entries}

        return cache

    def _update_donation_history(self, member_doc: "Document") -> int:
        """Update donation history for a member using DonationHistoryManager.

        Synchronizes donation records from Donor document to member's donation_history
        child table using the centralized DonationHistoryManager.

        Args:
            member_doc: Member document object

        Returns:
            int: Number of donation history changes (additions or removals)
        """
        if not (hasattr(member_doc, "donor") and member_doc.donor):
            return 0

        from verenigingen.utils.donation_history_manager import sync_donor_history

        # Sync uses the proper manager - check if it made changes
        original_donation_count = len(getattr(member_doc, "donation_history", []))
        sync_donor_history(member_doc.donor)
        # Reload to get updated donation history
        member_doc.reload()
        new_donation_count = len(getattr(member_doc, "donation_history", []))
        return abs(new_donation_count - original_donation_count)

    def _update_volunteer_expense_history(self, member_doc: "Document") -> int:
        """
        DEPRECATED: Volunteer expense history feature has been archived.

        The volunteer_expenses child table was removed from the Member DocType.
        This method is retained for backward compatibility but performs no operations.

        Scheduled for removal in v3.0.

        Args:
            member_doc: Member document object

        Returns:
            int: Always returns 0 (no changes)
        """
        # Feature archived - volunteer_expenses child table no longer exists
        return 0

    def _update_dues_payment_history(
        self, member_doc: "Document", payment_cache: PaymentReferenceCache
    ) -> int:
        """
        Rebuild membership dues payment history from Payment Entries with custom_member field
        that are NOT already reconciled with the member's Sales Invoices.

        Payment Entries that are reconciled with invoices are represented in the invoice
        history rows (created by _update_invoice_payment_history). This method only creates
        standalone rows for UNRECONCILED/UNALLOCATED payments.

        Args:
            member_doc: Member document object
            payment_cache: Prefetched payment reference data from _prefetch_payment_references()

        Returns:
            int: Total number of changes (adds + updates + removals)
        """
        removed_count = 0
        updated_count = 0
        added_count = 0

        # Get ALL dues payments (Payment Entries linked via custom_member) - full rebuild
        current_payments = frappe.get_all(
            "Payment Entry",
            filters={
                "custom_member": member_doc.name,
                "docstatus": 1,  # Only submitted payment entries
                "payment_type": "Receive",  # Only incoming payments
            },
            fields=[
                "name",
                "posting_date",
                "paid_amount",
                "received_amount",
                "reference_no",
                "reference_date",
                "mode_of_payment",
                "remarks",
            ],
            order_by="posting_date desc",
        )

        # Use cached reconciled payment entries to filter out payments already shown via invoices
        # This avoids redundant queries - the data was prefetched by _prefetch_payment_references()
        unreconciled_payments = [
            p for p in current_payments if p.name not in payment_cache.reconciled_payment_entries
        ]

        # Build a lookup of existing payment entries in history
        existing_payments = {row.payment_entry: row for row in (member_doc.payment_history or [])}
        current_payment_names = {payment.name for payment in unreconciled_payments}

        # Remove dues payment entries that no longer exist in database
        rows_to_remove = [
            idx
            for idx, row in enumerate(member_doc.payment_history or [])
            if row.payment_entry
            and row.payment_entry not in current_payment_names
            and row.transaction_type == "Membership Dues Payment"  # Only remove dues payments
        ]

        # Remove in reverse order to maintain indices
        for idx in reversed(rows_to_remove):
            member_doc.payment_history.pop(idx)
            removed_count += 1

        # Process each unreconciled payment (reconciled ones are shown via invoice rows)
        for payment in unreconciled_payments:
            # Build notes with reference_no if available (e.g., Mollie transaction ID)
            notes_parts = []
            if payment.remarks:
                notes_parts.append(payment.remarks)
            if payment.reference_no:
                notes_parts.append(f"Ref: {payment.reference_no}")

            expected_row = {
                "payment_entry": payment.name,
                "payment_entry_doctype": "Payment Entry",
                "transaction_type": "Membership Dues Payment",
                "posting_date": payment.posting_date,
                "payment_date": payment.posting_date,
                "amount": payment.received_amount or payment.paid_amount,
                "paid_amount": payment.received_amount or payment.paid_amount,
                "payment_status": "Paid",
                "payment_method": payment.mode_of_payment,
                # NOTE: reference_name is a Dynamic Link field requiring reference_doctype.
                # For dues payments, reference should link to Payment Entry (already in payment_entry field)
                # or be empty. Do NOT store arbitrary strings like Mollie transaction IDs here.
                "reference_doctype": None,
                "reference_name": None,
                "reconciled": 0,  # Unallocated payments are not reconciled
                "notes": " | ".join(notes_parts) if notes_parts else "",
            }

            if payment.name in existing_payments:
                # Check if existing row needs updating
                existing_row = existing_payments[payment.name]
                needs_update = any(
                    getattr(existing_row, field_name, None) != expected_value
                    for field_name, expected_value in expected_row.items()
                )

                if needs_update:
                    for field_name, expected_value in expected_row.items():
                        setattr(existing_row, field_name, expected_value)
                    updated_count += 1
            else:
                # Add new row
                try:
                    member_doc.append("payment_history", expected_row)
                    added_count += 1
                except Exception as e:
                    self.logger.error(
                        f"Failed to append dues payment {payment.name} for {member_doc.name}: {str(e)}"
                    )
                    # Continue processing other entries - don't break entire update
                    continue

        return removed_count + updated_count + added_count

    @staticmethod
    def _determine_payment_status(invoice, paid_amount: float) -> str:
        """Determine payment status string from invoice data and paid amount.

        Args:
            invoice: Invoice dict with docstatus, status, outstanding_amount, grand_total
            paid_amount: Total amount paid against this invoice

        Returns:
            Payment status string: Draft, Paid, Overdue, Cancelled, Partially Paid, or Unpaid
        """
        if invoice.docstatus == 0:
            return "Draft"
        if invoice.status == "Paid" or invoice.outstanding_amount <= 0:
            return "Paid"
        if invoice.status == "Overdue":
            return "Overdue"
        if invoice.status == "Cancelled":
            return "Cancelled"
        if paid_amount > 0 and paid_amount < invoice.grand_total:
            return "Partially Paid"
        return "Unpaid"

    @staticmethod
    def _resolve_payment_entry(payment_refs, payment_entries_data):
        """Resolve the most recent payment entry from prefetched reference data.

        Args:
            payment_refs: List of payment reference dicts for an invoice
            payment_entries_data: Dict mapping payment entry name → payment entry data

        Returns:
            Tuple of (payment_entry_name, payment_date, payment_method, reconciled)
        """
        if not payment_refs:
            return None, None, None, 0

        parent_names = [ref.parent for ref in payment_refs]
        valid_payments = [payment_entries_data[name] for name in parent_names if name in payment_entries_data]

        if not valid_payments:
            return None, None, None, 0

        most_recent = max(valid_payments, key=lambda p: p.posting_date)
        return (
            most_recent.name,
            most_recent.posting_date,  # ast-skip: Payment Entry field
            most_recent.mode_of_payment,  # ast-skip: Payment Entry field
            1,
        )

    @staticmethod
    def _build_invoice_history_row(
        invoice, payment_entry, payment_date, payment_method, paid_amount, reconciled, payment_status
    ):
        """Build a payment history row dict from invoice and payment data.

        Args:
            invoice: Invoice dict with all required fields
            payment_entry: Payment entry name or None
            payment_date: Payment date or None
            payment_method: Payment method string or None
            paid_amount: Total paid amount
            reconciled: 1 if reconciled, 0 otherwise
            payment_status: Status string from _determine_payment_status

        Returns:
            Dict suitable for appending to member_doc.payment_history
        """
        return {
            "invoice": invoice.name,
            "invoice_doctype": "Sales Invoice",
            "posting_date": invoice.posting_date,
            "due_date": invoice.due_date,
            "amount": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "payment_status": payment_status,
            "status": invoice.status,
            "payment_date": payment_date,
            "payment_entry": payment_entry,
            "payment_method": payment_method,
            "paid_amount": paid_amount,
            "reconciled": reconciled,
            "coverage_start_date": invoice.custom_coverage_start_date,
            "coverage_end_date": invoice.custom_coverage_end_date,
            "transaction_type": "Membership Invoice" if invoice.is_membership_invoice else "Regular Invoice",
            "reference_doctype": None,
            "reference_name": None,
        }

    def _update_invoice_payment_history(
        self, member_doc: "Document", payment_cache: PaymentReferenceCache
    ) -> int:
        """
        Rebuild membership invoice payment history from ALL Sales Invoices linked to member's customer.

        Args:
            member_doc: Member document object
            payment_cache: Prefetched payment reference data from _prefetch_payment_references()

        Returns:
            int: Total number of changes (adds + updates + removals)
        """
        if not member_doc.customer:
            return 0

        removed_count = 0
        updated_count = 0
        added_count = 0

        # Get ALL Sales Invoices for this member's customer - full rebuild
        current_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member_doc.customer,
                "docstatus": ["!=", 2],  # Exclude cancelled
            },
            fields=[
                "name",
                "posting_date",
                "due_date",
                "grand_total",
                "outstanding_amount",
                "status",
                "docstatus",
                "custom_coverage_start_date",
                "custom_coverage_end_date",
                "is_membership_invoice",
            ],
            order_by="posting_date desc",
        )

        # Build a lookup of existing invoices in history
        existing_invoices = {row.invoice: row for row in (member_doc.payment_history or []) if row.invoice}
        current_invoice_names = {invoice.name for invoice in current_invoices}

        # Remove invoice entries that no longer exist in database
        rows_to_remove = [
            idx
            for idx, row in enumerate(member_doc.payment_history or [])
            if row.invoice
            and row.invoice not in current_invoice_names
            and row.invoice_doctype == "Sales Invoice"
        ]

        for idx in reversed(rows_to_remove):
            member_doc.payment_history.pop(idx)
            removed_count += 1

        # Use prefetched payment reference data from cache
        payment_refs_by_invoice = payment_cache.payment_refs_by_invoice
        payment_entries_data = payment_cache.payment_entries_data

        # Process each current invoice
        for invoice in current_invoices:
            try:
                payment_refs = payment_refs_by_invoice.get(invoice.name, [])
                paid_amount = sum(float(ref.allocated_amount or 0) for ref in payment_refs)

                payment_entry, payment_date, payment_method, reconciled = self._resolve_payment_entry(
                    payment_refs, payment_entries_data
                )
                payment_status = self._determine_payment_status(invoice, paid_amount)
                expected_row = self._build_invoice_history_row(
                    invoice,
                    payment_entry,
                    payment_date,
                    payment_method,
                    paid_amount,
                    reconciled,
                    payment_status,
                )

                if invoice.name in existing_invoices:
                    existing_row = existing_invoices[invoice.name]
                    needs_update = any(
                        getattr(existing_row, field_name, None) != expected_value
                        for field_name, expected_value in expected_row.items()
                    )

                    if needs_update:
                        for field_name, expected_value in expected_row.items():
                            setattr(existing_row, field_name, expected_value)
                        updated_count += 1
                else:
                    try:
                        member_doc.append("payment_history", expected_row)
                        added_count += 1
                    except Exception as e:
                        self.logger.error(
                            f"Failed to append invoice {invoice.name} for {member_doc.name}: {str(e)}"
                        )
                        continue

            except Exception as e:
                self.logger.error(f"Failed to process invoice {invoice.name} for {member_doc.name}: {str(e)}")
                continue

        return removed_count + updated_count + added_count

    def _batch_fetch_with_chunking(
        self,
        doctype: str,
        name_list: List[str],
        fields: List[str],
        filters: Optional[Dict[str, Any]] = None,
        chunk_size: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Fetch records in batches to avoid SQL IN() clause limits.

        Args:
            doctype: DocType to query
            name_list: List of names to fetch
            fields: Fields to retrieve
            filters: Additional filters (will be merged with name IN clause)
            chunk_size: Maximum items per batch (default: 500)

        Returns:
            list: List of fetched records
        """
        if not name_list:
            return []

        results = []
        base_filters = filters or {}

        for i in range(0, len(name_list), chunk_size):
            chunk = name_list[i : i + chunk_size]
            chunk_filters = {**base_filters, "name": ["in", chunk]}

            chunk_results = frappe.get_all(doctype, filters=chunk_filters, fields=fields)
            results.extend(chunk_results)

        return results

    def _build_expense_entries_batched(
        self, member_doc: "Document", claims: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        DEPRECATED: Volunteer expense history feature has been archived.

        This method was used for batch-building expense entries with optimized queries.
        The volunteer_expenses child table was removed from the Member DocType.

        Retained for backward compatibility with existing code/tests.
        Scheduled for removal in v3.0.

        Args:
            member_doc: Member document object
            claims: List of expense claim data (ignored)

        Returns:
            list: Always returns empty list
        """
        # Feature archived - volunteer_expenses child table no longer exists
        return []

    def _build_lightweight_expense_entry(self, member_doc: "Document", claim_data) -> dict:
        """
        DEPRECATED: Volunteer expense history feature has been archived.

        This method was used for building individual expense entries.
        The volunteer_expenses child table was removed from the Member DocType.

        Retained for backward compatibility with existing code/tests.
        Scheduled for removal in v3.0.

        Args:
            member_doc: Member document object
            claim_data: Expense claim data (ignored)

        Returns:
            dict: Empty expense entry dictionary
        """
        # Feature archived - return minimal stub for backward compatibility
        return {
            "expense_claim": getattr(claim_data, "name", claim_data.get("name", "")),
            "volunteer": None,
            "posting_date": None,
            "total_claimed_amount": 0,
            "total_sanctioned_amount": 0,
            "status": "Archived",
            "payment_entry": None,
            "payment_date": None,
            "paid_amount": 0,
            "payment_method": None,
            "payment_status": "Archived",
        }

    def refresh_fee_change_history(self, member_name: str) -> OperationResult[Dict[str, Any]]:
        """
        Refresh fee change history from dues schedules and amendments with integrity checking.

        This method performs a complete rebuild of the member's fee_change_history child table
        by pulling data from:
        1. Membership Dues Schedules (for schedule creation events)
        2. Contribution Amendment Requests (for fee adjustments)

        The process includes:
        - Cleaning broken history entries via HistoryIntegrityManager
        - Processing applied amendments to capture fee changes
        - Processing dues schedules for initial schedule creation
        - Using secure_document_operation for atomic updates

        Args:
            member_name: Name/ID of the member document

        Returns:
            OperationResult[Dict[str, Any]]: Result with metadata:
                - history_count (int): Total history entries processed
                - amendments_found (int): Number of amendments processed
                - dues_schedules_found (int): Number of schedules processed
                - removed_entries (int): Number of broken entries cleaned
                - cleanup_details (dict): Detailed cleanup statistics
                - method (str): Method used (atomic_with_amendments/no_changes)
                - reload_doc (bool, optional): Whether to reload document

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - All errors logged and returned as OperationResult.fail()
        """
        try:
            # Import dependencies
            from verenigingen.utils.member_history_integrity import cleanup_member_history
            from verenigingen.utils.secure_operations import secure_document_operation

            # Get the member document - use get_doc with for_update to handle concurrency
            member_doc = frappe.get_doc("Member", member_name, for_update=True)

            # STEP 1: Clean broken history entries (all types for consistency)
            cleanup_result = cleanup_member_history(member_doc)
            # Extract fee-specific stats for backward compatibility
            cleanup_stats = {
                "removed": cleanup_result["fee_history"]["removed"],
                "reasons": {"total": cleanup_result["fee_history"]["removed"]},
                "errors": cleanup_result["fee_history"]["errors"],
            }

            # Get all dues schedules for this member
            dues_schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": member_name},
                fields=["name", "schedule_name", "dues_rate", "billing_frequency", "status", "creation"],
                order_by="creation",
            )

            # Get existing fee change history entries - track by both schedule and amendment
            existing_entries_by_schedule = {
                row.dues_schedule: row for row in member_doc.fee_change_history or [] if row.dues_schedule
            }
            existing_entries_by_amendment = {
                row.amendment_request: row
                for row in member_doc.fee_change_history or []
                if row.amendment_request
            }

            # STEP 2: Get all applied amendments for this member
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

            # Track if any changes are made to avoid unnecessary saves
            changes_made = False

            # Process amendments first to capture all changes
            for amendment in applied_amendments:
                amendment_name = amendment.name

                # Check if we already have an entry for this amendment
                if amendment_name not in existing_entries_by_amendment:
                    # Add new amendment entry
                    amendment_data = {
                        "amendment_request": amendment_name,
                        "dues_rate": amendment.requested_amount,
                        "old_dues_rate": amendment.current_amount or 0,
                        "change_type": "Fee Adjustment",
                        "reason": (
                            f"Amendment: {amendment.reason}"
                            if amendment.reason
                            else f"Amendment {amendment_name}"
                        ),
                        "change_date": amendment.applied_date or amendment.effective_date,
                        "changed_by": amendment.applied_by or "Administrator",
                    }
                    member_doc.add_fee_change_to_history(amendment_data)
                    changes_made = True

            # STEP 3: Process schedules (for initial schedule creation only)
            for schedule in dues_schedules:
                schedule_name = schedule.name

                # Check if entry already exists for this schedule
                if schedule_name in existing_entries_by_schedule:
                    # Update existing entry if needed
                    existing_entry = existing_entries_by_schedule[schedule_name]

                    # Check if update is needed (compare key fields)
                    needs_update = (
                        existing_entry.new_dues_rate != schedule.dues_rate
                        or existing_entry.billing_frequency  # ast-skip: Dues Schedule field
                        != schedule.billing_frequency
                        or existing_entry.reason  # ast-skip: Member Fee Change History field
                        != f"Dues schedule: {schedule.schedule_name or schedule.name}"
                    )

                    if needs_update:
                        # Use atomic update method
                        schedule_data = {
                            "name": schedule.name,
                            "schedule_name": schedule.schedule_name,
                            "dues_rate": schedule.dues_rate,
                            "billing_frequency": schedule.billing_frequency,
                            "old_dues_rate": existing_entry.old_dues_rate,  # Preserve old rate
                            "change_type": "Fee Adjustment",
                            "reason": f"Dues schedule: {schedule.schedule_name or schedule.name}",
                            "change_date": frappe.utils.now_datetime(),  # Update timestamp
                            "changed_by": frappe.session.user or "Administrator",
                        }
                        member_doc.update_fee_change_in_history(schedule_data)
                        changes_made = True
                else:
                    # Add new entry using atomic method (initial schedule creation only)
                    schedule_data = {
                        "name": schedule.name,
                        "schedule_name": schedule.schedule_name,
                        "dues_rate": schedule.dues_rate,
                        "billing_frequency": schedule.billing_frequency,
                        "creation": schedule.creation,
                        "old_dues_rate": 0,  # First schedule for this member
                        "change_type": "Schedule Created",
                        "reason": f"Dues schedule: {schedule.schedule_name or schedule.name}",
                        "changed_by": frappe.session.user or "Administrator",
                    }
                    member_doc.add_fee_change_to_history(schedule_data)
                    changes_made = True

            # Account for cleanup operations that may have removed entries
            if cleanup_stats["removed"] > 0:
                changes_made = True

            # Only save if changes were made
            if not changes_made:
                result_data = {
                    "history_count": len(member_doc.fee_change_history or []),
                    "amendments_found": len(applied_amendments),
                    "dues_schedules_found": len(dues_schedules),
                    "removed_entries": 0,
                    "cleanup_details": cleanup_stats,
                    "method": "no_changes",
                }
                return OperationResult.ok(
                    result_data, message=f"Fee change history is already up to date for {member_name}"
                )

            # Fee history updates are administrative operations that preserve audit trail
            member_doc.flags.ignore_validate_update_after_submit = True  # JUSTIFIED: Fee history update

            fee_history_result = secure_document_operation(
                operation="update_child_table",
                doc=member_doc,
                justification=f"Update fee change history for member {member_doc.name}",
                required_permissions=["Member:write"],
                allow_system_user=False,  # Require explicit user permissions for financial data
                bypass_validations=["link_validation"],  # Allow bypass of problematic chapter references
            )

            if not fee_history_result.success:
                # Log full traceback for debugging
                self.logger.error(
                    f"Fee history update failed for {member_doc.name}: {'; '.join(fee_history_result.errors)}"
                )
                frappe.throw(
                    frappe._("Failed to update fee change history: {0}").format(
                        "; ".join(fee_history_result.errors)
                    )
                )

            # Commit the changes to ensure they're saved
            frappe.db.commit()

            result_data = {
                "history_count": len(applied_amendments) + len(dues_schedules),
                "reload_doc": True,  # Signal to reload the document
                "amendments_found": len(applied_amendments),
                "dues_schedules_found": len(dues_schedules),
                "removed_entries": cleanup_stats["removed"],
                "cleanup_details": cleanup_stats,
                "method": "atomic_with_amendments",
            }

            return OperationResult.ok(
                result_data,
                message=f"Fee change history refreshed for {member_name} - {len(applied_amendments)} amendments + {len(dues_schedules)} schedules processed, {cleanup_stats['removed']} broken entries cleaned",
            )

        except Exception as e:
            log_operation_error("HIST_006", f"member {member_name}", e)
            error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)  # Truncate long errors
            return OperationResult.fail(
                f"Error: {error_msg}",
                errors=[str(e)],
                error_code="HIST_006",
                member=member_name,
            )


def get_member_history_update_service() -> MemberHistoryUpdateService:
    """Get singleton instance of MemberHistoryUpdateService"""
    return MemberHistoryUpdateService()
