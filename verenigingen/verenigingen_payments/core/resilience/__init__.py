# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Shared Resilience Patterns for PSP Integrations

This module provides resilience patterns used across all Payment Service Provider
integrations. The primary protection is retry with exponential backoff and jitter.

Usage:
    from verenigingen.verenigingen_payments.core.resilience import (
        RetryConfig,
        with_retry,
    )

    @with_retry(RetryConfig(max_attempts=3))
    def call_external_api():
        ...

Note: ``with_circuit_breaker`` and ``CircuitBreakerConfig`` are still exported for
backwards compatibility but are no-ops. Use ``@with_retry`` for resilience.
"""

import functools
from dataclasses import dataclass
from typing import Any, Callable, Optional

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
    DEPRECATED: Circuit breaker decorator - now a pass-through.

    Circuit breakers were removed as they add complexity without proportional
    benefit at the transaction volumes of a Dutch non-profit association.
    For transient failures, retry with exponential backoff (via @with_retry)
    is sufficient.

    This decorator now does nothing but is kept for backwards compatibility.
    Use @with_retry for resilience instead.

    Args:
        circuit_name: Ignored (kept for API compatibility)
        circuit_config: Ignored (kept for API compatibility)

    See: docs/architecture/PSP_INTEGRATION_CONSOLIDATION_PLAN.md for rationale
    """

    # Pass-through decorator - circuit breaker logic removed
    def decorator(func: Callable) -> Callable:
        return func

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
    "ExponentialBackoffRetry",
    "RetryStrategy",
]
