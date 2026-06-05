"""
Verenigingen Email Configuration Service

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

from verenigingen.utils.constants import Roles


class EmailConfigurationService:
    """Service for managing email configuration and notification settings."""

    # Cache timeout for configuration (5 minutes)
    CACHE_TIMEOUT = 300

    def __init__(self):
        """Initialize the service."""
        self._config_cache_key = "email_configuration:singleton"

    def _get_config(self) -> Optional[Any]:
        """Get Verenigingen Email Configuration document with caching.

        Returns:
            Verenigingen Email Configuration document or None if not found.
        """
        try:
            # Check if Verenigingen Email Configuration DocType exists
            if not frappe.db.exists("DocType", "Verenigingen Email Configuration"):
                return None

            return frappe.get_single("Verenigingen Email Configuration")
        except Exception:
            return None

    def is_email_enabled(self) -> bool:
        """Check if emails are globally enabled.

        Checks:
        1. Verenigingen Email Configuration exists
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

        # Resilience: a misconfigured/corrupted config (e.g. a missing
        # notification_types child table) must not break callers. Return an
        # empty config so the notification falls back to default behaviour.
        try:
            return config.get_notification_config(notification_key)
        except Exception as e:
            frappe.logger().warning(f"Failed to read notification config for '{notification_key}': {e}")
            return {}

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
        # Resilience: a cache (Redis) outage must not block legitimate sends.
        # On any cache read error, allow the send (fail open).
        try:
            last_sent = frappe.cache().get_value(cache_key)
        except Exception as e:
            frappe.logger().warning(f"Cooldown cache read failed for '{cache_key}': {e}")
            return True

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
        # Resilience: a cache (Redis) write failure must not break email
        # sending. Cooldown tracking is best-effort; log and continue.
        try:
            frappe.cache().set_value(cache_key, str(time.time()), expires_in_sec=cooldown_seconds)
        except Exception as e:
            frappe.logger().warning(f"Cooldown cache write failed for '{cache_key}': {e}")

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

    def get_frappe_notification_for(self, notification_key: str) -> Optional[str]:
        """Return the linked Frappe Notification name when delegation is enabled.

        When ``use_frappe_notifications`` is True on the configuration AND the
        notification type has a ``frappe_notification`` link configured, the
        email pipeline should hand off to Frappe's native Notification system
        instead of sending directly. This honors Frappe's own subscription,
        unsubscribe, and delivery rules.

        Args:
            notification_key: Notification type identifier.

        Returns:
            Notification document name to delegate to, or None to send directly.
        """
        config = self._get_config()
        if not config or not getattr(config, "use_frappe_notifications", False):
            return None

        notification_config = self.get_notification_config(notification_key)
        notification_name = notification_config.get("frappe_notification")
        if not notification_name:
            return None

        # Defensive: only delegate if the linked Notification still exists and is enabled
        try:
            enabled = frappe.db.get_value("Notification", notification_name, "enabled")
        except Exception:
            return None

        if not enabled:
            return None

        return notification_name

    def filter_recipients_by_preferences(
        self,
        recipients: List[str],
        reference_doctype: Optional[str] = None,
        reference_name: Optional[str] = None,
    ) -> List[str]:
        """Filter out recipients that have opted out via user preferences.

        Honors three sources of opt-out when ``respect_user_preferences`` is True:

        1. Global Email Unsubscribe rows (``global_unsubscribe=1``)
        2. Reference-scoped Email Unsubscribe rows matching
           ``(reference_doctype, reference_name)`` when provided
        3. User-level ``unsubscribed=1`` flag on a User whose ``email`` matches

        Args:
            recipients: Candidate email addresses.
            reference_doctype: Optional DocType the email is about.
            reference_name: Optional document the email is about.

        Returns:
            List of recipients that have not opted out. Returns the input list
            unchanged when ``respect_user_preferences`` is disabled or no
            recipients are provided.
        """
        if not recipients:
            return recipients

        config = self._get_config()
        if not config or not getattr(config, "respect_user_preferences", False):
            return list(recipients)

        # Normalize for lookup (Frappe stores emails as entered, but match is
        # typically case-insensitive in practice)
        candidates = [r for r in recipients if r]
        if not candidates:
            return candidates

        # 1) Global unsubscribes
        unsubscribed = set(
            frappe.get_all(
                "Email Unsubscribe",
                filters={"email": ["in", candidates], "global_unsubscribe": 1},
                pluck="email",
            )
        )

        # 2) Reference-scoped unsubscribes
        if reference_doctype and reference_name:
            unsubscribed.update(
                frappe.get_all(
                    "Email Unsubscribe",
                    filters={
                        "email": ["in", candidates],
                        "reference_doctype": reference_doctype,
                        "reference_name": reference_name,
                    },
                    pluck="email",
                )
            )

        # 3) User-level unsubscribed flag
        unsubscribed_users = frappe.get_all(
            "User",
            filters={"email": ["in", candidates], "unsubscribed": 1},
            pluck="email",
        )
        unsubscribed.update(unsubscribed_users)

        if not unsubscribed:
            return candidates

        return [r for r in candidates if r not in unsubscribed]

    def _is_suppressed(self) -> bool:
        """Check if notifications are suppressed by flags.

        Canonical suppression flags (set via context managers in notification_suppression.py):
        - suppress_notifications: Suppresses ALL notifications (set by suppress_all_notifications())
        - suppress_chapter_notifications: Suppresses chapter-related notifications only
          (set by suppress_chapter_notifications())

        Import-related flags (checked if suppress_during_imports is enabled):
        - in_import: Standard Frappe import flag
        - in_bulk_import: Bulk import operations
        - bulk_member_operations: Member bulk operations

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

        # Check explicit suppression flags (set by context managers)
        if getattr(frappe.flags, "suppress_notifications", False):
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
        fallback_role = Roles.SYSTEM_MANAGER
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
        # Resilience: a cache (Redis) delete failure must not propagate.
        try:
            frappe.cache().delete_value(cache_key)
        except Exception as e:
            frappe.logger().warning(f"Cooldown cache delete failed for '{cache_key}': {e}")


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
