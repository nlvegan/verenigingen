# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Shared Resilience Patterns for PSP Integrations

This module provides production-grade resilience patterns used across all Payment
Service Provider integrations. These patterns help protect against:

- Transient API failures (retry with exponential backoff)
- Cascading failures (circuit breaker)
- Thundering herd problems (jitter)

Usage:
    from verenigingen.verenigingen_payments.core.resilience import (
        RetryConfig,
        CircuitBreakerConfig,
        with_retry,
        with_circuit_breaker,
    )

    # Use decorators for simple cases
    @with_retry(RetryConfig(max_attempts=3))
    @with_circuit_breaker(CircuitBreakerConfig())
    def call_external_api():
        ...
"""

import functools
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .circuit_breaker import CircuitBreaker, CircuitBreakerOpenException
from .retry_policy import ExponentialBackoffRetry, RetryStrategy


# Configuration dataclasses for Mollie/Ponto compatibility
@dataclass
class RetryConfig:
    """Configuration for retry operations - compatible with Mollie interface."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    jitter: bool = True
    backoff_multiplier: float = 2.0


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker - compatible with Mollie interface."""

    failure_threshold: int = 5
    recovery_timeout: int = 60
    success_threshold: int = 3


# Global circuit breaker registry for decorator usage
_circuit_breakers: dict = {}


def with_retry(
    retry_config: Optional[RetryConfig] = None,
    operation_name: Optional[str] = None,
):
    """
    Decorator for adding retry logic to functions.

    Compatible with Mollie's error_recovery.py interface.

    Args:
        retry_config: Retry configuration (uses defaults if None)
        operation_name: Name for logging (defaults to function name)

    Usage:
        @with_retry(RetryConfig(max_attempts=3))
        def call_external_api():
            ...
    """
    if retry_config is None:
        retry_config = RetryConfig()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retry_policy = ExponentialBackoffRetry(
                max_attempts=retry_config.max_attempts,
                base_delay=retry_config.base_delay,
                max_delay=retry_config.max_delay,
                jitter=retry_config.jitter,
                exponential_base=retry_config.backoff_multiplier,
            )
            return retry_policy.execute(func, *args, **kwargs)

        return wrapper

    return decorator


def with_circuit_breaker(
    circuit_name: Optional[str] = None,
    circuit_config: Optional[CircuitBreakerConfig] = None,
):
    """
    Decorator for adding circuit breaker protection to functions.

    Compatible with Mollie's error_recovery.py interface.

    Args:
        circuit_name: Circuit identifier (defaults to function name)
        circuit_config: Circuit breaker configuration

    Usage:
        @with_circuit_breaker(CircuitBreakerConfig(failure_threshold=5))
        def call_external_api():
            ...

    Raises:
        CircuitBreakerOpenException: When circuit is open
    """
    if circuit_config is None:
        circuit_config = CircuitBreakerConfig()

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            name = circuit_name or func.__name__

            # Get or create circuit breaker for this name
            if name not in _circuit_breakers:
                _circuit_breakers[name] = CircuitBreaker(
                    name=name,
                    failure_threshold=circuit_config.failure_threshold,
                    recovery_timeout=circuit_config.recovery_timeout,
                    success_threshold=circuit_config.success_threshold,
                )

            breaker = _circuit_breakers[name]
            return breaker.call(func, *args, **kwargs)

        return wrapper

    return decorator


# Re-export underlying classes for advanced usage
__all__ = [
    # Configuration dataclasses
    "RetryConfig",
    "CircuitBreakerConfig",
    # Decorators (main interface)
    "with_retry",
    "with_circuit_breaker",
    # Underlying implementations for advanced usage
    "CircuitBreaker",
    "CircuitBreakerOpenException",
    "ExponentialBackoffRetry",
    "RetryStrategy",
]
