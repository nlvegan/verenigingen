"""
Circuit Breaker Pattern Implementation
Prevents cascading failures in distributed systems

Features:
- Three states: CLOSED, OPEN, HALF_OPEN
- Configurable failure thresholds
- Automatic recovery testing
- Per-endpoint circuit breakers
"""

import threading
import time
from collections import deque
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional

import frappe
from frappe import _


class CircuitState(Enum):
    """Circuit breaker states"""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Failing, reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker pattern for API resilience

    Protects against cascading failures by:
    - Monitoring failure rates
    - Opening circuit when threshold exceeded
    - Periodically testing recovery
    - Providing fallback mechanisms
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 3,
        expected_exception: type = Exception,
    ):
        """
        Initialize circuit breaker

        Args:
            name: Circuit breaker identifier
            failure_threshold: Failures before opening circuit
            recovery_timeout: Seconds before attempting recovery
            success_threshold: Successes needed to close circuit
            expected_exception: Exception type to catch
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        self.expected_exception = expected_exception

        # State management
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_state_change = datetime.now()

        # Thread safety
        self.lock = threading.RLock()

        # Metrics
        self.call_count = 0
        self.total_failures = 0
        self.total_successes = 0

        # Recent errors for debugging
        self.recent_errors = deque(maxlen=10)

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpenException: If circuit is open
            Exception: Original exception if circuit is closed
        """
        with self.lock:
            self.call_count += 1

            # Check circuit state
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    self._log_circuit_event("rejected", "Circuit breaker is OPEN")
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker '{self.name}' is OPEN. " f"Last failure: {self.last_failure_time}"
                    )

            # Attempt the call
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result

            except self.expected_exception as e:
                self._on_failure(e)
                raise

    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute async function with circuit breaker protection

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        with self.lock:
            self.call_count += 1

            # Check circuit state
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    raise CircuitBreakerOpenException(f"Circuit breaker '{self.name}' is OPEN")

            # Attempt the call
            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result

            except self.expected_exception as e:
                self._on_failure(e)
                raise

    def _on_success(self):
        """Handle successful call"""
        with self.lock:
            self.total_successes += 1

            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1

                if self.success_count >= self.success_threshold:
                    self._transition_to_closed()

            elif self.state == CircuitState.CLOSED:
                # Reset failure count on success
                self.failure_count = 0

    def _on_failure(self, exception: Exception):
        """Handle failed call"""
        with self.lock:
            self.total_failures += 1
            self.last_failure_time = datetime.now()

            # Store recent error for debugging
            self.recent_errors.append(
                {
                    "timestamp": self.last_failure_time,
                    "error": str(exception),
                    "type": type(exception).__name__,
                }
            )

            if self.state == CircuitState.HALF_OPEN:
                # Single failure in half-open state reopens circuit
                self._transition_to_open()

            elif self.state == CircuitState.CLOSED:
                self.failure_count += 1

                if self.failure_count >= self.failure_threshold:
                    self._transition_to_open()

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt recovery"""
        if self.last_failure_time:
            time_since_failure = (datetime.now() - self.last_failure_time).total_seconds()
            return time_since_failure >= self.recovery_timeout
        return False

    def _transition_to_open(self):
        """Transition to OPEN state"""
        self.state = CircuitState.OPEN
        self.last_state_change = datetime.now()

        self._log_circuit_event("opened", f"Circuit opened after {self.failure_count} failures")

        # Reset counters
        self.failure_count = 0
        self.success_count = 0

    def _transition_to_half_open(self):
        """Transition to HALF_OPEN state"""
        self.state = CircuitState.HALF_OPEN
        self.last_state_change = datetime.now()

        self._log_circuit_event("half_opened", "Testing recovery")

        # Reset counters for testing
        self.success_count = 0
        self.failure_count = 0

    def _transition_to_closed(self):
        """Transition to CLOSED state"""
        self.state = CircuitState.CLOSED
        self.last_state_change = datetime.now()

        self._log_circuit_event("closed", f"Circuit closed after {self.success_count} successes")

        # Reset counters
        self.failure_count = 0
        self.success_count = 0

    def _log_circuit_event(self, event: str, details: str):
        """Log circuit breaker state changes"""
        frappe.logger("circuit_breaker").info(f"Circuit '{self.name}' {event}: {details}")

    def get_state(self) -> Dict[str, Any]:
        """
        Get current circuit breaker state and metrics

        Returns:
            Dict with state information
        """
        with self.lock:
            return {
                "name": self.name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
                "last_state_change": self.last_state_change.isoformat(),
                "call_count": self.call_count,
                "total_failures": self.total_failures,
                "total_successes": self.total_successes,
                "failure_rate": self.total_failures / self.call_count if self.call_count > 0 else 0,
                "recent_errors": list(self.recent_errors),
            }

    def reset(self):
        """Manually reset circuit breaker to closed state"""
        with self.lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.last_failure_time = None
            self.last_state_change = datetime.now()

            self._log_circuit_event("reset", "Manual reset to CLOSED state")


class EndpointCircuitBreaker:
    """
    Manages multiple circuit breakers for different API endpoints

    Provides:
    - Per-endpoint circuit breaker isolation
    - Different thresholds for different endpoints
    - Centralized monitoring
    """

    def __init__(self):
        """Initialize endpoint circuit breaker manager"""
        self.breakers = {}
        self.default_config = {"failure_threshold": 5, "recovery_timeout": 60, "success_threshold": 3}

        # Endpoint-specific configurations
        self.endpoint_configs = {
            "payments": {
                "failure_threshold": 3,  # More sensitive
                "recovery_timeout": 30,
                "success_threshold": 2,
            },
            "settlements": {"failure_threshold": 5, "recovery_timeout": 60, "success_threshold": 3},
            "balances": {
                "failure_threshold": 2,  # Critical endpoint
                "recovery_timeout": 20,
                "success_threshold": 1,
            },
        }

    def get_breaker(self, endpoint: str) -> CircuitBreaker:
        """
        Get or create circuit breaker for endpoint

        Args:
            endpoint: API endpoint identifier

        Returns:
            CircuitBreaker instance for endpoint
        """
        if endpoint not in self.breakers:
            config = self.endpoint_configs.get(endpoint, self.default_config)
            self.breakers[endpoint] = CircuitBreaker(name=endpoint, **config)

        return self.breakers[endpoint]

    def call_with_breaker(self, endpoint: str, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with appropriate circuit breaker

        Args:
            endpoint: API endpoint identifier
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        breaker = self.get_breaker(endpoint)
        return breaker.call(func, *args, **kwargs)

    def get_all_states(self) -> Dict[str, Dict]:
        """
        Get state of all circuit breakers

        Returns:
            Dict mapping endpoint to state
        """
        return {endpoint: breaker.get_state() for endpoint, breaker in self.breakers.items()}

    def reset_all(self):
        """Reset all circuit breakers"""
        for breaker in self.breakers.values():
            breaker.reset()

    def get_health_status(self) -> Dict[str, Any]:
        """
        Get overall health status

        Returns:
            Dict with health metrics
        """
        states = self.get_all_states()

        open_circuits = [
            endpoint for endpoint, state in states.items() if state["state"] == CircuitState.OPEN.value
        ]

        half_open_circuits = [
            endpoint for endpoint, state in states.items() if state["state"] == CircuitState.HALF_OPEN.value
        ]

        total_calls = sum(state["call_count"] for state in states.values())
        total_failures = sum(state["total_failures"] for state in states.values())

        return {
            "healthy": len(open_circuits) == 0,
            "open_circuits": open_circuits,
            "half_open_circuits": half_open_circuits,
            "total_endpoints": len(self.breakers),
            "total_calls": total_calls,
            "total_failures": total_failures,
            "overall_failure_rate": total_failures / total_calls if total_calls > 0 else 0,
            "timestamp": datetime.now().isoformat(),
        }


class CircuitBreakerOpenException(Exception):
    """Exception raised when circuit breaker is open"""

    pass


# Global endpoint circuit breaker instance
_endpoint_breaker = None


def get_endpoint_circuit_breaker() -> EndpointCircuitBreaker:
    """
    Get global endpoint circuit breaker instance

    Returns:
        EndpointCircuitBreaker singleton
    """
    global _endpoint_breaker
    if _endpoint_breaker is None:
        _endpoint_breaker = EndpointCircuitBreaker()
    return _endpoint_breaker
