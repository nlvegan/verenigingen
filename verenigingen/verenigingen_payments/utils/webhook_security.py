"""
Webhook Security Utilities for Mollie Integration

Provides secure webhook signature verification to ensure webhook requests
actually originate from Mollie and prevent malicious attacks.
"""

import hmac
from typing import Optional

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
from verenigingen.verenigingen_payments.utils.shared.responses import compute_hmac_signature


class WebhookAuthenticationError(frappe.ValidationError):
    """Raised when webhook authentication fails"""

    pass


def _validate_test_mode_safety() -> None:
    """
    Validate that test_mode is not enabled in production environments.

    SECURITY: Test mode bypasses signature validation which is dangerous in production.
    This check ensures test_mode is only used in development environments.

    Raises:
        WebhookAuthenticationError: If test_mode is enabled without developer_mode
    """
    settings = frappe.get_single("Mollie Settings")

    if not settings.test_mode:
        return  # Live mode - no safety concern

    # Allow test mode in explicit development environments
    if frappe.conf.get("developer_mode"):
        return

    # Allow test mode with explicit override (for staging environments)
    if frappe.conf.get("allow_mollie_test_mode"):
        frappe.logger().warning(
            "Mollie test_mode enabled via allow_mollie_test_mode override. "
            "Ensure this is intentional for this environment."
        )
        return

    # SECURITY: Test mode is enabled without proper environment flags
    error_msg = (
        "CRITICAL SECURITY ERROR: Mollie test_mode is enabled but this does not appear "
        "to be a development environment (developer_mode is not set). "
        "Test mode bypasses webhook signature validation and is a security risk in production. "
        "Either: (1) Disable test_mode in Mollie Settings, or "
        "(2) Set developer_mode: true in site_config.json for dev environments, or "
        "(3) Set allow_mollie_test_mode: true in site_config.json for staging (not recommended for production)."
    )
    # frappe.log_error is log_error(title, message): the title lands in the
    # Error Log "method" field (max 140 chars). Pass the long explanation as the
    # message and a short title, otherwise inserting the Error Log itself raises
    # CharacterLengthExceededError and masks the real security rejection.
    frappe.log_error(message=error_msg, title="Mollie Security - CRITICAL")
    raise WebhookAuthenticationError(error_msg)


def verify_mollie_webhook_signature(payload: str, signature_header: Optional[str]) -> bool:
    """
    Verify Mollie webhook signature to authenticate the request

    Args:
        payload (str): Raw request payload as received
        signature_header (str): X-Mollie-Signature header value

    Returns:
        bool: True if the request is accepted — either the signature verified,
            or no signature was present (standard Mollie webhooks are unsigned).

    Raises:
        WebhookAuthenticationError: If a signature IS present and fails
            verification, or a signature is present but no secret is configured.
    """
    # Get Mollie settings
    settings = frappe.get_single("Mollie Settings")
    webhook_secret = settings.get_webhook_secret()

    # SECURITY: Validate test mode is safe before allowing bypass
    _validate_test_mode_safety()

    # IMPORTANT: In Mollie test mode, webhooks don't include signature headers
    # This is documented behavior for Mollie's test environment
    # (Only reaches here if test_mode safety check passed)
    if settings.test_mode and not signature_header:
        frappe.logger().info("🔒 Test mode: Accepting webhook without signature (Mollie test mode behavior)")
        return True

    # For testing purposes: Accept test signatures in test mode
    # (Only reaches here if test_mode safety check passed)
    if settings.test_mode and signature_header and signature_header.startswith("test_signature"):
        frappe.logger().info(f"🔒 Test mode: Accepting test signature: {signature_header}")
        return True

    # Standard Mollie Payments API webhooks are UNSIGNED: the request body
    # carries only an opaque resource id and no X-Mollie-Signature header
    # (signed webhooks exist only for Mollie Connect / next-gen webhooks).
    # The trust anchor is that the webhook handler re-fetches authoritative
    # state from the Mollie API by id. A missing signature is therefore
    # expected — accept it. If a signature IS present it is still verified
    # below. Hard-raising here would reject every genuine live webhook.
    if not signature_header:
        # Debug level: this is the normal path for every live webhook, so
        # logging it louder would only flood the log with non-actionable noise.
        frappe.logger().debug(
            "🔒 Webhook received without signature header — standard Mollie "
            "webhooks are unsigned; authenticity is confirmed via API re-fetch."
        )
        return True

    # A signature is present (Connect / next-gen webhook): a secret is
    # required to verify it.
    if not webhook_secret:
        frappe.logger().error("🔒 Signed webhook received but no webhook secret is configured")
        raise WebhookAuthenticationError(
            "Webhook secret not configured. Please add your webhook secret key to Mollie Settings."
        )

    try:
        # Create expected signature using webhook secret
        expected_signature = compute_hmac_signature(webhook_secret, payload)

        # Mollie sends signature in format "sha256=<hash>"
        expected_signature_header = f"sha256={expected_signature}"

        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(signature_header, expected_signature_header)

        if is_valid:
            frappe.logger().info("✅ Webhook signature verified successfully")
            return True
        else:
            frappe.logger().warning(
                f"🔒 Webhook signature mismatch. Expected: {expected_signature_header[:20]}..., Got: {signature_header[:20]}..."
            )
            raise WebhookAuthenticationError("Invalid webhook signature")

    except WebhookAuthenticationError:
        # Already a clean authentication error (e.g. "Invalid webhook
        # signature") — re-raise as-is rather than double-wrapping it.
        raise
    except Exception as e:
        frappe.logger().error(f"🔒 Webhook signature verification error: {str(e)}")
        raise WebhookAuthenticationError(f"Signature verification failed: {str(e)}")


def authenticate_mollie_webhook() -> str:
    """
    Authenticate current webhook request and return validated payload

    Returns:
        str: Validated raw payload

    Raises:
        WebhookAuthenticationError: If authentication fails
    """
    try:
        # Get raw payload from request
        payload = frappe.request.get_data(as_text=True)

        if not payload:
            raise WebhookAuthenticationError("Empty webhook payload")

        # Get signature header
        signature_header = frappe.request.headers.get("X-Mollie-Signature")

        # Verify signature
        verify_mollie_webhook_signature(payload, signature_header)

        # Return validated payload
        return payload

    except WebhookAuthenticationError:
        # Re-raise authentication errors
        raise
    except Exception as e:
        frappe.logger().error(f"🔒 Webhook authentication error: {str(e)}")
        raise WebhookAuthenticationError(f"Webhook authentication failed: {str(e)}")


def log_webhook_security_event(event_type: str, details: dict):
    """
    Log webhook security events for monitoring and debugging

    Args:
        event_type (str): Type of security event (success, failure, warning)
        details (dict): Event details to log
    """
    try:
        # Log to Frappe's standard logging
        log_message = f"🔒 Webhook Security [{event_type.upper()}]: {details}"

        if event_type == "success":
            frappe.logger().info(log_message)
        elif event_type == "warning":
            frappe.logger().warning(log_message)
        elif event_type == "failure":
            frappe.logger().error(log_message)

            # Also log to error log for security failures
            frappe.log_error(f"Mollie Webhook Security Failure: {details}", "Webhook Security Alert")

    except Exception as e:
        # Don't let logging errors break webhook processing
        frappe.logger().error(f"Failed to log webhook security event: {str(e)}")


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_webhook_signature_verification():
    """Test function to verify webhook signature verification works correctly"""
    try:
        # This is a test function - only works in development
        if not frappe.conf.get("developer_mode"):
            return {"error": "Test function only available in developer mode"}

        # Sample test payload and signature
        test_payload = '{"id": "sub_test", "status": "active"}'
        settings = frappe.get_single("Mollie Settings")
        webhook_secret = settings.get_webhook_secret()

        if not webhook_secret:
            return {"error": "Webhook secret not configured"}

        # Create test signature
        test_signature = compute_hmac_signature(webhook_secret, test_payload)

        test_signature_header = f"sha256={test_signature}"

        # Test verification
        is_valid = verify_mollie_webhook_signature(test_payload, test_signature_header)

        return {
            "success": True,
            "signature_valid": is_valid,
            "test_signature": test_signature_header[:30] + "...",
            "webhook_secret_configured": bool(webhook_secret),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
