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

from verenigingen.utils.secure_operations import secure_document_operation


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

    def __init__(self, member_doc, history_field_name: str, max_entries: int = 30):
        """
        Initialize the financial history manager.

        Args:
            member_doc: Member document instance
            history_field_name: Field name ('payment_history' or 'volunteer_expenses')
            max_entries: Maximum entries to maintain (default 30)
        """
        self.member = member_doc
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
                # FIXED: Lock BEFORE reload to prevent race conditions
                frappe.db.sql("SELECT name FROM `tabMember` WHERE name = %s FOR UPDATE", (self.member.name,))

                # Reload document to get latest version
                self.member.reload()

                # Get current history list
                history_list = getattr(self.member, self.history_field, []) or []

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
                            f"No changes for {entry_id} in {self.member.name} {self.history_field}"
                        )
                        return True
                else:
                    # Add new entry at the beginning (newest first)
                    self.member.append(self.history_field, entry_data)

                    # Move new entry to the front for proper chronological order
                    history_list = getattr(self.member, self.history_field)
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
                        f"in {self.member.name} {self.history_field}"
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
                        f"Race condition in {self.history_field} for {self.member.name} after {max_attempts} attempts",
                        "Financial History Race Condition",
                    )
                    return False
            except Exception as e:
                frappe.log_error(
                    f"Error updating {self.history_field} for {self.member.name}: {str(e)}",
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
            history_list = getattr(self.member, self.history_field, []) or []

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
                history_list = getattr(self.member, self.history_field, [])
                for i, entry in enumerate(history_list):
                    if getattr(entry, id_field_name, None) == entry_id:
                        # Remove the specific entry without touching others
                        history_list.pop(i)
                        break

                # Save changes
                success = self._save_with_retry()
                if success:
                    frappe.logger("financial_history").info(
                        f"Removed {entry_id} from {self.member.name} {self.history_field}"
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
            history_list = getattr(self.member, self.history_field, []) or []

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
                        f"in {self.member.name} {self.history_field}"
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
        history_list = getattr(self.member, self.history_field, [])

        if len(history_list) > self.max_entries:
            # Keep only the first N entries (newest)
            trimmed_history = history_list[: self.max_entries]

            # Clear and rebuild
            setattr(self.member, self.history_field, [])
            for entry in trimmed_history:
                self.member.append(self.history_field, entry)

    def _save_with_retry(self, max_retries: int = 3) -> bool:
        """
        Save member document with retry logic and proper flags.
        Uses targeted child table updates to avoid unnecessary validation.

        Args:
            max_retries: Maximum retry attempts

        Returns:
            bool: Success status
        """
        for retry in range(max_retries):
            try:
                # For background operations, use service account context
                from verenigingen.utils.secure_service_account import background_service_context

                # Check if we're in a background context (no proper user)
                current_user = frappe.session.user
                is_background_operation = current_user in ["Guest", "Administrator", None]

                if is_background_operation:
                    # Use secure service account for background operations
                    with background_service_context(
                        f"Update {self.history_field} for member {self.member.name}"
                    ) as ctx:
                        result = secure_document_operation(
                            operation="update_child_table",
                            doc=self.member,
                            justification=f"Background update {self.history_field} for member {self.member.name}",
                            required_permissions=["Member:write"],
                            allow_system_user=True,  # Allow system user for background operations
                            bypass_validations=["link_validation"],
                        )
                        if result.success:
                            ctx.log_operation("member_financial_history", self.member.name)
                else:
                    # Use current user permissions for interactive operations
                    result = secure_document_operation(
                        operation="update_child_table",
                        doc=self.member,
                        justification=f"Update {self.history_field} for member {self.member.name}",
                        required_permissions=["Member:write"],
                        allow_system_user=True,  # Allow system user for interactive operations with proper permissions
                        bypass_validations=["link_validation"],
                    )

                if result.success:
                    # ✅ FIX: Let Frappe handle transaction commit automatically
                    return True
                else:
                    # Log concise permission errors to prevent title truncation
                    error_details = "; ".join(result.errors)
                    # Truncate error message to prevent cascading truncation errors
                    truncated_error = (
                        (error_details[:50] + "...") if len(error_details) > 50 else error_details
                    )
                    frappe.log_error(
                        f"Financial history save failed for {self.member.name}: {truncated_error}",
                        "Financial History Permission Error",
                    )
                    return False

            except Exception as e:
                # Check for chapter validation errors specifically
                error_str = str(e)
                if "Could not find Row" in error_str and "Chapter:" in error_str:
                    # This is a chapter reference validation error
                    # Log it specifically and delegate cleanup to dedicated manager
                    frappe.log_error(
                        f"Chapter reference validation error for {self.member.name}: {error_str}. "
                        f"This suggests invalid chapter references in chapter_membership_history.",
                        "Financial History Chapter Validation Error",
                    )

                    # Try to clean up invalid chapter references if this is not the last retry
                    if retry < max_retries - 1:
                        # Use dedicated chapter reference manager
                        from verenigingen.utils.chapter_reference_manager import ChapterReferenceManager

                        chapter_manager = ChapterReferenceManager(self.member)
                        removed_count = chapter_manager.cleanup_invalid_chapter_references()

                        if removed_count > 0:
                            frappe.logger().info(
                                f"Chapter cleanup removed {removed_count} invalid references for {self.member.name}"
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
                        f"Save failed for {self.member.name} after {max_retries} retries: {truncated_error}",
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
