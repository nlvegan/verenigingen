"""
Email Configuration DocType Controller

Centralized management of email and notification settings for the Verenigingen app.
Provides master enable/disable, per-notification-type controls, and recipient management.
"""

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class EmailConfiguration(Document):
    """Controller for Email Configuration singleton DocType."""

    def validate(self):
        """Validate Email Configuration settings."""
        self._validate_pause_settings()
        self._validate_notification_keys()
        self._validate_email_lists()

    def _validate_pause_settings(self):
        """Ensure pause settings are consistent."""
        if self.email_mode == "Paused" and not self.pause_until:
            frappe.msgprint(
                "Consider setting a 'Pause Until' datetime so emails resume automatically.",
                indicator="orange",
                alert=True,
            )

    def _validate_notification_keys(self):
        """Ensure notification keys are unique."""
        keys = [nt.notification_key for nt in self.notification_types if nt.notification_key]
        if len(keys) != len(set(keys)):
            frappe.throw("Notification keys must be unique. Check for duplicates.")

    def _validate_email_lists(self):
        """Validate email address formats in recipient lists."""
        email_fields = ["admin_notification_emails", "financial_admin_emails", "system_alert_emails"]
        for field in email_fields:
            value = getattr(self, field, None)
            if value:
                emails = [e.strip() for e in value.split(",") if e.strip()]
                for email in emails:
                    if not frappe.utils.validate_email_address(email):
                        frappe.throw(f"Invalid email address in {field}: {email}")

    def is_email_enabled(self) -> bool:
        """Check if emails are globally enabled.

        Returns:
            True if emails should be sent, False if disabled or paused.
        """
        if not self.master_email_enabled:
            return False

        if self.email_mode == "Paused":
            if self.pause_until:
                pause_until = get_datetime(self.pause_until)
                if now_datetime() < pause_until:
                    return False
                # Pause period has passed, auto-resume
                self.db_set("email_mode", "Active")
            else:
                return False

        return True

    def get_notification_config(self, notification_key: str) -> dict:
        """Get configuration for a specific notification type.

        Args:
            notification_key: Unique identifier for the notification type.

        Returns:
            Dictionary with notification configuration, or empty dict if not found.
        """
        for nt in self.notification_types:
            if nt.notification_key == notification_key:
                return {
                    "enabled": bool(nt.enabled),
                    "label": nt.label,
                    "category": nt.category,
                    "priority": nt.priority,
                    "cooldown_minutes": nt.cooldown_minutes or 0,
                    "email_template": nt.email_template,
                    "frappe_notification": nt.frappe_notification,
                    "recipient_policy": nt.recipient_policy,
                    "fixed_recipients": nt.fixed_recipients,
                    "recipient_roles": nt.recipient_roles,
                    "recipient_field": nt.recipient_field,
                    "description": nt.description,
                }
        return {}

    def is_notification_enabled(self, notification_key: str) -> bool:
        """Check if a specific notification type is enabled.

        Args:
            notification_key: Unique identifier for the notification type.

        Returns:
            True if the notification type is enabled, False otherwise.
        """
        config = self.get_notification_config(notification_key)
        return config.get("enabled", False)

    def get_recipients_for_category(self, category: str) -> list:
        """Get default recipients for a notification category.

        Args:
            category: Notification category (Admin, System, Payment, etc.)

        Returns:
            List of email addresses.
        """
        if category in ("Admin", "System"):
            if category == "System" and self.system_alert_emails:
                return self._parse_email_list(self.system_alert_emails)
            if self.admin_notification_emails:
                return self._parse_email_list(self.admin_notification_emails)
        elif category == "Payment":
            if self.financial_admin_emails:
                return self._parse_email_list(self.financial_admin_emails)

        # Fallback to role-based lookup
        return self._get_users_with_role(self.fallback_admin_role or "System Manager")

    def _parse_email_list(self, email_string: str) -> list:
        """Parse comma-separated email list."""
        if not email_string:
            return []
        return [e.strip() for e in email_string.split(",") if e.strip()]

    def _get_users_with_role(self, role: str) -> list:
        """Get email addresses of users with a specific role."""
        # Get user names that have this role
        users_with_role = frappe.get_all(
            "Has Role",
            filters={"role": role, "parenttype": "User"},
            pluck="parent",
        )

        if not users_with_role:
            return []

        # Get emails for enabled users
        return frappe.get_all(
            "User",
            filters={"enabled": 1, "name": ["in", users_with_role]},
            pluck="email",
        )


def get_email_configuration() -> EmailConfiguration:
    """Get the Email Configuration singleton document.

    Returns:
        EmailConfiguration document instance.
    """
    return frappe.get_single("Email Configuration")


@frappe.whitelist()
def send_test_email(recipient: str) -> dict:
    """Send a test email to verify email configuration.

    Args:
        recipient: Email address to send test to.

    Returns:
        Dict with success status and message.
    """
    from verenigingen.utils.security.api_security_framework import OperationType, validate_api_operation

    # Validate permissions
    validate_api_operation(OperationType.ADMIN)

    # Validate email format
    if not recipient or not frappe.utils.validate_email_address(recipient):
        return {"success": False, "error": f"Invalid email address: {recipient}"}

    try:
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        result = email_service.send_simple_email(
            recipients=[recipient],
            subject="[Test] Email Configuration Test",
            message=f"""
            <h2>Email Configuration Test</h2>
            <p>This is a test email from your Verenigingen Email Configuration.</p>
            <p>If you received this email, your email system is working correctly.</p>
            <hr>
            <p><strong>Test Details:</strong></p>
            <ul>
                <li>Sent at: {frappe.utils.now()}</li>
                <li>Site: {frappe.local.site}</li>
                <li>Sent by: {frappe.session.user}</li>
            </ul>
            """,
            notification_key=None,  # Bypass notification checks for test
        )

        if result.get("success"):
            return {"success": True, "message": f"Test email queued for {recipient}"}
        else:
            return {"success": False, "error": result.get("error", "Unknown error")}

    except Exception as e:
        frappe.log_error(f"Test email failed: {str(e)}", "Email Configuration Test")
        return {"success": False, "error": str(e)}
