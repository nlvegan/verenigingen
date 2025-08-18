"""
Webhook Validator
Enhanced webhook validation for Mollie integration

Features:
- Signature validation with HMAC-SHA256
- Replay attack prevention
- Payload size validation
- Malformed data detection
"""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


class WebhookValidator:
    """
    Comprehensive webhook validation for financial security

    Provides multi-layer validation including:
    - Signature verification
    - Replay attack prevention
    - Payload size limits
    - JSON structure validation
    """

    # Maximum payload size (1MB)
    MAX_PAYLOAD_SIZE = 1024 * 1024

    # Replay attack window (5 minutes)
    REPLAY_WINDOW_SECONDS = 300

    def __init__(self, security_manager):
        """
        Initialize webhook validator

        Args:
            security_manager: MollieSecurityManager instance
        """
        self.security_manager = security_manager
        self.processed_webhooks = {}  # Cache for replay detection

    def validate_webhook(
        self, payload: str, signature: str, headers: Dict[str, str] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive webhook validation

        Args:
            payload: Raw webhook payload
            signature: Webhook signature from header
            headers: Additional headers for validation

        Returns:
            Dict with validation status and parsed payload

        Raises:
            WebhookValidationException: If validation fails
        """
        validation_result = {"valid": False, "payload": None, "errors": []}

        try:
            # Step 1: Validate payload size
            if not self._validate_payload_size(payload):
                validation_result["errors"].append("Payload exceeds size limit")
                raise WebhookValidationException("Payload too large")

            # Step 2: Parse JSON payload
            try:
                parsed_payload = json.loads(payload)
                validation_result["payload"] = parsed_payload
            except json.JSONDecodeError as e:
                validation_result["errors"].append(f"Invalid JSON: {str(e)}")
                raise WebhookValidationException("Malformed JSON payload")

            # Step 3: Extract timestamp for replay prevention
            timestamp = None
            if headers:
                timestamp = headers.get("X-Mollie-Timestamp")
            if not timestamp and parsed_payload:
                timestamp = parsed_payload.get("timestamp")

            # Step 4: Validate signature
            if not self.security_manager.validate_webhook_signature(payload, signature, timestamp):
                validation_result["errors"].append("Invalid signature")
                raise WebhookValidationException("Webhook signature validation failed")

            # Step 5: Check for replay attack
            if not self._check_replay_attack(parsed_payload, timestamp):
                validation_result["errors"].append("Possible replay attack")
                raise WebhookValidationException("Webhook replay detected")

            # Step 6: Validate required fields
            if not self._validate_required_fields(parsed_payload):
                validation_result["errors"].append("Missing required fields")
                raise WebhookValidationException("Webhook missing required fields")

            # All validations passed
            validation_result["valid"] = True

            # Log successful validation
            self._log_webhook_validation(True, parsed_payload.get("id"))

            return validation_result

        except WebhookValidationException:
            # Re-raise validation exceptions
            raise
        except Exception as e:
            # Log unexpected errors
            frappe.log_error(f"Webhook validation error: {str(e)}", "Webhook Validator")
            validation_result["errors"].append(f"Unexpected error: {str(e)}")
            raise WebhookValidationException(f"Webhook validation failed: {str(e)}")

    def _validate_payload_size(self, payload: str) -> bool:
        """
        Validate webhook payload size

        Args:
            payload: Raw payload string

        Returns:
            bool: True if size is within limits
        """
        payload_size = len(payload.encode("utf-8"))

        if payload_size > self.MAX_PAYLOAD_SIZE:
            frappe.log_error(f"Webhook payload too large: {payload_size} bytes", "Webhook Size Validation")
            return False

        return True

    def _check_replay_attack(self, payload: Dict[str, Any], timestamp: str = None) -> bool:
        """
        Check for webhook replay attacks

        Args:
            payload: Parsed webhook payload
            timestamp: Webhook timestamp

        Returns:
            bool: True if not a replay
        """
        # Get unique webhook identifier
        webhook_id = payload.get("id")
        if not webhook_id:
            # No ID to check for replay
            return True

        # Check if we've seen this webhook before
        if webhook_id in self.processed_webhooks:
            last_seen = self.processed_webhooks[webhook_id]
            time_diff = (now_datetime() - last_seen).total_seconds()

            # If seen within replay window, it's likely a replay
            if time_diff < self.REPLAY_WINDOW_SECONDS:
                frappe.log_error(
                    f"Possible webhook replay: {webhook_id} seen {time_diff}s ago", "Webhook Replay Detection"
                )
                return False

        # Check timestamp if provided
        if timestamp:
            try:
                webhook_time = get_datetime(timestamp)
                current_time = now_datetime()
                time_diff = abs((current_time - webhook_time).total_seconds())

                if time_diff > self.REPLAY_WINDOW_SECONDS:
                    frappe.log_error(
                        f"Webhook timestamp too old: {time_diff}s", "Webhook Timestamp Validation"
                    )
                    return False

            except Exception as e:
                frappe.log_error(f"Timestamp validation error: {str(e)}", "Webhook Timestamp Validation")
                return False

        # Record this webhook
        self.processed_webhooks[webhook_id] = now_datetime()

        # Clean old entries from cache
        self._cleanup_webhook_cache()

        return True

    def _validate_required_fields(self, payload: Dict[str, Any]) -> bool:
        """
        Validate webhook has required fields

        Args:
            payload: Parsed webhook payload

        Returns:
            bool: True if all required fields present
        """
        # Define required fields based on webhook type
        base_required_fields = ["id"]

        # Check for payment webhook fields
        if "resource" in payload:
            if payload["resource"] == "payment":
                base_required_fields.extend(["status", "amount"])
            elif payload["resource"] == "settlement":
                base_required_fields.extend(["reference", "amount"])

        # Validate all required fields exist
        for field in base_required_fields:
            if field not in payload:
                frappe.log_error(f"Webhook missing required field: {field}", "Webhook Field Validation")
                return False

        return True

    def _cleanup_webhook_cache(self):
        """Clean old entries from webhook cache to prevent memory leak"""
        current_time = now_datetime()
        cutoff_time = current_time - timedelta(seconds=self.REPLAY_WINDOW_SECONDS * 2)

        # Remove entries older than double the replay window
        self.processed_webhooks = {
            webhook_id: timestamp
            for webhook_id, timestamp in self.processed_webhooks.items()
            if timestamp > cutoff_time
        }

    def _log_webhook_validation(self, success: bool, webhook_id: str = None):
        """
        Log webhook validation attempt

        Args:
            success: Whether validation succeeded
            webhook_id: Webhook identifier
        """
        try:
            # Create validation log entry
            log_entry = {
                "timestamp": frappe.utils.now(),
                "webhook_id": webhook_id,
                "validation_status": "success" if success else "failed",
                "ip_address": frappe.local.request.environ.get("REMOTE_ADDR")
                if frappe.local.request
                else None,
            }

            # Log to file for monitoring
            frappe.logger("webhook_validation").info(json.dumps(log_entry))

        except Exception as e:
            # Don't fail on logging errors
            frappe.log_error(f"Webhook logging error: {str(e)}", "Webhook Validator")


class WebhookValidationException(Exception):
    """Custom exception for webhook validation errors"""

    pass


def validate_mollie_webhook(payload: str, signature: str, headers: Dict[str, str] = None) -> Dict[str, Any]:
    """
    Convenience function to validate Mollie webhook

    Args:
        payload: Raw webhook payload
        signature: Webhook signature
        headers: Optional headers

    Returns:
        Dict with validation result and parsed payload
    """
    from .mollie_security_manager import MollieSecurityManager

    # Get Mollie settings
    settings = frappe.get_single("Mollie Settings")

    # Initialize security manager and validator
    security_manager = MollieSecurityManager(settings)
    validator = WebhookValidator(security_manager)

    # Validate webhook
    return validator.validate_webhook(payload, signature, headers)
