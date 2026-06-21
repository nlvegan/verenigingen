"""
Retry Utilities for Verenigingen

Provides exponential backoff and retry logic for handling transient failures
in bulk operations and database operations.

Features:
- Exponential backoff with jitter to prevent thundering herd
- Error classification (transient vs permanent)
- Configurable retry strategies
- Context manager for automatic retry
- Deadlock-specific retry helpers for database operations

Author: Verenigingen Development Team
"""

import random
import time
from enum import Enum
from functools import wraps
from typing import Callable, Optional, Tuple, Type

import frappe


class ErrorCategory(Enum):
    """Classification of error types for retry strategies"""

    TRANSIENT = "transient"  # Temporary errors, safe to retry
    PERMANENT = "permanent"  # Permanent errors, fail fast
    UNKNOWN = "unknown"  # Unknown errors, cautious retry


def classify_error(exception: Exception) -> ErrorCategory:
    """
    Classify an error as transient, permanent, or unknown.

    Args:
        exception: The exception to classify

    Returns:
        ErrorCategory classification
    """
    error_str = str(exception).lower()

    # Transient errors - safe to retry
    transient_indicators = [
        "broken pipe",
        "connection reset",
        "connection refused",
        "timeout",
        "timestamp mismatch",
        "lock wait timeout",
        "deadlock",
        "too many connections",
    ]

    for indicator in transient_indicators:
        if indicator in error_str:
            return ErrorCategory.TRANSIENT

    # Permanent errors - fail fast
    permanent_indicators = [
        "permission denied",
        "does not exist",
        "validation error",
        "duplicate entry",
        "foreign key constraint",
        "not found",
    ]

    for indicator in permanent_indicators:
        if indicator in error_str:
            return ErrorCategory.PERMANENT

    # Unknown - cautious retry
    return ErrorCategory.UNKNOWN


def exponential_backoff_with_jitter(
    attempt: int, base_delay: float = 0.1, max_delay: float = 10.0, jitter_factor: float = 0.5
) -> float:
    """
    Calculate exponential backoff delay with jitter.

    Formula: delay = min(base_delay * (2 ** attempt), max_delay) + random_jitter

    Args:
        attempt: Current retry attempt (0-indexed)
        base_delay: Base delay in seconds (default: 0.1)
        max_delay: Maximum delay in seconds (default: 10.0)
        jitter_factor: Maximum jitter as fraction of delay (default: 0.5 = ±50%)

    Returns:
        Delay in seconds before next retry
    """
    # Calculate exponential delay
    exponential_delay = base_delay * (2**attempt)

    # Cap at maximum delay
    delay = min(exponential_delay, max_delay)

    # Add randomized jitter to prevent thundering herd
    jitter = random.uniform(-jitter_factor * delay, jitter_factor * delay)

    return max(0, delay + jitter)


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 10.0,
    retry_on: Optional[Tuple[Type[Exception], ...]] = None,
    skip_on: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
):
    """
    Decorator for automatic retry with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 3)
        base_delay: Base delay in seconds (default: 0.1)
        max_delay: Maximum delay in seconds (default: 10.0)
        retry_on: Tuple of exception types to retry. If given, exceptions not in
            this tuple are still retried unless they classify as PERMANENT (see
            classify_error). If None, every exception is retried.
        skip_on: Tuple of exception types to never retry (re-raised immediately).
            If None, no exception is skipped on type alone.
        on_retry: Optional callback function(exception, attempt, delay) called before each retry

    Default behavior (retry_on=None and skip_on=None): retries ALL exceptions up
    to max_retries, then re-raises the last one. Permanent errors are only skipped
    when retry_on is provided (via classify_error); they are NOT skipped by default.

    Example:
        @retry_with_backoff(max_retries=5, base_delay=0.5)
        def unreliable_operation():
            # ... operation that might fail transiently
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    # Check if we should skip retry for this exception
                    if skip_on and isinstance(e, skip_on):
                        raise

                    # Check if this error type is retryable
                    if retry_on and not isinstance(e, retry_on):
                        # Not in retry list - check error classification
                        category = classify_error(e)
                        if category == ErrorCategory.PERMANENT:
                            raise

                    # Last attempt - don't retry
                    if attempt >= max_retries:
                        raise

                    # Calculate backoff delay
                    delay = exponential_backoff_with_jitter(attempt, base_delay, max_delay)

                    # Call retry callback if provided
                    if on_retry:
                        on_retry(e, attempt, delay)
                    else:
                        frappe.logger().warning(
                            f"Retry {attempt + 1}/{max_retries} for {func.__name__} "
                            f"after error: {str(e)[:100]}. Waiting {delay:.2f}s"
                        )

                    # Wait before retry
                    time.sleep(delay)

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


class RetryContext:
    """
    Context manager for retry logic with exponential backoff.

    Example:
        retry_ctx = RetryContext(max_retries=5, base_delay=0.5)

        for attempt in retry_ctx:
            try:
                # Your operation here
                result = unreliable_operation()
                break  # Success - exit retry loop
            except Exception as e:
                if retry_ctx.should_retry(e):
                    continue  # Retry
                else:
                    raise  # Permanent error - fail fast
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 0.1,
        max_delay: float = 10.0,
        jitter_factor: float = 0.5,
    ):
        """
        Initialize retry context.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Base delay in seconds
            max_delay: Maximum delay in seconds
            jitter_factor: Maximum jitter as fraction of delay
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter_factor = jitter_factor
        self.current_attempt = 0

    def __iter__(self):
        """Return iterator for retry loop"""
        return self

    def __next__(self):
        """Get next retry attempt"""
        if self.current_attempt > self.max_retries:
            raise StopIteration

        attempt = self.current_attempt
        self.current_attempt += 1

        # Wait before retry (except for first attempt)
        if attempt > 0:
            delay = exponential_backoff_with_jitter(
                attempt - 1, self.base_delay, self.max_delay, self.jitter_factor
            )
            frappe.logger().info(f"Retry attempt {attempt}/{self.max_retries}, waiting {delay:.2f}s")
            time.sleep(delay)

        return attempt

    def should_retry(self, exception: Exception) -> bool:
        """
        Check if the given exception should trigger a retry.

        Args:
            exception: The exception that occurred

        Returns:
            True if should retry, False if should fail fast
        """
        if self.current_attempt > self.max_retries:
            return False

        category = classify_error(exception)

        if category == ErrorCategory.PERMANENT:
            frappe.logger().info(f"Permanent error detected, not retrying: {str(exception)[:100]}")
            return False

        if category == ErrorCategory.UNKNOWN:
            frappe.logger().warning(f"Unknown error type, retrying cautiously: {str(exception)[:100]}")
            return True

        # Transient error - safe to retry
        return True


# Convenience function for common retry patterns
def retry_operation(
    operation: Callable,
    operation_name: str = "operation",
    max_retries: int = 3,
    base_delay: float = 0.1,
    log_errors: bool = True,
) -> any:
    """
    Execute an operation with automatic retry and exponential backoff.

    Args:
        operation: Callable operation to retry
        operation_name: Human-readable operation name for logging
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds
        log_errors: Whether to log errors to Frappe error log

    Returns:
        Result of successful operation

    Raises:
        Last exception if all retries exhausted
    """
    retry_ctx = RetryContext(max_retries=max_retries, base_delay=base_delay)

    last_exception = None

    for attempt in retry_ctx:
        try:
            result = operation()
            if attempt > 0:
                frappe.logger().info(f"{operation_name} succeeded on retry attempt {attempt}/{max_retries}")
            return result

        except Exception as e:
            last_exception = e

            if not retry_ctx.should_retry(e):
                if log_errors:
                    frappe.log_error(f"{operation_name} failed permanently: {str(e)}")
                raise

            frappe.logger().warning(
                f"{operation_name} failed on attempt {attempt + 1}/{max_retries + 1}: {str(e)[:100]}"
            )

    # All retries exhausted
    if log_errors and last_exception:
        frappe.log_error(f"{operation_name} failed after {max_retries + 1} attempts: {str(last_exception)}")

    if last_exception:
        raise last_exception


# =============================================================================
# Deadlock-Specific Retry Utilities
# =============================================================================
# These utilities provide specialized handling for MySQL deadlock errors
# (error code 1213) which are common in concurrent database operations.
#
# MySQL deadlocks are transient by nature - retrying the transaction will
# typically succeed. These helpers provide consistent deadlock handling
# across the codebase.
# =============================================================================

# Constants for deadlock retry configuration
DEADLOCK_MAX_RETRIES = 3
DEADLOCK_BASE_DELAY = 0.1  # 100ms base delay
DEADLOCK_MAX_DELAY = 2.0  # Cap at 2 seconds


def is_deadlock_error(exception: Exception) -> bool:
    """
    Check if an exception is a MySQL deadlock error.

    Detects deadlocks via:
    1. frappe.QueryDeadlockError (explicit type)
    2. MySQL error code 1213 in error message
    3. "Deadlock" keyword in error message

    Args:
        exception: The exception to check

    Returns:
        bool: True if this is a deadlock error

    Example:
        try:
            frappe.db.sql("UPDATE ...")
        except Exception as e:
            if is_deadlock_error(e):
                # Safe to retry
                pass
    """
    # Check for explicit Frappe deadlock exception type
    if hasattr(frappe, "QueryDeadlockError"):
        if isinstance(exception, frappe.QueryDeadlockError):
            return True

    # Also check frappe.exceptions path
    if hasattr(frappe, "exceptions") and hasattr(frappe.exceptions, "QueryDeadlockError"):
        if isinstance(exception, frappe.exceptions.QueryDeadlockError):
            return True

    # Fall back to string matching for MySQL error code 1213
    error_str = str(exception).lower()
    return "1213" in error_str or "deadlock" in error_str


def with_deadlock_retry(
    max_retries: int = DEADLOCK_MAX_RETRIES,
    base_delay: float = DEADLOCK_BASE_DELAY,
    max_delay: float = DEADLOCK_MAX_DELAY,
    operation_name: Optional[str] = None,
):
    """
    Decorator for automatic retry on MySQL deadlock errors.

    Pre-configured for deadlock handling with sensible defaults:
    - 3 retries
    - 100ms base delay with exponential backoff
    - Jitter to prevent thundering herd

    Args:
        max_retries: Maximum retry attempts (default: 3)
        base_delay: Base delay in seconds (default: 0.1)
        max_delay: Maximum delay cap (default: 2.0)
        operation_name: Optional name for logging (defaults to function name)

    Example:
        @with_deadlock_retry()
        def create_invoice(member_name: str):
            invoice = frappe.new_doc("Sales Invoice")
            # ... setup invoice ...
            invoice.insert()
            invoice.submit()
            return invoice.name

        @with_deadlock_retry(max_retries=5, operation_name="batch_update")
        def update_many_records():
            # ... bulk operation ...
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            func_name = operation_name or func.__name__
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    # Only retry on deadlock errors
                    if not is_deadlock_error(e):
                        raise

                    # Last attempt - don't retry
                    if attempt >= max_retries:
                        frappe.logger().error(
                            f"[Deadlock] {func_name} failed after {max_retries + 1} attempts"
                        )
                        raise

                    # Calculate backoff delay with jitter
                    delay = exponential_backoff_with_jitter(attempt, base_delay, max_delay, jitter_factor=0.3)

                    frappe.logger().warning(
                        f"[Deadlock] {func_name} hit deadlock on attempt {attempt + 1}/{max_retries + 1}, "
                        f"retrying in {delay:.2f}s"
                    )

                    time.sleep(delay)

            # Should never reach here
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def execute_with_deadlock_retry(
    operation: Callable,
    operation_name: str = "database operation",
    max_retries: int = DEADLOCK_MAX_RETRIES,
    base_delay: float = DEADLOCK_BASE_DELAY,
    max_delay: float = DEADLOCK_MAX_DELAY,
    log_errors: bool = True,
) -> any:
    """
    Execute an operation with deadlock-specific retry logic.

    Use this for inline operations where a decorator isn't practical.

    Args:
        operation: Callable to execute (no arguments)
        operation_name: Human-readable name for logging
        max_retries: Maximum retry attempts (default: 3)
        base_delay: Base delay in seconds (default: 0.1)
        max_delay: Maximum delay cap (default: 2.0)
        log_errors: Whether to log to Frappe error log on final failure

    Returns:
        Result of successful operation

    Raises:
        Exception: Last exception if all retries exhausted, or non-deadlock error

    Example:
        # Inline usage for operations that can't use decorator
        def create_and_submit():
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = customer
            invoice.append("items", {...})
            invoice.insert()
            invoice.submit()
            return invoice.name

        invoice_name = execute_with_deadlock_retry(
            create_and_submit,
            operation_name=f"create invoice for {member_name}"
        )
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            result = operation()
            if attempt > 0:
                frappe.logger().info(
                    f"[Deadlock] {operation_name} succeeded on retry {attempt}/{max_retries}"
                )
            return result

        except Exception as e:
            last_exception = e

            # Only retry on deadlock errors
            if not is_deadlock_error(e):
                if log_errors:
                    frappe.log_error(
                        f"{operation_name} failed with non-deadlock error: {str(e)}",
                        "Operation Error",
                    )
                raise

            # Last attempt - don't retry
            if attempt >= max_retries:
                if log_errors:
                    frappe.log_error(
                        f"{operation_name} failed after {max_retries + 1} deadlock retries",
                        "Deadlock Retry Exhausted",
                    )
                raise

            # Calculate backoff delay with jitter
            delay = exponential_backoff_with_jitter(attempt, base_delay, max_delay, jitter_factor=0.3)

            frappe.logger().warning(
                f"[Deadlock] {operation_name} hit deadlock on attempt {attempt + 1}/{max_retries + 1}, "
                f"retrying in {delay:.2f}s"
            )

            time.sleep(delay)

    # Should never reach here
    if last_exception:
        raise last_exception


# =============================================================================
# Files with inline deadlock retry logic - refactoring assessment
# =============================================================================
#
# REFACTORED:
# - verenigingen/utils/optimized_queries.py - Now uses execute_with_deadlock_retry()
#
# NOT REFACTORED (specialized behavior justifies inline logic):
# - bank_transaction_creator.py:728 - Shared retry loop handles both deadlock
#   AND duplicate entry errors (race condition recovery). Interleaved structure
#   not cleanly extractable.
# - account_creation_manager.py:584,634 - Does frappe.db.rollback() and recreates
#   fresh document before each retry. Specialized for User creation conflicts.
# - invoice_generator.py:727 - Returns OperationResult.fail() on exhaustion
#   instead of raising. Custom error handling for return type.
#
# =============================================================================
