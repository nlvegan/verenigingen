"""
SEPA Retry Manager with Exponential Backoff

Comprehensive retry system for SEPA operations with intelligent backoff strategies,
circuit breaker patterns, and failure recovery mechanisms.

Implements Week 3 Day 1-2 requirements from the SEPA billing improvements project.
"""

import math
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import add_seconds, get_datetime, now

from verenigingen.utils.error_handling import SEPAError, handle_api_error, log_error
from verenigingen.utils.performance_utils import performance_monitor


class RetryStrategy(Enum):
    """Retry strategy types"""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"
    FIBONACCI = "fibonacci"
    CUSTOM = "custom"


class FailureType(Enum):
    """Types of failures that can be retried"""

    TRANSIENT = "transient"  # Temporary issues (network, DB lock)
    RESOURCE = "resource"  # Resource contention
    VALIDATION = "validation"  # Data validation errors
    SYSTEM = "system"  # System-level errors
    BUSINESS = "business"  # Business rule violations
    PERMANENT = "permanent"  # Non-retryable errors


@dataclass
class RetryConfig:
    """Configuration for retry behavior"""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter_factor: float = 0.1
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    retryable_exceptions: List[type] = field(default_factory=lambda: [Exception])
    non_retryable_exceptions: List[type] = field(default_factory=lambda: [])
    timeout: Optional[float] = None
    circuit_breaker_threshold: int = 5
    circuit_breaker_window: int = 300  # 5 minutes


@dataclass
class RetryAttempt:
    """Information about a retry attempt"""

    attempt: int
    timestamp: datetime
    delay: float
    error: Optional[Exception]
    success: bool
    duration: float
    details: Dict[str, Any]


@dataclass
class RetryResult:
    """Result of retry operation"""

    success: bool
    result: Any
    total_attempts: int
    total_duration: float
    attempts: List[RetryAttempt]
    final_error: Optional[Exception]


class CircuitBreaker:
    """Circuit breaker pattern implementation"""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise SEPAError(_("Circuit breaker is OPEN - too many recent failures"))

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt reset"""
        if not self.last_failure_time:
            return True

        time_since_failure = time.time() - self.last_failure_time
        return time_since_failure >= self.recovery_timeout

    def _on_success(self):
        """Handle successful operation"""
        self.failure_count = 0
        self.state = "CLOSED"

    def _on_failure(self):
        """Handle failed operation"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"


class SEPARetryManager:
    """
    Advanced retry manager for SEPA operations

    Provides sophisticated retry mechanisms with:
    - Multiple backoff strategies
    - Circuit breaker patterns
    - Failure classification
    - Performance monitoring
    - Comprehensive logging
    """

    def __init__(self):
        self.circuit_breakers = {}
        self.failure_stats = {}
        self.default_config = RetryConfig()

    def retry_operation(
        self,
        operation: Callable,
        config: Optional[RetryConfig] = None,
        operation_id: str = None,
        context: Dict[str, Any] = None,
    ) -> RetryResult:
        """
        Execute operation with retry logic

        Args:
            operation: Function to execute
            config: Retry configuration
            operation_id: Unique identifier for operation
            context: Additional context for logging

        Returns:
            RetryResult with operation outcome
        """
        config = config or self.default_config
        operation_id = operation_id or f"operation_{int(time.time())}"
        context = context or {}

        attempts = []
        start_time = time.time()

        # Get or create circuit breaker for this operation type
        circuit_breaker = self._get_circuit_breaker(operation_id, config)

        for attempt_num in range(1, config.max_attempts + 1):
            attempt_start = time.time()

            try:
                # Use circuit breaker if configured
                if config.circuit_breaker_threshold > 0:
                    result = circuit_breaker.call(operation)
                else:
                    result = operation()

                # Success!
                attempt_duration = time.time() - attempt_start
                attempts.append(
                    RetryAttempt(
                        attempt=attempt_num,
                        timestamp=get_datetime(now()),
                        delay=0,
                        error=None,
                        success=True,
                        duration=attempt_duration,
                        details={"context": context},
                    )
                )

                total_duration = time.time() - start_time

                # Log successful retry if there were previous failures
                if attempt_num > 1:
                    frappe.logger().info(
                        f"Operation {operation_id} succeeded on attempt {attempt_num} "
                        f"after {total_duration:.2f}s"
                    )

                return RetryResult(
                    success=True,
                    result=result,
                    total_attempts=attempt_num,
                    total_duration=total_duration,
                    attempts=attempts,
                    final_error=None,
                )

            except Exception as error:
                attempt_duration = time.time() - attempt_start

                # Classify the error
                failure_type = self._classify_failure(error)

                # Check if error is retryable
                if not self._is_retryable_error(error, config, failure_type):
                    attempts.append(
                        RetryAttempt(
                            attempt=attempt_num,
                            timestamp=get_datetime(now()),
                            delay=0,
                            error=error,
                            success=False,
                            duration=attempt_duration,
                            details={
                                "context": context,
                                "failure_type": failure_type.value,
                                "retryable": False,
                            },
                        )
                    )

                    # Non-retryable error
                    frappe.logger().error(f"Non-retryable error in operation {operation_id}: {str(error)}")

                    return RetryResult(
                        success=False,
                        result=None,
                        total_attempts=attempt_num,
                        total_duration=time.time() - start_time,
                        attempts=attempts,
                        final_error=error,
                    )

                # Calculate delay for next attempt
                if attempt_num < config.max_attempts:
                    delay = self._calculate_delay(attempt_num, config, failure_type)

                    attempts.append(
                        RetryAttempt(
                            attempt=attempt_num,
                            timestamp=get_datetime(now()),
                            delay=delay,
                            error=error,
                            success=False,
                            duration=attempt_duration,
                            details={
                                "context": context,
                                "failure_type": failure_type.value,
                                "retryable": True,
                                "next_delay": delay,
                            },
                        )
                    )

                    # Log retry attempt
                    frappe.logger().warning(
                        f"Operation {operation_id} failed on attempt {attempt_num}, "
                        f"retrying in {delay:.2f}s: {str(error)}"
                    )

                    # Wait before retry
                    if delay > 0:
                        time.sleep(delay)
                else:
                    # Final attempt failed
                    attempts.append(
                        RetryAttempt(
                            attempt=attempt_num,
                            timestamp=get_datetime(now()),
                            delay=0,
                            error=error,
                            success=False,
                            duration=attempt_duration,
                            details={
                                "context": context,
                                "failure_type": failure_type.value,
                                "final_attempt": True,
                            },
                        )
                    )

        # All attempts failed
        total_duration = time.time() - start_time

        frappe.logger().error(
            f"Operation {operation_id} failed after {config.max_attempts} attempts "
            f"in {total_duration:.2f}s"
        )

        # Update failure statistics
        self._update_failure_stats(operation_id, attempts)

        return RetryResult(
            success=False,
            result=None,
            total_attempts=config.max_attempts,
            total_duration=total_duration,
            attempts=attempts,
            final_error=attempts[-1].error if attempts else None,
        )

    def _get_circuit_breaker(self, operation_id: str, config: RetryConfig) -> CircuitBreaker:
        """Get or create circuit breaker for operation"""
        if operation_id not in self.circuit_breakers:
            self.circuit_breakers[operation_id] = CircuitBreaker(
                failure_threshold=config.circuit_breaker_threshold,
                recovery_timeout=config.circuit_breaker_window,
            )
        return self.circuit_breakers[operation_id]

    def _classify_failure(self, error: Exception) -> FailureType:
        """Classify failure type for appropriate retry strategy"""
        error_str = str(error).lower()

        # Database-related errors (often transient)
        if any(
            keyword in error_str
            for keyword in ["deadlock", "lock wait", "connection", "timeout", "temporary"]
        ):
            return FailureType.TRANSIENT

        # Resource contention
        if any(keyword in error_str for keyword in ["resource", "busy", "unavailable", "limit exceeded"]):
            return FailureType.RESOURCE

        # Validation errors (usually not retryable)
        if any(
            keyword in error_str for keyword in ["validation", "invalid", "format", "required"]
        ) or isinstance(error, (ValueError, TypeError)):
            return FailureType.VALIDATION

        # Business logic errors (usually not retryable)
        if isinstance(error, SEPAError):
            return FailureType.BUSINESS

        # Permission errors (not retryable)
        if "permission" in error_str or isinstance(error, frappe.PermissionError):
            return FailureType.PERMANENT

        # System errors (may be retryable)
        return FailureType.SYSTEM

    def _is_retryable_error(self, error: Exception, config: RetryConfig, failure_type: FailureType) -> bool:
        """Determine if error should be retried"""
        # Check explicit non-retryable exceptions
        if any(isinstance(error, exc_type) for exc_type in config.non_retryable_exceptions):
            return False

        # Check failure type
        if failure_type in [FailureType.VALIDATION, FailureType.PERMANENT, FailureType.BUSINESS]:
            return False

        # Check explicit retryable exceptions
        if config.retryable_exceptions:
            return any(isinstance(error, exc_type) for exc_type in config.retryable_exceptions)

        # Default: retry transient, resource, and system errors
        return failure_type in [FailureType.TRANSIENT, FailureType.RESOURCE, FailureType.SYSTEM]

    def _calculate_delay(self, attempt: int, config: RetryConfig, failure_type: FailureType) -> float:
        """Calculate delay before next retry attempt"""
        if config.strategy == RetryStrategy.FIXED:
            base_delay = config.base_delay

        elif config.strategy == RetryStrategy.LINEAR:
            base_delay = config.base_delay * attempt

        elif config.strategy == RetryStrategy.EXPONENTIAL:
            base_delay = config.base_delay * (config.exponential_base ** (attempt - 1))

        elif config.strategy == RetryStrategy.FIBONACCI:
            base_delay = config.base_delay * self._fibonacci(attempt)

        else:  # CUSTOM or fallback
            base_delay = config.base_delay * (config.exponential_base ** (attempt - 1))

        # Apply failure type modifiers
        if failure_type == FailureType.TRANSIENT:
            base_delay *= 0.5  # Faster retry for transient issues
        elif failure_type == FailureType.RESOURCE:
            base_delay *= 1.5  # Slower retry for resource contention

        # Cap at maximum delay
        base_delay = min(base_delay, config.max_delay)

        # Add jitter to avoid thundering herd
        if config.jitter_factor > 0:
            jitter = base_delay * config.jitter_factor * random.random()
            base_delay += jitter

        return max(0, base_delay)

    def _fibonacci(self, n: int) -> int:
        """Calculate nth Fibonacci number"""
        if n <= 1:
            return n
        a, b = 0, 1
        for i in range(2, n + 1):
            a, b = b, a + b
        return b

    def _update_failure_stats(self, operation_id: str, attempts: List[RetryAttempt]):
        """Update failure statistics for monitoring"""
        if operation_id not in self.failure_stats:
            self.failure_stats[operation_id] = {
                "total_failures": 0,
                "total_attempts": 0,
                "last_failure": None,
                "failure_types": {},
            }

        stats = self.failure_stats[operation_id]
        stats["total_failures"] += 1
        stats["total_attempts"] += len(attempts)
        stats["last_failure"] = now()

        # Count failure types
        for attempt in attempts:
            if not attempt.success and attempt.details.get("failure_type"):
                failure_type = attempt.details["failure_type"]
                stats["failure_types"][failure_type] = stats["failure_types"].get(failure_type, 0) + 1

    def get_failure_stats(self, operation_id: str = None) -> Dict[str, Any]:
        """Get failure statistics"""
        if operation_id:
            return self.failure_stats.get(operation_id, {})
        return self.failure_stats

    def reset_circuit_breaker(self, operation_id: str) -> bool:
        """Reset circuit breaker for operation"""
        if operation_id in self.circuit_breakers:
            cb = self.circuit_breakers[operation_id]
            cb.failure_count = 0
            cb.state = "CLOSED"
            cb.last_failure_time = None
            return True
        return False


def with_retry(config: Optional[RetryConfig] = None, operation_id: str = None):
    """
    Decorator to add retry functionality to any function

    Args:
        config: Retry configuration
        operation_id: Unique operation identifier

    Usage:
        @with_retry(RetryConfig(max_attempts=5))
        def my_sepa_operation():
            # Implementation
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            retry_manager = SEPARetryManager()

            def operation():
                return func(*args, **kwargs)

            actual_operation_id = operation_id or f"{func.__module__}.{func.__name__}"
            result = retry_manager.retry_operation(
                operation=operation,
                config=config,
                operation_id=actual_operation_id,
                context={
                    "function": func.__name__,
                    "args_count": len(args),
                    "kwargs_keys": list(kwargs.keys()),
                },
            )

            if result.success:
                return result.result
            else:
                # Raise the final error
                raise result.final_error or SEPAError(_("Operation failed after retries"))

        return wrapper

    return decorator


# Specialized retry configurations for SEPA operations


class SEPARetryConfigs:
    """Predefined retry configurations for common SEPA operations"""

    @staticmethod
    def batch_creation() -> RetryConfig:
        """Configuration for batch creation operations"""
        return RetryConfig(
            max_attempts=3,
            base_delay=2.0,
            max_delay=30.0,
            strategy=RetryStrategy.EXPONENTIAL,
            exponential_base=2.0,
            jitter_factor=0.2,
            non_retryable_exceptions=[ValueError, TypeError, frappe.ValidationError],
            circuit_breaker_threshold=5,
            circuit_breaker_window=300,
        )

    @staticmethod
    def xml_generation() -> RetryConfig:
        """Configuration for XML generation operations"""
        return RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=10.0,
            strategy=RetryStrategy.FIXED,
            non_retryable_exceptions=[ValueError, TypeError],
            circuit_breaker_threshold=3,
            circuit_breaker_window=180,
        )

    @staticmethod
    def database_operations() -> RetryConfig:
        """Configuration for database operations"""
        return RetryConfig(
            max_attempts=5,
            base_delay=0.5,
            max_delay=15.0,
            strategy=RetryStrategy.EXPONENTIAL,
            exponential_base=1.5,
            jitter_factor=0.3,
            retryable_exceptions=[Exception],  # Most DB errors are retryable
            non_retryable_exceptions=[frappe.ValidationError, ValueError],
            circuit_breaker_threshold=10,
            circuit_breaker_window=600,
        )

    @staticmethod
    def file_operations() -> RetryConfig:
        """Configuration for file operations"""
        return RetryConfig(
            max_attempts=3,
            base_delay=1.0,
            max_delay=20.0,
            strategy=RetryStrategy.LINEAR,
            jitter_factor=0.1,
            circuit_breaker_threshold=3,
            circuit_breaker_window=120,
        )

    @staticmethod
    def network_operations() -> RetryConfig:
        """Configuration for network operations"""
        return RetryConfig(
            max_attempts=4,
            base_delay=2.0,
            max_delay=60.0,
            strategy=RetryStrategy.EXPONENTIAL,
            exponential_base=2.0,
            jitter_factor=0.25,
            circuit_breaker_threshold=5,
            circuit_breaker_window=300,
        )


# API Functions


@frappe.whitelist()
@handle_api_error
def execute_with_retry(operation_type: str, operation_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    API endpoint to execute SEPA operations with retry logic

    Args:
        operation_type: Type of operation (batch_creation, xml_generation, etc.)
        operation_data: Data for the operation

    Returns:
        Operation result with retry information
    """
    retry_manager = SEPARetryManager()

    # Get appropriate configuration
    config_map = {
        "batch_creation": SEPARetryConfigs.batch_creation(),
        "xml_generation": SEPARetryConfigs.xml_generation(),
        "database": SEPARetryConfigs.database_operations(),
        "file": SEPARetryConfigs.file_operations(),
        "network": SEPARetryConfigs.network_operations(),
    }

    config = config_map.get(operation_type, SEPARetryManager().default_config)

    # This is a placeholder - in real implementation, you'd route to actual operations
    def mock_operation():
        if operation_type == "batch_creation":
            # Import and call actual batch creation
            from verenigingen.utils.sepa_race_condition_manager import SEPABatchRaceConditionManager

            manager = SEPABatchRaceConditionManager()
            return manager.create_batch_with_race_protection(operation_data)
        else:
            # Placeholder for other operations
            return {"success": True, "message": f"Operation {operation_type} completed"}

    result = retry_manager.retry_operation(
        operation=mock_operation,
        config=config,
        operation_id=f"api_{operation_type}",
        context={"operation_type": operation_type, "api_call": True},
    )

    return {
        "success": result.success,
        "result": result.result,
        "retry_info": {
            "total_attempts": result.total_attempts,
            "total_duration": result.total_duration,
            "attempts": [
                {
                    "attempt": a.attempt,
                    "success": a.success,
                    "duration": a.duration,
                    "delay": a.delay,
                    "error": str(a.error) if a.error else None,
                }
                for a in result.attempts
            ],
        },
        "final_error": str(result.final_error) if result.final_error else None,
    }


@frappe.whitelist()
@handle_api_error
def get_retry_statistics(operation_id: str = None) -> Dict[str, Any]:
    """
    Get retry statistics for monitoring

    Args:
        operation_id: Specific operation ID or None for all

    Returns:
        Retry statistics
    """
    retry_manager = SEPARetryManager()
    return {
        "failure_stats": retry_manager.get_failure_stats(operation_id),
        "circuit_breaker_states": {
            op_id: {"state": cb.state, "failure_count": cb.failure_count}
            for op_id, cb in retry_manager.circuit_breakers.items()
        },
    }


@frappe.whitelist()
@handle_api_error
def reset_retry_circuit_breaker(operation_id: str) -> Dict[str, Any]:
    """
    Reset circuit breaker for operation (admin only)

    Args:
        operation_id: Operation to reset

    Returns:
        Reset result
    """
    if not frappe.has_permission("System Manager"):
        raise SEPAError(_("Only system managers can reset circuit breakers"))

    retry_manager = SEPARetryManager()
    success = retry_manager.reset_circuit_breaker(operation_id)

    return {
        "success": success,
        "message": f"Circuit breaker reset for {operation_id}" if success else "Operation not found",
    }
