"""
SEPA Error Handler with Retry Mechanisms and Circuit Breaker Pattern
Provides granular error handling for SEPA batch processing operations
"""

import random
import time
from typing import Any, Callable, Dict, List

import frappe
from frappe.utils import now_datetime, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.select_options import coerce_select_option
from verenigingen.verenigingen_payments.utils.shared.backoff import calculate_backoff_delay


def normalize_operation_type(operation: str) -> str:
    """
    Map a free-form operation name onto a SEPA Retry Operation.operation_type option.

    The operation name reaching create_retry_batch() is either a Python function
    name (execute_with_retry uses ``operation.__name__``) or whatever an API caller
    put in the "operation" key, so it is almost never one of the Select's options.
    Anything unrecognised becomes "Other", which the Select carries for this purpose.
    """
    # Function names for the operations the Select does have a value for.
    known = {
        "validate_mandate": "Mandate Validation",
        "create_invoice": "Invoice Creation",
        "process_batch": "Batch Processing",
        "determine_sequence_type": "Sequence Type Determination",
        "process_payment": "Payment Processing",
        "send_notification": "Notification Sending",
    }
    return coerce_select_option(
        "SEPA Retry Operation", "operation_type", known.get(operation, operation), "Other"
    )


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
        """Categorize error for appropriate handling strategy.

        Iterates ``self.error_categories`` in insertion order and returns the
        first category whose keyword list contains a match against the lower-cased
        error message.  Falls back to ``"unknown"`` when no keyword matches.

        This is a keyword-only lookup — exception types are not inspected.
        """
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
        """Calculate delay before retry using exponential backoff with jitter.

        Delegates to the shared ``calculate_backoff_delay`` helper. This module's
        ``attempt`` is 0-based (attempt 0 -> base_delay) while the helper is
        1-based, so we pass ``attempt + 1``. Jitter is 10% (matching the legacy
        ``delay * 0.1 * random.random()``), applied after the max_delay cap.
        """
        return calculate_backoff_delay(
            attempt + 1,
            base_delay=self.retry_config["base_delay"],
            max_delay=self.retry_config["max_delay"],
            strategy="exponential",
            exponential_base=self.retry_config["backoff_multiplier"],
            jitter_factor=0.1,
            rng=random.random,
        )

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

                # Check if we should retry.
                #
                # should_retry() returns False for two distinct reasons:
                #   (a) the error is genuinely non-retryable (validation/data/
                #       authorization) -> this is a final, non-retried attempt.
                #   (b) the error is retryable but we have reached max_retries
                #       -> the retry sequence is exhausted.
                # These two cases need different terminal results, so we only
                # return the `final_attempt` result for case (a). For case (b)
                # we fall through to the post-loop `retries_exhausted` block.
                if not self.should_retry(e, attempt):
                    retries_remaining = attempt < self.retry_config["max_retries"]
                    error_is_retryable = self.categorize_error(e) in ["temporary", "unknown"]
                    if retries_remaining or not error_is_retryable:
                        # Case (a): non-retryable error (or stopped early) -> final attempt.
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
                    # Case (b): retryable error but max_retries reached -> fall
                    # through to the post-loop retries_exhausted block.
                    break

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
                operation = op.get("operation", "")
                operation_type = normalize_operation_type(operation)
                retry_batch.append(
                    "operations",
                    {
                        "operation_type": operation_type,
                        # Keep the caller's own name for the operation; it is the only
                        # way to tell two "Other" rows apart when reviewing the batch.
                        "retry_notes": operation if operation_type == "Other" else None,
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

                # Convert any failure back to an exception so callers don't
                # silently receive a missing/None result. The circuit-open case
                # is surfaced as a clear exception too (the early-return dict has
                # no "result" key, so blindly indexing it would KeyError).
                raise Exception(result["error"])

            return result["result"]

        return wrapper

    return decorator


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_sepa_error_handler_status():
    """API to get error handler status"""
    handler = get_sepa_error_handler()
    return handler.get_circuit_breaker_status()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def reset_sepa_circuit_breaker():
    """API to reset SEPA circuit breaker"""
    handler = get_sepa_error_handler()
    handler.reset_circuit_breaker()
    return {"success": True, "message": "Circuit breaker reset successfully"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_retry_batch_from_errors(error_data):
    """API to create retry batch from error data"""
    if isinstance(error_data, str):
        error_data = frappe.parse_json(error_data)

    handler = get_sepa_error_handler()
    return handler.create_retry_batch(error_data)
