"""
Mollie Security Manager
Comprehensive security management for Mollie integration

Features:
- Webhook signature validation using HMAC-SHA256
- Manual API key management (Mollie doesn't support automatic rotation)
- Data encryption/decryption for sensitive information
- Security audit logging and monitoring
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import frappe
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from frappe import _
from frappe.utils import get_datetime, now_datetime

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.secure_operations import secure_document_operation


class MollieSecurityManager:
    """
    Comprehensive security management for Mollie integration

    Provides multi-layer security for financial data including:
    - Webhook signature validation using HMAC-SHA256
    - Manual API key management (Mollie doesn't support automatic rotation)
    - AES encryption for sensitive data storage
    - Immutable audit trail logging
    """

    def __init__(self, mollie_settings):
        """
        Initialize security manager with Mollie settings

        Args:
            mollie_settings: MollieSettings DocType instance
        """
        self.settings = mollie_settings
        self.encryption_key = self._get_or_create_encryption_key()
        self.cipher_suite = Fernet(self.encryption_key)

    def validate_webhook_signature(self, payload: str, signature: str, timestamp: str = None) -> bool:
        """
        Validate Mollie webhook signature using HMAC-SHA256

        Args:
            payload: Raw webhook payload string
            signature: X-Mollie-Signature header value
            timestamp: Optional timestamp for replay attack prevention

        Returns:
            bool: True if signature is valid and not replayed

        Raises:
            SecurityException: If signature validation fails
        """
        # Get webhook secret from settings. Mollie Settings has no plain
        # "webhook_secret" field — the secret is the test-mode-aware
        # testing_/live_webhook_secret_key, resolved by get_webhook_secret().
        webhook_secret = self.settings.get_webhook_secret()
        if not webhook_secret:
            self._create_security_alert("WEBHOOK_SECRET_MISSING", "critical")
            frappe.log_error("Webhook secret not configured", "Mollie Security")
            raise SecurityException("Webhook secret not configured - cannot validate webhook security")

        # Validate timestamp to prevent replay attacks (5 minute window)
        if timestamp:
            if not self._validate_webhook_timestamp(timestamp):
                self._create_security_alert("WEBHOOK_REPLAY_ATTEMPT", "warning", f"Timestamp: {timestamp}")
                raise SecurityException("Webhook timestamp validation failed - possible replay attack")

        # Calculate expected signature
        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(signature, expected_signature)

        if not is_valid:
            self._create_security_alert(
                "WEBHOOK_SIGNATURE_INVALID", "critical", f"Received: {signature[:20]}..."
            )
            raise SecurityException("Webhook signature validation failed - invalid signature")

        # Successful validations are routine infrastructure - no audit logging needed

        return True

    def rotate_api_keys(self) -> Dict[str, str]:
        """
        Rotate API keys with graceful fallback for zero downtime

        NOTE: Mollie does not support automatic API key rotation.
        This method is disabled as it's not applicable to Mollie's API model.
        API keys should be manually rotated through the Mollie dashboard.

        Returns:
            Dict with status and information about manual rotation process
        """
        try:
            # Log that automatic rotation is not supported
            self._create_audit_log(
                "API_KEY_ROTATION",
                "skipped",
                {
                    "reason": "Mollie does not support automatic API key rotation",
                    "action_required": "Manual rotation through Mollie dashboard",
                    "timestamp": frappe.utils.now(),
                },
            )

            return {
                "status": "info",
                "message": _(
                    "Mollie API keys do not support automatic rotation. Please rotate keys manually through the Mollie dashboard."
                ),
                "manual_process": [
                    "1. Generate new API key in Mollie dashboard",
                    "2. Update key in Verenigingen settings",
                    "3. Monitor for any issues",
                    "4. Keep old key for 24 hours as backup",
                ],
            }

        except Exception as e:
            # Don't create critical alerts for disabled functionality
            frappe.log_error(f"API key rotation info: {str(e)}", "Mollie Security Info")
            return {
                "status": "info",
                "message": _("API key rotation is not available for Mollie integration"),
            }

    def encrypt_sensitive_data(self, data: str) -> str:
        """
        Encrypt sensitive financial data using Fernet (AES)

        Args:
            data: Plain text data to encrypt

        Returns:
            str: Base64 encoded encrypted data
        """
        if not data:
            return ""

        try:
            # Ensure data is string
            if not isinstance(data, str):
                data = str(data)

            # Encrypt and return base64 string
            encrypted = self.cipher_suite.encrypt(data.encode("utf-8"))
            return encrypted.decode("utf-8")

        except Exception as e:
            frappe.log_error(f"Encryption failed: {str(e)}", "Mollie Security")
            raise SecurityException(f"Failed to encrypt data: {str(e)}")

    def decrypt_sensitive_data(self, encrypted_data: str) -> str:
        """
        Decrypt sensitive financial data

        Args:
            encrypted_data: Base64 encoded encrypted data

        Returns:
            str: Decrypted plain text data
        """
        if not encrypted_data:
            return ""

        try:
            # Decrypt and return string
            decrypted = self.cipher_suite.decrypt(encrypted_data.encode("utf-8"))
            return decrypted.decode("utf-8")

        except Exception as e:
            frappe.log_error(f"Decryption failed: {str(e)}", "Mollie Security")
            raise SecurityException(f"Failed to decrypt data: {str(e)}")

    def _get_or_create_encryption_key(self) -> bytes:
        """
        Get or create encryption key for data protection

        Returns:
            bytes: Encryption key for Fernet
        """
        # Check if encryption key exists - use raise_exception=False to handle missing field gracefully
        stored_key = self.settings.get_password("encryption_key", raise_exception=False)

        if stored_key:
            # Decode from base64
            return base64.urlsafe_b64decode(stored_key.encode("utf-8"))
        else:
            # Generate new key
            key = Fernet.generate_key()

            # Try to store as base64 string - use proper Frappe method for Single DocType
            try:
                # For Single DocTypes, use the frappe.db.set_value method for Password fields
                frappe.db.set_value(
                    "Mollie Settings", None, "encryption_key", base64.urlsafe_b64encode(key).decode("utf-8")
                )
                frappe.db.commit()
                self._create_audit_log("ENCRYPTION_KEY_CREATED", "success")
            except Exception as e:
                # SECURITY: Do NOT fall back to a deterministic key - this is a security risk
                # If the encryption key cannot be persisted, fail loudly and require manual intervention
                error_msg = (
                    f"CRITICAL: Could not persist Mollie encryption key: {str(e)}. "
                    "Manual intervention required. Please ensure the 'encryption_key' "
                    "Password field exists in Mollie Settings DocType and has proper permissions."
                )
                frappe.log_error(error_msg, "Mollie Security - CRITICAL")
                self._create_security_alert(
                    "ENCRYPTION_KEY_STORAGE_FAILED",
                    "critical",
                    f"Cannot persist encryption key: {str(e)}",
                )
                raise SecurityException(
                    "Failed to store encryption key securely. Cannot proceed without secure key storage. "
                    "Please check that Mollie Settings DocType has the 'encryption_key' Password field "
                    "and that the current user has permission to modify it."
                )

            return key

    def _validate_webhook_timestamp(self, timestamp: str, tolerance_seconds: int = 300) -> bool:
        """
        Validate webhook timestamp to prevent replay attacks

        Args:
            timestamp: ISO format timestamp from webhook
            tolerance_seconds: Maximum age of webhook in seconds (default 5 minutes)

        Returns:
            bool: True if timestamp is within tolerance
        """
        try:
            webhook_time = get_datetime(timestamp)
            current_time = now_datetime()

            # Calculate time difference
            time_diff = abs((current_time - webhook_time).total_seconds())

            # Check if within tolerance
            return time_diff <= tolerance_seconds

        except Exception as e:
            frappe.log_error(f"Timestamp validation failed: {str(e)}", "Mollie Security")
            return False

    def _test_api_connectivity(self, api_key: str) -> bool:
        """
        Test API connectivity with given key

        Args:
            api_key: API key to test

        Returns:
            bool: True if connectivity test passes
        """
        try:
            from mollie.api.client import Client

            client = Client()
            client.set_api_key(api_key)

            # Simple test call to verify key works
            client.methods.list()
            return True

        except Exception as e:
            frappe.log_error(f"API connectivity test failed: {str(e)}", "Mollie Security")
            return False

    def _schedule_fallback_cleanup(self):
        """Schedule cleanup of fallback API key after 24 hours"""
        from frappe.utils.background_jobs import enqueue

        enqueue(
            "verenigingen.verenigingen_payments.core.security.mollie_security_manager.cleanup_fallback_key",
            queue="long",
            timeout=300,
            enqueue_after_commit=True,
            mollie_settings_name=self.settings.name,
        )

    def _create_audit_log(self, action: str, status: str, details: Any = None):
        """
        Create immutable security audit log

        Args:
            action: Action being logged
            status: Status of action (success/failed)
            details: Additional details to log
        """
        try:
            # Check if Mollie Audit Log DocType exists
            if not frappe.db.exists("DocType", "Mollie Audit Log"):
                # Skip audit logging if DocType doesn't exist yet
                frappe.logger().warning(f"Audit log skipped - DocType not created yet: {action}")
                return

            audit_log = frappe.new_doc("Mollie Audit Log")
            audit_log.update(
                {
                    "action": action,
                    "status": status,
                    "details": json.dumps(details) if details else None,
                    "user": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                    "ip_address": (
                        frappe.local.request.environ.get("REMOTE_ADDR") if frappe.local.request else None
                    ),
                }
            )

            # Calculate integrity hash for immutability
            audit_log.integrity_hash = self._calculate_integrity_hash(audit_log)

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="insert",
                doc=audit_log,
                justification=f"Create Mollie security audit log for {action} with status {status} - critical financial security audit trail",
                required_permissions=["Mollie Audit Log:create"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to create Mollie audit log: {'; '.join(result.errors)}", "Mollie Security Audit"
                )

        except Exception as e:
            # Log error but don't fail the main operation
            frappe.log_error(f"Failed to create audit log: {str(e)}", "Mollie Security Audit")

    def _create_security_alert(self, alert_type: str, severity: str, details: str = None):
        """
        Create security alert for monitoring

        Args:
            alert_type: Type of security alert
            severity: Severity level (info/warning/critical)
            details: Additional alert details
        """
        # Log security alert
        frappe.log_error(
            f"Security Alert: {alert_type}\nSeverity: {severity}\nDetails: {details}", "Mollie Security Alert"
        )

        # Send notification to security team if critical
        if severity == "critical":
            # Send email notification to administrators
            try:
                from frappe.utils.user import get_system_managers

                system_managers = get_system_managers(only_name=True)

                if system_managers:
                    email_service = get_email_service()
                    email_service.send_simple_email(
                        recipients=system_managers,
                        subject=f"🚨 Critical Mollie Security Alert: {alert_type}",
                        message=f"""
                        <h3>Critical Security Alert</h3>
                        <p><strong>Alert Type:</strong> {alert_type}</p>
                        <p><strong>Severity:</strong> {severity}</p>
                        <p><strong>Details:</strong> {details}</p>
                        <p><strong>Timestamp:</strong> {frappe.utils.now()}</p>
                        <p><strong>Site:</strong> {frappe.local.site}</p>

                        <p>Please investigate this security incident immediately.</p>
                        """,
                        now=True,
                        notification_key="mollie_security_alert",
                    )
            except Exception as e:
                frappe.log_error(f"Failed to send security alert email: {str(e)}", "Mollie Security")

    def _calculate_integrity_hash(self, audit_log) -> str:
        """
        Calculate integrity hash for audit log immutability

        Args:
            audit_log: Audit log document

        Returns:
            str: SHA256 hash of audit log data
        """
        # Create hash of critical fields
        hash_data = f"{audit_log.action}|{audit_log.status}|{audit_log.details}|{audit_log.timestamp}|{audit_log.user}"
        return hashlib.sha256(hash_data.encode("utf-8")).hexdigest()


class SecurityException(Exception):
    """Custom exception for security-related errors"""

    pass


def cleanup_fallback_key():
    """
    Background job to cleanup fallback API key after expiry
    """
    try:
        settings = frappe.get_single("Mollie Settings")

        # Check if fallback key has expired
        if settings.fallback_key_expiry and get_datetime(settings.fallback_key_expiry) < now_datetime():
            # Clear fallback key
            frappe.db.set_value("Mollie Settings", None, "secret_key_fallback", "")
            settings.db_set("fallback_key_expiry", None)

            # Log cleanup
            security_manager = MollieSecurityManager(settings)
            security_manager._create_audit_log("FALLBACK_KEY_CLEANUP", "success")

    except Exception as e:
        frappe.log_error(f"Fallback key cleanup failed: {str(e)}", "Mollie Security")
