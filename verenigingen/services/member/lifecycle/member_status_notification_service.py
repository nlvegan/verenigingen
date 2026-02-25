# Copyright (c) 2025, Verenigingen
# For license information, please see license.txt

"""
Member Status Notification Service

Handles sending notifications to members when their membership status changes.
Extracted from Member DocType's _send_member_status_notification() method.

This service:
- Determines appropriate notification content based on status transitions
- Builds email context with member and status information
- Delegates to email_service for actual email delivery
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberStatusNotificationService(StatelessService):
    """Service for sending member status change notifications."""

    # Notification configurations for different status transitions
    STATUS_NOTIFICATIONS = {
        "Active": {
            "notification_key": "member_activated",
            "subject": "Your Membership is Now Active",
            "message": "Your membership has been activated. Welcome to our community!",
        },
        "Suspended": {
            "notification_key": "member_suspended",
            "subject": "Membership Suspended",
            "message": "Your membership has been temporarily suspended. Please contact us for more information.",
        },
        "Quit": {
            "notification_key": "member_terminated",
            "subject": "Membership Terminated",
            "message": "Your membership has been terminated. Thank you for being part of our community.",
        },
    }

    def send_status_change_notification(
        self,
        member_doc: "Document",
        old_status: str,
        new_status: str,
    ) -> bool:
        """Send notification when member status changes.

        Args:
            member_doc: The Member document
            old_status: Previous status value
            new_status: New status value

        Returns:
            bool: True if notification was sent, False if skipped (e.g., no email)
        """
        if not member_doc.email:
            return False

        notification_config = self._get_notification_config(old_status, new_status)
        context = self._build_email_context(member_doc, old_status, new_status, notification_config)

        self._send_email(
            member_doc=member_doc,
            recipients=[member_doc.email],
            context=context,
            subject=notification_config["subject"],
            notification_key=notification_config["notification_key"],
        )

        return True

    def _get_notification_config(self, old_status: str, new_status: str) -> dict:
        """Get notification configuration for a status transition.

        Args:
            old_status: Previous status value
            new_status: New status value

        Returns:
            dict: Configuration with notification_key, subject, and message
        """
        if new_status in self.STATUS_NOTIFICATIONS:
            return self.STATUS_NOTIFICATIONS[new_status]

        # Generic status change for unlisted statuses
        return {
            "notification_key": "member_status_change",
            "subject": f"Membership Status Update: {new_status}",
            "message": f"Your membership status has been updated from {old_status} to {new_status}.",
        }

    def _build_email_context(
        self,
        member_doc: "Document",
        old_status: str,
        new_status: str,
        notification_config: dict,
    ) -> dict:
        """Build the email template context.

        Args:
            member_doc: The Member document
            old_status: Previous status value
            new_status: New status value
            notification_config: Notification configuration dict

        Returns:
            dict: Context for email template rendering
        """
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

        member_name = member_doc.full_name or f"{member_doc.first_name} {member_doc.last_name}"

        return {
            "member_name": member_name,
            "old_status": old_status,
            "new_status": new_status,
            "change_type": "Status Change",
            "effective_date": frappe.utils.formatdate(frappe.utils.today()),
            "additional_message": notification_config["message"],
            "company": get_mollie_config().get_default_company(),
        }

    def _send_email(
        self,
        member_doc: "Document",
        recipients: list,
        context: dict,
        subject: str,
        notification_key: str,
    ) -> None:
        """Send the notification email via email service.

        Args:
            member_doc: The Member document (for reference)
            recipients: List of email recipients
            context: Email template context
            subject: Email subject line
            notification_key: Key for notification tracking/deduplication
        """
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        email_service.send_templated_email(
            template_name="member_lifecycle_notification",
            recipients=recipients,
            context=context,
            subject_override=subject,
            reference_doctype="Member",
            reference_name=member_doc.name,
            notification_key=notification_key,
        )


# Module-level singleton accessor
_service_instance: Optional[MemberStatusNotificationService] = None


def get_member_status_notification_service() -> MemberStatusNotificationService:
    """Get or create the MemberStatusNotificationService singleton.

    Returns:
        MemberStatusNotificationService: The service instance
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberStatusNotificationService()
    return _service_instance
