"""
Email Configuration Service

Service layer for centralized email and notification configuration management.
Provides methods to check if emails are enabled, get notification configurations,
manage cooldowns, and determine recipients.

Usage:
    from verenigingen.services.communication.email_configuration_service import (
        get_email_configuration_service
    )

    config_service = get_email_configuration_service()

    # Check if emails are globally enabled
    if not config_service.is_email_enabled():
        return

    # Check specific notification type
    if config_service.should_send("chapter_assignment", recipient="user@example.com"):
        email_service.send_templated_email(...)
"""

import hashlib
import time
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import get_datetime, now_datetime


class EmailConfigurationService:
    """Service for managing email configuration and notification settings."""

    # Cache timeout for configuration (5 minutes)
    CACHE_TIMEOUT = 300

    def __init__(self):
        """Initialize the service."""
        self._config_cache_key = "email_configuration:singleton"

    def _get_config(self) -> Optional[Any]:
        """Get Email Configuration document with caching.

        Returns:
            Email Configuration document or None if not found.
        """
        try:
            # Check if Email Configuration DocType exists
            if not frappe.db.exists("DocType", "Email Configuration"):
                return None

            return frappe.get_single("Email Configuration")
        except Exception:
            return None

    def is_email_enabled(self) -> bool:
        """Check if emails are globally enabled.

        Checks:
        1. Email Configuration exists
        2. Master email enabled flag
        3. Email mode (Active/Paused)
        4. Pause expiration

        Returns:
            True if emails should be sent, False if disabled.
        """
        config = self._get_config()
        if not config:
            # If no configuration exists, default to enabled
            return True

        return config.is_email_enabled()

    def is_notification_enabled(self, notification_key: str) -> bool:
        """Check if a specific notification type is enabled.

        Args:
            notification_key: Unique identifier for the notification type.

        Returns:
            True if the notification is enabled, False otherwise.
        """
        # First check global enable
        if not self.is_email_enabled():
            return False

        config = self._get_config()
        if not config:
            # If no configuration, default to enabled
            return True

        return config.is_notification_enabled(notification_key)

    def get_notification_config(self, notification_key: str) -> Dict[str, Any]:
        """Get configuration for a specific notification type.

        Args:
            notification_key: Unique identifier for the notification type.

        Returns:
            Dictionary with notification configuration:
            {
                "enabled": bool,
                "label": str,
                "category": str,
                "priority": str,
                "cooldown_minutes": int,
                "email_template": str,
                "frappe_notification": str,
                "recipient_policy": str,
                "fixed_recipients": str,
                "recipient_roles": str,
                "recipient_field": str,
                "description": str
            }
        """
        config = self._get_config()
        if not config:
            return {}

        return config.get_notification_config(notification_key)

    def check_cooldown(self, notification_key: str, recipient: str) -> bool:
        """Check if notification can be sent (not in cooldown).

        Uses Redis cache to track per-recipient, per-notification-type cooldowns.

        Args:
            notification_key: Unique identifier for the notification type.
            recipient: Email address of the recipient.

        Returns:
            True if notification can be sent (not in cooldown), False otherwise.
        """
        notification_config = self.get_notification_config(notification_key)
        cooldown_minutes = notification_config.get("cooldown_minutes", 0)

        if cooldown_minutes <= 0:
            # No cooldown configured
            return True

        cache_key = self._get_cooldown_cache_key(notification_key, recipient)
        last_sent = frappe.cache().get_value(cache_key)

        if not last_sent:
            return True

        try:
            last_sent_time = float(last_sent)
            cooldown_seconds = cooldown_minutes * 60
            return (time.time() - last_sent_time) > cooldown_seconds
        except (ValueError, TypeError):
            return True

    def record_send(self, notification_key: str, recipient: str) -> None:
        """Record that a notification was sent for cooldown tracking.

        Args:
            notification_key: Unique identifier for the notification type.
            recipient: Email address of the recipient.
        """
        notification_config = self.get_notification_config(notification_key)
        cooldown_minutes = notification_config.get("cooldown_minutes", 60)
        cooldown_seconds = max(cooldown_minutes * 60, 60)  # Minimum 1 minute

        cache_key = self._get_cooldown_cache_key(notification_key, recipient)
        frappe.cache().set_value(cache_key, str(time.time()), expires_in_sec=cooldown_seconds)

    def _get_cooldown_cache_key(self, notification_key: str, recipient: str) -> str:
        """Generate cache key for cooldown tracking.

        Args:
            notification_key: Notification type identifier.
            recipient: Email address (will be hashed for privacy).

        Returns:
            Cache key string.
        """
        recipient_hash = hashlib.md5(recipient.lower().encode()).hexdigest()[:12]
        return f"email_cooldown:{notification_key}:{recipient_hash}"

    def should_send(
        self,
        notification_key: str,
        recipient: Optional[str] = None,
        check_cooldown: bool = True,
    ) -> bool:
        """Combined check for whether a notification should be sent.

        Args:
            notification_key: Unique identifier for the notification type.
            recipient: Email address for cooldown check (optional if check_cooldown=False).
            check_cooldown: Whether to check cooldown (default True).

        Returns:
            True if notification should be sent, False otherwise.
        """
        # Check suppression flags first (bulk imports, etc.)
        if self._is_suppressed():
            return False

        # Check global email enabled
        if not self.is_email_enabled():
            return False

        # Check notification type enabled
        if not self.is_notification_enabled(notification_key):
            return False

        # Check cooldown if recipient provided
        if check_cooldown and recipient:
            if not self.check_cooldown(notification_key, recipient):
                return False

        return True

    def _is_suppressed(self) -> bool:
        """Check if notifications are suppressed by flags.

        Returns:
            True if notifications should be suppressed.
        """
        config = self._get_config()
        suppress_during_imports = config.suppress_during_imports if config else True

        if suppress_during_imports:
            if getattr(frappe.flags, "in_import", False):
                return True
            if getattr(frappe.flags, "in_bulk_import", False):
                return True
            if getattr(frappe.flags, "bulk_member_operations", False):
                return True

        if getattr(frappe.flags, "suppress_notifications", False):
            return True
        if getattr(frappe.flags, "suppress_all_notifications", False):
            return True

        return False

    def get_recipients_for_notification(
        self,
        notification_key: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Get recipients for a notification based on its configuration.

        Args:
            notification_key: Unique identifier for the notification type.
            context: Context dictionary containing document references for
                     Document-Field recipient policy.

        Returns:
            List of email addresses.
        """
        notification_config = self.get_notification_config(notification_key)
        if not notification_config:
            return self._get_fallback_recipients()

        policy = notification_config.get("recipient_policy", "Document-Field")

        if policy == "Fixed":
            return self._parse_email_list(notification_config.get("fixed_recipients", ""))

        elif policy == "Role-Based":
            roles = notification_config.get("recipient_roles", "")
            role_list = [r.strip() for r in roles.split(",") if r.strip()]
            return self._get_users_with_roles(role_list)

        elif policy == "Document-Field":
            field_path = notification_config.get("recipient_field", "")
            if field_path and context:
                return self._resolve_recipient_field(field_path, context)
            return []

        elif policy == "Custom":
            # Custom policy requires caller to handle recipients
            return []

        return self._get_fallback_recipients()

    def get_category_recipients(self, category: str) -> List[str]:
        """Get default recipients for a notification category.

        Args:
            category: Notification category (Admin, System, Payment, etc.)

        Returns:
            List of email addresses.
        """
        config = self._get_config()
        if not config:
            return self._get_fallback_recipients()

        return config.get_recipients_for_category(category)

    def _get_fallback_recipients(self) -> List[str]:
        """Get fallback recipients when no specific config exists."""
        config = self._get_config()
        fallback_role = "System Manager"
        if config and config.fallback_admin_role:
            fallback_role = config.fallback_admin_role

        return self._get_users_with_roles([fallback_role])

    def _parse_email_list(self, email_string: str) -> List[str]:
        """Parse comma-separated email list."""
        if not email_string:
            return []
        return [e.strip() for e in email_string.split(",") if e.strip()]

    def _get_users_with_roles(self, roles: List[str]) -> List[str]:
        """Get email addresses of users with specified roles."""
        if not roles:
            return []

        # Get user names that have any of these roles
        users_with_roles = frappe.get_all(
            "Has Role",
            filters={"role": ["in", roles], "parenttype": "User"},
            pluck="parent",
        )

        if not users_with_roles:
            return []

        # Get emails for enabled users (deduplicated via set)
        return frappe.get_all(
            "User",
            filters={"enabled": 1, "name": ["in", list(set(users_with_roles))]},
            pluck="email",
        )

    def _resolve_recipient_field(
        self,
        field_path: str,
        context: Dict[str, Any],
    ) -> List[str]:
        """Resolve recipient from document field path.

        Args:
            field_path: Dot-notation path (e.g., "member.email", "owner")
            context: Dictionary with document references

        Returns:
            List of email addresses.
        """
        parts = field_path.split(".")

        if len(parts) == 1:
            # Simple field like "owner" or "email"
            value = context.get(parts[0])
            if value and isinstance(value, str):
                return [value]
            return []

        elif len(parts) == 2:
            # Nested field like "member.email"
            doc_key, field_name = parts
            doc = context.get(doc_key)

            if doc is None:
                return []

            if hasattr(doc, field_name):
                value = getattr(doc, field_name)
                if value and isinstance(value, str):
                    return [value]

        return []

    def clear_cooldown(self, notification_key: str, recipient: str) -> None:
        """Clear cooldown for a specific notification and recipient.

        Useful for testing or manual override.

        Args:
            notification_key: Notification type identifier.
            recipient: Email address.
        """
        cache_key = self._get_cooldown_cache_key(notification_key, recipient)
        frappe.cache().delete_value(cache_key)


# Singleton instance
_email_configuration_service = None


def get_email_configuration_service() -> EmailConfigurationService:
    """Get the singleton EmailConfigurationService instance.

    Returns:
        EmailConfigurationService instance.
    """
    global _email_configuration_service
    if _email_configuration_service is None:
        _email_configuration_service = EmailConfigurationService()
    return _email_configuration_service
