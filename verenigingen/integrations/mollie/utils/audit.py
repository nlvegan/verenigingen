"""
Mollie Audit Logging

Comprehensive audit logging for Mollie integration operations.
Provides financial audit trails and compliance tracking.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime


class MollieAuditLogger:
    """
    Audit logger for Mollie integration operations.

    Provides comprehensive logging for:
    - Payment processing
    - Subscription management
    - Webhook events
    - API calls
    - Security events
    """

    def __init__(self):
        """Initialize audit logger."""
        self.log_settings = self._load_audit_settings()

    def _load_audit_settings(self) -> Dict[str, Any]:
        """Load audit logging settings."""
        try:
            mollie_settings = frappe.get_single("Mollie Settings")
            return {
                "enable_audit_logging": mollie_settings.get("enable_audit_logging", True),
                "log_api_calls": mollie_settings.get("log_api_calls", True),
                "log_webhooks": mollie_settings.get("log_webhooks", True),
                "log_retention_days": mollie_settings.get("log_retention_days", 90),
                "detailed_logging": mollie_settings.get("detailed_audit_logging", False),
            }
        except Exception:
            # Safe defaults if settings can't be loaded
            return {
                "enable_audit_logging": True,
                "log_api_calls": True,
                "log_webhooks": True,
                "log_retention_days": 90,
                "detailed_logging": False,
            }

    def log_payment_created(self, payment_data: Dict[str, Any], context: Optional[Dict] = None):
        """
        Log payment creation event.

        Args:
            payment_data: Payment information
            context: Additional context information
        """
        if not self.log_settings.get("enable_audit_logging"):
            return

        self._create_audit_log(
            event_type="payment_created",
            event_category="payment",
            description=f"Payment created: {payment_data.get('id', 'Unknown')}",
            data={
                "payment_id": payment_data.get("id"),
                "amount": payment_data.get("amount"),
                "currency": payment_data.get("currency", "EUR"),
                "description": payment_data.get("description"),
                "customer_id": payment_data.get("customer_id"),
                "context": context or {},
            },
        )

    def log_payment_completed(self, payment_id: str, payment_details: Dict[str, Any]):
        """
        Log payment completion event.

        Args:
            payment_id: Mollie payment ID
            payment_details: Payment completion details
        """
        if not self.log_settings.get("enable_audit_logging"):
            return

        self._create_audit_log(
            event_type="payment_completed",
            event_category="payment",
            description=f"Payment completed: {payment_id}",
            data={
                "payment_id": payment_id,
                "amount": payment_details.get("amount"),
                "currency": payment_details.get("currency"),
                "paid_at": payment_details.get("paid_at"),
                "method": payment_details.get("method"),
                "processing_result": payment_details.get("processing_result"),
            },
        )

    def log_payment_failed(self, payment_id: str, failure_reason: str, details: Optional[Dict] = None):
        """
        Log payment failure event.

        Args:
            payment_id: Mollie payment ID
            failure_reason: Reason for failure
            details: Additional failure details
        """
        self._create_audit_log(
            event_type="payment_failed",
            event_category="payment",
            description=f"Payment failed: {payment_id} - {failure_reason}",
            data={"payment_id": payment_id, "failure_reason": failure_reason, "details": details or {}},
            severity="error",
        )

    def log_subscription_created(self, subscription_data: Dict[str, Any], context: Optional[Dict] = None):
        """
        Log subscription creation event.

        Args:
            subscription_data: Subscription information
            context: Additional context
        """
        if not self.log_settings.get("enable_audit_logging"):
            return

        self._create_audit_log(
            event_type="subscription_created",
            event_category="subscription",
            description=f"Subscription created: {subscription_data.get('id', 'Unknown')}",
            data={
                "subscription_id": subscription_data.get("id"),
                "customer_id": subscription_data.get("customer_id"),
                "amount": subscription_data.get("amount"),
                "interval": subscription_data.get("interval"),
                "description": subscription_data.get("description"),
                "context": context or {},
            },
        )

    def log_subscription_canceled(self, subscription_id: str, reason: str, details: Optional[Dict] = None):
        """
        Log subscription cancellation event.

        Args:
            subscription_id: Mollie subscription ID
            reason: Cancellation reason
            details: Additional details
        """
        self._create_audit_log(
            event_type="subscription_canceled",
            event_category="subscription",
            description=f"Subscription canceled: {subscription_id} - {reason}",
            data={
                "subscription_id": subscription_id,
                "cancellation_reason": reason,
                "details": details or {},
            },
        )

    def log_webhook_received(self, webhook_data: Dict[str, Any], headers: Dict[str, str]):
        """
        Log incoming webhook event.

        Args:
            webhook_data: Webhook payload
            headers: HTTP headers
        """
        if not self.log_settings.get("log_webhooks"):
            return

        # Sanitize sensitive headers
        safe_headers = {
            k: v
            for k, v in headers.items()
            if not any(sensitive in k.lower() for sensitive in ["authorization", "signature", "secret"])
        }

        self._create_audit_log(
            event_type="webhook_received",
            event_category="webhook",
            description="Mollie webhook received",
            data={
                "webhook_data": webhook_data
                if self.log_settings.get("detailed_logging")
                else {"id": webhook_data.get("id")},
                "headers": safe_headers,
                "timestamp": now_datetime(),
            },
        )

    def log_webhook_processed(self, webhook_id: str, processing_result: Dict[str, Any]):
        """
        Log webhook processing completion.

        Args:
            webhook_id: Webhook identifier
            processing_result: Processing result
        """
        self._create_audit_log(
            event_type="webhook_processed",
            event_category="webhook",
            description=f"Webhook processed: {webhook_id}",
            data={
                "webhook_id": webhook_id,
                "processing_result": processing_result,
                "processing_time": processing_result.get("processing_time"),
            },
        )

    def log_webhook_error(self, error_message: str, webhook_data: Dict[str, Any]):
        """
        Log webhook processing error.

        Args:
            error_message: Error description
            webhook_data: Original webhook data
        """
        self._create_audit_log(
            event_type="webhook_error",
            event_category="webhook",
            description=f"Webhook processing error: {error_message}",
            data={
                "error_message": error_message,
                "webhook_data": webhook_data
                if self.log_settings.get("detailed_logging")
                else {"id": webhook_data.get("id")},
                "timestamp": now_datetime(),
            },
            severity="error",
        )

    def log_webhook_ping(self, ping_data: Dict[str, Any]):
        """
        Log webhook ping event.

        Args:
            ping_data: Ping event data
        """
        self._create_audit_log(
            event_type="webhook_ping",
            event_category="webhook",
            description="Mollie webhook ping received",
            data={"ping_data": ping_data, "test_mode": ping_data.get("test_mode", True)},
        )

    def log_api_call(
        self,
        method: str,
        endpoint: str,
        request_data: Optional[Dict] = None,
        response_data: Optional[Dict] = None,
        duration_ms: Optional[float] = None,
    ):
        """
        Log Mollie API call.

        Args:
            method: HTTP method
            endpoint: API endpoint
            request_data: Request payload (optional)
            response_data: Response data (optional)
            duration_ms: Call duration in milliseconds
        """
        if not self.log_settings.get("log_api_calls"):
            return

        # Sanitize sensitive data
        safe_request = self._sanitize_api_data(request_data) if request_data else None
        safe_response = self._sanitize_api_data(response_data) if response_data else None

        self._create_audit_log(
            event_type="api_call",
            event_category="api",
            description=f"Mollie API call: {method} {endpoint}",
            data={
                "method": method,
                "endpoint": endpoint,
                "request_data": safe_request if self.log_settings.get("detailed_logging") else None,
                "response_data": safe_response if self.log_settings.get("detailed_logging") else None,
                "duration_ms": duration_ms,
                "timestamp": now_datetime(),
            },
        )

    def log_security_event(
        self, event_type: str, description: str, details: Dict[str, Any], severity: str = "warning"
    ):
        """
        Log security-related event.

        Args:
            event_type: Type of security event
            description: Event description
            details: Event details
            severity: Event severity
        """
        self._create_audit_log(
            event_type=f"security_{event_type}",
            event_category="security",
            description=description,
            data=details,
            severity=severity,
        )

    def log_configuration_change(
        self, setting_name: str, old_value: Any, new_value: Any, user: Optional[str] = None
    ):
        """
        Log configuration change.

        Args:
            setting_name: Name of changed setting
            old_value: Previous value
            new_value: New value
            user: User making the change
        """
        # Sanitize sensitive values
        safe_old_value = (
            "***" if "secret" in setting_name.lower() or "key" in setting_name.lower() else old_value
        )
        safe_new_value = (
            "***" if "secret" in setting_name.lower() or "key" in setting_name.lower() else new_value
        )

        self._create_audit_log(
            event_type="configuration_change",
            event_category="configuration",
            description=f"Configuration changed: {setting_name}",
            data={
                "setting_name": setting_name,
                "old_value": safe_old_value,
                "new_value": safe_new_value,
                "changed_by": user or frappe.session.user,
                "timestamp": now_datetime(),
            },
        )

    def _create_audit_log(
        self,
        event_type: str,
        event_category: str,
        description: str,
        data: Dict[str, Any],
        severity: str = "info",
    ):
        """
        Create audit log entry.

        Args:
            event_type: Type of event
            event_category: Event category
            description: Event description
            data: Event data
            severity: Event severity
        """
        try:
            # Create audit log document
            audit_log = frappe.get_doc(
                {
                    "doctype": "Mollie Audit Log",
                    "event_type": event_type,
                    "event_category": event_category,
                    "description": description,
                    "event_data": json.dumps(data, default=str),
                    "severity": severity,
                    "timestamp": now_datetime(),
                    "user": frappe.session.user if frappe.session else "System",
                    "ip_address": frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None,
                }
            )

            audit_log.insert(ignore_permissions=True)

            # Also log to system log for critical events
            if severity in ["error", "critical"]:
                frappe.log_error(
                    f"Mollie {event_category} event: {description}\nData: {json.dumps(data, default=str)}",
                    f"Mollie {event_type}",
                )

        except Exception as e:
            # Fallback to system logging if audit log creation fails
            frappe.log_error(
                f"Failed to create Mollie audit log: {e}\nOriginal event: {description}",
                "Mollie Audit Log Error",
            )

    def _sanitize_api_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sanitize API data to remove sensitive information.

        Args:
            data: Raw API data

        Returns:
            Sanitized data dictionary
        """
        if not isinstance(data, dict):
            return data

        sanitized = {}
        sensitive_fields = ["authorization", "signature", "secret", "password", "key", "token"]

        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                sanitized[key] = "***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_api_data(value)
            else:
                sanitized[key] = value

        return sanitized

    def cleanup_old_logs(self, days_to_keep: Optional[int] = None):
        """
        Clean up old audit logs based on retention policy.

        Args:
            days_to_keep: Number of days to keep logs (uses setting if not provided)
        """
        retention_days = days_to_keep or self.log_settings.get("log_retention_days", 90)

        if retention_days <= 0:
            return  # Don't clean up if retention is disabled

        try:
            from frappe.utils import add_days

            cutoff_date = add_days(now_datetime(), -retention_days)

            # Delete old audit logs
            frappe.db.delete("Mollie Audit Log", {"timestamp": ("<", cutoff_date)})

            frappe.db.commit()

            frappe.logger().info(f"Cleaned up Mollie audit logs older than {retention_days} days")

        except Exception as e:
            frappe.log_error(f"Failed to cleanup old Mollie audit logs: {e}", "Mollie Audit Cleanup")


# Convenience functions for easy access
def log_mollie_payment_event(event_type: str, payment_data: Dict[str, Any], **kwargs):
    """Convenience function for logging payment events."""
    logger = MollieAuditLogger()

    if event_type == "created":
        logger.log_payment_created(payment_data, kwargs.get("context"))
    elif event_type == "completed":
        logger.log_payment_completed(payment_data.get("id"), payment_data)
    elif event_type == "failed":
        logger.log_payment_failed(payment_data.get("id"), kwargs.get("reason", "Unknown"), payment_data)


def log_mollie_webhook_event(event_type: str, webhook_data: Dict[str, Any], **kwargs):
    """Convenience function for logging webhook events."""
    logger = MollieAuditLogger()

    if event_type == "received":
        logger.log_webhook_received(webhook_data, kwargs.get("headers", {}))
    elif event_type == "processed":
        logger.log_webhook_processed(webhook_data.get("id"), kwargs.get("result", {}))
    elif event_type == "error":
        logger.log_webhook_error(kwargs.get("error", "Unknown error"), webhook_data)


def log_mollie_security_event(
    event_type: str, description: str, details: Dict[str, Any], severity: str = "warning"
):
    """Convenience function for logging security events."""
    logger = MollieAuditLogger()
    logger.log_security_event(event_type, description, details, severity)
