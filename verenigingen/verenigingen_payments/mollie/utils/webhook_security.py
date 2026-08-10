"""
Mollie Webhook Security

Security functions for webhook authentication and validation.

This module provides:
1. Webhook signature validation (HMAC-SHA256) to verify requests originate from Mollie
2. User context setting for proper Frappe permissions during webhook processing
"""

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.service_user import get_service_user
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.utils.payment_services.logging_utils import (
    log_signature_validation_failed,
)


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
        log_signature_validation_failed(
            webhook_id="mollie",
            expected_vs_actual={"error": str(e)},
        )
        raise

    # STEP 2: Set webhook user context using shared service user resolution
    # This provides consistent behavior with Ponto and ING Checkout webhooks
    try:
        webhook_user = get_service_user(
            settings_doctype="Verenigingen Payments Settings",
            user_field="webhook_user",
            service_name="Mollie Webhook",
        )
        frappe.set_user(webhook_user)
    except ValueError as e:
        frappe.log_error(
            f"Mollie webhook user configuration error: {e}",
            "Mollie Webhook Authentication Error",
        )
        frappe.throw(str(e))

    # Validate permissions (log but don't block - webhook user may have different role structure)
    if not validate_webhook_user_permissions():
        frappe.logger().warning(
            f"Webhook user {webhook_user} may have insufficient permissions, proceeding anyway"
        )

    frappe.logger().info(f"Mollie webhook authenticated with user: {webhook_user}")

    # Return the validated payload
    return payload


# Doctypes required for donation and membership payment processing
# - Donation: Core donation records
# - Bank Transaction: Financial transaction records for bank reconciliation
# - Journal Entry: Accounting entries for donations (income recognition)
# - Member: Member payment history updates
# - Donor: Donor subscription and payment history updates
# - Mollie Audit Log: Webhook event logging
#
# - Payment Entry: created and submitted by PaymentEntryCreationService on the dues path
# - Sales Invoice (read-only, below): the invoice that entry is allocated against
#
# The two are not alike in how they are granted: Payment Entry comes directly from the
# literal "Verenigingen Webhook User" role (fixtures/custom_docperm.json grants
# create/write/submit), whereas Sales Invoice arrives only through Accounts User in that
# user's role PROFILE (fixtures/role_profile.json). Both are visible to the check below
# because it evaluates the session user's EFFECTIVE roles - which is exactly why listing
# them was reverted on 2026-08-01 (f8c7f59f) and is safe now: the previous checker read
# DocPerm rows for the literal role, could not see the profile grant, and would have
# logged an Error Log on every webhook forever.
#
# Module-level so tests can substitute a different list; the contents are the contract.
# Tuple, not list: this is the contract the webhook user is checked against, and a
# module-level mutable would let any importer append to it for the whole process.
# Tests override it with patch.object rather than mutating in place.
REQUIRED_DOCTYPES = (
    "Donation",
    "Bank Transaction",
    "Journal Entry",
    "Member",
    "Donor",
    "Mollie Audit Log",
    # Submittable, so "submit" is demanded automatically below - which is the gate
    # PaymentEntryCreationService relies on most.
    "Payment Entry",
)

# Checked for "read" only. Splitting these out rather than widening REQUIRED_DOCTYPES
# keeps the list an honest statement of what the gateway path needs:
# payment_entry_creation_service's own contract (its module docstring) is "Payment
# Entry create/submit and Sales Invoice read". Demanding create/write on Sales Invoice
# would pass today - the role profile happens to grant them via Accounts User - but it
# would turn any future least-privilege narrowing to read-only into a permanent
# false alarm, and this check runs on every webhook.
REQUIRED_READ_DOCTYPES = ("Sales Invoice",)


def validate_webhook_user_permissions():
    """
    Validate that the webhook user has necessary permissions.

    Uses frappe.has_permission, which resolves the session user's effective roles --
    so permissions materialised by a role profile (e.g. Accounts User) count.

    This used to consult DocPerm/Custom DocPerm rows directly for service accounts,
    justified as "list-level frappe.has_permission() doesn't invoke custom
    has_permission methods on Documents". That is a non-reason for a doctype-level
    check: there is no document, so no controller hook applies, and a doctype-level
    has_permission call is exactly the semantics wanted. The hand-rolled version was
    also wrong in BOTH directions -- Meta.set_custom_permissions() discards every
    standard DocPerm once any Custom DocPerm row exists for a doctype, so a stale
    DocPerm row that Frappe ignores still read as a grant, and it saw nothing of
    User Permissions, if_owner or permlevel. A sweep of all 78 Custom-DocPerm
    doctypes on the live site found 5 doctypes where it disagreed with reality.

    "submit" is checked only for submittable doctypes - a non-submittable doctype has no
    submit DocPerm at all, so requiring one would report a miss that means nothing.

    REQUIRED_READ_DOCTYPES are checked for "read" alone. See the constant for why the
    distinction is kept rather than demanding create/write everywhere.

    Returns True if every required permission is present, False otherwise. Callers treat
    a False as a warning; this function never blocks webhook processing.
    """
    current_user = frappe.session.user
    missing_permissions = []

    for doctype in REQUIRED_DOCTYPES + REQUIRED_READ_DOCTYPES:
        read_only = doctype in REQUIRED_READ_DOCTYPES

        # Screen out unknown doctypes ONCE, before anything that would raise on one.
        # Both frappe.get_meta and frappe.has_permission raise DoesNotExistError for a
        # doctype that does not exist, and this function is called unguarded from
        # authenticate_mollie_webhook, whose only handler is a generic `except
        # Exception` -> HTTP 500 -> Mollie retries. This check must only ever report.
        if not frappe.db.exists("DocType", doctype):
            missing_permissions.append(f"{doctype} (no such doctype)")
            continue

        if read_only:
            perm_types = ["read"]
        else:
            perm_types = ["create", "write"]
            # "submit" only for submittable doctypes: a non-submittable one has no submit
            # DocPerm at all, so requiring it would report a miss that means nothing.
            if frappe.get_meta(doctype).is_submittable:
                perm_types.append("submit")

        for perm_type in perm_types:
            if not frappe.has_permission(doctype, perm_type):
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
