"""
Mollie Webhook Security

Security functions for webhook authentication and validation.
"""

import frappe
from frappe.utils import now_datetime


def authenticate_mollie_webhook():
    """
    Authenticate Mollie webhook requests by setting proper user context.

    Mollie webhooks are unauthenticated HTTP POST requests, so we need to
    set a dedicated webhook user context for proper permission handling.
    """
    # Use the dedicated webhook user account
    webhook_user = "webhook.user@veganisme.org"

    # Verify the webhook user exists
    if not frappe.db.exists("User", webhook_user):
        frappe.log_error(
            f"Webhook user {webhook_user} does not exist. Mollie webhooks will fail.",
            "Mollie Webhook Authentication Error",
        )
        frappe.throw(f"Webhook user {webhook_user} not configured")

    # Set user context
    frappe.set_user(webhook_user)

    frappe.logger().info(f"Mollie webhook authenticated with user: {webhook_user}")


def validate_webhook_user_permissions():
    """
    Validate that the webhook user has necessary permissions.
    """
    required_doctypes = ["Donation", "Payment Entry", "Member", "Donor", "Mollie Audit Log"]

    current_user = frappe.session.user
    missing_permissions = []

    for doctype in required_doctypes:
        if not frappe.has_permission(doctype, "create"):
            missing_permissions.append(f"{doctype} (create)")
        if not frappe.has_permission(doctype, "write"):
            missing_permissions.append(f"{doctype} (write)")

    if missing_permissions:
        frappe.log_error(
            f"Webhook user {current_user} missing permissions: {missing_permissions}",
            "Mollie Webhook Permissions Error",
        )
        return False

    return True


def log_webhook_security_event(event_type: str, details: dict):
    """
    Log security-related webhook events.
    """
    try:
        frappe.get_doc(
            {
                "doctype": "Mollie Audit Log",
                "event_type": f"webhook_security_{event_type}",
                "event_category": "security",
                "description": f"Webhook security event: {event_type}",
                "event_data": frappe.as_json(details),
                "severity": "info",
                "timestamp": now_datetime(),
                "user": frappe.session.user,
                "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None,
            }
        ).insert(ignore_permissions=True)
    except Exception as e:
        frappe.log_error(f"Failed to log webhook security event: {e}", "Webhook Security Logging")
