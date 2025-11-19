"""
Notification Dispatcher

Handles different types of system notifications with appropriate routing
and template selection.
"""

from typing import Any, Dict, List, Union

import frappe

from .email_service import get_email_service


class NotificationDispatcher:
    """Dispatches notifications based on type and recipient preferences."""

    def __init__(self):
        self.email_service = get_email_service()

        # Notification type mappings
        self.template_mapping = {
            "member_approval": "membership_application_approved",
            "chapter_membership_approval": "chapter_membership_approved",
            "member_suspension": "Member Suspension Notification",
            "member_termination": "Member Termination Notification",
            "member_reactivation": "Member Reactivation Notification",
            "member_rejection": "membership_application_rejected",
            "payment_failure": "Payment Failure Notification",
            "payment_success": "Payment Success Notification",
            "sepa_mandate_created": "SEPA Mandate Created",
            "sepa_mandate_expired": "SEPA Mandate Expired",
            "board_member_added": "Board Member Added",
            "board_member_removed": "Board Member Removed",
            "chapter_assignment": "Chapter Assignment Notification",
            "membership_renewal": "Membership Renewal Notice",
            "dues_reminder": "Membership Dues Reminder",
            "welcome": "Welcome New Member",
        }

    def dispatch_notification(
        self, notification_type: str, recipients: Union[str, List[str]], data: Dict[str, Any], **options
    ) -> Dict[str, Any]:
        """
        Dispatch notification based on type and recipient preferences.

        Args:
            notification_type: Type of notification
            recipients: Target recipients
            data: Notification data and context
            **options: Additional options

        Returns:
            Dispatch result
        """
        try:
            # Validate notification type
            if notification_type not in self.template_mapping:
                return {
                    "success": False,
                    "errors": [f"Unknown notification type: {notification_type}"],
                    "notification_type": notification_type,
                }

            # Get template name
            template_name = self.template_mapping[notification_type]

            # Check recipient preferences (if applicable)
            filtered_recipients = self._filter_recipients_by_preferences(recipients, notification_type, data)

            if not filtered_recipients:
                return {
                    "success": True,
                    "message": "No recipients after preference filtering",
                    "skipped_count": len(recipients) if isinstance(recipients, list) else 1,
                }

            # Dispatch via email service
            return self.email_service.send_templated_email(
                template_name=template_name, recipients=filtered_recipients, context=data, **options
            )

        except Exception as e:
            frappe.logger("notification_dispatcher").error(
                f"Notification dispatch failed for {notification_type}: {str(e)}"
            )
            return {"success": False, "errors": [str(e)], "notification_type": notification_type}

    def dispatch_bulk_notifications(self, notifications: List[Dict[str, Any]], **options) -> Dict[str, Any]:
        """
        Dispatch multiple notifications efficiently.

        Args:
            notifications: List of notification configs
            **options: Bulk processing options

        Returns:
            Bulk dispatch results
        """
        try:
            results = []
            total_notifications = len(notifications)
            success_count = 0
            failed_count = 0

            for notification in notifications:
                try:
                    result = self.dispatch_notification(**notification)
                    if result.get("success"):
                        success_count += 1
                    else:
                        failed_count += 1
                    results.append(result)

                except Exception as e:
                    failed_count += 1
                    results.append({"success": False, "errors": [str(e)], "notification": notification})

            return {
                "success": True,
                "total_notifications": total_notifications,
                "success_count": success_count,
                "failed_count": failed_count,
                "success_rate": (success_count / total_notifications) * 100 if total_notifications > 0 else 0,
                "results": results,
            }

        except Exception as e:
            return {"success": False, "errors": [str(e)], "operation": "dispatch_bulk_notifications"}

    def _filter_recipients_by_preferences(
        self, recipients: Union[str, List[str]], notification_type: str, data: Dict[str, Any]
    ) -> List[str]:
        """Filter recipients based on their communication preferences."""
        try:
            # Normalize to list
            if isinstance(recipients, str):
                recipients = [recipients]

            # For now, return all recipients
            # TODO: Implement preference filtering when Member communication preferences are available
            return recipients

        except Exception as e:
            frappe.logger("notification_dispatcher").warning(
                f"Recipient filtering failed: {str(e)}, returning all recipients"
            )
            return recipients if isinstance(recipients, list) else [recipients]

    def get_supported_notification_types(self) -> List[str]:
        """Get list of supported notification types."""
        return list(self.template_mapping.keys())

    def validate_notification_type(self, notification_type: str) -> bool:
        """Check if notification type is supported."""
        return notification_type in self.template_mapping
