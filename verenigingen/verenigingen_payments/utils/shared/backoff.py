"""Shared backoff delay calculator for payment retry logic."""

import random
from typing import Callable, Optional


def calculate_backoff_delay(
    attempt: int,
    *,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    strategy: str = "exponential",
    exponential_base: float = 2.0,
    jitter_factor: float = 0.0,
    rng: Optional[Callable[[], float]] = None,
) -> float:
    """Calculate backoff delay for retry logic with optional jitter.

    Args:
        attempt: 1-based attempt number.
        base_delay: Base delay in seconds (default 1.0).
        max_delay: Maximum delay in seconds (default 60.0). Cap applied before jitter.
        strategy: Backoff strategy ('exponential', 'linear', 'fixed', 'fibonacci').
        exponential_base: Base for exponential strategy (default 2.0).
        jitter_factor: Jitter factor (0 disables; else adds [0, delay*jitter_factor)).
        rng: Injectable random() function for deterministic tests (default random.random).

    Returns:
        Backoff delay in seconds, always >= 0.0.

    Examples:
        >>> calculate_backoff_delay(1)  # 1.0
        1.0
        >>> calculate_backoff_delay(2)  # 2.0
        2.0
        >>> calculate_backoff_delay(3)  # 4.0
        4.0
        >>> calculate_backoff_delay(10, max_delay=60)  # 60.0 (capped)
        60.0
    """
    # Use default rng if not provided
    if rng is None:
        rng = random.random

    # Calculate base delay based on strategy
    if strategy == "exponential":
        delay = base_delay * (exponential_base ** (attempt - 1))
    elif strategy == "linear":
        delay = base_delay * attempt
    elif strategy == "fixed":
        delay = base_delay
    elif strategy == "fibonacci":
        # Calculate fibonacci number for this attempt
        # fib(1) = 1, fib(2) = 1, fib(3) = 2, fib(4) = 3, fib(5) = 5, ...
        delay = base_delay * _fibonacci(attempt)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    # Cap at max_delay BEFORE jitter
    delay = min(delay, max_delay)

    # Add jitter if requested
    if jitter_factor > 0:
        jitter = delay * jitter_factor * rng()
        delay = delay + jitter

    # Ensure non-negative
    return max(0.0, delay)


def _fibonacci(n: int) -> int:
    """Calculate fibonacci number at position n (1-based).

    Args:
        n: 1-based position in fibonacci sequence.

    Returns:
        Fibonacci number at position n, with fib(1)=1, fib(2)=1.
    """
    if n <= 0:
        return 0
    if n == 1 or n == 2:
        return 1

    a, b = 1, 1
    for _ in range(n - 2):
        a, b = b, a + b
    return b
