"""
E-Boekhouden HTTP Client Mixin

This module provides a mixin class with common HTTP functionality for all
e-Boekhouden API clients. It consolidates token management, retry logic,
and error handling to ensure consistent behavior across different clients.

The mixin is designed to be inherited by concrete client classes:
- EBoekhoudenRESTClient (main migration client)
- EBoekhoudenRESTIterator (ID-based iteration)
- EBoekhoudenAPI (general API access)

Key Features:
- Session token caching with automatic expiry tracking (55-minute TTL)
- Automatic token refresh on 401/403 responses
- Exponential backoff retry for transient errors (429, 5xx)
- Retry-After header support for rate limiting
- Thread-safe token management
- Metrics collection for monitoring
- Consistent error handling and logging
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

import frappe
import requests
from requests.exceptions import ConnectionError, RequestException, Timeout


@dataclass
class HTTPClientMetrics:
    """
    Metrics for HTTP client operations.

    Provides visibility into API behavior during migrations and normal operations.
    All counters are cumulative within a client instance lifetime.
    """

    requests_total: int = 0
    requests_success: int = 0
    requests_failed: int = 0
    retries_total: int = 0
    token_refreshes: int = 0
    rate_limits_hit: int = 0

    def to_dict(self) -> Dict[str, int]:
        """Return metrics as dictionary for logging/monitoring."""
        return {
            "requests_total": self.requests_total,
            "requests_success": self.requests_success,
            "requests_failed": self.requests_failed,
            "retries_total": self.retries_total,
            "token_refreshes": self.token_refreshes,
            "rate_limits_hit": self.rate_limits_hit,
        }


class EBoekhoudenHTTPClientMixin:
    """
    Mixin providing common HTTP functionality for e-Boekhouden API clients.

    This mixin provides:
    - Token caching with automatic expiry tracking
    - Retry mechanism with exponential backoff for transient errors
    - Automatic token refresh on authentication failures
    - Retry-After header support for rate limiting
    - Thread-safe token management for concurrent operations
    - Metrics collection for monitoring and diagnostics
    - Consistent error handling patterns

    Usage:
        class MyClient(EBoekhoudenHTTPClientMixin):
            def __init__(self, settings=None):
                self._init_http_client(settings)

            def my_api_method(self):
                response = self._request_with_retry("GET", f"{self.base_url}/v1/endpoint")
                return response.json()

    Attributes:
        TOKEN_TTL_MINUTES: Token lifetime (55 min, safety margin from 60 min expiry)
        MAX_RETRIES: Maximum retry attempts for transient errors
        RETRY_BACKOFF_FACTOR: Base delay for exponential backoff (seconds)
        MAX_RETRY_DELAY: Maximum delay between retries (seconds)
        RETRY_STATUS_CODES: HTTP status codes that trigger retry
        AUTH_REFRESH_STATUS_CODES: HTTP status codes that trigger token refresh
        metrics: HTTPClientMetrics instance for monitoring
    """

    # Token lifetime configuration
    # e-Boekhouden tokens expire after ~60 minutes; use 55 minutes for safety margin
    TOKEN_TTL_MINUTES = 55

    # Retry configuration for transient errors
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 1.0  # Base delay in seconds (1s, 2s, 4s with exponential backoff)
    MAX_RETRY_DELAY = 60.0  # Cap retry delay at 60 seconds
    RETRY_STATUS_CODES = (429, 500, 502, 503, 504)  # Status codes that trigger retry
    AUTH_REFRESH_STATUS_CODES = (401, 403)  # Status codes that trigger token refresh

    def _init_http_client(self, settings=None) -> None:
        """
        Initialize HTTP client settings.

        This method should be called in the __init__ of classes using this mixin.

        Args:
            settings: E-Boekhouden Settings document, or None to load automatically

        Raises:
            ValueError: If API token is not configured
        """
        if not settings:
            settings = frappe.get_single("E-Boekhouden Settings")

        self.settings = settings
        self.base_url = settings.api_url if hasattr(settings, "api_url") else "https://api.e-boekhouden.nl"

        # Ensure base_url has proper scheme
        if self.base_url and not self.base_url.startswith(("http://", "https://")):
            self.base_url = f"https://{self.base_url}"

        self.base_url = self.base_url.rstrip("/")  # Remove trailing slash

        self.api_token = settings.get_password("api_token") if hasattr(settings, "api_token") else None

        if not self.api_token:
            raise ValueError("API token is required for REST API access")

        # Session token will be obtained on first use
        self._session_token = None
        self._token_obtained_at = None  # Track when token was acquired for expiry

        # Thread safety: lock for token operations
        self._token_lock = threading.Lock()

        # Metrics for monitoring
        self.metrics = HTTPClientMetrics()

    def _token_is_expired(self) -> bool:
        """
        Check if the cached session token has expired.

        Uses TOKEN_TTL_MINUTES to determine if the token is still valid.
        e-Boekhouden tokens typically expire after ~60 minutes; we use
        55 minutes as a safety margin to avoid mid-request expiry.

        Returns:
            bool: True if token is expired or missing, False if still valid
        """
        if not self._session_token or not self._token_obtained_at:
            return True

        expiry_time = self._token_obtained_at + timedelta(minutes=self.TOKEN_TTL_MINUTES)
        is_expired = datetime.now() >= expiry_time

        if is_expired:
            frappe.logger().debug(
                f"E-Boekhouden token expired (obtained at {self._token_obtained_at}, "
                f"TTL={self.TOKEN_TTL_MINUTES}min)"
            )

        return is_expired

    def _get_session_token(self) -> Optional[str]:
        """
        Obtain and cache session token for API authentication.

        Session tokens are required for all REST API calls and have a limited
        lifetime (~60 minutes). This method handles token acquisition, caching,
        and automatic refresh when the token expires.

        Thread-safe: Uses lock to prevent concurrent token refresh attempts.

        Returns:
            str: Valid session token for API requests
            None: If authentication fails

        Raises:
            ValueError: If API token is not configured
        """
        with self._token_lock:
            # Return cached token if still valid (check inside lock to avoid race)
            if not self._token_is_expired():
                return self._session_token

            try:
                session_url = f"{self.base_url}/v1/session"
                source = getattr(self.settings, "source_application", None) or "Verenigingen ERPNext"
                session_data = {
                    "accessToken": self.api_token,
                    "source": source,
                }

                response = requests.post(session_url, json=session_data, timeout=30)

                if response.status_code == 200:
                    session_response = response.json()
                    self._session_token = session_response.get("token")
                    self._token_obtained_at = datetime.now()
                    self.metrics.token_refreshes += 1

                    frappe.logger().debug(f"E-Boekhouden session token acquired at {self._token_obtained_at}")

                    return self._session_token
                else:
                    frappe.log_error(
                        f"Session token request failed: {response.status_code} - {response.text}",
                        "E-Boekhouden REST",
                    )
                    return None

            except Exception as e:
                frappe.log_error(f"Error getting session token: {str(e)}", "E-Boekhouden REST")
                return None

    def invalidate_token(self) -> None:
        """
        Invalidate the cached session token, forcing refresh on next request.

        Thread-safe: Uses lock to prevent race conditions during invalidation.

        Use this method when:
        - A 401/403 response indicates the token may be invalid
        - You need to force a fresh token for testing
        - Recovering from API errors that may be token-related
        """
        with self._token_lock:
            if self._session_token:
                frappe.logger().debug("E-Boekhouden session token invalidated")
            self._session_token = None
            self._token_obtained_at = None

    def _get_headers(self) -> Dict[str, str]:
        """
        Build HTTP headers for authenticated API requests.

        Returns:
            dict: Headers including authorization token and content type

        Raises:
            ValueError: If session token cannot be obtained
        """
        token = self._get_session_token()
        if not token:
            raise ValueError("Failed to obtain session token")

        return {
            "Authorization": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _get_retry_delay(self, response: Optional[requests.Response], attempt: int) -> float:
        """
        Calculate retry delay, preferring Retry-After header if present.

        The Retry-After header (from 429 responses) tells us exactly how long
        to wait. When present, we use it instead of calculated exponential backoff.

        Args:
            response: HTTP response (may contain Retry-After header)
            attempt: Current retry attempt number (0-indexed)

        Returns:
            float: Delay in seconds before next retry
        """
        # Check for Retry-After header if response is available
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    # Try parsing as seconds (most common format)
                    delay = float(retry_after)
                    # Cap at MAX_RETRY_DELAY to prevent excessive waits
                    return min(delay, self.MAX_RETRY_DELAY)
                except ValueError:
                    # Could be HTTP date format, fall through to default
                    pass

        # Default: exponential backoff with cap
        delay = self.RETRY_BACKOFF_FACTOR * (2**attempt)
        return min(delay, self.MAX_RETRY_DELAY)

    def get_metrics(self) -> Dict[str, int]:
        """
        Return current metrics for monitoring.

        Returns:
            dict: Current metric values
        """
        return self.metrics.to_dict()

    def reset_metrics(self) -> None:
        """Reset all metrics counters to zero."""
        self.metrics = HTTPClientMetrics()

    def _request_with_retry(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: int = 30,
    ) -> requests.Response:
        """
        Make HTTP request with automatic retry and token refresh.

        This method handles:
        - Exponential backoff retry for transient errors (429, 5xx)
        - Retry-After header support for rate limiting
        - Automatic token refresh on 401/403 responses
        - Timeout and connection error handling
        - Metrics collection for monitoring

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL for the request
            params: Query parameters for GET requests
            json_data: JSON body for POST requests
            timeout: Request timeout in seconds

        Returns:
            requests.Response: The HTTP response object

        Raises:
            RequestException: If all retries are exhausted
            ValueError: If session token cannot be obtained
        """
        last_exception = None
        response = None
        headers = self._get_headers()
        self.metrics.requests_total += 1

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                if method.upper() == "GET":
                    response = requests.get(url, headers=headers, params=params, timeout=timeout)
                elif method.upper() == "POST":
                    response = requests.post(url, headers=headers, json=json_data, timeout=timeout)
                else:
                    response = requests.request(
                        method, url, headers=headers, params=params, json=json_data, timeout=timeout
                    )

                # Handle authentication errors with token refresh
                if response.status_code in self.AUTH_REFRESH_STATUS_CODES:
                    if attempt == 0:  # Only try token refresh once
                        frappe.logger().info(
                            f"E-Boekhouden API returned {response.status_code}, refreshing token..."
                        )
                        self.invalidate_token()
                        headers = self._get_headers()  # Get fresh headers with new token
                        self.metrics.retries_total += 1
                        continue  # Retry with new token

                # Handle retryable errors with backoff (respects Retry-After header)
                if response.status_code in self.RETRY_STATUS_CODES:
                    if response.status_code == 429:
                        self.metrics.rate_limits_hit += 1

                    if attempt < self.MAX_RETRIES:
                        delay = self._get_retry_delay(response, attempt)
                        frappe.logger().warning(
                            f"E-Boekhouden API returned {response.status_code}, "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                        )
                        time.sleep(delay)
                        self.metrics.retries_total += 1
                        continue

                # Success or non-retryable error
                if response.status_code == 200:
                    self.metrics.requests_success += 1
                else:
                    self.metrics.requests_failed += 1

                return response

            except (Timeout, ConnectionError) as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    delay = self._get_retry_delay(None, attempt)
                    error_type = "Timeout" if isinstance(e, Timeout) else "Connection error"
                    frappe.logger().warning(
                        f"E-Boekhouden API {error_type}, "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(delay)
                    self.metrics.retries_total += 1
                    continue
                self.metrics.requests_failed += 1
                raise

            except RequestException as e:
                # Non-retryable request errors
                self.metrics.requests_failed += 1
                frappe.log_error(f"E-Boekhouden API request failed: {str(e)}", "E-Boekhouden REST")
                raise

        # If we get here, all retries were exhausted
        self.metrics.requests_failed += 1
        if last_exception:
            raise last_exception

        return response

    def _make_simple_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Tuple[bool, Any, int]:
        """
        Make HTTP request and return simplified result tuple.

        This is a convenience wrapper around _request_with_retry that returns
        a consistent tuple format for backward compatibility.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL for the request
            params: Query parameters for GET requests
            json_data: JSON body for POST requests
            timeout: Request timeout in seconds

        Returns:
            Tuple of (success: bool, data: Any, status_code: int)
            - On success: (True, response_text, 200)
            - On failure: (False, error_message, status_code)
        """
        try:
            response = self._request_with_retry(method, url, params, json_data, timeout)

            if response.status_code == 200:
                return True, response.text, response.status_code
            else:
                return False, f"HTTP {response.status_code}: {response.text[:500]}", response.status_code

        except Timeout:
            return False, "Request timeout - API call took too long", 0
        except ConnectionError:
            return False, "Connection error - could not reach API", 0
        except RequestException as e:
            return False, str(e), 0
        except ValueError as e:
            # Token acquisition failure
            return False, str(e), 0
