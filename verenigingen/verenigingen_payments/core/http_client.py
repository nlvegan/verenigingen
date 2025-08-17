"""
Resilient HTTP Client
Production-ready HTTP client with integrated resilience patterns

Features:
- Circuit breaker for fault tolerance
- Rate limiting with token bucket
- Exponential backoff retry
- Request/response logging
- Performance monitoring
- Timeout management
"""

import json
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import frappe
import requests
from frappe import _
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from .compliance.audit_trail import AuditEventType, AuditSeverity, get_audit_trail
from .resilience.circuit_breaker import CircuitBreaker
from .resilience.rate_limiter import AdaptiveRateLimiter
from .resilience.retry_policy import SmartRetryPolicy


class ResilientHTTPClient:
    """
    Enterprise-grade HTTP client with resilience patterns

    Provides:
    - Automatic retry with exponential backoff
    - Circuit breaker for cascading failure prevention
    - Rate limiting to respect API limits
    - Comprehensive audit logging
    - Performance monitoring
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
        rate_limit: int = 10,
        circuit_breaker_threshold: int = 5,
    ):
        """
        Initialize resilient HTTP client

        Args:
            base_url: Base URL for API
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts
            rate_limit: Requests per second limit
            circuit_breaker_threshold: Failure threshold for circuit breaker
        """
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries

        # Initialize session with connection pooling
        self.session = requests.Session()
        self._configure_session()

        # Initialize resilience components
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_threshold,
            recovery_timeout=60,
            expected_exception=requests.RequestException,
        )

        self.rate_limiter = AdaptiveRateLimiter(initial_rate=rate_limit, burst_size=rate_limit * 2)

        self.retry_policy = SmartRetryPolicy(
            max_retries=max_retries, initial_delay=1.0, max_delay=60.0, exponential_base=2.0
        )

        self.audit_trail = get_audit_trail()

        # Performance metrics
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency": 0.0,
            "circuit_breaker_trips": 0,
            "rate_limit_throttles": 0,
        }

    def _configure_session(self):
        """Configure session with optimized settings"""

        # Configure retry adapter
        retry_strategy = Retry(
            total=self.max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"],
            backoff_factor=1,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=20)

        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Set default headers
        self.session.headers.update(
            {
                "User-Agent": f"Frappe-Verenigingen/{frappe.__version__}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def request(
        self,
        method: str,
        endpoint: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """
        Make HTTP request with resilience patterns

        Args:
            method: HTTP method
            endpoint: API endpoint
            headers: Additional headers
            params: Query parameters
            json_data: JSON payload
            data: Form data

        Returns:
            Tuple of (response_data, status_code)
        """
        # Check rate limit
        if not self.rate_limiter.allow_request():
            self.metrics["rate_limit_throttles"] += 1
            self._log_throttle(endpoint)
            raise frappe.ValidationError(_("Rate limit exceeded. Please try again later."))

        # Build full URL
        url = urljoin(self.base_url, endpoint)

        # Prepare request
        request_kwargs = {"method": method, "url": url, "timeout": self.timeout, "params": params}

        if headers:
            request_kwargs["headers"] = {**self.session.headers, **headers}

        if json_data:
            request_kwargs["json"] = json_data
        elif data:
            request_kwargs["data"] = data

        # Execute with circuit breaker and retry
        try:
            response = self._execute_with_resilience(request_kwargs)
            return self._process_response(response)

        except Exception as e:
            self._handle_error(method, endpoint, e)
            raise

    def _execute_with_resilience(self, request_kwargs: Dict[str, Any]) -> requests.Response:
        """
        Execute request with all resilience patterns

        Args:
            request_kwargs: Request parameters

        Returns:
            Response object
        """
        start_time = time.time()

        try:
            # Use circuit breaker
            response = self.circuit_breaker.call(self._make_request_with_retry, request_kwargs)

            # Update metrics
            self.metrics["total_requests"] += 1
            self.metrics["successful_requests"] += 1
            self.metrics["total_latency"] += time.time() - start_time

            # Log successful request
            self._log_request_success(
                request_kwargs["method"],
                request_kwargs["url"],
                response.status_code,
                time.time() - start_time,
            )

            return response

        except Exception as e:
            # Update metrics
            self.metrics["total_requests"] += 1
            self.metrics["failed_requests"] += 1
            self.metrics["total_latency"] += time.time() - start_time

            # Check if circuit breaker tripped
            if self.circuit_breaker.state == "OPEN":
                self.metrics["circuit_breaker_trips"] += 1

            # Log failure
            self._log_request_failure(
                request_kwargs["method"], request_kwargs["url"], str(e), time.time() - start_time
            )

            raise

    def _make_request_with_retry(self, request_kwargs: Dict[str, Any]) -> requests.Response:
        """
        Make request with retry policy

        Args:
            request_kwargs: Request parameters

        Returns:
            Response object
        """

        def make_request():
            response = self.session.request(**request_kwargs)

            # Check for rate limit headers
            self._update_rate_limit_from_headers(response.headers)

            # Raise for error status codes
            response.raise_for_status()

            return response

        # Use smart retry policy
        return self.retry_policy.execute_with_retry(make_request)

    def _update_rate_limit_from_headers(self, headers: Dict[str, str]):
        """
        Update rate limiter based on API response headers

        Args:
            headers: Response headers
        """
        # Check for standard rate limit headers
        if "X-RateLimit-Limit" in headers:
            try:
                limit = int(headers["X-RateLimit-Limit"])
                self.rate_limiter.adjust_rate(limit)
            except ValueError:
                pass

        # Check for retry-after header
        if "Retry-After" in headers:
            try:
                retry_after = int(headers["Retry-After"])
                time.sleep(retry_after)
            except ValueError:
                pass

    def _process_response(self, response: requests.Response) -> Tuple[Optional[Dict[str, Any]], int]:
        """
        Process HTTP response

        Args:
            response: Response object

        Returns:
            Tuple of (response_data, status_code)
        """
        # Handle different content types
        content_type = response.headers.get("Content-Type", "")

        if "application/json" in content_type:
            try:
                data = response.json()
            except json.JSONDecodeError:
                data = {"raw_response": response.text}
        else:
            data = {"raw_response": response.text}

        return data, response.status_code

    def _handle_error(self, method: str, endpoint: str, error: Exception):
        """
        Handle request error

        Args:
            method: HTTP method
            endpoint: API endpoint
            error: Exception that occurred
        """
        error_details = {
            "method": method,
            "endpoint": endpoint,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }

        # Log to audit trail
        self.audit_trail.log_event(
            AuditEventType.ERROR_OCCURRED,
            AuditSeverity.ERROR,
            f"HTTP request failed: {method} {endpoint}",
            details=error_details,
        )

        # Log to Frappe error log
        frappe.log_error(message=f"HTTP Client Error: {error_details}", title="HTTP Request Failed")

    def _log_request_success(self, method: str, url: str, status_code: int, latency: float):
        """Log successful request"""
        self.audit_trail.log_event(
            AuditEventType.API_KEY_ROTATION,  # Would have specific event type
            AuditSeverity.INFO,
            f"HTTP request successful: {method} {url}",
            details={"status_code": status_code, "latency_ms": round(latency * 1000, 2)},
        )

    def _log_request_failure(self, method: str, url: str, error: str, latency: float):
        """Log failed request"""
        self.audit_trail.log_event(
            AuditEventType.ERROR_OCCURRED,
            AuditSeverity.WARNING,
            f"HTTP request failed: {method} {url}",
            details={"error": error, "latency_ms": round(latency * 1000, 2)},
        )

    def _log_throttle(self, endpoint: str):
        """Log rate limit throttle"""
        self.audit_trail.log_event(
            AuditEventType.RATE_LIMIT_EXCEEDED,
            AuditSeverity.WARNING,
            f"Rate limit exceeded for endpoint: {endpoint}",
            details={"endpoint": endpoint},
        )

    def get(self, endpoint: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        """Make GET request"""
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        """Make POST request"""
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        """Make PUT request"""
        return self.request("PUT", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        """Make DELETE request"""
        return self.request("DELETE", endpoint, **kwargs)

    def patch(self, endpoint: str, **kwargs) -> Tuple[Optional[Dict[str, Any]], int]:
        """Make PATCH request"""
        return self.request("PATCH", endpoint, **kwargs)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get client performance metrics

        Returns:
            Dict with metrics
        """
        metrics = self.metrics.copy()

        # Calculate averages
        if metrics["total_requests"] > 0:
            metrics["average_latency"] = metrics["total_latency"] / metrics["total_requests"]
            metrics["success_rate"] = metrics["successful_requests"] / metrics["total_requests"]
        else:
            metrics["average_latency"] = 0
            metrics["success_rate"] = 0

        # Add circuit breaker state
        metrics["circuit_breaker_state"] = self.circuit_breaker.state

        # Add rate limiter info
        metrics["rate_limiter"] = {
            "current_rate": self.rate_limiter.rate,
            "available_tokens": self.rate_limiter.available_tokens,
        }

        return metrics

    def reset_metrics(self):
        """Reset performance metrics"""
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency": 0.0,
            "circuit_breaker_trips": 0,
            "rate_limit_throttles": 0,
        }

    def close(self):
        """Close HTTP session"""
        self.session.close()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
