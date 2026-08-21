"""
Member Financial History Manager

Consolidated manager for member financial history updates including:
- Payment history (invoices, payments, dues)
- Volunteer expense history (expense claims, reimbursements)

This replaces the duplicate logic in payment_mixin.py and expense_mixin.py
with a single, consistent, atomic-update approach.
"""

import random
import time
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe.utils import now


class MemberFinancialHistoryManager:
    """
    Consolidated manager for member financial history updates.

    Handles both payment history and volunteer expense history with:
    - Atomic updates only (no dangerous full-rebuilds)
    - Consistent concurrency protection
    - Proper sorting (newest first)
    - Configurable entry limits
    - Standardized error handling
    """

    def __init__(self, doc, history_field_name: str, max_entries: int = 30):
        """
        Initialize the financial history manager.

        Args:
            doc: The document that OWNS the history table -- a Member on the
                payment/expense/fee-change paths, a Donor on the Mollie
                donation path. It was called `member_doc` until #424, which is
                what let a `tabMember` lock sit unnoticed on the Donor path.
            history_field_name: Field name ('payment_history' or 'volunteer_expenses')
            max_entries: Maximum entries to maintain (default 30)
        """
        self.doc = doc
        self.history_field = history_field_name
        self.max_entries = max_entries

    def add_or_update_entry(
        self, entry_id: str, entry_builder: Callable, id_field_name: str = "invoice"
    ) -> bool:
        """
        Add or update a financial history entry atomically.

        Args:
            entry_id: ID of the entry (invoice name, expense claim name, etc.)
            entry_builder: Function that builds the entry data dictionary
            id_field_name: Field name used to identify entries (default 'invoice')

        Returns:
            bool: Success status
        """
        max_attempts = 5

        for attempt in range(max_attempts):
            try:
                # Lock BEFORE reload to prevent race conditions.
                #
                # The table comes from the document, not from this class's name:
                # the manager is built with whatever doc the caller has, and the
                # Mollie webhook builds it with a Donor. Hard-coding `tabMember`
                # meant that lock matched zero rows on that path and silently
                # took no lock at all -- a FOR UPDATE that matches nothing is not
                # an error. #424.
                frappe.db.get_value(self.doc.doctype, self.doc.name, "name", for_update=True)

                # Reload document to get latest version
                self.doc.reload()

                # Get current history list
                history_list = getattr(self.doc, self.history_field, []) or []

                # Find existing entry
                existing_idx = None
                for idx, entry in enumerate(history_list):
                    if getattr(entry, id_field_name, None) == entry_id:
                        existing_idx = idx
                        break

                # Build entry data
                try:
                    entry_data = entry_builder()
                except Exception as e:
                    frappe.log_error(
                        f"Entry builder failed for {entry_id}: {str(e)}",
                        "Financial History Entry Builder Error",
                    )
                    return False

                # Check if builder returned None (invoice not found, customer mismatch, etc.)
                if entry_data is None:
                    frappe.logger("financial_history").debug(
                        f"Entry builder returned None for {entry_id} in {self.doc.name} {self.history_field} "
                        f"(likely invoice not found or customer mismatch)"
                    )
                    return False

                if existing_idx is not None:
                    # Update existing entry with change detection
                    existing_entry = history_list[existing_idx]
                    data_changed = False

                    for key, value in entry_data.items():
                        if getattr(existing_entry, key, None) != value:
                            setattr(existing_entry, key, value)
                            data_changed = True

                    if not data_changed:
                        # No changes, skip save
                        frappe.logger("financial_history").debug(
                            f"No changes for {entry_id} in {self.doc.name} {self.history_field}"
                        )
                        return True
                else:
                    # Add new entry at the beginning (newest first)
                    self.doc.append(self.history_field, entry_data)

                    # Move new entry to the front for proper chronological order
                    history_list = getattr(self.doc, self.history_field)
                    if len(history_list) > 1:
                        new_entry = history_list.pop()  # Remove from end
                        history_list.insert(0, new_entry)  # Insert at beginning

                # Trim to max entries (remove oldest from the end)
                self._trim_history()

                # Save with concurrency protection
                success = self._save_with_retry()
                if success:
                    frappe.logger("financial_history").info(
                        f"{'Updated' if existing_idx is not None else 'Added'} {entry_id} "
                        f"in {self.doc.name} {self.history_field}"
                    )
                    return True

            except frappe.exceptions.TimestampMismatchError:
                # Race condition detected, retry with backoff
                if attempt < max_attempts - 1:
                    delay = random.uniform(0.1, 0.5) * (2**attempt)  # Exponential backoff
                    time.sleep(delay)
                    # ✅ FIX: Let Frappe handle transaction rollback automatically on exceptions
                    continue
                else:
                    frappe.log_error(
                        f"Race condition in {self.history_field} for {self.doc.name} after {max_attempts} attempts",
                        "Financial History Race Condition",
                    )
                    return False
            except Exception as e:
                frappe.log_error(
                    f"Error updating {self.history_field} for {self.doc.name}: {str(e)}",
                    "Financial History Update Error",
                )
                return False

        return False

    def remove_entry(self, entry_id: str, id_field_name: str = "invoice") -> bool:
        """
        Remove a financial history entry atomically.

        Args:
            entry_id: ID of the entry to remove
            id_field_name: Field name used to identify entries

        Returns:
            bool: Success status
        """
        try:
            # Get current history list
            history_list = getattr(self.doc, self.history_field, []) or []

            # Filter out the entry to remove
            updated_history = []
            removed = False

            for entry in history_list:
                if getattr(entry, id_field_name, None) != entry_id:
                    updated_history.append(entry)
                else:
                    removed = True

            if removed:
                # Remove entry directly from the child table (truly atomic)
                history_list = getattr(self.doc, self.history_field, [])
                for i, entry in enumerate(history_list):
                    if getattr(entry, id_field_name, None) == entry_id:
                        # Remove the specific entry without touching others
                        history_list.pop(i)
                        break

                # Save changes
                success = self._save_with_retry()
                if success:
                    frappe.logger("financial_history").info(
                        f"Removed {entry_id} from {self.doc.name} {self.history_field}"
                    )
                return success

            return True  # Entry wasn't found, consider it successful

        except Exception as e:
            frappe.log_error(
                f"Error removing {entry_id} from {self.history_field}: {str(e)}",
                "Financial History Removal Error",
            )
            return False

    def update_entry_field(
        self, entry_id: str, field_updates: Dict[str, Any], id_field_name: str = "invoice"
    ) -> bool:
        """
        Update specific fields in an existing entry.

        Args:
            entry_id: ID of the entry to update
            field_updates: Dictionary of field names and values to update
            id_field_name: Field name used to identify entries

        Returns:
            bool: Success status
        """
        try:
            history_list = getattr(self.doc, self.history_field, []) or []

            # Find and update the entry
            updated = False
            for entry in history_list:
                if getattr(entry, id_field_name, None) == entry_id:
                    for field_name, field_value in field_updates.items():
                        setattr(entry, field_name, field_value)
                    updated = True
                    break

            if updated:
                success = self._save_with_retry()
                if success:
                    frappe.logger("financial_history").info(
                        f"Updated fields {list(field_updates.keys())} for {entry_id} "
                        f"in {self.doc.name} {self.history_field}"
                    )
                return success

            return False  # Entry not found

        except Exception as e:
            frappe.log_error(
                f"Error updating {entry_id} fields in {self.history_field}: {str(e)}",
                "Financial History Field Update Error",
            )
            return False

    def _trim_history(self):
        """Trim history to max entries, keeping newest entries."""
        history_list = getattr(self.doc, self.history_field, [])

        if len(history_list) > self.max_entries:
            # Keep only the first N entries (newest)
            trimmed_history = history_list[: self.max_entries]

            # Clear and rebuild
            setattr(self.doc, self.history_field, [])
            for entry in trimmed_history:
                self.doc.append(self.history_field, entry)

    def _save_with_retry(self, max_retries: int = 3) -> bool:
        """
        Save the owning document with retry logic and proper flags.
        Uses targeted child table updates to avoid unnecessary validation.

        Args:
            max_retries: Maximum retry attempts

        Returns:
            bool: Success status
        """
        for retry in range(max_retries):
            try:
                # Suppress version tracking for history table cleanup
                # These are maintenance operations, not meaningful changes to track
                self.doc.flags.ignore_version = True

                # Use Frappe's native update_child_table() - no timestamp conflicts!
                #
                # Deliberately does NOT commit. This runs in ordinary request and
                # hook context -- the financial-history batch queue is drained
                # INLINE from add_invoice_to_payment_history(), and the fee-change
                # recorder reaches this from a document save. A transaction-wide
                # commit here flushed whatever the caller had half-finished, and
                # took every savepoint with it (MariaDB discards them all on
                # commit), so FinancialHistoryBatchProcessor's per-member scoped
                # rollback silently became a no-op and its RELEASE raised 1305.
                #
                # Durability belongs to the owning request or scheduled job, which
                # commits at its own boundary. The one caller that wanted it sooner
                # -- bulk_invoice_generation_service, a scheduler job that already
                # committed its invoices before writing history -- now commits for
                # itself, where the decision is visible. #411.
                #
                # TRADE-OFF, stated because it is not free: add_or_update_entry takes
                # `SELECT ... FOR UPDATE` on the owning document's row, and a row lock lives
                # until the transaction ends. That commit used to release it on the
                # spot; without it the lock is held for the rest of the caller's
                # request. That is the correct transactional semantic -- you cannot
                # hold a lock for consistency AND release it early without ending the
                # transaction -- but it is longer contention than before, so a caller
                # that loops over many members must commit per member rather than
                # once at the end. bulk_update_payment_history does exactly that, and
                # says so. The one inner commit still left on this path is #421.
                self.doc.update_child_table(self.history_field)
                return True

            except Exception as e:
                # Check for chapter validation errors specifically
                error_str = str(e)
                if "Could not find Row" in error_str and "Chapter:" in error_str:
                    # This is a chapter reference validation error
                    # Log it specifically and delegate cleanup to dedicated manager
                    frappe.log_error(
                        f"Chapter reference validation error for {self.doc.name}: {error_str}. "
                        f"This suggests invalid chapter references in chapter_membership_history.",
                        "Financial History Chapter Validation Error",
                    )

                    # Try to clean up invalid chapter references if this is not the last retry
                    if retry < max_retries - 1:
                        # Use dedicated chapter reference manager
                        from verenigingen.services.chapter.chapter_reference_manager import (
                            ChapterReferenceManager,
                        )

                        chapter_manager = ChapterReferenceManager(self.doc)
                        removed_count = chapter_manager.cleanup_invalid_chapter_references()

                        if removed_count > 0:
                            frappe.logger().info(
                                f"Chapter cleanup removed {removed_count} invalid references for {self.doc.name}"
                            )

                        time.sleep(0.1 * (retry + 1))
                        # ✅ FIX: Let Frappe handle transaction rollback automatically on exceptions
                        continue
                    else:
                        return False

                elif retry < max_retries - 1:
                    time.sleep(0.1 * (retry + 1))  # Progressive delay
                    # ✅ FIX: Let Frappe handle transaction rollback automatically on exceptions
                    continue
                else:
                    # Truncate error message to prevent cascading truncation errors
                    error_msg = str(e)
                    truncated_error = (error_msg[:50] + "...") if len(error_msg) > 50 else error_msg
                    frappe.log_error(
                        f"Save failed for {self.doc.name} after {max_retries} retries: {truncated_error}",
                        "Financial History Save Error",
                    )
                    return False

        return False


def get_payment_history_manager(member_doc) -> MemberFinancialHistoryManager:
    """Factory function for payment history manager."""
    return MemberFinancialHistoryManager(member_doc, "payment_history", max_entries=30)


def get_expense_history_manager(member_doc) -> MemberFinancialHistoryManager:
    """Factory function for expense history manager."""
    return MemberFinancialHistoryManager(member_doc, "volunteer_expenses", max_entries=30)


def get_fee_change_history_manager(member_doc) -> MemberFinancialHistoryManager:
    """Factory function for fee change history manager."""
    return MemberFinancialHistoryManager(member_doc, "fee_change_history", max_entries=50)
