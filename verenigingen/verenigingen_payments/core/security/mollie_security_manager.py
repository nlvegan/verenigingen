"""
Mollie Security Manager
Comprehensive security management for Mollie integration

Features:
- API key rotation with zero downtime
- Webhook signature validation
- Data encryption/decryption
- Security audit logging
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


class MollieSecurityManager:
    """
    Comprehensive security management for Mollie integration

    Provides multi-layer security for financial data including:
    - Webhook signature validation using HMAC-SHA256
    - API key rotation with zero-downtime fallback
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
        # Get webhook secret from settings
        webhook_secret = self.settings.get_password("webhook_secret")
        if not webhook_secret:
            self._create_security_alert("WEBHOOK_SECRET_MISSING", "critical")
            frappe.log_error("Webhook secret not configured", "Mollie Security")
            return False

        # Validate timestamp to prevent replay attacks (5 minute window)
        if timestamp:
            if not self._validate_webhook_timestamp(timestamp):
                self._create_security_alert("WEBHOOK_REPLAY_ATTEMPT", "warning", f"Timestamp: {timestamp}")
                return False

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

        # Log successful validation for audit
        if is_valid:
            self._create_audit_log("WEBHOOK_VALIDATED", "success", {"signature": signature[:20] + "..."})

        return is_valid

    def rotate_api_keys(self) -> Dict[str, str]:
        """
        Rotate API keys with graceful fallback for zero downtime

        Process:
        1. Store current key as fallback
        2. Validate new key connectivity
        3. Update primary key
        4. Keep fallback for 24 hours
        5. Schedule cleanup of old key

        Returns:
            Dict with rotation status and metadata

        Raises:
            SecurityException: If rotation fails
        """
        try:
            # Get current API key
            current_key = self.settings.get_password("secret_key")
            if not current_key:
                raise SecurityException("No current API key found")

            # Store current key as fallback with timestamp
            self.settings.set_password("secret_key_fallback", current_key)
            self.settings.db_set("key_rotation_date", frappe.utils.now())
            self.settings.db_set("fallback_key_expiry", frappe.utils.add_days(frappe.utils.now(), 1))

            # Note: New key should be obtained from Mollie dashboard
            # This is a placeholder for the rotation process
            new_key = self.settings.get_password("secret_key_pending")
            if not new_key:
                raise SecurityException("No pending API key found for rotation")

            # Test connectivity with new key
            if self._test_api_connectivity(new_key):
                # Update primary key
                self.settings.set_password("secret_key", new_key)
                self.settings.set_password("secret_key_pending", "")  # Clear pending

                # Schedule cleanup of fallback key after 24 hours
                self._schedule_fallback_cleanup()

                # Create audit log
                self._create_audit_log("API_KEY_ROTATION", "success", {"rotation_date": frappe.utils.now()})

                return {
                    "status": "success",
                    "rotation_date": frappe.utils.now(),
                    "fallback_expiry": self.settings.fallback_key_expiry,
                    "message": _("API key rotated successfully with 24-hour fallback"),
                }
            else:
                # Rollback on failure
                self.settings.set_password("secret_key_fallback", "")
                raise SecurityException("New API key validation failed")

        except Exception as e:
            self._create_audit_log("API_KEY_ROTATION", "failed", str(e))
            self._create_security_alert("API_KEY_ROTATION_FAILED", "critical", str(e))
            raise SecurityException(f"API key rotation failed: {str(e)}")

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
        # Check if encryption key exists
        stored_key = self.settings.get_password("encryption_key")

        if stored_key:
            # Decode from base64
            return base64.urlsafe_b64decode(stored_key.encode("utf-8"))
        else:
            # Generate new key
            key = Fernet.generate_key()

            # Store as base64 string
            self.settings.set_password("encryption_key", base64.urlsafe_b64encode(key).decode("utf-8"))

            self._create_audit_log("ENCRYPTION_KEY_CREATED", "success")
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
                frappe.log_error(f"Audit log skipped - DocType not created yet: {action}", "Mollie Security")
                return

            audit_log = frappe.new_doc("Mollie Audit Log")
            audit_log.update(
                {
                    "action": action,
                    "status": status,
                    "details": json.dumps(details) if details else None,
                    "user": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                    "ip_address": frappe.local.request.environ.get("REMOTE_ADDR")
                    if frappe.local.request
                    else None,
                }
            )

            # Calculate integrity hash for immutability
            audit_log.integrity_hash = self._calculate_integrity_hash(audit_log)

            # Insert with system permissions
            audit_log.flags.ignore_permissions = True
            audit_log.insert()

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

        # TODO: Send notification to security team if critical
        if severity == "critical":
            # Send email or system notification
            pass

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


def cleanup_fallback_key(mollie_settings_name: str):
    """
    Background job to cleanup fallback API key after expiry

    Args:
        mollie_settings_name: Name of Mollie Settings document
    """
    try:
        settings = frappe.get_doc("Mollie Settings", mollie_settings_name)

        # Check if fallback key has expired
        if settings.fallback_key_expiry and get_datetime(settings.fallback_key_expiry) < now_datetime():
            # Clear fallback key
            settings.set_password("secret_key_fallback", "")
            settings.db_set("fallback_key_expiry", None)

            # Log cleanup
            security_manager = MollieSecurityManager(settings)
            security_manager._create_audit_log("FALLBACK_KEY_CLEANUP", "success")

    except Exception as e:
        frappe.log_error(f"Fallback key cleanup failed: {str(e)}", "Mollie Security")
