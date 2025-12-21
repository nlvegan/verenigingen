"""
Mollie Integration Logging Utilities

Comprehensive logging for Mollie operations with structured logging,
performance monitoring, and security considerations.
"""

import json
import time
from datetime import datetime
from functools import wraps
from typing import Any, Dict, Optional, Union

import frappe


class MollieLogger:
    """
    Structured logger for Mollie integration operations.

    Provides consistent logging format, security filtering, and performance tracking.
    """

    def __init__(self, operation_type: str = "general"):
        self.operation_type = operation_type
        self.start_time = time.time()

    def _get_base_context(self) -> Dict[str, Any]:
        """Get base logging context."""
        return {
            "timestamp": datetime.now().isoformat(),
            "operation_type": self.operation_type,
            "site": frappe.local.site if hasattr(frappe.local, "site") else None,
            "user": frappe.session.user if hasattr(frappe, "session") and frappe.session else None,
        }

    def _sanitize_data(self, data: Any) -> Any:
        """
        Remove sensitive information from log data.

        Args:
            data: Data to sanitize

        Returns:
            Sanitized data safe for logging
        """
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Remove API keys, tokens, secrets
                if any(
                    sensitive in key.lower() for sensitive in ["key", "token", "secret", "password", "auth"]
                ):
                    sanitized[key] = "***REDACTED***"
                # Truncate payment IDs to prevent log flooding while keeping debuggability
                elif key.lower() in ["id", "payment_id", "subscription_id", "customer_id"]:
                    sanitized[key] = str(value)[:12] + "..." if len(str(value)) > 12 else value
                else:
                    sanitized[key] = self._sanitize_data(value)
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        elif isinstance(data, str) and len(data) > 200:
            # Truncate very long strings to prevent log bloat
            return data[:200] + "..."
        else:
            return data

    def info(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log info level message."""
        context = self._get_base_context()
        if data:
            context["data"] = self._sanitize_data(data)
        context.update(kwargs)

        frappe.logger("mollie").info(f"🔵 [{self.operation_type}] {message}", extra=context)

    def success(
        self, message: str, data: Optional[Dict[str, Any]] = None, duration: Optional[float] = None, **kwargs
    ):
        """Log successful operation."""
        context = self._get_base_context()
        if data:
            context["data"] = self._sanitize_data(data)
        if duration:
            context["duration_ms"] = round(duration * 1000, 2)
        context.update(kwargs)

        frappe.logger("mollie").info(f"✅ [{self.operation_type}] {message}", extra=context)

    def warning(self, message: str, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log warning message."""
        context = self._get_base_context()
        if data:
            context["data"] = self._sanitize_data(data)
        context.update(kwargs)

        frappe.logger("mollie").warning(f"⚠️ [{self.operation_type}] {message}", extra=context)

    def error(
        self, message: str, error: Optional[Exception] = None, data: Optional[Dict[str, Any]] = None, **kwargs
    ):
        """Log error with optional exception details."""
        context = self._get_base_context()
        if data:
            context["data"] = self._sanitize_data(data)
        if error:
            context["error_type"] = type(error).__name__
            context["error_message"] = str(error)
        context.update(kwargs)

        frappe.logger("mollie").error(f"❌ [{self.operation_type}] {message}", extra=context)

        # Also log to Frappe error log for visibility
        if error:
            frappe.log_error(
                f"Mollie {self.operation_type}: {message}\nError: {error}", "Mollie Integration Error"
            )

    def performance(self, operation: str, duration: float, data: Optional[Dict[str, Any]] = None, **kwargs):
        """Log performance metrics."""
        context = self._get_base_context()
        context.update(
            {"operation": operation, "duration_ms": round(duration * 1000, 2), "performance_log": True}
        )
        if data:
            context["data"] = self._sanitize_data(data)
        context.update(kwargs)

        # Log as warning if operation is slow (>2 seconds)
        level = "warning" if duration > 2.0 else "info"
        emoji = "🐌" if duration > 2.0 else "⚡"

        getattr(frappe.logger("mollie"), level)(
            f"{emoji} [{self.operation_type}] {operation} completed in {duration:.2f}s", extra=context
        )


def mollie_operation_logger(operation_type: str):
    """
    Decorator for automatic operation logging with performance tracking.

    Args:
        operation_type: Type of operation for logging context

    Usage:
        @mollie_operation_logger("webhook_processing")
        def process_webhook(payment_id):
            # Your code here
            return result
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = MollieLogger(operation_type)
            start_time = time.time()

            # Extract identifiable information for logging
            func_args = {
                "function": func.__name__,
                "args_count": len(args),
                "kwargs_keys": list(kwargs.keys()),
            }

            # Try to extract payment_id or other identifiers
            if args and hasattr(args[0], "__dict__"):
                # Method call - args[0] is self
                if len(args) > 1:
                    func_args["primary_arg"] = str(args[1])[:50]
            elif args:
                func_args["primary_arg"] = str(args[0])[:50]

            logger.info(f"Starting {func.__name__}", func_args)

            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time

                result_info = {"success": True}
                if isinstance(result, dict) and "status" in result:
                    result_info["status"] = result["status"]

                logger.success(f"Completed {func.__name__}", result_info, duration=duration)
                return result

            except Exception as e:
                duration = time.time() - start_time
                logger.error(f"Failed {func.__name__}", error=e, duration=duration)
                raise

        return wrapper

    return decorator


def log_mollie_api_call(
    method: str,
    endpoint: str,
    response_status: int,
    duration: float,
    request_data: Optional[Dict] = None,
    response_data: Optional[Dict] = None,
):
    """
    Log Mollie API calls with request/response details.

    Args:
        method: HTTP method (GET, POST, etc.)
        endpoint: API endpoint called
        response_status: HTTP response status code
        duration: Request duration in seconds
        request_data: Request payload (will be sanitized)
        response_data: Response data (will be sanitized)
    """
    logger = MollieLogger("api_call")

    call_data = {
        "method": method,
        "endpoint": endpoint,
        "status_code": response_status,
        "duration_ms": round(duration * 1000, 2),
    }

    if request_data:
        call_data["request"] = logger._sanitize_data(request_data)
    if response_data:
        call_data["response"] = logger._sanitize_data(response_data)

    if 200 <= response_status < 300:
        logger.success(f"API call {method} {endpoint}", call_data)
    elif 400 <= response_status < 500:
        logger.warning(f"API call {method} {endpoint} - Client Error", call_data)
    else:
        logger.error(f"API call {method} {endpoint} - Server Error", data=call_data)


def log_webhook_received(payment_id: str, webhook_data: Dict[str, Any]):
    """
    Log incoming webhook with security filtering.

    Args:
        payment_id: Payment ID from webhook
        webhook_data: Raw webhook data
    """
    logger = MollieLogger("webhook_incoming")

    webhook_info = {
        "payment_id": payment_id,
        "data_keys": list(webhook_data.keys()),
        "data_size": len(str(webhook_data)),
    }

    logger.info(f"Webhook received for payment {payment_id}", webhook_info)


def log_payment_processing(payment_id: str, operation: str, status: str, details: Optional[Dict] = None):
    """
    Log payment processing steps with business context.

    Args:
        payment_id: Payment ID being processed
        operation: Operation being performed (e.g., "create_payment_entry", "update_donation")
        status: Operation status (success, error, skipped)
        details: Additional operation details
    """
    logger = MollieLogger("payment_processing")

    processing_data = {"payment_id": payment_id, "operation": operation, "status": status}

    if details:
        processing_data["details"] = details

    if status == "success":
        logger.success(f"Payment processing: {operation}", processing_data)
    elif status == "error":
        logger.error(f"Payment processing failed: {operation}", data=processing_data)
    else:
        logger.info(f"Payment processing: {operation}", processing_data)


def log_integration_health_check(service: str, status: str, details: Optional[Dict] = None):
    """
    Log integration health check results.

    Args:
        service: Service being checked (e.g., "mollie_api", "webhook_endpoint")
        status: Health status (healthy, degraded, unhealthy)
        details: Additional health check details
    """
    logger = MollieLogger("health_check")

    health_data = {"service": service, "status": status, "check_time": datetime.now().isoformat()}

    if details:
        health_data["details"] = details

    if status == "healthy":
        logger.success(f"Health check passed: {service}", health_data)
    elif status == "degraded":
        logger.warning(f"Health check degraded: {service}", health_data)
    else:
        logger.error(f"Health check failed: {service}", data=health_data)
