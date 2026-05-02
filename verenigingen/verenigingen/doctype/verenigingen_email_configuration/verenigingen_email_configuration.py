"""
Verenigingen Email Configuration DocType Controller

Centralized management of email and notification settings for the Verenigingen app.
Provides master enable/disable, per-notification-type controls, and recipient management.
"""

import os
import re
import subprocess

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from verenigingen.utils.constants import Roles


class VerenigingenEmailConfiguration(Document):
    """Controller for Verenigingen Email Configuration singleton DocType."""

    def validate(self):
        """Validate Verenigingen Email Configuration settings."""
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
        return self._get_users_with_role(self.fallback_admin_role or Roles.SYSTEM_MANAGER)

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


def get_email_configuration() -> VerenigingenEmailConfiguration:
    """Get the Verenigingen Email Configuration singleton document.

    Returns:
        VerenigingenEmailConfiguration document instance.
    """
    return frappe.get_single("Verenigingen Email Configuration")


@frappe.whitelist()
def send_test_email(recipient: str) -> dict:
    """Send a test email to verify email configuration.

    Args:
        recipient: Email address to send test to.

    Returns:
        Dict with success status and message.

    Raises:
        frappe.PermissionError: If user lacks write permission on Verenigingen Email Configuration.
    """
    # Require write permission on Verenigingen Email Configuration (System Manager role)
    if not frappe.has_permission("Verenigingen Email Configuration", "write"):
        frappe.throw("You need System Manager permissions to send test emails", frappe.PermissionError)

    # Validate email format
    if not recipient or not frappe.utils.validate_email_address(recipient):
        return {"success": False, "error": f"Invalid email address: {recipient}"}

    try:
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        result = email_service.send_simple_email(
            recipients=[recipient],
            subject="[Test] Verenigingen Email Configuration Test",
            message=f"""
            <h2>Verenigingen Email Configuration Test</h2>
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
        frappe.log_error(f"Test email failed: {str(e)}", "Verenigingen Email Configuration Test")
        return {"success": False, "error": str(e)}


def _infer_category_from_path(file_path: str) -> str:
    """Infer notification category from file path.

    Args:
        file_path: Path to the Python file containing the notification key.

    Returns:
        Category string (Member, Payment, Chapter, Volunteer, Admin, System).
    """
    path_lower = file_path.lower()

    # Payment-related paths
    if any(
        pattern in path_lower
        for pattern in [
            "payment",
            "sepa",
            "mollie",
            "ponto",
            "billing",
            "invoice",
            "dues",
            "donation",
        ]
    ):
        return "Payment"

    # Chapter-related paths
    if "chapter" in path_lower:
        return "Chapter"

    # Volunteer-related paths
    if any(pattern in path_lower for pattern in ["volunteer", "expense", "team"]):
        return "Volunteer"

    # Member-related paths
    if any(pattern in path_lower for pattern in ["member", "membership", "application"]):
        return "Member"

    # System/scheduler paths
    if any(pattern in path_lower for pattern in ["scheduler", "alert", "analytics", "critical"]):
        return "System"

    # Default to Admin for anything else
    return "Admin"


def _make_label_from_key(notification_key: str) -> str:
    """Convert notification_key to human-readable label.

    Args:
        notification_key: Snake_case notification key.

    Returns:
        Title Case label.
    """
    # Replace underscores with spaces and title case
    return notification_key.replace("_", " ").title()


def _discover_notification_keys() -> dict:
    """Discover all notification keys used in the codebase.

    Returns:
        Dict with keys:
            - found: List of dicts with notification_key, file_path, category, label, description
            - unregistered: List of keys found in code but not in notification_registry.py
            - errors: List of error messages if any
    """
    from verenigingen.notification_registry import NOTIFICATION_KEYS, get_notification_meta

    app_path = frappe.get_app_path("verenigingen")
    results = {"found": [], "unregistered": [], "errors": []}

    try:
        # Use grep to find all notification_key= patterns
        # Exclude test files, __pycache__, and .pyc files
        cmd = [
            "grep",
            "-rn",
            "--include=*.py",
            r'notification_key\s*=\s*["\']',
            app_path,
        ]

        process = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if process.returncode not in (0, 1):  # 1 means no matches, which is ok
            results["errors"].append(f"grep failed: {process.stderr}")
            return results

        # Parse grep output
        # Format: filepath:lineno:content
        pattern = re.compile(r'notification_key\s*=\s*["\']([^"\']+)["\']')
        seen_keys = {}  # key -> first file found in

        for line in process.stdout.splitlines():
            # Skip test files
            if "/tests/" in line or "test_" in line:
                continue

            # Skip __pycache__
            if "__pycache__" in line:
                continue

            # Skip the notification_registry.py itself (has example in docstring)
            if "notification_registry.py" in line:
                continue

            # Extract file path
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue

            file_path = parts[0]
            content = parts[2]

            # Extract notification key from the line
            match = pattern.search(content)
            if match:
                key = match.group(1)
                # Track first occurrence of each key
                if key not in seen_keys:
                    # Make path relative to app
                    rel_path = os.path.relpath(file_path, app_path)
                    seen_keys[key] = rel_path

        # Build result list with metadata from registry (or inferred)
        for key, file_path in sorted(seen_keys.items()):
            meta = get_notification_meta(key)

            if meta:
                # Key is in the registry - use registry metadata
                results["found"].append(
                    {
                        "notification_key": key,
                        "file_path": file_path,
                        "category": meta.get("category", "Admin"),
                        "label": meta.get("label", _make_label_from_key(key)),
                        "description": meta.get("description", ""),
                        "priority": meta.get("priority", "Medium"),
                        "recipient_policy": meta.get("recipient_policy", "Document-Field"),
                        "in_registry": True,
                    }
                )
            else:
                # Key not in registry - infer metadata and flag it
                results["found"].append(
                    {
                        "notification_key": key,
                        "file_path": file_path,
                        "category": _infer_category_from_path(file_path),
                        "label": _make_label_from_key(key),
                        "description": "(Not documented - add to notification_registry.py)",
                        "priority": "Medium",
                        "recipient_policy": "Document-Field",
                        "in_registry": False,
                    }
                )
                results["unregistered"].append(key)

    except subprocess.TimeoutExpired:
        results["errors"].append("Discovery timed out after 30 seconds")
    except Exception as e:
        results["errors"].append(f"Discovery failed: {str(e)}")

    return results


@frappe.whitelist()
def discover_notification_keys() -> dict:
    """API endpoint to discover notification keys in the codebase.

    Returns:
        Dict with:
            - discovered: List of notification keys found in code (with metadata from registry)
            - configured: List of keys already configured in Verenigingen Email Configuration
            - new_keys: List of keys in code but not configured
            - orphaned_keys: List of keys configured but not in code
            - undocumented_keys: List of keys in code but not in notification_registry.py
            - errors: Any errors during discovery
    """
    # Require write permission on Verenigingen Email Configuration
    if not frappe.has_permission("Verenigingen Email Configuration", "write"):
        frappe.throw(
            "You need System Manager permissions to sync notification registry",
            frappe.PermissionError,
        )

    # Get currently configured keys in Verenigingen Email Configuration (database)
    config = get_email_configuration()
    configured_keys = {nt.notification_key for nt in config.notification_types if nt.notification_key}

    # Discover keys in codebase (with metadata from notification_registry.py)
    discovery = _discover_notification_keys()
    discovered_keys = {item["notification_key"] for item in discovery["found"]}

    # Calculate differences
    new_keys = discovered_keys - configured_keys  # In code, not in Verenigingen Email Configuration
    orphaned_keys = configured_keys - discovered_keys  # In Verenigingen Email Configuration, not in code

    # Build detailed response
    new_keys_detail = [item for item in discovery["found"] if item["notification_key"] in new_keys]

    return {
        "discovered": discovery["found"],
        "configured": list(configured_keys),
        "new_keys": new_keys_detail,
        "orphaned_keys": list(orphaned_keys),
        "undocumented_keys": discovery.get("unregistered", []),
        "errors": discovery["errors"],
        "summary": {
            "total_discovered": len(discovered_keys),
            "total_configured": len(configured_keys),
            "new_count": len(new_keys),
            "orphaned_count": len(orphaned_keys),
            "undocumented_count": len(discovery.get("unregistered", [])),
        },
    }


@frappe.whitelist()
def add_notification_types(notification_types: str) -> dict:
    """Add new notification types to Verenigingen Email Configuration.

    Uses metadata from notification_registry.py when available.

    Args:
        notification_types: JSON string of list of notification type dicts.
            Each dict should have: notification_key (required), and optionally
            label, category, description, priority, recipient_policy.

    Returns:
        Dict with success status and count of added types.
    """
    import json

    from verenigingen.notification_registry import get_notification_meta

    # Require write permission on Verenigingen Email Configuration
    if not frappe.has_permission("Verenigingen Email Configuration", "write"):
        frappe.throw(
            "You need System Manager permissions to modify notification registry",
            frappe.PermissionError,
        )

    try:
        types_to_add = json.loads(notification_types)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {str(e)}"}

    if not isinstance(types_to_add, list):
        return {"success": False, "error": "Expected a list of notification types"}

    config = frappe.get_single("Verenigingen Email Configuration")
    existing_keys = {nt.notification_key for nt in config.notification_types if nt.notification_key}

    added_count = 0
    skipped = []

    for nt_data in types_to_add:
        key = nt_data.get("notification_key")
        if not key:
            continue

        if key in existing_keys:
            skipped.append(key)
            continue

        # Get metadata from registry (if available) and merge with provided data
        registry_meta = get_notification_meta(key)

        # Add new row to child table - prefer provided data, fall back to registry, then defaults
        config.append(
            "notification_types",
            {
                "notification_key": key,
                "label": nt_data.get("label") or registry_meta.get("label") or _make_label_from_key(key),
                "category": nt_data.get("category") or registry_meta.get("category") or "Admin",
                "description": nt_data.get("description") or registry_meta.get("description") or "",
                "priority": nt_data.get("priority") or registry_meta.get("priority") or "Medium",
                "cooldown_minutes": nt_data.get("cooldown_minutes", 60),
                "enabled": 1,
                "recipient_policy": nt_data.get("recipient_policy")
                or registry_meta.get("recipient_policy")
                or "Document-Field",
            },
        )
        existing_keys.add(key)
        added_count += 1

    if added_count > 0:
        config.save()

    return {
        "success": True,
        "added": added_count,
        "skipped": skipped,
        "message": f"Added {added_count} notification type(s)",
    }
