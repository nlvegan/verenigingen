"""
Notification Helper Functions

Utilities for getting configurable notification recipients from settings
"""

import frappe


def get_notification_recipients(setting_field, default_roles=None):
    """
    Get notification recipients from settings or fall back to default roles

    Args:
        setting_field: Field name in Verenigingen Settings containing email addresses
        default_roles: List of roles to use if no emails configured

    Returns:
        List of email addresses
    """
    if default_roles is None:
        default_roles = ["System Manager", "Verenigingen Administrator"]

    try:
        settings = frappe.get_single("Verenigingen Settings")
        custom_emails = getattr(settings, setting_field, None)

        if custom_emails:
            # Parse comma-separated emails and clean them
            emails = [email.strip() for email in custom_emails.split(",") if email.strip()]
            if emails:
                return emails

        # Fall back to default roles
        admin_users = frappe.get_all(
            "User",
            filters=[["enabled", "=", 1], ["Has Role", "role", "in", default_roles]],
            fields=["email", "full_name"],
        )

        return [user.email for user in admin_users if user.email]

    except Exception as e:
        frappe.log_error(f"Failed to get notification recipients: {str(e)}", "Notification Helper Error")
        # Emergency fallback - get System Managers
        try:
            admin_emails = frappe.get_all(
                "User", filters=[["Has Role", "role", "=", "System Manager"]], pluck="email"
            )
            return [email for email in admin_emails if email]
        except:
            return []


def get_threshold_setting(setting_field, default_value):
    """
    Get threshold setting from Verenigingen Settings

    Args:
        setting_field: Field name in Verenigingen Settings
        default_value: Default value if setting not found

    Returns:
        Setting value or default
    """
    try:
        settings = frappe.get_single("Verenigingen Settings")
        return getattr(settings, setting_field, default_value)
    except:
        return default_value
