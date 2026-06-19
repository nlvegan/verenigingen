"""
Logging Utilities for Payment Services

Provides consistent logging patterns and structured logging for payment processing.
"""

import json
from typing import Any, Dict, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.payment_services.constants import (
    LOG_CATEGORY_PAYMENT,
    LOG_CATEGORY_REFUND,
    LOG_CATEGORY_SECURITY,
    LOG_CATEGORY_VALIDATION,
    LOG_CATEGORY_WEBHOOK,
)


class PaymentLogger:
    """Centralized logging for payment services with structured data."""

    @staticmethod
    def log_debug(message: str, category: str, context: Optional[Dict[str, Any]] = None):
        """Log debug messages with structured context. Never raises.

        This sink is called from inside money-path try/except blocks, so a logging
        failure must never propagate into (and mask/alter) the real outcome.
        """
        structured_message = PaymentLogger._format_message(message, category, context)
        try:
            frappe.logger().debug(structured_message)
        except Exception:
            pass

    @staticmethod
    def log_info(message: str, category: str, context: Optional[Dict[str, Any]] = None):
        """Log info messages with structured context. Never raises."""
        structured_message = PaymentLogger._format_message(message, category, context)
        try:
            frappe.logger().info(structured_message)
        except Exception:
            pass

    @staticmethod
    def log_warning(message: str, category: str, context: Optional[Dict[str, Any]] = None):
        """Log warning messages with structured context. Never raises."""
        structured_message = PaymentLogger._format_message(message, category, context)
        try:
            frappe.logger().warning(structured_message)
        except Exception:
            pass

    @staticmethod
    def log_error(
        message: str, category: str, context: Optional[Dict[str, Any]] = None, exc_info: bool = False
    ):
        """Log error messages to both logger and Frappe error log. Never raises."""
        structured_message = PaymentLogger._format_message(message, category, context)

        # Log to standard logger
        try:
            frappe.logger().error(structured_message, exc_info=exc_info)
        except Exception:
            pass

        # Also log to Frappe error log for visibility in desk. Truncate the title
        # to <=140 chars to avoid CharacterLengthExceededError on long messages.
        try:
            frappe.log_error(title=f"{category}: {message}"[:140], message=structured_message)
        except Exception:
            pass

    @staticmethod
    def log_payment_event(event_type: str, payment_id: str, details: Dict[str, Any]):
        """Log payment-specific events with standardized format."""
        context = {
            "event_type": event_type,
            "payment_id": payment_id,
            "details": details,
            "timestamp": now_datetime().isoformat(),
        }

        PaymentLogger.log_info(f"Payment event: {event_type} for {payment_id}", LOG_CATEGORY_PAYMENT, context)

    @staticmethod
    def log_refund_event(event_type: str, payment_id: str, refund_id: Optional[str], details: Dict[str, Any]):
        """Log refund-specific events with standardized format."""
        context = {
            "event_type": event_type,
            "payment_id": payment_id,
            "refund_id": refund_id,
            "details": details,
            "timestamp": now_datetime().isoformat(),
        }

        PaymentLogger.log_info(
            f"Refund event: {event_type} for payment {payment_id}"
            + (f", refund {refund_id}" if refund_id else ""),
            LOG_CATEGORY_REFUND,
            context,
        )

    @staticmethod
    def log_webhook_event(event_type: str, webhook_id: str, details: Dict[str, Any]):
        """Log webhook-specific events with standardized format."""
        context = {
            "event_type": event_type,
            "webhook_id": webhook_id,
            "details": details,
            "timestamp": now_datetime().isoformat(),
        }

        PaymentLogger.log_info(f"Webhook event: {event_type} for {webhook_id}", LOG_CATEGORY_WEBHOOK, context)

    @staticmethod
    def log_security_event(event_type: str, details: Dict[str, Any], severity: str = "warning"):
        """Log security-related events with high visibility."""
        context = {
            "event_type": event_type,
            "severity": severity,
            "details": details,
            "timestamp": now_datetime().isoformat(),
            "user": frappe.session.user if frappe.session else "System",
        }

        message = f"Security event: {event_type}"

        if severity == "error":
            PaymentLogger.log_error(message, LOG_CATEGORY_SECURITY, context)
        else:
            PaymentLogger.log_warning(message, LOG_CATEGORY_SECURITY, context)

    @staticmethod
    def log_validation_error(validation_type: str, error_details: Dict[str, Any]):
        """Log validation errors with structured context."""
        context = {
            "validation_type": validation_type,
            "error_details": error_details,
            "timestamp": now_datetime().isoformat(),
        }

        PaymentLogger.log_warning(f"Validation error: {validation_type}", LOG_CATEGORY_VALIDATION, context)

    @staticmethod
    def _format_message(message: str, category: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Format log message with structured context."""
        formatted_message = f"[{category}] {message}"

        if context:
            try:
                context_json = json.dumps(context, indent=2, default=str)
                formatted_message += f"\nContext: {context_json}"
            except (TypeError, ValueError) as e:
                formatted_message += f"\nContext (serialization failed): {str(context)} - Error: {str(e)}"

        return formatted_message


# Convenience functions for common logging patterns
def log_payment_initiated(payment_id: str, amount: float, payment_method: str):
    """Log payment initiation."""
    PaymentLogger.log_payment_event(
        "payment_initiated", payment_id, {"amount": amount, "payment_method": payment_method}
    )


def log_refund_initiated(payment_id: str, refund_id: str, amount: float, reason: str):
    """Log refund initiation."""
    PaymentLogger.log_refund_event(
        "refund_initiated", payment_id, refund_id, {"amount": amount, "reason": reason}
    )


def log_webhook_received(webhook_id: str, webhook_type: str, payload_size: int):
    """Log webhook receipt."""
    PaymentLogger.log_webhook_event(
        "webhook_received", webhook_id, {"webhook_type": webhook_type, "payload_size": payload_size}
    )


def log_signature_validation_failed(webhook_id: str, expected_vs_actual: Dict[str, str]):
    """Log signature validation failure."""
    PaymentLogger.log_security_event(
        "signature_validation_failed",
        {"webhook_id": webhook_id, "expected_vs_actual": expected_vs_actual},
        severity="error",
    )


def log_concurrent_refund_detected(payment_id: str, attempted_amount: float, available_amount: float):
    """Log concurrent refund attempt detection."""
    PaymentLogger.log_security_event(
        "concurrent_refund_detected",
        {
            "payment_id": payment_id,
            "attempted_amount": attempted_amount,
            "available_amount": available_amount,
        },
        severity="warning",
    )
