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
from frappe.model import child_table_fields, default_fields, optional_fields
from frappe.utils import now

# Frappe's own list of the columns every row has outside the doctype's `fields`.
# Taken from the framework rather than hand-written: a hand-written set was
# asymmetric -- it allowed `parent` but refused `creation`/`modified`/`doctype`,
# which is exactly what `as_dict()` returns, and returning `row.as_dict()` is a
# live pattern in this app (`payment_history_service.py:551`).
_STD_ROW_FIELDS = frozenset(default_fields) | frozenset(child_table_fields) | frozenset(optional_fields)


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
        child_doctype = self._resolve_child_doctype()
        if not child_doctype:
            return False

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
                #
                # get_value has two shapes that lock nothing just as quietly: a
                # Single (get_values_from_single ignores for_update) and a doc whose
                # name EQUALS its doctype (get_values treats that as the Single form
                # and emits no SQL at all). Neither is reachable from the callers --
                # every one holds a saved Member or Donor, both series/format-named.
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

                entry_data = self._drop_unknown_fields(child_doctype, entry_data, entry_id)
                if entry_data is None:
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
            child_doctype = self._resolve_child_doctype()
            if not child_doctype:
                return False
            field_updates = self._drop_unknown_fields(child_doctype, field_updates, entry_id)
            if field_updates is None:
                return False

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

    def _resolve_child_doctype(self):
        """The child doctype behind `self.history_field`, or None if it is not a table.

        Resolved BEFORE the row lock is taken: a manager built with a misspelt
        `history_field_name` can never write anything and should not hold a lock
        while finding that out.

        Callers treat None as a hard failure. An earlier version treated it as
        "nothing to check against" and passed, which made the field filter below
        fail OPEN on the exact typo class it exists to catch -- measured, with a
        control: `history_field_name="payment_histroy"` accepted an entry of pure
        nonsense while `"payment_history"` refused the same entry.
        `history_field_name` is a bare string literal at every call site
        (`webhook_wrapper_service_unified.py:2774` passes "donor_history"), so that
        is a live shape, not a hypothetical.
        """
        table_field = self.doc.meta.get_field(self.history_field)
        child_doctype = table_field.options if table_field else None
        if child_doctype:
            return child_doctype

        frappe.log_error(
            title="Financial History Unknown Table",
            message=(
                f"{self.doc.doctype} {self.doc.name} has no child table "
                f"{self.history_field!r}; nothing can be written to it."
            ),
        )
        return None

    def _drop_unknown_fields(self, child_doctype, entry_data, entry_id):
        """Strip keys the child doctype does not have, loudly. None == unwritable.

        Frappe drops an unknown key silently -- `append()` and `setattr` put it on
        the Python object, it never reaches `get_valid_dict()`, and no column
        exists -- so a misspelt or copy-pasted key is lost with no error at all.
        That is #465: the Mollie donation writer set `mollie_payment_id`,
        `journal_entry` and `payment_type` on `Member Payment History`, none of
        which exist, for as long as the code had been there.

        STRIP AND CONTINUE, not refuse. Refusing was the first version of this and
        it was wrong. An unknown key is unstorable by definition, so refusing
        converts "lose one field" into "lose the whole row" -- and on the Mollie
        donation path a False becomes `status: "error"`, which
        `verenigingen_payments/mollie/api/unified_payment_api.py:85` turns into
        HTTP 500 under the comment "Trigger Mollie retry". A schema typo is the
        most permanent refusal there is, so every re-delivery for the next ~26h
        would hit the identical refusal and write another Error Log row. The
        webhook service already excludes permanent refusals from the retry ladder
        for exactly this reason (its `not activation.get("permanent")` branch); a
        new guard should not walk into it.

        Loudness comes from the Error Log instead, which the harness already
        watches (`ErrorLogGuardMixin`; `VERENIGINGEN_FAIL_ON_ERROR_LOG=1` turns any
        Error Log written during a test into a failure). CI is the gate, not
        production traffic.

        SCOPE, narrowly: this covers writers that go through this manager. It is
        NOT every writer that touches these tables -- eight production sites call
        `doc.append(<history table>, ...)` directly and are invisible here, three
        of them carrying this very defect. All eight are enumerated in #712. Had
        the Mollie donation writer used `member.append(...)`, as its own file's
        siblings do, this guard would not have caught #465 either.
        """
        known = {df.fieldname for df in frappe.get_meta(child_doctype).fields if df.fieldname}
        unknown = sorted(k for k in entry_data if k not in known and k not in _STD_ROW_FIELDS)
        if not unknown:
            return entry_data

        kept = {k: v for k, v in entry_data.items() if k not in unknown}
        # Keyword arguments, and title first: `frappe.log_error(title, message)` puts
        # arg 1 in `Error Log.method` and arg 2 in `Error Log.error` -- measured, not
        # read. The sibling calls in this module pass them the other way round, which
        # files the whole message as the title; that is #485's class, not fixed here.
        frappe.log_error(
            title="Financial History Unknown Field",
            message=(
                f"{child_doctype} has no field(s) {unknown}; they were DROPPED from "
                f"entry {entry_id} for {self.doc.doctype} {self.doc.name} "
                f"{self.history_field}. Frappe would have dropped them silently. "
                f"Kept: {sorted(kept)}"
            ),
        )
        return kept or None

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
