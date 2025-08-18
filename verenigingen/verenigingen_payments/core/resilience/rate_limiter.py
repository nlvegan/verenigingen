"""
Token Bucket Rate Limiter
Controls API request rates with burst capacity

Features:
- Token bucket algorithm for smooth rate limiting
- Burst capacity handling
- Per-endpoint rate limiting
- Adaptive rate adjustment based on API responses
"""

import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import frappe
from frappe import _


class TokenBucketRateLimiter:
    """
    Token bucket algorithm for API rate limiting

    Provides:
    - Smooth rate limiting with burst capacity
    - Thread-safe token management
    - Configurable refill rates
    - Wait capabilities for token availability
    """

    def __init__(self, max_tokens: int = 300, refill_rate: float = 5.0, refill_period: float = 1.0):
        """
        Initialize token bucket rate limiter

        Args:
            max_tokens: Maximum tokens in bucket (burst capacity)
            refill_rate: Tokens added per refill period
            refill_period: Seconds between refills
        """
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_rate = refill_rate
        self.refill_period = refill_period
        self.last_refill = time.time()

        # Thread safety
        self.lock = threading.RLock()

        # Metrics
        self.total_requests = 0
        self.total_granted = 0
        self.total_denied = 0
        self.total_wait_time = 0.0

    def acquire(self, tokens: int = 1, wait: bool = False, timeout: float = 30.0) -> bool:
        """
        Acquire tokens for API request

        Args:
            tokens: Number of tokens to acquire
            wait: Whether to wait for tokens if not available
            timeout: Maximum wait time in seconds

        Returns:
            bool: True if tokens acquired, False otherwise
        """
        with self.lock:
            self.total_requests += 1

            # Refill bucket
            self._refill_bucket()

            # Check if tokens available
            if self.tokens >= tokens:
                self.tokens -= tokens
                self.total_granted += 1
                return True

            # If not waiting, deny immediately
            if not wait:
                self.total_denied += 1
                return False

            # Wait for tokens
            return self._wait_for_tokens(tokens, timeout)

    def wait_for_token(self, timeout: float = 30.0) -> bool:
        """
        Wait for a single token to become available

        Args:
            timeout: Maximum wait time in seconds

        Returns:
            bool: True if token acquired within timeout
        """
        return self.acquire(tokens=1, wait=True, timeout=timeout)

    def _refill_bucket(self):
        """Refill bucket based on elapsed time"""
        current_time = time.time()
        time_elapsed = current_time - self.last_refill

        # Calculate tokens to add
        refill_count = int(time_elapsed / self.refill_period)
        if refill_count > 0:
            tokens_to_add = refill_count * self.refill_rate
            self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
            self.last_refill = current_time

    def _wait_for_tokens(self, tokens: int, timeout: float) -> bool:
        """
        Wait for tokens to become available

        Args:
            tokens: Number of tokens needed
            timeout: Maximum wait time

        Returns:
            bool: True if tokens acquired within timeout
        """
        start_time = time.time()
        wait_interval = 0.1  # Check every 100ms

        while time.time() - start_time < timeout:
            time.sleep(wait_interval)

            with self.lock:
                self._refill_bucket()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    wait_time = time.time() - start_time
                    self.total_wait_time += wait_time
                    self.total_granted += 1
                    return True

        # Timeout reached
        self.total_denied += 1
        return False

    def get_available_tokens(self) -> int:
        """
        Get current available tokens

        Returns:
            int: Number of available tokens
        """
        with self.lock:
            self._refill_bucket()
            return int(self.tokens)

    def get_metrics(self) -> Dict[str, any]:
        """
        Get rate limiter metrics

        Returns:
            Dict with usage metrics
        """
        with self.lock:
            return {
                "max_tokens": self.max_tokens,
                "available_tokens": self.get_available_tokens(),
                "refill_rate": self.refill_rate,
                "refill_period": self.refill_period,
                "total_requests": self.total_requests,
                "total_granted": self.total_granted,
                "total_denied": self.total_denied,
                "grant_rate": self.total_granted / self.total_requests if self.total_requests > 0 else 0,
                "average_wait_time": self.total_wait_time / self.total_granted
                if self.total_granted > 0
                else 0,
            }

    def reset(self):
        """Reset rate limiter to initial state"""
        with self.lock:
            self.tokens = self.max_tokens
            self.last_refill = time.time()
            self.total_requests = 0
            self.total_granted = 0
            self.total_denied = 0
            self.total_wait_time = 0.0


class AdaptiveRateLimiter(TokenBucketRateLimiter):
    """
    Adaptive rate limiter that adjusts based on API responses

    Features:
    - Automatic rate adjustment based on 429 responses
    - Respects Retry-After headers
    - Gradual recovery after rate limit errors
    """

    def __init__(
        self,
        initial_max_tokens: int = 300,
        initial_refill_rate: float = 5.0,
        min_refill_rate: float = 1.0,
        max_refill_rate: float = 10.0,
    ):
        """
        Initialize adaptive rate limiter

        Args:
            initial_max_tokens: Starting burst capacity
            initial_refill_rate: Starting refill rate
            min_refill_rate: Minimum refill rate
            max_refill_rate: Maximum refill rate
        """
        super().__init__(initial_max_tokens, initial_refill_rate)

        self.min_refill_rate = min_refill_rate
        self.max_refill_rate = max_refill_rate
        self.initial_refill_rate = initial_refill_rate

        # Adaptation state
        self.consecutive_successes = 0
        self.last_rate_limit_time = None
        self.retry_after = None

    def on_success(self):
        """Handle successful API call"""
        with self.lock:
            self.consecutive_successes += 1

            # Gradually increase rate after successes
            if self.consecutive_successes >= 100:
                self._increase_rate()
                self.consecutive_successes = 0

    def on_rate_limit(self, retry_after: Optional[int] = None):
        """
        Handle rate limit response from API

        Args:
            retry_after: Seconds to wait before retry (from header)
        """
        with self.lock:
            self.last_rate_limit_time = time.time()
            self.consecutive_successes = 0

            if retry_after:
                self.retry_after = retry_after
                # Pause for retry_after duration
                self.tokens = 0
                self.last_refill = time.time() + retry_after

            # Reduce rate significantly
            self._decrease_rate()

    def _increase_rate(self):
        """Gradually increase refill rate"""
        new_rate = min(self.max_refill_rate, self.refill_rate * 1.1)
        if new_rate != self.refill_rate:
            self.refill_rate = new_rate
            frappe.logger("rate_limiter").info(f"Increased refill rate to {self.refill_rate}")

    def _decrease_rate(self):
        """Reduce refill rate on rate limit"""
        new_rate = max(self.min_refill_rate, self.refill_rate * 0.5)
        if new_rate != self.refill_rate:
            self.refill_rate = new_rate
            frappe.logger("rate_limiter").info(f"Decreased refill rate to {self.refill_rate}")

    def adapt_from_headers(self, response_headers: Dict[str, str]):
        """
        Adapt rate limiting based on API response headers

        Args:
            response_headers: HTTP response headers
        """
        # Check for rate limit headers
        if "X-RateLimit-Remaining" in response_headers:
            remaining = int(response_headers["X-RateLimit-Remaining"])

            # Preemptively slow down if approaching limit
            if remaining < 10:
                with self.lock:
                    self.refill_rate = max(self.min_refill_rate, self.refill_rate * 0.8)

        if "X-RateLimit-Reset" in response_headers:
            reset_time = int(response_headers["X-RateLimit-Reset"])
            current_time = int(time.time())

            if reset_time > current_time:
                # Pause until reset
                with self.lock:
                    self.tokens = 0
                    self.last_refill = reset_time

        if "Retry-After" in response_headers:
            retry_after = int(response_headers["Retry-After"])
            self.on_rate_limit(retry_after)


class EndpointRateLimiter:
    """
    Manages rate limiting for multiple API endpoints

    Provides:
    - Per-endpoint rate limits
    - Shared global limit
    - Priority-based token allocation
    """

    def __init__(self, global_limit: int = 1000):
        """
        Initialize endpoint rate limiter

        Args:
            global_limit: Total API calls per minute across all endpoints
        """
        self.global_limiter = TokenBucketRateLimiter(
            max_tokens=global_limit, refill_rate=global_limit / 60.0, refill_period=1.0  # Per second
        )

        self.endpoint_limiters = {}

        # Endpoint-specific limits (per minute)
        self.endpoint_limits = {
            "payments": 300,  # High volume
            "settlements": 60,  # Medium volume
            "balances": 120,  # Regular checks
            "chargebacks": 30,  # Low volume
            "invoices": 60,  # Medium volume
        }

        # Priority levels (higher = more important)
        self.endpoint_priorities = {
            "payments": 10,
            "balances": 8,
            "settlements": 6,
            "chargebacks": 5,
            "invoices": 4,
        }

    def acquire(self, endpoint: str, tokens: int = 1, wait: bool = True) -> bool:
        """
        Acquire tokens for endpoint request

        Args:
            endpoint: API endpoint identifier
            tokens: Number of tokens needed
            wait: Whether to wait for tokens

        Returns:
            bool: True if tokens acquired
        """
        # Get or create endpoint limiter
        if endpoint not in self.endpoint_limiters:
            limit = self.endpoint_limits.get(endpoint, 60)
            self.endpoint_limiters[endpoint] = AdaptiveRateLimiter(
                initial_max_tokens=limit, initial_refill_rate=limit / 60.0
            )

        endpoint_limiter = self.endpoint_limiters[endpoint]

        # Check global limit first
        if not self.global_limiter.acquire(tokens, wait=False):
            if not wait:
                return False

            # Wait based on priority
            priority = self.endpoint_priorities.get(endpoint, 1)
            timeout = 30.0 * (priority / 10.0)  # Higher priority = longer wait

            if not self.global_limiter.acquire(tokens, wait=True, timeout=timeout):
                return False

        # Check endpoint limit
        if not endpoint_limiter.acquire(tokens, wait=wait):
            # Return global tokens if endpoint fails
            self.global_limiter.tokens += tokens
            return False

        return True

    def on_response(self, endpoint: str, status_code: int, headers: Dict[str, str]):
        """
        Handle API response for rate limit adaptation

        Args:
            endpoint: API endpoint
            status_code: HTTP status code
            headers: Response headers
        """
        if endpoint in self.endpoint_limiters:
            limiter = self.endpoint_limiters[endpoint]

            if status_code == 429:
                # Rate limited
                retry_after = headers.get("Retry-After")
                limiter.on_rate_limit(int(retry_after) if retry_after else None)
            elif 200 <= status_code < 300:
                # Success
                limiter.on_success()

            # Adapt based on headers
            if isinstance(limiter, AdaptiveRateLimiter):
                limiter.adapt_from_headers(headers)

    def get_endpoint_metrics(self) -> Dict[str, Dict]:
        """
        Get metrics for all endpoints

        Returns:
            Dict mapping endpoints to metrics
        """
        metrics = {"global": self.global_limiter.get_metrics()}

        for endpoint, limiter in self.endpoint_limiters.items():
            metrics[endpoint] = limiter.get_metrics()

        return metrics

    def reset_all(self):
        """Reset all rate limiters"""
        self.global_limiter.reset()
        for limiter in self.endpoint_limiters.values():
            limiter.reset()


class RateLimitTimeoutException(Exception):
    """Exception raised when rate limit wait timeout is exceeded"""

    pass


# Global endpoint rate limiter instance
_endpoint_rate_limiter = None


def get_endpoint_rate_limiter() -> EndpointRateLimiter:
    """
    Get global endpoint rate limiter instance

    Returns:
        EndpointRateLimiter singleton
    """
    global _endpoint_rate_limiter
    if _endpoint_rate_limiter is None:
        _endpoint_rate_limiter = EndpointRateLimiter()
    return _endpoint_rate_limiter
