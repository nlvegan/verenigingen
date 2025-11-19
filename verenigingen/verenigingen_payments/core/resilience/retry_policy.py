"""
Exponential Backoff Retry Policy
Smart retry logic with jitter for distributed systems

Features:
- Exponential backoff with configurable base and max delay
- Jitter to prevent thundering herd
- Retry budget to prevent retry storms
- Different strategies for different error types
"""

import functools
import random
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import frappe
from frappe import _


class RetryStrategy(Enum):
    """Retry strategies for different scenarios"""

    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    FIXED = "fixed"
    FIBONACCI = "fibonacci"


class ExponentialBackoffRetry:
    """
    Exponential backoff retry with jitter

    Provides:
    - Configurable backoff strategies
    - Jitter to prevent synchronized retries
    - Maximum retry attempts
    - Retry budget management
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        jitter_range: Tuple[float, float] = (0.5, 1.5),
    ):
        """
        Initialize exponential backoff retry policy

        Args:
            max_attempts: Maximum retry attempts
            base_delay: Initial delay in seconds
            max_delay: Maximum delay between retries
            exponential_base: Base for exponential calculation
            jitter: Whether to add jitter
            jitter_range: Multiplier range for jitter
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.jitter_range = jitter_range

        # Metrics
        self.total_attempts = 0
        self.successful_retries = 0
        self.failed_retries = 0
        self.total_delay_time = 0.0

    def execute(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with retry policy

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result

        Raises:
            Last exception if all retries fail
        """
        last_exception = None
        attempt = 0

        while attempt < self.max_attempts:
            self.total_attempts += 1

            try:
                result = func(*args, **kwargs)

                if attempt > 0:
                    self.successful_retries += 1
                    self._log_retry_success(func.__name__, attempt)

                return result

            except Exception as e:
                last_exception = e
                attempt += 1

                if attempt >= self.max_attempts:
                    self.failed_retries += 1
                    self._log_retry_failure(func.__name__, attempt, e)
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt)
                self.total_delay_time += delay

                self._log_retry_attempt(func.__name__, attempt, delay, e)

                # Wait before retry
                time.sleep(delay)

        # All retries exhausted
        raise last_exception

    async def execute_async(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute async function with retry policy

        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        import asyncio

        last_exception = None
        attempt = 0

        while attempt < self.max_attempts:
            self.total_attempts += 1

            try:
                result = await func(*args, **kwargs)

                if attempt > 0:
                    self.successful_retries += 1

                return result

            except Exception as e:
                last_exception = e
                attempt += 1

                if attempt >= self.max_attempts:
                    self.failed_retries += 1
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt)
                self.total_delay_time += delay

                # Async wait
                await asyncio.sleep(delay)

        raise last_exception

    def _calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for given attempt

        Args:
            attempt: Current attempt number (1-based)

        Returns:
            float: Delay in seconds
        """
        # Base exponential calculation
        delay = min(self.base_delay * (self.exponential_base ** (attempt - 1)), self.max_delay)

        # Add jitter if enabled
        if self.jitter:
            jitter_multiplier = random.uniform(*self.jitter_range)
            delay *= jitter_multiplier

        return delay

    def _log_retry_attempt(self, func_name: str, attempt: int, delay: float, exception: Exception):
        """Log retry attempt"""
        frappe.logger("retry_policy").info(
            f"Retry attempt {attempt}/{self.max_attempts} for {func_name}. "
            f"Waiting {delay:.2f}s. Error: {str(exception)}"
        )

    def _log_retry_success(self, func_name: str, attempts: int):
        """Log successful retry"""
        frappe.logger("retry_policy").info(f"Retry successful for {func_name} after {attempts} attempts")

    def _log_retry_failure(self, func_name: str, attempts: int, exception: Exception):
        """Log retry failure"""
        frappe.logger("retry_policy").error(
            f"All retries failed for {func_name} after {attempts} attempts. " f"Last error: {str(exception)}"
        )

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get retry metrics

        Returns:
            Dict with retry statistics
        """
        return {
            "max_attempts": self.max_attempts,
            "total_attempts": self.total_attempts,
            "successful_retries": self.successful_retries,
            "failed_retries": self.failed_retries,
            "retry_success_rate": (
                self.successful_retries / (self.successful_retries + self.failed_retries)
                if (self.successful_retries + self.failed_retries) > 0
                else 0
            ),
            "total_delay_time": self.total_delay_time,
            "average_delay": (
                self.total_delay_time / self.successful_retries if self.successful_retries > 0 else 0
            ),
        }


class SmartRetryPolicy:
    """
    Intelligent retry policy with error classification

    Features:
    - Different strategies for different error types
    - Retry budget to prevent storms
    - Circuit breaker integration
    - Error pattern learning
    """

    def __init__(self, retry_budget: int = 100):
        """
        Initialize smart retry policy

        Args:
            retry_budget: Maximum retries per time window
        """
        self.retry_budget = retry_budget
        self.remaining_budget = retry_budget
        self.budget_reset_time = datetime.now() + timedelta(minutes=1)

        # Error classification
        self.retryable_errors = {
            # Network errors - aggressive retry
            ConnectionError: {"strategy": RetryStrategy.EXPONENTIAL, "max_attempts": 5},
            TimeoutError: {"strategy": RetryStrategy.EXPONENTIAL, "max_attempts": 3},
            # Rate limiting - respectful retry
            "RateLimitError": {"strategy": RetryStrategy.EXPONENTIAL, "max_attempts": 3, "base_delay": 5},
            # Server errors - moderate retry
            "ServerError": {"strategy": RetryStrategy.EXPONENTIAL, "max_attempts": 3},
            "ServiceUnavailable": {"strategy": RetryStrategy.LINEAR, "max_attempts": 2},
        }

        self.non_retryable_errors = [
            "AuthenticationError",
            "InvalidRequestError",
            "NotFoundError",
            "PermissionError",
        ]

        # Strategy implementations
        self.strategies = {
            RetryStrategy.EXPONENTIAL: ExponentialBackoffRetry(),
            RetryStrategy.LINEAR: LinearBackoffRetry(),
            RetryStrategy.FIXED: FixedDelayRetry(),
            RetryStrategy.FIBONACCI: FibonacciBackoffRetry(),
        }

        # Error pattern tracking
        self.error_patterns = {}
        self.consecutive_errors = {}

    def should_retry(self, exception: Exception) -> Tuple[bool, Optional[Dict]]:
        """
        Determine if error should be retried

        Args:
            exception: Exception that occurred

        Returns:
            Tuple of (should_retry, retry_config)
        """
        # Check retry budget
        if not self._check_budget():
            return False, None

        # Check non-retryable errors
        error_type = type(exception).__name__
        if error_type in self.non_retryable_errors:
            return False, None

        # Check retryable errors
        for error_class, config in self.retryable_errors.items():
            if isinstance(error_class, str):
                if error_type == error_class:
                    return True, config
            else:
                if isinstance(exception, error_class):
                    return True, config

        # Default: don't retry unknown errors
        return False, None

    def execute_with_classification(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with intelligent retry

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Function result
        """
        attempt = 0

        while True:
            try:
                result = func(*args, **kwargs)

                # Reset consecutive errors on success
                self._reset_error_tracking(func.__name__)

                return result

            except Exception as e:
                # last_exception = e
                attempt += 1

                # Track error pattern
                self._track_error_pattern(func.__name__, e)

                # Check if should retry
                should_retry, retry_config = self.should_retry(e)

                if not should_retry:
                    raise

                # Check if attempts exceeded
                max_attempts = retry_config.get("max_attempts", 3)
                if attempt >= max_attempts:
                    raise

                # Get retry strategy
                strategy_type = retry_config.get("strategy", RetryStrategy.EXPONENTIAL)
                strategy = self.strategies[strategy_type]

                # Apply custom config
                if "base_delay" in retry_config:
                    strategy.base_delay = retry_config["base_delay"]

                # Calculate and apply delay
                delay = strategy._calculate_delay(attempt)
                time.sleep(delay)

                # Consume budget
                self._consume_budget()

    def _check_budget(self) -> bool:
        """Check if retry budget available"""
        # Reset budget if time window passed
        if datetime.now() > self.budget_reset_time:
            self.remaining_budget = self.retry_budget
            self.budget_reset_time = datetime.now() + timedelta(minutes=1)

        return self.remaining_budget > 0

    def _consume_budget(self):
        """Consume retry budget"""
        self.remaining_budget = max(0, self.remaining_budget - 1)

    def _track_error_pattern(self, func_name: str, exception: Exception):
        """Track error patterns for learning"""
        error_key = f"{func_name}:{type(exception).__name__}"

        if error_key not in self.error_patterns:
            self.error_patterns[error_key] = {"count": 0, "first_seen": datetime.now(), "last_seen": None}

        self.error_patterns[error_key]["count"] += 1
        self.error_patterns[error_key]["last_seen"] = datetime.now()

        # Track consecutive errors
        if func_name not in self.consecutive_errors:
            self.consecutive_errors[func_name] = 0
        self.consecutive_errors[func_name] += 1

    def _reset_error_tracking(self, func_name: str):
        """Reset error tracking on success"""
        if func_name in self.consecutive_errors:
            self.consecutive_errors[func_name] = 0

    def get_error_patterns(self) -> Dict[str, Dict]:
        """Get tracked error patterns"""
        return self.error_patterns


class LinearBackoffRetry(ExponentialBackoffRetry):
    """Linear backoff retry policy"""

    def _calculate_delay(self, attempt: int) -> float:
        """Linear delay calculation"""
        delay = min(self.base_delay * attempt, self.max_delay)

        if self.jitter:
            jitter_multiplier = random.uniform(*self.jitter_range)
            delay *= jitter_multiplier

        return delay


class FixedDelayRetry(ExponentialBackoffRetry):
    """Fixed delay retry policy"""

    def _calculate_delay(self, attempt: int) -> float:
        """Fixed delay calculation"""
        delay = self.base_delay

        if self.jitter:
            jitter_multiplier = random.uniform(*self.jitter_range)
            delay *= jitter_multiplier

        return delay


class FibonacciBackoffRetry(ExponentialBackoffRetry):
    """Fibonacci sequence backoff retry policy"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fib_sequence = [1, 1]

    def _calculate_delay(self, attempt: int) -> float:
        """Fibonacci delay calculation"""
        # Extend sequence if needed
        while len(self.fib_sequence) <= attempt:
            self.fib_sequence.append(self.fib_sequence[-1] + self.fib_sequence[-2])

        delay = min(self.base_delay * self.fib_sequence[attempt - 1], self.max_delay)

        if self.jitter:
            jitter_multiplier = random.uniform(*self.jitter_range)
            delay *= jitter_multiplier

        return delay


def retry_with_backoff(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception]] = (Exception,),
):
    """
    Decorator for adding retry logic to functions

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay between retries
        max_delay: Maximum delay between retries
        exceptions: Tuple of exceptions to catch

    Usage:
        @retry_with_backoff(max_attempts=3, exceptions=(ConnectionError,))
        def api_call():
            # Make API call
            pass
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retry_policy = ExponentialBackoffRetry(
                max_attempts=max_attempts, base_delay=base_delay, max_delay=max_delay
            )

            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt < max_attempts - 1:
                        delay = retry_policy._calculate_delay(attempt + 1)
                        time.sleep(delay)
                    else:
                        raise

            raise last_exception

        return wrapper

    return decorator
