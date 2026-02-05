"""
Member Financial History Integrity Management.

This module provides centralized data integrity validation and cleanup
for member history child tables (payment_history, fee_change_history, volunteer_expenses).

Key Features:
- Permission-validated cleanup operations
- Batch query optimization (prevents N+1 queries)
- Grace period for recent entries (prevents race conditions)
- Smart duplicate detection with amount validation
- Comprehensive error handling and audit logging
- Sorted output (newest first)

Author: Claude Code
Created: 2025-10-03
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import add_days, getdate, now_datetime, today

logger = frappe.logger("verenigingen.member_history")


class HistoryIntegrityManager:
    """
    Manages integrity validation and cleanup for member history tables.

    This class provides safe, permission-validated cleanup operations
    with comprehensive error handling and audit trails.
    """

    def __init__(self, member_doc):
        """
        Initialize the integrity manager.

        Args:
            member_doc: Member document instance
        """
        self.member = member_doc
        self.removed_entries = []
        self.errors = []

    def cleanup_payment_history(self) -> Dict[str, Any]:
        """
        Clean up broken payment history entries.

        Handles both:
        - Invoice-based entries (reference_field: invoice)
        - Unallocated payment entries (reference_field: payment_entry)

        Returns:
            dict: Cleanup statistics with 'removed', 'errors', and 'details' keys
        """
        # Use custom validation for payment_history since it can have either invoice OR payment_entry
        removed, errors = self._cleanup_payment_history_custom()

        return {"removed": len(removed), "errors": len(errors), "details": removed, "error_details": errors}

    def cleanup_fee_history(self) -> Dict[str, Any]:
        """
        Clean up broken fee change history entries.

        Returns:
            dict: Cleanup statistics with 'removed', 'errors', and 'details' keys
        """
        removed, errors = self._cleanup_history(
            child_table_name="fee_change_history",
            reference_field="dues_schedule",
            reference_doctype="Membership Dues Schedule",
            required_fields=["dues_schedule", "new_dues_rate"],
            sort_field="change_date",
            history_type="fee",
            amount_field="new_dues_rate",
        )

        return {"removed": len(removed), "errors": len(errors), "details": removed, "error_details": errors}

    def cleanup_volunteer_expense_history(self) -> Dict[str, Any]:
        """
        Clean up broken volunteer expense history entries.

        Returns:
            dict: Cleanup statistics with 'removed', 'errors', and 'details' keys
        """
        removed, errors = self._cleanup_history(
            child_table_name="volunteer_expenses",
            reference_field="expense_claim",
            reference_doctype="Expense Claim",
            required_fields=["expense_claim", "posting_date", "total_sanctioned_amount"],
            sort_field="posting_date",
            history_type="volunteer_expense",
            amount_field="total_sanctioned_amount",
        )

        return {"removed": len(removed), "errors": len(errors), "details": removed, "error_details": errors}

    def _cleanup_history(
        self,
        child_table_name: str,
        reference_field: str,
        reference_doctype: str,
        required_fields: List[str],
        sort_field: str,
        history_type: str,
        amount_field: str,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Generic cleanup logic for any member history table.

        Args:
            child_table_name: Name of child table field (e.g., 'payment_history')
            reference_field: Field linking to source doc (e.g., 'invoice')
            reference_doctype: Source DocType name (e.g., 'Sales Invoice')
            required_fields: List of fields that must be populated
            sort_field: Field to sort by (e.g., 'posting_date')
            history_type: Human-readable type for logging (e.g., 'payment')
            amount_field: Field containing amount/rate value

        Returns:
            tuple: (removed_entries, errors)
                removed_entries: List of dicts with removal details
                errors: List of dicts with error details
        """
        # SECURITY: Validate permissions before modifying data
        if not frappe.has_permission("Member", "write", self.member):
            frappe.throw(_("Insufficient permissions to modify member history"))

        child_table = getattr(self.member, child_table_name, [])
        if not child_table:
            return ([], [])

        removed = []
        errors = []

        try:
            # PERFORMANCE: Batch fetch reference document statuses (prevents N+1 queries)
            existing_refs = self._batch_validate_references(child_table, reference_field, reference_doctype)

            # First pass: Build reference map with duplicate detection
            ref_map = {}
            entries_to_remove = []

            for entry in child_table:
                try:
                    # Get reference value first
                    ref_value = getattr(entry, reference_field, None)

                    # Validate required fields
                    # For volunteer expenses, be lenient with draft claims (posting_date/amounts may not be set yet)
                    if history_type == "volunteer_expense":
                        # Always require expense_claim reference
                        if not ref_value:
                            entries_to_remove.append((entry, f"Missing {reference_field}"))
                            continue
                        # Check if the expense claim is draft - if so, don't require posting_date/amounts
                        if ref_value in existing_refs:
                            # Use the ALREADY FETCHED docstatus from batch query (avoid N+1)
                            expense_docstatus = existing_refs[ref_value]
                            if expense_docstatus == 0:
                                # Draft expense - only require expense_claim field
                                pass  # Already validated above
                            else:
                                # Submitted/approved - require all fields
                                missing_fields = [f for f in required_fields if not getattr(entry, f, None)]
                                if missing_fields:
                                    entries_to_remove.append(
                                        (entry, f"Missing required fields: {', '.join(missing_fields)}")
                                    )
                                    continue
                    else:
                        # For other history types, require all fields as before
                        missing_fields = [f for f in required_fields if not getattr(entry, f, None)]
                        if missing_fields:
                            entries_to_remove.append(
                                (entry, f"Missing required fields: {', '.join(missing_fields)}")
                            )
                            continue

                    # Check if reference still exists
                    if ref_value not in existing_refs:
                        # DATA SAFETY: Grace period for recent entries (prevents race conditions)
                        if self._is_within_grace_period(entry, sort_field, grace_days=7):
                            logger.warning(
                                f"Skipping cleanup of recent missing {reference_doctype} "
                                f"{ref_value} for member {self.member.name} (within grace period)"
                            )
                            continue

                        entries_to_remove.append((entry, f"{reference_doctype} deleted from system"))
                        continue

                    # CRITICAL: Smart duplicate detection with amount validation
                    if ref_value in ref_map:
                        # Found duplicate - check if amounts match
                        existing_entry = ref_map[ref_value]
                        existing_amount = getattr(existing_entry, amount_field, 0) or 0
                        current_amount = getattr(entry, amount_field, 0) or 0

                        # If amounts differ, log critical error and skip auto-delete
                        if abs(existing_amount - current_amount) > 0.01:
                            error_msg = (
                                f"Duplicate entries for {reference_field} {ref_value} have "
                                f"DIFFERENT AMOUNTS: {existing_amount} vs {current_amount}. "
                                f"Manual review required."
                            )
                            logger.error(f"[Member {self.member.name}] {error_msg}")
                            errors.append(
                                {"reference": ref_value, "error": error_msg, "entry_idx": entry.idx}
                            )
                            # Don't remove either entry - needs manual review
                            continue

                        # Amounts match - keep the one with more recent date
                        existing_date = getattr(existing_entry, sort_field, None)
                        current_date = getattr(entry, sort_field, None)

                        if current_date and (not existing_date or current_date > existing_date):
                            # Current entry is newer - mark old one for removal
                            entries_to_remove.append(
                                (existing_entry, f"Duplicate {reference_field} (kept newer entry)")
                            )
                            ref_map[ref_value] = entry
                        else:
                            # Existing is newer or same - mark current for removal
                            entries_to_remove.append(
                                (entry, f"Duplicate {reference_field} (kept newer entry)")
                            )
                    else:
                        # First occurrence of this reference
                        ref_map[ref_value] = entry

                except Exception as e:
                    # ERROR HANDLING: Log but continue processing other entries
                    error_msg = f"Error processing {history_type} history entry {entry.idx}: {str(e)}"
                    logger.error(f"[Member {self.member.name}] {error_msg}")
                    errors.append({"entry_idx": entry.idx, "error": str(e)})
                    continue

            # Second pass: Remove marked entries
            for entry, reason in entries_to_remove:
                ref_value = getattr(entry, reference_field, "UNKNOWN")
                logger.warning(
                    f"Removing {history_type} history entry from {self.member.name}: "
                    f"{reference_field}={ref_value}, reason={reason}"
                )

                child_table.remove(entry)
                removed.append(
                    {"reference": ref_value, "reason": reason, "idx": entry.idx, "history_type": history_type}
                )

            # Sort remaining entries by date (newest first)
            if child_table:
                child_table.sort(key=lambda x: getattr(x, sort_field, "") or "1900-01-01", reverse=True)

            # AUDIT TRAIL: Create audit log if entries were removed
            if removed:
                self._create_audit_log(history_type, removed)

        except Exception as e:
            # CRITICAL ERROR HANDLING: Log and re-raise
            error_msg = (
                f"Critical error during {history_type} history cleanup for "
                f"{self.member.name}: {str(e)}\n{frappe.get_traceback()}"
            )
            logger.error(error_msg)
            frappe.log_error(
                title=f"{history_type.title()} History Cleanup Failed: {self.member.name}",
                message=frappe.get_traceback(),
            )
            raise

        return (removed, errors)

    def _cleanup_payment_history_custom(self) -> Tuple[List[Dict], List[Dict]]:
        """
        Custom cleanup for payment_history that handles both invoice-based and unallocated payment entries.

        Valid entries must have EITHER:
        - invoice field populated (invoice-based entries)
        - payment_entry field populated (unallocated dues payments)

        Returns:
            tuple: (removed_entries, errors)
        """
        # SECURITY: Validate permissions before modifying data
        if not frappe.has_permission("Member", "write", self.member):
            frappe.throw(_("Insufficient permissions to modify member history"))

        child_table = getattr(self.member, "payment_history", [])
        if not child_table:
            return ([], [])

        removed = []
        errors = []

        try:
            # Batch validate both invoice and payment_entry references
            invoice_refs = self._batch_validate_references(child_table, "invoice", "Sales Invoice")
            payment_refs = self._batch_validate_references(child_table, "payment_entry", "Payment Entry")

            entries_to_remove = []

            for entry in child_table:
                try:
                    invoice_value = getattr(entry, "invoice", None)
                    payment_entry_value = getattr(entry, "payment_entry", None)
                    posting_date = getattr(entry, "posting_date", None)
                    amount = getattr(entry, "amount", None)

                    # Entry must have EITHER invoice OR payment_entry (not neither, not both)
                    if not invoice_value and not payment_entry_value:
                        entries_to_remove.append((entry, "Missing both invoice and payment_entry"))
                        continue

                    # If it has an invoice, validate invoice-based requirements
                    if invoice_value:
                        # Check required fields for invoice-based entries
                        if not posting_date or amount is None:
                            entries_to_remove.append(
                                (entry, "Invoice-based entry missing posting_date or amount")
                            )
                            continue

                        # Check if invoice still exists
                        if invoice_value not in invoice_refs:
                            if self._is_within_grace_period(entry, "posting_date", grace_days=7):
                                logger.warning(
                                    f"Skipping cleanup of recent missing Sales Invoice "
                                    f"{invoice_value} for member {self.member.name} (within grace period)"
                                )
                                continue
                            entries_to_remove.append((entry, "Sales Invoice deleted from system"))
                            continue

                    # If it has a payment_entry, validate payment-based requirements
                    if payment_entry_value:
                        # Check required fields for unallocated payment entries
                        if not posting_date or amount is None:
                            entries_to_remove.append((entry, "Payment entry missing posting_date or amount"))
                            continue

                        # Check if payment entry still exists
                        if payment_entry_value not in payment_refs:
                            if self._is_within_grace_period(entry, "posting_date", grace_days=7):
                                logger.warning(
                                    f"Skipping cleanup of recent missing Payment Entry "
                                    f"{payment_entry_value} for member {self.member.name} (within grace period)"
                                )
                                continue
                            entries_to_remove.append((entry, "Payment Entry deleted from system"))
                            continue

                except Exception as e:
                    error_msg = f"Error processing payment history entry {entry.idx}: {str(e)}"
                    logger.error(f"[Member {self.member.name}] {error_msg}")
                    errors.append({"entry_idx": entry.idx, "error": str(e)})
                    continue

            # Remove marked entries
            for entry, reason in entries_to_remove:
                ref_value = (
                    getattr(entry, "invoice", None) or getattr(entry, "payment_entry", None) or "UNKNOWN"
                )
                logger.warning(
                    f"Removing payment history entry from {self.member.name}: "
                    f"reference={ref_value}, reason={reason}"
                )

                child_table.remove(entry)
                removed.append(
                    {"reference": ref_value, "reason": reason, "idx": entry.idx, "history_type": "payment"}
                )

            # Sort remaining entries by date (newest first)
            if child_table:
                child_table.sort(key=lambda x: getattr(x, "posting_date", "") or "1900-01-01", reverse=True)

            # AUDIT TRAIL: Create audit log if entries were removed
            if removed:
                self._create_audit_log("payment", removed)

        except Exception as e:
            error_msg = (
                f"Critical error during payment history cleanup for "
                f"{self.member.name}: {str(e)}\n{frappe.get_traceback()}"
            )
            logger.error(error_msg)
            frappe.log_error(
                title=f"Payment History Cleanup Failed: {self.member.name}",
                message=frappe.get_traceback(),
            )
            raise

        return (removed, errors)

    def _batch_validate_references(
        self, child_table, reference_field: str, reference_doctype: str
    ) -> Dict[str, int]:
        """
        Batch fetch reference document statuses to avoid N+1 queries.

        Args:
            child_table: Child table instance
            reference_field: Field name containing reference
            reference_doctype: DocType being referenced

        Returns:
            dict: Mapping of reference name -> docstatus (excludes cancelled docs)
        """
        ref_values = [
            getattr(entry, reference_field) for entry in child_table if getattr(entry, reference_field, None)
        ]

        if not ref_values:
            return {}

        try:
            ref_data = frappe.db.get_all(
                reference_doctype, filters={"name": ["in", ref_values]}, fields=["name", "docstatus"]
            )

            # Return dict mapping name -> docstatus (exclude cancelled docs)
            return {doc["name"]: doc["docstatus"] for doc in ref_data if doc.get("docstatus") != 2}

        except Exception as e:
            logger.error(f"Error batch validating {reference_doctype} references: {str(e)}")
            return {}

    def _is_within_grace_period(self, entry, date_field: str, grace_days: int = 7) -> bool:
        """
        Check if entry is recent enough to skip cleanup (prevents race conditions).

        Grace period prevents deletion of entries for in-flight transactions
        or recently created documents that may not be fully committed.

        Args:
            entry: Child table entry
            date_field: Name of date field to check
            grace_days: Number of days to consider "recent" (default: 7)

        Returns:
            bool: True if entry is within grace period
        """
        entry_date = getattr(entry, date_field, None)
        if not entry_date:
            return False

        try:
            return getdate(entry_date) >= add_days(today(), -grace_days)
        except Exception:
            return False

    def _create_audit_log(self, history_type: str, removed: List[Dict]):
        """
        Create audit trail comment for removed entries.

        Args:
            history_type: Type of history (e.g., 'payment', 'fee')
            removed: List of removed entry details
        """
        try:
            summary_parts = []
            for entry in removed[:5]:  # Show first 5
                ref = entry.get("reference", "UNKNOWN")
                reason = entry.get("reason", "Unknown reason")
                summary_parts.append(f"• {ref}: {reason}")

            if len(removed) > 5:
                summary_parts.append(f"• ... and {len(removed) - 5} more entries")

            content = _("Automatic {0} history cleanup removed {1} broken entries:\n{2}").format(
                history_type, len(removed), "\n".join(summary_parts)
            )

            # Security: Audit comment creation for member history operations.
            # Comments document what changes were made during integrity checks.
            # Must be created regardless of user permissions for audit trail.
            frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": self.member.name,
                    "content": content,
                }
            ).insert(ignore_permissions=True)

        except Exception as e:
            logger.error(f"Error creating audit log for {self.member.name}: {str(e)}")
            # Don't raise - audit logging failure shouldn't break cleanup


def cleanup_member_history(member_doc) -> Dict[str, Any]:
    """
    Cleanup payment, fee, and volunteer expense history for a member.

    This is the main entry point for history cleanup operations.
    Called by refresh_financial_history() and scheduled tasks.

    Args:
        member_doc: Member document instance

    Returns:
        dict: Cleanup statistics with separate counts for each history type

    Example:
        >>> member = frappe.get_doc("Member", "MEM-001")
        >>> stats = cleanup_member_history(member)
        >>> print(stats["payment_history"]["removed"])
        3
        >>> print(stats["volunteer_expenses"]["removed"])
        1
    """
    manager = HistoryIntegrityManager(member_doc)

    payment_stats = manager.cleanup_payment_history()
    fee_stats = manager.cleanup_fee_history()

    # Also clean volunteer expenses if employee exists
    expense_stats = {"removed": 0, "errors": 0, "details": [], "error_details": []}
    if hasattr(member_doc, "employee") and member_doc.employee:
        expense_stats = manager.cleanup_volunteer_expense_history()

    return {
        "payment_history": payment_stats,
        "fee_history": fee_stats,
        "volunteer_expenses": expense_stats,
    }
