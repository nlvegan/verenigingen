# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChapterMember(Document):
    def validate(self):
        """Validate chapter member operations and ensure proper history tracking"""
        self.validate_chapter_membership_tracking()

    def validate_chapter_membership_tracking(self):
        """Ensure chapter membership changes go through proper tracking"""
        # Allow creation through Chapter Manager or specific whitelisted contexts
        allowed_contexts = [
            "Chapter.member_manager.add_member",
            "ChapterMembershipManager",
            "Data Import",  # Allow data imports
            "Migration",  # Allow migrations
            "Test",  # Allow test contexts
        ]

        # Check if we're in an allowed context by examining the call stack
        import traceback

        call_stack = traceback.format_stack()

        # Look for allowed contexts in the call stack
        is_allowed_context = any(context in "".join(call_stack) for context in allowed_contexts)

        # Also allow if the change is being made by administrator or system user
        current_user = frappe.session.user
        is_admin_user = current_user in ["Administrator", "Guest"] or "System Manager" in frappe.get_roles(
            current_user
        )

        # Allow if we're updating an existing record without changing key fields
        if (
            not self.is_new()
            and not self.has_value_changed("member")
            and not self.has_value_changed("parent")
        ):
            return

        # For new records or key field changes, ensure proper tracking
        if not (is_allowed_context or is_admin_user):
            # Log the attempt for debugging
            frappe.log_error(
                f"Direct chapter member manipulation attempted by {current_user} for member {self.member} in chapter {self.parent}",
                "Chapter Member Direct Manipulation",
            )

            # Provide helpful guidance
            frappe.msgprint(
                _(
                    "Chapter membership changes should be made through the Chapter Management interface or using the ChapterMembershipManager utility for proper history tracking."
                ),
                title=_("Use Proper Chapter Management"),
                indicator="yellow",
            )

    def on_update(self):
        """Handle updates to chapter membership"""
        self.update_chapter_membership_history()

    def update_chapter_membership_history(self):
        """
        DEPRECATED: Chapter membership history is now managed explicitly by
        ChapterMembershipHistoryManager via application code (application_helpers.py,
        member_manager.py, etc.).

        This hook was causing duplicate history entries because both the hook AND
        the explicit calls were adding history. History management is now centralized
        in the manager to avoid this issue.

        Keeping this method as a placeholder in case we need hook-based history
        in the future, but it's currently disabled.
        """
        # History is now managed explicitly by ChapterMembershipHistoryManager
        # via application_helpers.py and other modules. No automatic hook-based
        # history creation to avoid duplicates.
        pass
