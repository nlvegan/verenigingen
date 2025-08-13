"""
SEPA Error Handler with Retry Mechanisms and Circuit Breaker Pattern
Provides granular error handling for SEPA batch processing operations
"""

import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import frappe
from frappe.utils import cstr, now_datetime, today


class SEPAErrorHandler:
    """
    Advanced error handler for SEPA operations with retry logic and circuit breaker
    """

    def __init__(self):
        self.retry_config = {
            "max_retries": 3,
            "base_delay": 1.0,  # seconds
            "max_delay": 60.0,  # seconds
            "backoff_multiplier": 2.0,
        }

        # Circuit breaker state
        self.circuit_breaker = {
            "failure_threshold": 5,  # failures before opening circuit
            "recovery_timeout": 300,  # seconds (5 minutes)
            "half_open_max_calls": 3,
            "failure_count": 0,
            "state": "closed",  # closed, open, half_open
            "last_failure_time": None,
        }

        # Error categories for different handling strategies
        self.error_categories = {
            "temporary": [
                "connection",
                "timeout",
                "temporary",
                "server",
                "network",
                "busy",
                "unavailable",
                "overload",
            ],
            "validation": [
                "validation",
                "invalid",
                "missing",
                "format",
                "required",
                "constraint",
                "duplicate",
            ],
            "authorization": ["permission", "unauthorized", "access", "forbidden", "authentication"],
            "data": ["not found", "does not exist", "empty", "null"],
        }

    def categorize_error(self, error: Exception) -> str:
        """Categorize error for appropriate handling strategy"""
        error_message = str(error).lower()

        for category, keywords in self.error_categories.items():
            if any(keyword in error_message for keyword in keywords):
                return category

        return "unknown"

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if operation should be retried based on error type and attempt count"""
        if attempt >= self.retry_config["max_retries"]:
            return False

        error_category = self.categorize_error(error)

        # Don't retry validation or data errors - they need manual intervention
        if error_category in ["validation", "data"]:
            return False

        # Don't retry authorization errors unless it's the first attempt
        if error_category == "authorization" and attempt > 0:
            return False

        # Retry temporary errors and unknown errors (could be temporary)
        return error_category in ["temporary", "unknown"]

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay before retry using exponential backoff with jitter"""
        import random

        delay = min(
            self.retry_config["base_delay"] * (self.retry_config["backoff_multiplier"] ** attempt),
            self.retry_config["max_delay"],
        )

        # Add jitter to prevent thundering herd
        jitter = delay * 0.1 * random.random()
        return delay + jitter

    def check_circuit_breaker(self) -> bool:
        """Check if circuit breaker allows operation"""
        now = now_datetime()

        if self.circuit_breaker["state"] == "closed":
            return True

        elif self.circuit_breaker["state"] == "open":
            # Check if recovery timeout has passed
            if (
                self.circuit_breaker["last_failure_time"]
                and (now - self.circuit_breaker["last_failure_time"]).seconds
                >= self.circuit_breaker["recovery_timeout"]
            ):
                self.circuit_breaker["state"] = "half_open"
                self.circuit_breaker["failure_count"] = 0
                frappe.logger().info("SEPA Circuit breaker: Moving to half-open state")
                return True
            return False

        elif self.circuit_breaker["state"] == "half_open":
            # Allow limited calls in half-open state
            return self.circuit_breaker["failure_count"] < self.circuit_breaker["half_open_max_calls"]

        return False

    def record_success(self):
        """Record successful operation for circuit breaker"""
        if self.circuit_breaker["state"] == "half_open":
            self.circuit_breaker["state"] = "closed"
            self.circuit_breaker["failure_count"] = 0
            frappe.logger().info("SEPA Circuit breaker: Returning to closed state")

    def record_failure(self, error: Exception):
        """Record failed operation for circuit breaker"""
        self.circuit_breaker["failure_count"] += 1
        self.circuit_breaker["last_failure_time"] = now_datetime()

        if (
            self.circuit_breaker["failure_count"] >= self.circuit_breaker["failure_threshold"]
            and self.circuit_breaker["state"] != "open"
        ):
            self.circuit_breaker["state"] = "open"
            frappe.logger().error(
                f"SEPA Circuit breaker: Opening circuit after {self.circuit_breaker['failure_count']} failures"
            )

    def execute_with_retry(self, operation: Callable, *args, **kwargs) -> Dict[str, Any]:
        """
        Execute operation with retry logic and circuit breaker

        Args:
            operation: Function to execute
            *args, **kwargs: Arguments for the operation

        Returns:
            Dict with success status, result/error, and execution metadata
        """
        operation_name = operation.__name__ if hasattr(operation, "__name__") else str(operation)

        # Check circuit breaker
        if not self.check_circuit_breaker():
            return {
                "success": False,
                "error": "Circuit breaker is open - operation blocked",
                "error_category": "circuit_breaker",
                "operation": operation_name,
                "retries_attempted": 0,
                "circuit_breaker_state": self.circuit_breaker["state"],
            }

        last_error = None

        for attempt in range(self.retry_config["max_retries"] + 1):
            try:
                # Execute the operation
                result = operation(*args, **kwargs)

                # Record success for circuit breaker
                self.record_success()

                return {
                    "success": True,
                    "result": result,
                    "operation": operation_name,
                    "retries_attempted": attempt,
                    "circuit_breaker_state": self.circuit_breaker["state"],
                }

            except Exception as e:
                last_error = e
                error_category = self.categorize_error(e)

                frappe.log_error(
                    f"SEPA operation failed - Attempt {attempt + 1}: {str(e)}",
                    f"SEPA Error Handler - {operation_name}",
                )

                # Check if we should retry
                if not self.should_retry(e, attempt):
                    self.record_failure(e)
                    return {
                        "success": False,
                        "error": str(e),
                        "error_category": error_category,
                        "operation": operation_name,
                        "retries_attempted": attempt,
                        "final_attempt": True,
                        "circuit_breaker_state": self.circuit_breaker["state"],
                    }

                # Calculate delay before retry
                if attempt < self.retry_config["max_retries"]:
                    delay = self.calculate_delay(attempt)
                    frappe.logger().info(f"Retrying {operation_name} in {delay:.2f} seconds...")
                    time.sleep(delay)

        # All retries exhausted
        self.record_failure(last_error)
        return {
            "success": False,
            "error": str(last_error),
            "error_category": self.categorize_error(last_error),
            "operation": operation_name,
            "retries_attempted": self.retry_config["max_retries"],
            "retries_exhausted": True,
            "circuit_breaker_state": self.circuit_breaker["state"],
        }

    def create_retry_batch(self, failed_operations: List[Dict]) -> Dict:
        """
        Create a retry batch for failed operations that can be retried

        Args:
            failed_operations: List of failed operation results

        Returns:
            Dict with retry batch information
        """
        retryable_operations = []

        for operation in failed_operations:
            error_category = operation.get("error_category", "unknown")

            # Only retry temporary errors and some unknown errors
            if error_category in ["temporary", "unknown"]:
                # Don't retry if we've already exhausted retries for this operation
                if not operation.get("retries_exhausted", False):
                    retryable_operations.append(operation)

        if retryable_operations:
            # Create retry batch document for tracking
            retry_batch = frappe.new_doc("SEPA Retry Batch")
            retry_batch.batch_date = today()
            retry_batch.total_operations = len(retryable_operations)
            retry_batch.status = "Pending"
            retry_batch.created_by_error_handler = True

            for op in retryable_operations:
                retry_batch.append(
                    "operations",
                    {
                        "operation_type": op.get("operation", "unknown"),
                        "original_error": op.get("error", ""),
                        "error_category": op.get("error_category", "unknown"),
                        "retry_attempts": op.get("retries_attempted", 0),
                        "reference_document": op.get("reference_document", ""),
                        "status": "Pending",
                    },
                )

            retry_batch.save()

            return {
                "success": True,
                "retry_batch": retry_batch.name,
                "retryable_count": len(retryable_operations),
                "total_failed": len(failed_operations),
            }

        return {
            "success": False,
            "message": "No operations eligible for retry",
            "retryable_count": 0,
            "total_failed": len(failed_operations),
        }

    def get_circuit_breaker_status(self) -> Dict:
        """Get current circuit breaker status"""
        return {
            "state": self.circuit_breaker["state"],
            "failure_count": self.circuit_breaker["failure_count"],
            "last_failure_time": self.circuit_breaker["last_failure_time"],
            "failure_threshold": self.circuit_breaker["failure_threshold"],
            "recovery_timeout": self.circuit_breaker["recovery_timeout"],
        }

    def reset_circuit_breaker(self):
        """Manually reset circuit breaker (admin function)"""
        self.circuit_breaker["state"] = "closed"
        self.circuit_breaker["failure_count"] = 0
        self.circuit_breaker["last_failure_time"] = None
        frappe.logger().info("SEPA Circuit breaker manually reset")


# Global error handler instance
_error_handler = None


def get_sepa_error_handler() -> SEPAErrorHandler:
    """Get the global SEPA error handler instance"""
    global _error_handler
    if _error_handler is None:
        _error_handler = SEPAErrorHandler()
    return _error_handler


# Decorator for automatic retry handling
def sepa_retry(operation_name: str = None):
    """
    Decorator to automatically add retry logic to SEPA operations

    Usage:
        @sepa_retry("mandate_validation")
        def validate_mandate(mandate_name):
            # operation code here
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            handler = get_sepa_error_handler()
            nonlocal operation_name
            if operation_name is None:
                operation_name = func.__name__

            result = handler.execute_with_retry(func, *args, **kwargs)

            if not result["success"]:
                # Log the final failure
                frappe.log_error(
                    f"SEPA operation {operation_name} failed after retries: {result['error']}",
                    f"SEPA Retry Handler - {operation_name} Final Failure",
                )

                # For functions that need to raise exceptions, convert back to exception
                if result.get("error_category") != "circuit_breaker":
                    raise Exception(result["error"])

            return result["result"]

        return wrapper

    return decorator


@frappe.whitelist()
def get_sepa_error_handler_status():
    """API to get error handler status"""
    handler = get_sepa_error_handler()
    return handler.get_circuit_breaker_status()


@frappe.whitelist()
def reset_sepa_circuit_breaker():
    """API to reset SEPA circuit breaker"""
    handler = get_sepa_error_handler()
    handler.reset_circuit_breaker()
    return {"success": True, "message": "Circuit breaker reset successfully"}


@frappe.whitelist()
def create_retry_batch_from_errors(error_data):
    """API to create retry batch from error data"""
    if isinstance(error_data, str):
        error_data = frappe.parse_json(error_data)

    handler = get_sepa_error_handler()
    return handler.create_retry_batch(error_data)
