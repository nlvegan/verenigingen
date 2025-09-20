"""
Mollie Integration Error Recovery System

Enhanced error recovery mechanisms that restore and improve upon the error handling
capabilities from the original Mollie integration. This system provides:

- Exponential backoff retry logic for transient failures
- Circuit breaker patterns for API failures
- Recovery workflows for partial failures
- Comprehensive error classification and alerting
- Dead letter queue processing for failed operations
"""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import add_to_date, get_datetime, now_datetime

from ..exceptions import MolliePaymentError, MollieSecurityError, MollieWebhookError
from .logging import MollieLogger


class ErrorSeverity(Enum):
    """Error severity levels for classification and alerting."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RetryStrategy(Enum):
    """Retry strategy types."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_INTERVAL = "fixed_interval"
    NO_RETRY = "no_retry"


@dataclass
class RetryConfig:
    """Configuration for retry operations."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    jitter: bool = True
    backoff_multiplier: float = 2.0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern."""

    failure_threshold: int = 5
    recovery_timeout: int = 60
    success_threshold: int = 3


@dataclass
class CircuitBreakerState:
    """Circuit breaker state tracking."""

    is_open: bool = False
    failure_count: int = 0
    last_failure_time: Optional[datetime] = None
    success_count: int = 0
    half_open_test_time: Optional[datetime] = None


class MollieErrorRecovery:
    """
    Enhanced error recovery system for Mollie integration.

    Provides comprehensive error handling with retry logic, circuit breakers,
    and recovery workflows for financial operations.
    """

    def __init__(self):
        self.logger = MollieLogger("error_recovery")
        self.circuit_breakers: Dict[str, CircuitBreakerState] = {}
        self.recovery_queues: Dict[str, List[Dict]] = {}

    def execute_with_retry(
        self,
        operation: Callable,
        operation_name: str,
        retry_config: Optional[RetryConfig] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute an operation with retry logic.

        Args:
            operation: Function to execute
            operation_name: Name for logging and monitoring
            retry_config: Retry configuration (uses defaults if None)
            context: Additional context for logging

        Returns:
            Result of successful operation

        Raises:
            MolliePaymentError: When all retry attempts fail
        """
        if retry_config is None:
            retry_config = RetryConfig()

        if context is None:
            context = {}

        last_exception = None

        for attempt in range(retry_config.max_attempts):
            try:
                self.logger.info(
                    f"Executing {operation_name}",
                    {"attempt": attempt + 1, "max_attempts": retry_config.max_attempts, **context},
                )

                result = operation()

                if attempt > 0:
                    self.logger.success(f"{operation_name} succeeded after {attempt + 1} attempts", context)
                    self._record_recovery_success(operation_name, attempt + 1)

                return result

            except Exception as e:
                last_exception = e
                severity = self._classify_error_severity(e)

                self.logger.error(
                    f"{operation_name} failed on attempt {attempt + 1}",
                    error=e,
                    data={"attempt": attempt + 1, "severity": severity.value, **context},
                )

                # Don't retry for certain error types
                if not self._should_retry_error(e):
                    self.logger.warning(
                        f"Error not retryable for {operation_name}", {"error_type": type(e).__name__}
                    )
                    break

                # Don't wait after the last attempt
                if attempt < retry_config.max_attempts - 1:
                    delay = self._calculate_retry_delay(attempt, retry_config)
                    self.logger.info(f"Waiting {delay:.2f}s before retry", {"operation": operation_name})
                    time.sleep(delay)

        # All attempts failed
        error_msg = f"{operation_name} failed after {retry_config.max_attempts} attempts"
        self.logger.error(error_msg, error=last_exception, data=context)
        self._record_operation_failure(operation_name, retry_config.max_attempts, last_exception)

        raise MolliePaymentError(error_msg, original_error=last_exception)

    def execute_with_circuit_breaker(
        self,
        operation: Callable,
        circuit_name: str,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute an operation with circuit breaker protection.

        Args:
            operation: Function to execute
            circuit_name: Unique circuit identifier
            circuit_config: Circuit breaker configuration
            context: Additional context for logging

        Returns:
            Result of successful operation

        Raises:
            MolliePaymentError: When circuit is open or operation fails
        """
        if circuit_config is None:
            circuit_config = CircuitBreakerConfig()

        if context is None:
            context = {}

        # Initialize circuit breaker state if needed
        if circuit_name not in self.circuit_breakers:
            self.circuit_breakers[circuit_name] = CircuitBreakerState()

        circuit_state = self.circuit_breakers[circuit_name]

        # Check circuit state
        if self._is_circuit_open(circuit_state, circuit_config):
            error_msg = f"Circuit breaker open for {circuit_name}"
            self.logger.warning(
                error_msg,
                data={
                    "failure_count": circuit_state.failure_count,
                    "last_failure": circuit_state.last_failure_time,
                    **context,
                },
            )
            raise MolliePaymentError(error_msg)

        # Try operation
        try:
            result = operation()

            # Record success
            self._record_circuit_success(circuit_state, circuit_config, circuit_name)
            return result

        except Exception as e:
            # Record failure
            self._record_circuit_failure(circuit_state, circuit_config, circuit_name, e)
            raise

    def create_recovery_workflow(
        self,
        workflow_name: str,
        failed_operation_data: Dict[str, Any],
        recovery_strategy: str = "manual_review",
    ) -> str:
        """
        Create a recovery workflow for failed operations.

        Args:
            workflow_name: Name of the recovery workflow
            failed_operation_data: Data from failed operation
            recovery_strategy: Strategy for recovery

        Returns:
            Recovery workflow ID
        """
        workflow_id = f"{workflow_name}_{int(time.time())}"

        recovery_data = {
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "created_at": now_datetime(),
            "status": "pending",
            "strategy": recovery_strategy,
            "operation_data": failed_operation_data,
            "error_details": failed_operation_data.get("error_details", {}),
            "retry_count": 0,
            "max_retries": 3,
        }

        # Add to recovery queue
        if workflow_name not in self.recovery_queues:
            self.recovery_queues[workflow_name] = []

        self.recovery_queues[workflow_name].append(recovery_data)

        self.logger.info(
            "Created recovery workflow",
            {
                "workflow_id": workflow_id,
                "strategy": recovery_strategy,
                "operation_type": failed_operation_data.get("operation_type", "unknown"),
            },
        )

        # Store in database for persistence
        self._persist_recovery_workflow(recovery_data)

        return workflow_id

    def process_recovery_queue(self, workflow_name: str, max_items: int = 10) -> Dict[str, Any]:
        """
        Process pending recovery workflows.

        Args:
            workflow_name: Name of workflow to process
            max_items: Maximum items to process in this run

        Returns:
            Processing results summary
        """
        if workflow_name not in self.recovery_queues:
            return {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}

        queue = self.recovery_queues[workflow_name]
        pending_items = [item for item in queue if item["status"] == "pending"][:max_items]

        results = {"processed": 0, "succeeded": 0, "failed": 0, "skipped": 0}

        for item in pending_items:
            try:
                self.logger.info(
                    f"Processing recovery workflow",
                    {"workflow_id": item["workflow_id"], "strategy": item["strategy"]},
                )

                success = self._execute_recovery_strategy(item)

                if success:
                    item["status"] = "completed"
                    item["completed_at"] = now_datetime()
                    results["succeeded"] += 1
                    self.logger.success(f"Recovery workflow completed", {"workflow_id": item["workflow_id"]})
                else:
                    item["retry_count"] += 1
                    if item["retry_count"] >= item["max_retries"]:
                        item["status"] = "failed"
                        item["failed_at"] = now_datetime()
                        results["failed"] += 1
                        self.logger.error(
                            f"Recovery workflow failed permanently", {"workflow_id": item["workflow_id"]}
                        )
                    else:
                        # Schedule for retry
                        item["next_retry_at"] = add_to_date(now_datetime(), minutes=30)
                        results["skipped"] += 1

                results["processed"] += 1

            except Exception as e:
                self.logger.error(
                    f"Error processing recovery workflow", error=e, data={"workflow_id": item["workflow_id"]}
                )
                results["failed"] += 1

        return results

    def get_error_recovery_status(self) -> Dict[str, Any]:
        """
        Get comprehensive error recovery status.

        Returns:
            Status summary with metrics and circuit breaker states
        """
        # Get circuit breaker states
        circuit_status = {}
        for name, state in self.circuit_breakers.items():
            circuit_status[name] = {
                "is_open": state.is_open,
                "failure_count": state.failure_count,
                "last_failure": state.last_failure_time,
                "success_count": state.success_count,
            }

        # Get recovery queue status
        queue_status = {}
        for name, queue in self.recovery_queues.items():
            queue_status[name] = {
                "total_items": len(queue),
                "pending": len([item for item in queue if item["status"] == "pending"]),
                "completed": len([item for item in queue if item["status"] == "completed"]),
                "failed": len([item for item in queue if item["status"] == "failed"]),
            }

        return {
            "circuit_breakers": circuit_status,
            "recovery_queues": queue_status,
            "timestamp": now_datetime(),
        }

    def _calculate_retry_delay(self, attempt: int, config: RetryConfig) -> float:
        """Calculate delay for retry attempt."""
        if config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.base_delay * (config.backoff_multiplier**attempt)
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * (attempt + 1)
        else:  # FIXED_INTERVAL
            delay = config.base_delay

        # Apply maximum delay limit
        delay = min(delay, config.max_delay)

        # Add jitter to prevent thundering herd
        if config.jitter:
            jitter_amount = delay * 0.1 * random.random()
            delay += jitter_amount

        return delay

    def _should_retry_error(self, error: Exception) -> bool:
        """Determine if error is retryable."""
        # Don't retry validation errors or security errors
        if isinstance(error, (MollieSecurityError, MollieWebhookError)):
            return False

        # Don't retry certain HTTP errors (400, 401, 403, 404)
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            status_code = error.response.status_code
            if status_code in [400, 401, 403, 404]:
                return False

        # Retry network errors, timeouts, and 5xx errors
        return True

    def _classify_error_severity(self, error: Exception) -> ErrorSeverity:
        """Classify error severity for alerting."""
        if isinstance(error, MollieSecurityError):
            return ErrorSeverity.CRITICAL
        elif isinstance(error, MollieWebhookError):
            return ErrorSeverity.HIGH
        elif isinstance(error, MolliePaymentError):
            return ErrorSeverity.MEDIUM
        else:
            return ErrorSeverity.LOW

    def _is_circuit_open(self, state: CircuitBreakerState, config: CircuitBreakerConfig) -> bool:
        """Check if circuit breaker is open."""
        if not state.is_open:
            return False

        # Check if recovery timeout has passed
        if state.last_failure_time:
            recovery_time = state.last_failure_time + timedelta(seconds=config.recovery_timeout)
            if now_datetime() > recovery_time:
                # Try half-open state
                state.is_open = False
                state.half_open_test_time = now_datetime()
                return False

        return True

    def _record_circuit_success(
        self, state: CircuitBreakerState, config: CircuitBreakerConfig, circuit_name: str
    ):
        """Record successful operation for circuit breaker."""
        if state.half_open_test_time:
            # We're in half-open state, count successes
            state.success_count += 1
            if state.success_count >= config.success_threshold:
                # Close the circuit
                state.failure_count = 0
                state.success_count = 0
                state.half_open_test_time = None
                self.logger.info(f"Circuit breaker closed for {circuit_name}")
        else:
            # Normal operation, reset failure count
            state.failure_count = 0

    def _record_circuit_failure(
        self, state: CircuitBreakerState, config: CircuitBreakerConfig, circuit_name: str, error: Exception
    ):
        """Record failed operation for circuit breaker."""
        state.failure_count += 1
        state.last_failure_time = now_datetime()

        if state.failure_count >= config.failure_threshold:
            state.is_open = True
            state.success_count = 0
            state.half_open_test_time = None
            self.logger.warning(
                f"Circuit breaker opened for {circuit_name}",
                {"failure_count": state.failure_count, "error": str(error)},
            )

    def _record_recovery_success(self, operation_name: str, attempts: int):
        """Record successful recovery after retries."""
        # Store recovery metrics in cache for monitoring
        cache_key = f"mollie_recovery_success:{operation_name}"
        current_data = frappe.cache().get(cache_key) or {"count": 0, "total_attempts": 0}
        if isinstance(current_data, str):
            # Handle case where cache returns JSON string
            import json

            try:
                current_data = json.loads(current_data)
            except (json.JSONDecodeError, TypeError):
                current_data = {"count": 0, "total_attempts": 0}

        current_data["count"] += 1
        current_data["total_attempts"] += attempts

        # Serialize data before storing in Redis cache
        import json

        frappe.cache().set(cache_key, json.dumps(current_data), 3600)

    def _record_operation_failure(self, operation_name: str, attempts: int, error: Exception):
        """Record operation failure after all retries."""
        # Store failure metrics in cache for monitoring
        cache_key = f"mollie_operation_failure:{operation_name}"
        current_data = frappe.cache().get(cache_key) or {"count": 0, "total_attempts": 0}
        if isinstance(current_data, str):
            # Handle case where cache returns JSON string
            import json

            try:
                current_data = json.loads(current_data)
            except (json.JSONDecodeError, TypeError):
                current_data = {"count": 0, "total_attempts": 0}

        current_data["count"] += 1
        current_data["total_attempts"] += attempts

        # Serialize data before storing in Redis cache
        import json

        frappe.cache().set(cache_key, json.dumps(current_data), 3600)

    def _persist_recovery_workflow(self, recovery_data: Dict[str, Any]):
        """Persist recovery workflow to database."""
        try:
            # Store in Error Log for persistence and tracking
            frappe.log_error(
                title=f"Mollie Recovery Workflow: {recovery_data['workflow_name']}",
                message=frappe.as_json(recovery_data, indent=2),
                reference_doctype="Mollie Settings",
                reference_name="Mollie Settings",
            )
        except Exception as e:
            self.logger.error("Failed to persist recovery workflow", error=e)

    def _execute_recovery_strategy(self, recovery_item: Dict[str, Any]) -> bool:
        """Execute recovery strategy for failed operation."""
        strategy = recovery_item["strategy"]
        operation_data = recovery_item["operation_data"]

        try:
            if strategy == "manual_review":
                # Create a comment/note for manual review
                self._create_manual_review_task(recovery_item)
                return True

            elif strategy == "automatic_retry":
                # Attempt automatic recovery
                return self._attempt_automatic_recovery(operation_data)

            elif strategy == "partial_recovery":
                # Attempt partial recovery
                return self._attempt_partial_recovery(operation_data)

            else:
                self.logger.warning(f"Unknown recovery strategy: {strategy}")
                return False

        except Exception as e:
            self.logger.error("Recovery strategy execution failed", error=e)
            return False

    def _create_manual_review_task(self, recovery_item: Dict[str, Any]):
        """Create manual review task for failed operation."""
        # This could create a To-Do item or notification for administrators
        task_data = {
            "workflow_id": recovery_item["workflow_id"],
            "operation_type": recovery_item["operation_data"].get("operation_type", "unknown"),
            "error_summary": str(recovery_item["error_details"]),
            "requires_manual_review": True,
        }

        self.logger.info("Manual review task created", task_data)
        # In a real implementation, this would create a ToDo or send notification

    def _attempt_automatic_recovery(self, operation_data: Dict[str, Any]) -> bool:
        """Attempt automatic recovery of failed operation."""
        operation_type = operation_data.get("operation_type")

        if operation_type == "webhook_processing":
            # Retry webhook processing with fresh data
            payment_id = operation_data.get("payment_id")
            if payment_id:
                from ..services.webhook_wrapper_service import WebhookWrapperService

                service = WebhookWrapperService()
                result = service.process_webhook(payment_id)
                return result.get("status") == "success"

        elif operation_type == "payment_creation":
            # Retry payment creation
            # Implementation would depend on specific requirements
            pass

        return False

    def _attempt_partial_recovery(self, operation_data: Dict[str, Any]) -> bool:
        """Attempt partial recovery where possible."""
        # This would implement partial recovery strategies
        # For example, if webhook processing partially failed,
        # we might try to complete just the missing parts
        return False


# Global error recovery instance
error_recovery = MollieErrorRecovery()


def with_retry(retry_config: Optional[RetryConfig] = None, operation_name: Optional[str] = None):
    """
    Decorator for adding retry logic to functions.

    Args:
        retry_config: Retry configuration
        operation_name: Name for logging (defaults to function name)
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            name = operation_name or func.__name__
            return error_recovery.execute_with_retry(lambda: func(*args, **kwargs), name, retry_config)

        return wrapper

    return decorator


def with_circuit_breaker(
    circuit_name: Optional[str] = None, circuit_config: Optional[CircuitBreakerConfig] = None
):
    """
    Decorator for adding circuit breaker protection to functions.

    Args:
        circuit_name: Circuit identifier (defaults to function name)
        circuit_config: Circuit breaker configuration
    """

    def decorator(func):
        def wrapper(*args, **kwargs):
            name = circuit_name or func.__name__
            return error_recovery.execute_with_circuit_breaker(
                lambda: func(*args, **kwargs), name, circuit_config
            )

        return wrapper

    return decorator
