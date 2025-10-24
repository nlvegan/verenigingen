"""
Retry Utilities for Verenigingen

Provides exponential backoff and retry logic for handling transient failures
in bulk operations and database operations.

Features:
- Exponential backoff with jitter to prevent thundering herd
- Error classification (transient vs permanent)
- Configurable retry strategies
- Context manager for automatic retry

Author: Verenigingen Development Team
"""

import random
import time
from enum import Enum
from functools import wraps
from typing import Callable, Optional, Tuple, Type

import frappe
from frappe import _


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
        retry_on: Tuple of exception types to retry (default: all transient errors)
        skip_on: Tuple of exception types to never retry (default: permanent errors)
        on_retry: Optional callback function(exception, attempt, delay) called before each retry

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
