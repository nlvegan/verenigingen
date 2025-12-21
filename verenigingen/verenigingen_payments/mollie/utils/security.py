"""
Mollie Security Utilities

Security functions for webhook validation, signature verification, and audit logging.
"""

import hashlib
import hmac
import json
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from ..exceptions import MollieSecurityError


class WebhookSecurityManager:
    """Security manager for Mollie webhook validation."""

    def __init__(self):
        """Initialize security manager with settings."""
        self.settings = self._load_security_settings()

    def _load_security_settings(self) -> Dict[str, Any]:
        """Load security settings from Mollie Settings."""
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            return {
                "webhook_secret": mollie_settings.get_password(
                    fieldname="webhook_secret", raise_exception=False
                ),
                "verify_ssl": mollie_settings.get("verify_ssl", True),
                "allowed_ips": (
                    mollie_settings.get("allowed_webhook_ips", "").split(",")
                    if mollie_settings.get("allowed_webhook_ips")
                    else []
                ),
                "signature_validation": mollie_settings.get("enable_signature_validation", True),
            }
        except Exception as e:
            frappe.log_error(f"Failed to load Mollie security settings: {e}", "Mollie Security")
            # Return safe defaults
            return {
                "webhook_secret": None,
                "verify_ssl": True,
                "allowed_ips": [],
                "signature_validation": True,
            }

    def validate_webhook_signature(self, request_data: Dict[str, Any], headers: Dict[str, str]) -> bool:
        """
        Validate Mollie webhook signature.

        Args:
            request_data: Raw request data
            headers: HTTP headers from request

        Returns:
            True if signature is valid, False otherwise

        Raises:
            MollieSecurityError: If signature validation fails critically
        """
        # Skip validation if disabled in settings
        if not self.settings.get("signature_validation", True):
            frappe.log_error("Webhook signature validation is disabled", "Mollie Security Warning")
            return True

        webhook_secret = self.settings.get("webhook_secret")
        if not webhook_secret:
            # In test mode, we might not have webhook secret configured
            mollie_settings = frappe.get_single("Mollie Settings")
            if mollie_settings.test_mode:
                frappe.logger().info("Skipping webhook signature validation in test mode")
                return True
            else:
                raise MollieSecurityError("Webhook secret not configured for live mode")

        # Get signature from headers
        signature = headers.get("X-Mollie-Signature") or headers.get("x-mollie-signature")
        if not signature:
            raise MollieSecurityError("Missing webhook signature header")

        # Calculate expected signature
        if isinstance(request_data, dict):
            payload = json.dumps(request_data, separators=(",", ":"), sort_keys=True)
        else:
            payload = str(request_data)

        expected_signature = self._calculate_signature(payload, webhook_secret)

        # Compare signatures securely
        return hmac.compare_digest(signature, expected_signature)

    def _calculate_signature(self, payload: str, secret: str) -> str:
        """
        Calculate webhook signature using HMAC-SHA256.

        Args:
            payload: Request payload as string
            secret: Webhook secret

        Returns:
            Calculated signature
        """
        return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()

    def validate_webhook_origin(self, headers: Dict[str, str]) -> bool:
        """
        Validate webhook origin based on IP allowlist.

        Args:
            headers: HTTP headers from request

        Returns:
            True if origin is valid, False otherwise
        """
        allowed_ips = self.settings.get("allowed_ips", [])
        if not allowed_ips:
            # No IP restriction configured
            return True

        # Get client IP from headers
        client_ip = self._get_client_ip(headers)
        if not client_ip:
            frappe.log_error("Could not determine client IP for webhook validation", "Mollie Security")
            return False

        # Check if IP is in allowed list
        return any(
            self._ip_matches(client_ip, allowed_ip.strip())
            for allowed_ip in allowed_ips
            if allowed_ip.strip()
        )

    def _get_client_ip(self, headers: Dict[str, str]) -> Optional[str]:
        """Extract client IP from request headers."""
        # Check common headers for client IP
        ip_headers = [
            "X-Forwarded-For",
            "X-Real-IP",
            "X-Client-IP",
            "CF-Connecting-IP",  # Cloudflare
            "X-Cluster-Client-IP",
        ]

        for header in ip_headers:
            ip = headers.get(header) or headers.get(header.lower())
            if ip:
                # Take first IP if comma-separated list
                return ip.split(",")[0].strip()

        # Fallback to REMOTE_ADDR if available
        return headers.get("REMOTE_ADDR") or headers.get("remote_addr")

    def _ip_matches(self, client_ip: str, allowed_ip: str) -> bool:
        """
        Check if client IP matches allowed IP (supports CIDR notation).

        Args:
            client_ip: Client IP address
            allowed_ip: Allowed IP or CIDR range

        Returns:
            True if IP matches, False otherwise
        """
        try:
            import ipaddress

            if "/" in allowed_ip:
                # CIDR notation
                network = ipaddress.ip_network(allowed_ip, strict=False)
                return ipaddress.ip_address(client_ip) in network
            else:
                # Exact IP match
                return client_ip == allowed_ip

        except (ValueError, ipaddress.AddressValueError):
            # Fallback to string comparison
            return client_ip == allowed_ip

    def log_security_event(self, event_type: str, details: Dict[str, Any], severity: str = "info"):
        """
        Log security-related events.

        Args:
            event_type: Type of security event
            details: Event details
            severity: Event severity (info, warning, error)
        """
        log_entry = {
            "timestamp": now_datetime(),
            "event_type": event_type,
            "severity": severity,
            "details": details,
            "user": frappe.session.user if frappe.session else "Guest",
        }

        if severity == "error":
            frappe.log_error(json.dumps(log_entry, default=str), f"Mollie Security - {event_type}")
        elif severity == "warning":
            frappe.logger().warning(f"Mollie Security Event: {json.dumps(log_entry, default=str)}")
        else:
            frappe.logger().info(f"Mollie Security Event: {json.dumps(log_entry, default=str)}")


class APISecurityManager:
    """Security manager for Mollie API operations."""

    @staticmethod
    def validate_api_key(api_key: str) -> Dict[str, Any]:
        """
        Validate Mollie API key format and determine environment.

        Args:
            api_key: Mollie API key

        Returns:
            Dictionary with validation results
        """
        if not api_key:
            return {"valid": False, "error": "API key is required"}

        # Check format
        if api_key.startswith("test_"):
            return {"valid": True, "environment": "test", "key_type": "test"}
        elif api_key.startswith("live_"):
            return {"valid": True, "environment": "live", "key_type": "live"}
        else:
            return {"valid": False, "error": "Invalid API key format. Must start with 'test_' or 'live_'"}

    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """
        Mask API key for logging/display purposes.

        Args:
            api_key: Full API key

        Returns:
            Masked API key string
        """
        if not api_key or len(api_key) < 8:
            return "***"

        # Show first 4 and last 4 characters
        return f"{api_key[:4]}...{api_key[-4:]}"

    @staticmethod
    def validate_webhook_url(webhook_url: str) -> Dict[str, Any]:
        """
        Validate webhook URL format and security.

        Args:
            webhook_url: Webhook URL to validate

        Returns:
            Validation results
        """
        if not webhook_url:
            return {"valid": False, "error": "Webhook URL is required"}

        # Must be HTTPS in production
        if not webhook_url.startswith("https://"):
            # Allow HTTP only for localhost/development
            if not (webhook_url.startswith("http://localhost") or webhook_url.startswith("http://127.0.0.1")):
                return {
                    "valid": False,
                    "error": "Webhook URL must use HTTPS (except for localhost development)",
                }

        # Basic URL format validation
        import re

        url_pattern = r"^https?://[a-zA-Z0-9.-]+(?:\:[0-9]+)?(?:/.*)?$"
        if not re.match(url_pattern, webhook_url):
            return {"valid": False, "error": "Invalid webhook URL format"}

        return {"valid": True, "secure": webhook_url.startswith("https://")}


def validate_mollie_webhook_request(request_data: Dict[str, Any], headers: Dict[str, str]) -> bool:
    """
    Convenience function for webhook validation.

    Args:
        request_data: Raw request data
        headers: HTTP headers

    Returns:
        True if webhook is valid and secure

    Raises:
        MollieSecurityError: If validation fails
    """
    security_manager = WebhookSecurityManager()

    # Validate signature
    if not security_manager.validate_webhook_signature(request_data, headers):
        raise MollieSecurityError("Invalid webhook signature")

    # Validate origin
    if not security_manager.validate_webhook_origin(headers):
        raise MollieSecurityError("Webhook origin not allowed")

    # Log successful validation
    security_manager.log_security_event(
        "webhook_validated",
        {
            "user_agent": headers.get("User-Agent", "Unknown"),
            "content_type": headers.get("Content-Type", "Unknown"),
        },
    )

    return True
