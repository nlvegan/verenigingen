# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
ING Checkout (Pay.nl) Webhook Security

Handles webhook authentication and validation for Pay.nl webhooks.

Pay.nl uses exchange URLs (webhooks) to notify about order status changes.
This module provides:
1. IP validation (recommended - Pay.nl provides IP list via API)
2. Webhook secret verification (HMAC-SHA256) as fallback
3. User context authentication
4. Idempotency protection via webhook logging

Pay.nl IP Validation:
    Pay.nl provides an API endpoint to retrieve valid IP addresses:
    GET https://rest.pay.nl/v2/ipaddresses
    This is the recommended method per their SDKs.

Usage:
    from verenigingen.verenigingen_payments.ing_checkout.utils.webhook_security import (
        verify_ing_checkout_webhook,
        get_webhook_user,
        is_duplicate_webhook,
    )

    # In webhook handler:
    if not verify_ing_checkout_webhook(payload, signature):
        frappe.throw("Invalid webhook signature", frappe.AuthenticationError)

    if is_duplicate_webhook(event_id, payload):
        return {"status": "duplicate"}
"""

import hashlib
import hmac
from typing import List, Optional

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from verenigingen.utils.service_user import get_service_user
from verenigingen.utils.settings_utils import get_payments_settings

# Cache for Pay.nl IP addresses (refreshed every hour)
_paynl_ip_cache = {"ips": [], "last_updated": None}


class INGCheckoutWebhookError(Exception):
    """Exception for ING Checkout webhook errors."""

    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


def get_webhook_secret() -> Optional[str]:
    """
    Get the ING Checkout webhook secret from settings.

    Returns:
        Webhook secret string or None if not configured
    """
    try:
        settings = get_payments_settings()
        return settings.get_password("ing_checkout_webhook_secret")
    except Exception:
        return None


def fetch_paynl_ip_addresses() -> List[str]:
    """
    Fetch current Pay.nl IP addresses from their API.

    Pay.nl provides an endpoint to retrieve all IP addresses they use
    for webhook callbacks. This is the recommended validation method.

    Returns:
        List of IP address strings
    """
    import requests

    global _paynl_ip_cache

    # Check cache (refresh every hour)
    if _paynl_ip_cache["last_updated"]:
        age = (now_datetime() - _paynl_ip_cache["last_updated"]).total_seconds()
        if age < 3600 and _paynl_ip_cache["ips"]:
            return _paynl_ip_cache["ips"]

    try:
        response = requests.get(
            "https://rest.pay.nl/v2/ipaddresses",
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        # Extract IP addresses from response
        # Response format may vary - handle common patterns
        ip_list = []
        if isinstance(data, list):
            ip_list = [item.get("ipAddress") or item for item in data if item]
        elif isinstance(data, dict) and "ipAddresses" in data:
            ip_list = data["ipAddresses"]
        elif isinstance(data, dict) and "data" in data:
            ip_list = [item.get("ipAddress") or item for item in data["data"] if item]

        # Update cache
        _paynl_ip_cache["ips"] = ip_list
        _paynl_ip_cache["last_updated"] = now_datetime()

        frappe.logger().debug(f"Fetched {len(ip_list)} Pay.nl IP addresses")
        return ip_list

    except Exception as e:
        frappe.logger().warning(f"Failed to fetch Pay.nl IP addresses: {e}")
        # Return cached IPs if available, empty list otherwise
        return _paynl_ip_cache.get("ips", [])


def verify_webhook_ip(remote_ip: str) -> bool:
    """
    Verify that the webhook request comes from a Pay.nl IP address.

    Args:
        remote_ip: IP address of the incoming request

    Returns:
        True if IP is valid Pay.nl IP, False otherwise
    """
    if not remote_ip:
        return False

    valid_ips = fetch_paynl_ip_addresses()

    if not valid_ips:
        # SECURITY: Fail-closed - reject when IP list unavailable and no signature fallback
        frappe.logger().error(
            "Could not fetch Pay.nl IP addresses - IP validation unavailable. "
            "Configure ing_checkout_webhook_secret in Verenigingen Payments Settings as fallback."
        )
        # Return False to indicate IP validation failed - signature can still validate
        return False

    return remote_ip in valid_ips


def get_request_ip() -> Optional[str]:
    """
    Get the IP address of the current request.

    Handles X-Forwarded-For header for reverse proxy setups.

    Returns:
        IP address string or None
    """
    if not hasattr(frappe, "request") or not frappe.request:
        return None

    # Check X-Forwarded-For header (for reverse proxy)
    forwarded_for = frappe.request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first (client IP)
        return forwarded_for.split(",")[0].strip()

    # Check X-Real-IP header
    real_ip = frappe.request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    # Fall back to remote_addr
    return frappe.request.remote_addr


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify Pay.nl webhook signature using HMAC-SHA256.

    Pay.nl sends a signature header that can be verified against the payload.

    Args:
        payload: Raw request body (bytes)
        signature: Signature from webhook header
        secret: Webhook secret from settings

    Returns:
        True if signature is valid, False otherwise
    """
    if not secret:
        return False

    if not signature:
        return False

    # Pay.nl uses HMAC-SHA256 for webhook signatures
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature.lower(), expected_signature.lower())


def verify_ing_checkout_webhook(
    payload: bytes, signature: str = None, skip_ip_validation: bool = False
) -> bool:
    """
    Verify an ING Checkout webhook request.

    Security is applied in layers:
    1. IP validation (primary - recommended by Pay.nl)
    2. Signature verification (secondary - if secret configured)

    In production, at least one security layer should be active.
    In development mode, logs warnings but allows requests.

    Args:
        payload: Raw request body (bytes)
        signature: Optional signature from webhook header
        skip_ip_validation: Skip IP validation (for testing)

    Returns:
        True if verification passes

    Raises:
        INGCheckoutWebhookError: If verification fails
    """
    secret = get_webhook_secret()
    ip_validated = False
    signature_validated = False

    # Layer 1: IP validation (primary security mechanism)
    if not skip_ip_validation:
        remote_ip = get_request_ip()
        if remote_ip:
            ip_validated = verify_webhook_ip(remote_ip)
            if not ip_validated:
                # Don't raise yet - signature verification may still pass
                frappe.logger().warning(
                    f"ING Checkout webhook from IP {remote_ip} not validated. "
                    "Will check signature if configured."
                )

    # Layer 2: Signature verification (if secret configured)
    if secret:
        if signature:
            if verify_webhook_signature(payload, signature, secret):
                signature_validated = True
            else:
                raise INGCheckoutWebhookError(
                    message="Invalid webhook signature",
                    details={"reason": "Signature verification failed"},
                )
        elif not ip_validated:
            # No signature provided and IP not validated - require signature
            raise INGCheckoutWebhookError(
                message="Missing webhook signature",
                details={"reason": "Signature required when IP validation not available"},
            )

    # Check if any security layer validated the request
    if ip_validated or signature_validated:
        return True

    # SECURITY: Fail-closed - reject webhooks that fail all validation
    # This prevents accepting webhooks when:
    # 1. IP list fetch failed AND no signature configured
    # 2. IP not in whitelist AND no signature configured
    # 3. IP not in whitelist AND signature verification failed
    remote_ip = get_request_ip() if not skip_ip_validation else "unknown"
    frappe.log_error(
        title="ING Checkout webhook rejected - no valid security layer",
        message=(
            f"Webhook from IP {remote_ip} rejected. "
            "Neither IP validation nor signature verification passed. "
            "Configure ing_checkout_webhook_secret in Verenigingen Payments Settings."
        ),
    )
    raise INGCheckoutWebhookError(
        message="Webhook security validation failed",
        details={
            "reason": "No valid security layer",
            "ip": remote_ip,
            "ip_validated": ip_validated,
            "signature_validated": signature_validated,
            "secret_configured": bool(secret),
        },
    )


def get_webhook_user() -> str:
    """
    Get the configured webhook user for background job execution.

    Returns:
        str: Username from Verenigingen Payments Settings

    Raises:
        ValueError: If no valid user is available
    """
    return get_service_user(
        settings_doctype="Verenigingen Payments Settings",
        user_field="webhook_user",
        service_name="ING Checkout Webhook",
    )


def authenticate_webhook():
    """
    Authenticate ING Checkout webhook request by setting proper user context.

    Sets the webhook user from settings and validates permissions.
    """
    webhook_user = get_webhook_user()

    if not webhook_user:
        frappe.log_error(
            "Webhook user not configured in Verenigingen Payments Settings",
            "ING Checkout Webhook Authentication Error",
        )
        frappe.throw(_("Webhook user not configured"))

    if not frappe.db.exists("User", webhook_user):
        frappe.log_error(
            f"Webhook user {webhook_user} does not exist",
            "ING Checkout Webhook Authentication Error",
        )
        frappe.throw(_("Webhook user does not exist"))

    # Set user context
    frappe.set_user(webhook_user)
    frappe.logger().info(f"ING Checkout webhook authenticated with user: {webhook_user}")


def compute_webhook_hash(event_id: str, payload: str) -> str:
    """
    Compute a unique hash for a webhook event.

    Args:
        event_id: Unique event identifier from Pay.nl
        payload: Raw webhook payload

    Returns:
        SHA256 hash string
    """
    return hashlib.sha256(f"{event_id}:{payload}".encode()).hexdigest()


def is_duplicate_webhook(event_id: str, payload: str) -> bool:
    """
    Check if this webhook has already been processed (idempotency check).

    Uses Webhook Processing Log to track processed webhooks.

    Args:
        event_id: Unique event identifier
        payload: Raw webhook payload

    Returns:
        True if this webhook was already processed
    """
    webhook_hash = compute_webhook_hash(event_id, payload)

    # Check for existing log entry with same hash
    existing = frappe.db.exists(
        "Webhook Processing Log",
        {"webhook_hash": webhook_hash},
    )

    if existing:
        frappe.logger().debug(f"Duplicate ING Checkout webhook detected: {event_id}")
        return True

    return False


def log_webhook(
    event_id: str,
    webhook_type: str,
    raw_payload: str,
    status: str = "success",
    processing_result: str = None,
    error_details: str = None,
) -> Optional[str]:
    """
    Create a Webhook Processing Log entry for idempotency tracking.

    Args:
        event_id: Unique identifier for the webhook
        webhook_type: Type of webhook (ing_checkout_payment, ing_checkout_mandate, etc.)
        raw_payload: Original webhook payload as string
        status: Processing status (success, error, duplicate)
        processing_result: JSON string with processing result details
        error_details: Error message if status is error

    Returns:
        Name of created log document or None if logging failed
    """
    try:
        webhook_hash = compute_webhook_hash(event_id, raw_payload)

        # Double-check for duplicate (race condition protection)
        existing = frappe.db.exists("Webhook Processing Log", {"webhook_hash": webhook_hash})
        if existing:
            frappe.logger().debug(f"Duplicate webhook detected during logging: {event_id}")
            return None

        log = frappe.new_doc("Webhook Processing Log")
        log.webhook_id = event_id[:140] if event_id else "unknown"
        log.webhook_type = webhook_type
        log.webhook_hash = webhook_hash
        log.processed_at = now_datetime()
        log.status = status
        log.raw_payload = raw_payload

        if processing_result:
            log.processing_result = processing_result

        if error_details:
            log.error_details = error_details[:65535] if len(error_details) > 65535 else error_details

        # SECURITY JUSTIFICATION: Webhook logging is a system audit function during
        # webhook processing. No user session during webhook callbacks.
        log.insert(ignore_permissions=True)

        return log.name

    except Exception as e:
        frappe.logger().error(f"Failed to create ING Checkout webhook log: {e}")
        return None
