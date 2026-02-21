# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.utils.constants import Roles


class ChapterMember(Document):
    def after_insert(self):
        """Handle new chapter member creation"""
        self._send_chapter_welcome_notification()

    def on_trash(self):
        """Handle chapter member removal"""
        self._send_chapter_farewell_notification()

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
        is_admin_user = current_user in [
            "Administrator",
            "Guest",
        ] or Roles.SYSTEM_MANAGER in frappe.get_roles(current_user)

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

    def _send_chapter_welcome_notification(self):
        """Send welcome notification when a member joins a chapter."""
        if not self.member:
            return

        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.email:
            return

        # Get chapter name from parent
        chapter_name = frappe.db.get_value("Chapter", self.parent, "name") or self.parent

        from verenigingen.services.communication.email_service import get_email_service
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        email_service = get_email_service()
        context = {
            "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
            "chapter_name": chapter_name,
            "change_type": "Chapter Welcome",
            "effective_date": frappe.utils.formatdate(self.chapter_join_date or frappe.utils.today()),
            "additional_message": f"Welcome to {chapter_name}! We're excited to have you as part of our chapter.",
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="chapter_board_notification",
            recipients=[member_doc.email],
            context=context,
            subject_override=f"Welcome to {chapter_name}",
            reference_doctype="Chapter",
            reference_name=self.parent,
            notification_key="chapter_member_joined",
        )

    def _send_chapter_farewell_notification(self):
        """Send farewell notification when a member leaves a chapter."""
        if not self.member:
            return

        member_doc = frappe.get_doc("Member", self.member)
        if not member_doc.email:
            return

        # Get chapter name from parent
        chapter_name = frappe.db.get_value("Chapter", self.parent, "name") or self.parent

        from verenigingen.services.communication.email_service import get_email_service
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        email_service = get_email_service()
        farewell_message = (
            f"We're sorry to see you leave {chapter_name}. Thank you for being part of our community."
        )
        if self.leave_reason:
            farewell_message += f"\n\nReason: {self.leave_reason}"
        farewell_message += "\n\nYou're always welcome back!"

        context = {
            "member_name": member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}",
            "chapter_name": chapter_name,
            "change_type": "Chapter Departure",
            "effective_date": frappe.utils.formatdate(frappe.utils.today()),
            "additional_message": farewell_message,
            "company": get_mollie_config().get_default_company(),
        }

        email_service.send_templated_email(
            template_name="chapter_board_notification",
            recipients=[member_doc.email],
            context=context,
            subject_override=f"Farewell from {chapter_name}",
            reference_doctype="Chapter",
            reference_name=self.parent,
            notification_key="chapter_member_left",
        )
