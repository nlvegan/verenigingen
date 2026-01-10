"""
Mollie Webhook Security

Security functions for webhook authentication and validation.

This module provides:
1. Webhook signature validation (HMAC-SHA256) to verify requests originate from Mollie
2. User context setting for proper Frappe permissions during webhook processing
"""

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.settings_utils import get_payments_settings


def authenticate_mollie_webhook() -> str:
    """
    Authenticate Mollie webhook requests with rate limiting, signature validation, and user context.

    This function performs three critical security steps:
    1. Rate limiting to prevent DoS attacks (checked first for efficiency)
    2. Validates the webhook signature (HMAC-SHA256) to ensure the request is from Mollie
    3. Sets the dedicated webhook user context for proper permission handling

    Returns:
        str: The validated raw payload from the request

    Raises:
        WebhookRateLimitExceeded: If rate limit is exceeded
        WebhookAuthenticationError: If signature validation fails
        frappe.ValidationError: If webhook user is not configured or payload is empty
    """
    # STEP 0: Rate limiting (before any expensive operations)
    from verenigingen.utils.webhook_rate_limiter import WebhookRateLimitExceeded, get_webhook_rate_limiter

    # Get client IP and webhook ID for rate limiting
    ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else "unknown"
    webhook_id = frappe.form_dict.get("id") if frappe.form_dict else None

    rate_limiter = get_webhook_rate_limiter()
    is_allowed, reason = rate_limiter.check_rate_limit(ip_address, webhook_id)

    if not is_allowed:
        frappe.log_error(
            f"Mollie webhook rate limited: IP={ip_address}, webhook_id={webhook_id}, reason={reason}",
            "Mollie Webhook Rate Limit",
        )
        raise WebhookRateLimitExceeded(f"Rate limit exceeded: {reason}")

    # STEP 1: Validate webhook signature
    # Import the signature validation from the canonical location
    from verenigingen.utils.webhook_security import (
        WebhookAuthenticationError,
        verify_mollie_webhook_signature,
    )

    # Get raw payload and signature header
    payload = frappe.request.get_data(as_text=True) if frappe.request else None
    signature_header = frappe.request.headers.get("X-Mollie-Signature") if frappe.request else None

    if not payload:
        frappe.log_error(
            "Empty webhook payload received",
            "Mollie Webhook Security Error",
        )
        raise WebhookAuthenticationError("Empty webhook payload")

    try:
        # Validate signature (handles test mode bypass internally)
        verify_mollie_webhook_signature(payload, signature_header)
        frappe.logger().info("Mollie webhook signature validated successfully")

    except WebhookAuthenticationError as e:
        frappe.log_error(
            f"Mollie webhook signature validation failed: {e}",
            "Mollie Webhook Security Error",
        )
        raise

    # STEP 2: Set webhook user context
    webhook_user = None
    try:
        settings = get_payments_settings()
        webhook_user = getattr(settings, "webhook_user", None)
    except Exception as e:
        frappe.log_error(
            f"Failed to load Verenigingen Payments Settings: {e}",
            "Mollie Webhook Authentication Error",
        )

    if not webhook_user:
        frappe.log_error(
            "Webhook user not configured in Verenigingen Payments Settings",
            "Mollie Webhook Authentication Error",
        )
        frappe.throw("Webhook user not configured in Verenigingen Payments Settings")

    # Verify the webhook user exists
    if not frappe.db.exists("User", webhook_user):
        frappe.log_error(
            f"Webhook user {webhook_user} does not exist. Mollie webhooks will fail.",
            "Mollie Webhook Authentication Error",
        )
        frappe.throw(f"Webhook user {webhook_user} not configured")

    # Set user context
    frappe.set_user(webhook_user)

    # Validate permissions (log but don't block - webhook user may have different role structure)
    if not validate_webhook_user_permissions():
        frappe.logger().warning(
            f"Webhook user {webhook_user} may have insufficient permissions, proceeding anyway"
        )

    frappe.logger().info(f"Mollie webhook authenticated with user: {webhook_user}")

    # Return the validated payload
    return payload


def validate_webhook_user_permissions():
    """
    Validate that the webhook user has necessary permissions.

    For service accounts (like Verenigingen Webhook User), we check DocPerm entries
    directly since list-level frappe.has_permission() doesn't invoke custom
    has_permission methods on Documents.
    """
    # Doctypes required for donation and membership payment processing
    # - Donation: Core donation records
    # - Bank Transaction: Financial transaction records for bank reconciliation
    # - Journal Entry: Accounting entries for donations (income recognition)
    # - Member: Member payment history updates
    # - Donor: Donor subscription and payment history updates
    # - Mollie Audit Log: Webhook event logging
    required_doctypes = [
        "Donation",
        "Bank Transaction",
        "Journal Entry",
        "Member",
        "Donor",
        "Mollie Audit Log",
    ]

    current_user = frappe.session.user
    user_roles = frappe.get_roles(current_user)

    # Service account roles that should be checked via DocPerm directly
    service_roles = ["Verenigingen Webhook User"]
    is_service_account = any(role in user_roles for role in service_roles)

    missing_permissions = []

    for doctype in required_doctypes:
        for perm_type in ["create", "write"]:
            has_perm = False

            if is_service_account:
                # Check DocPerm entries directly for service accounts
                has_perm = _check_docperm_for_roles(doctype, perm_type, service_roles)
            else:
                # Standard permission check for regular users
                has_perm = frappe.has_permission(doctype, perm_type)

            if not has_perm:
                missing_permissions.append(f"{doctype} ({perm_type})")

    if missing_permissions:
        # Use shorter title to avoid exceeding Error Log title length (140 chars)
        error_msg = f"Webhook user {current_user} missing permissions:\n\n{chr(10).join(missing_permissions)}"
        frappe.log_error(
            error_msg,
            "Webhook Permissions Error",
        )
        return False

    return True


def _check_docperm_for_roles(doctype: str, perm_type: str, roles: list) -> bool:
    """
    Check if any of the given roles have the specified permission type for a DocType.

    This checks both DocPerm and Custom DocPerm entries directly, bypassing Frappe's
    standard permission system which may not invoke custom has_permission methods
    for list-level checks.

    Args:
        doctype: The DocType to check permissions for
        perm_type: Permission type ('read', 'write', 'create', 'delete', 'submit')
        roles: List of role names to check

    Returns:
        True if any role has the permission, False otherwise
    """
    # Check regular DocPerm table (for custom DocTypes in our app)
    if frappe.db.exists(
        "DocPerm",
        {
            "parent": doctype,
            "role": ["in", roles],
            perm_type: 1,
        },
    ):
        return True

    # Check Custom DocPerm table (for core Frappe/ERPNext DocTypes)
    if frappe.db.exists(
        "Custom DocPerm",
        {
            "parent": doctype,
            "role": ["in", roles],
            perm_type: 1,
        },
    ):
        return True

    return False


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
