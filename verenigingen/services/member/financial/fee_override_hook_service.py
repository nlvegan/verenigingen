# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
FeeOverrideHookService - Handles fee override changes after member save.

This service processes pending fee changes that were deferred during the
member save process to avoid recursion and ensure proper transaction handling.

Extracted from member.py handle_fee_override_after_save() function.

Key responsibilities:
- Check if fee change processing should be skipped (bulk operations)
- Create contribution amendment requests
- Update fee change history
- Update active dues schedules

Transaction handling:
- Uses separate database transaction for atomicity
- Rolls back on error to prevent partial updates
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class FeeOverrideHookService(StatelessService):
    """
    Service for handling fee override changes after member save.

    This service is called as a hook after member documents are saved
    to process any pending fee changes that were deferred.
    """

    def __init__(self) -> None:
        """Initialize the fee override hook service."""
        super().__init__(service_name="FeeOverrideHookService")

    def should_skip_processing(self, doc: "Document") -> bool:
        """
        Check if fee change processing should be skipped.

        Skips processing during bulk operations to avoid deadlocks
        from concurrent amendment processing during bulk imports.

        Args:
            doc: The member document

        Returns:
            bool: True if processing should be skipped
        """
        bulk_flag = getattr(frappe.flags, "bulk_member_operations", False)
        csv_flag = getattr(doc, "_csv_import", False)
        system_update_flag = getattr(doc, "_system_update", False)
        # CRITICAL: Also check persistent tracking set (survives document reloads)
        in_bulk_import = (
            hasattr(frappe.local, "bulk_import_members") and doc.name in frappe.local.bulk_import_members
        )

        if bulk_flag or csv_flag or system_update_flag or in_bulk_import:
            self.logger.info(
                f"[FEE OVERRIDE HOOK] Skipping for {doc.name} - "
                f"bulk_flag={bulk_flag}, csv_flag={csv_flag}, "
                f"system_flag={system_update_flag}, in_bulk_import={in_bulk_import}"
            )
            return True

        return False

    def process_pending_fee_change(self, doc: "Document") -> bool:
        """
        Process a pending fee change for a member.

        Creates amendment request, updates history, and updates dues schedules
        in a separate transaction for atomicity.

        Args:
            doc: The member document with _pending_fee_change attribute

        Returns:
            bool: True if processing succeeded, False otherwise
        """
        if not hasattr(doc, "_pending_fee_change"):
            self.logger.debug(f"No pending fee change found for member {doc.name}")
            return False

        pending_change = doc._pending_fee_change

        try:
            self.logger.info(f"Processing pending fee change for member {doc.name}")

            # Use separate database transaction for fee change processing
            frappe.db.begin()
            try:
                # Create amendment request
                dues_schedule_action = self._create_amendment_request(doc.name, pending_change)

                # Build history entry
                history_entry = self._build_history_entry(pending_change, dues_schedule_action)

                # Update fee change history
                self._update_fee_change_history(doc.name, history_entry)

                # Update dues schedules
                self._update_dues_schedules(doc.name)

                # Commit the transaction
                frappe.db.commit()

            except Exception as transaction_error:
                # Rollback the transaction on error
                frappe.db.rollback()
                self.logger.error(
                    f"Transaction error processing fee override for member {doc.name}: {str(transaction_error)}"
                )
                raise transaction_error

            # Clean up the pending change
            delattr(doc, "_pending_fee_change")
            self.logger.info(f"Successfully processed fee override change for member {doc.name}")
            return True

        except Exception as e:
            self.logger.error(f"Error processing fee override for member {doc.name}: {str(e)}")
            # Clean up the pending change to avoid repeated processing
            if hasattr(doc, "_pending_fee_change"):
                delattr(doc, "_pending_fee_change")
            return False

    def _create_amendment_request(self, member_name: str, pending_change: Dict[str, Any]) -> str:
        """
        Create a contribution amendment request for the fee change.

        Args:
            member_name: Name of the member
            pending_change: Dictionary with fee change details

        Returns:
            str: Description of the action taken
        """
        try:
            from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
                create_fee_change_amendment,
            )

            amendment = create_fee_change_amendment(
                member_name=member_name,
                new_amount=pending_change["new_amount"],
                reason=pending_change["reason"],
            )

            return f"Amendment request created: {amendment.name}"

        except Exception as e:
            self.logger.warning(f"Could not create amendment request: {str(e)}")
            return "Amendment creation failed, direct dues schedule update"

    def _build_history_entry(
        self, pending_change: Dict[str, Any], dues_schedule_action: str
    ) -> Dict[str, Any]:
        """
        Build a history entry for the fee change.

        Args:
            pending_change: Dictionary with fee change details
            dues_schedule_action: Description of dues schedule action

        Returns:
            dict: History entry dictionary
        """
        return {
            "change_date": pending_change["change_date"],
            "old_amount": pending_change["old_amount"],
            "new_amount": pending_change["new_amount"],
            "reason": pending_change["reason"],
            "changed_by": pending_change["changed_by"],
            "dues_schedule_action": dues_schedule_action,
        }

    def _update_fee_change_history(self, member_name: str, history_entry: Dict[str, Any]) -> None:
        """
        Update the fee change history for a member.

        Uses direct SQL to avoid triggering hooks and recursion.

        Args:
            member_name: Name of the member
            history_entry: History entry to add
        """
        # Get current fee change history with safe parsing
        current_history = frappe.db.get_value("Member", member_name, "fee_change_history")
        if not current_history or current_history.strip() == "":
            history_list = []
        else:
            try:
                history_list = frappe.parse_json(current_history)
                if not isinstance(history_list, list):
                    frappe.log_error(
                        f"Invalid fee_change_history format for member {member_name}: {type(history_list)}",
                        "MemberHistory",
                    )
                    history_list = []
            except (ValueError, TypeError) as e:
                frappe.log_error(
                    f"Failed to parse fee_change_history for member {member_name}: {e}", "MemberHistory"
                )
                history_list = []

        history_list.append(history_entry)

        # Update history directly in database
        frappe.db.sql(
            """
            UPDATE `tabMember`
            SET fee_change_history = %s
            WHERE name = %s
        """,
            (frappe.as_json(history_list), member_name),
        )

    def _update_dues_schedules(self, member_name: str) -> None:
        """
        Update active dues schedules for a member.

        Args:
            member_name: Name of the member
        """
        try:
            # Create a temporary member object to avoid modifying the original
            temp_member = frappe.get_doc("Member", member_name)
            # Mark as system update to bypass fee override validation
            temp_member._system_update = True
            result = temp_member.update_active_dues_schedules()
            self.logger.info(f"Dues schedule update result: {result}")
        except Exception as e:
            self.logger.error(f"Error updating dues schedules: {str(e)}")

    def handle_after_save(self, doc: "Document", method: Optional[str] = None) -> None:
        """
        Main entry point for the after_save hook.

        This is the function that should be called from the hooks configuration.

        Args:
            doc: The member document
            method: The hook method name (optional)
        """
        self.logger.info(f"handle_fee_override_after_save called for member {doc.name}, method={method}")

        if self.should_skip_processing(doc):
            return

        self.process_pending_fee_change(doc)


# Singleton instance
_fee_override_hook_service: Optional[FeeOverrideHookService] = None


def get_fee_override_hook_service() -> FeeOverrideHookService:
    """Get singleton instance of FeeOverrideHookService."""
    global _fee_override_hook_service
    if _fee_override_hook_service is None:
        _fee_override_hook_service = FeeOverrideHookService()
    return _fee_override_hook_service


def handle_fee_override_after_save(doc: "Document", method: Optional[str] = None) -> None:
    """
    Hook function to handle fee override changes after save.

    This is the entry point called from hooks.py. Delegates to
    FeeOverrideHookService for the actual processing.

    Args:
        doc: The member document
        method: The hook method name (optional)
    """
    get_fee_override_hook_service().handle_after_save(doc, method)
