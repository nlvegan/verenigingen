# Copyright (c) 2025, Vegan Netwerk Nederland and contributors
# For license information, please see license.txt

"""
Ponto REST API Client

Low-level HTTP client for Ponto API with OAuth2 authentication,
circuit breaker protection, and retry logic.

Usage:
    from verenigingen.verenigingen_payments.ponto.core.ponto_client import (
        PontoClient,
        get_ponto_client,
    )

    client = get_ponto_client()
    accounts = client.get("/accounts")
    transactions = client.get_paginated("/accounts/{id}/transactions")
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
import requests

from verenigingen.utils.error_handling import sanitize_error_for_display
from verenigingen.verenigingen_payments.core.resilience import (
    CircuitBreakerConfig,
    RetryConfig,
    with_circuit_breaker,
    with_retry,
)
from verenigingen.verenigingen_payments.ponto.exceptions import (
    PontoAPIError,
    PontoAuthenticationError,
    PontoRateLimitError,
)
from verenigingen.verenigingen_payments.ponto.services.configuration_service import get_ponto_config
from verenigingen.verenigingen_payments.ponto.utils.secure_cert_manager import SecureCertManager
from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager


def _sanitize_error_message(detailed_message: str, generic_message: str) -> str:
    """
    Return appropriate error message based on user permissions.

    Uses centralized sanitize_error_for_display utility for role-based
    error message display.

    Args:
        detailed_message: Full technical error message for admins
        generic_message: User-friendly message for regular users

    Returns:
        str: Appropriate message based on user role
    """
    return sanitize_error_for_display(detailed_message, generic_message)


class PontoClient:
    """
    Low-level REST client for Ponto API.

    Handles:
    - OAuth2 authentication via PontoTokenManager
    - JSON:API content type headers
    - Circuit breaker protection for API failures
    - Retry logic for transient errors
    - Cursor-based pagination

    Attributes:
        BASE_URL: Ponto API base URL
    """

    BASE_URL = "https://api.myponto.com"

    # Retry configuration for transient failures (network timeouts, 5xx errors)
    # - max_attempts: 3 retries balances reliability vs latency
    # - base_delay: 1 second initial backoff
    # - max_delay: 30 seconds cap to prevent excessive waits
    DEFAULT_RETRY_CONFIG = RetryConfig(
        max_attempts=3,
        base_delay=1.0,
        max_delay=30.0,
    )

    # Circuit breaker protects against cascading failures when Ponto API is down
    # - failure_threshold: 5 failures before opening circuit (prevents hammering)
    # - recovery_timeout: 60 seconds before allowing test request
    # - success_threshold: 3 successes needed to close circuit
    DEFAULT_CIRCUIT_CONFIG = CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60,
        success_threshold=3,
    )

    def __init__(self, token_manager: Optional[PontoTokenManager] = None):
        """
        Initialize Ponto client.

        Args:
            token_manager: Optional token manager instance (creates new if not provided)
        """
        self._token_manager = token_manager or PontoTokenManager()
        self._session = requests.Session()
        self._config = get_ponto_config()

        # mTLS configuration using SecureCertManager
        self._use_mtls = False
        self._cert_files: Optional[Tuple[str, str]] = None
        self._cert_manager: Optional[SecureCertManager] = None

        # Check if mTLS is enabled
        self._setup_mtls()

    def _setup_mtls(self):
        """
        Set up mTLS certificate authentication if enabled.

        Uses SecureCertManager for secure certificate file handling.
        """
        try:
            settings = frappe.get_single("Ponto Settings")
            if not settings.use_ibanity_mtls:
                return

            # Use SecureCertManager for certificate handling
            self._cert_manager = SecureCertManager()
            if not self._cert_manager.setup_from_settings():
                self._cert_manager = None
                return

            self._use_mtls = True
            self._cert_files = self._cert_manager.get_cert_files()

            # Update base URL to Ibanity Ponto Connect API
            ibanity_base = settings.ibanity_api_url or "https://api.ibanity.com"
            self.BASE_URL = f"{ibanity_base.rstrip('/')}/ponto-connect"

            frappe.logger().info(f"Ponto mTLS enabled, using {self.BASE_URL}")

        except Exception as e:
            frappe.logger().error(f"Failed to setup mTLS: {e}")
            self._use_mtls = False
            if self._cert_manager:
                self._cert_manager._cleanup()
                self._cert_manager = None

    def __del__(self):
        """Clean up certificate files on object destruction."""
        if self._cert_manager:
            self._cert_manager._cleanup()
            self._cert_manager = None

    def _get_headers(self) -> Dict[str, str]:
        """
        Get HTTP headers with OAuth2 token.

        Returns:
            Dict with Authorization and JSON:API content type headers
        """
        return {
            "Authorization": f"Bearer {self._token_manager.get_valid_token()}",
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
        }

    def _handle_error_response(self, response: requests.Response, endpoint: str):
        """
        Handle error responses from Ponto API.

        Error messages are sanitized based on user permissions:
        - System Managers see detailed technical information
        - Regular users see generic, user-friendly messages

        Detailed errors are always logged for debugging.

        Args:
            response: HTTP response object
            endpoint: API endpoint for error context

        Raises:
            PontoAuthenticationError: For 401 errors
            PontoRateLimitError: For 429 errors
            PontoAPIError: For other error responses
        """
        status_code = response.status_code

        # Try to parse JSON:API error response
        error_data = {}
        error_code = None
        detailed_message = f"Ponto API error on {endpoint}"

        try:
            data = response.json()
            if "errors" in data and data["errors"]:
                error = data["errors"][0]
                error_code = error.get("code")
                detailed_message = error.get("detail") or error.get("title") or detailed_message
                error_data = error
        except (ValueError, KeyError):
            detailed_message = response.text[:200] if response.text else detailed_message

        # Always log detailed error for debugging (admin-visible in Error Log)
        frappe.logger().error(
            f"Ponto API error: status={status_code}, endpoint={endpoint}, "
            f"message={detailed_message}, code={error_code}"
        )

        if status_code == 401:
            # Invalidate token and raise auth error
            self._token_manager.invalidate_token()
            user_message = _sanitize_error_message(
                f"Ponto authentication failed: {detailed_message}",
                "Bank connection authentication failed. Please contact support.",
            )
            raise PontoAuthenticationError(
                user_message,
                details={"endpoint": endpoint, "error": error_data},
            )

        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
            user_message = _sanitize_error_message(
                f"Ponto rate limit exceeded on {endpoint}",
                "Too many requests. Please try again in a few minutes.",
            )
            raise PontoRateLimitError(
                user_message,
                retry_after=retry_seconds,
                details={"endpoint": endpoint},
            )

        user_message = _sanitize_error_message(
            detailed_message,
            "An error occurred while communicating with the bank. Please try again later.",
        )
        raise PontoAPIError(
            user_message,
            status_code=status_code,
            error_code=error_code,
            details={"endpoint": endpoint, "response": error_data},
        )

    @with_circuit_breaker("ponto_api", DEFAULT_CIRCUIT_CONFIG)
    @with_retry(DEFAULT_RETRY_CONFIG, "ponto_request")
    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make GET request to Ponto API.

        Args:
            endpoint: API endpoint (e.g., "/accounts")
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            Dict with JSON response data

        Raises:
            PontoAPIError: For API errors
            PontoAuthenticationError: For auth failures
            PontoRateLimitError: For rate limiting
        """
        url = f"{self.BASE_URL}{endpoint}" if endpoint.startswith("/") else endpoint

        frappe.logger().debug(f"Ponto GET: {url} (mTLS: {self._use_mtls})")

        try:
            # Build request kwargs
            request_kwargs = {
                "headers": self._get_headers(),
                "params": params,
                "timeout": timeout,
            }
            # Add client certificate for mTLS
            if self._use_mtls and self._cert_files:
                request_kwargs["cert"] = self._cert_files

            response = self._session.get(url, **request_kwargs)
        except requests.RequestException as e:
            frappe.logger().error(f"Ponto request failed: {e}")
            user_message = _sanitize_error_message(
                f"Failed to connect to Ponto API: {str(e)}",
                "Unable to connect to the bank service. Please try again later.",
            )
            raise PontoAPIError(
                user_message,
                details={"endpoint": endpoint, "error": str(e)},
            )

        if not response.ok:
            self._handle_error_response(response, endpoint)

        return response.json()

    @with_circuit_breaker("ponto_api", DEFAULT_CIRCUIT_CONFIG)
    @with_retry(DEFAULT_RETRY_CONFIG, "ponto_request")
    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make POST request to Ponto API.

        Args:
            endpoint: API endpoint
            data: Request body (JSON:API format)
            timeout: Request timeout in seconds

        Returns:
            Dict with JSON response data

        Raises:
            PontoAPIError: For API errors
        """
        url = f"{self.BASE_URL}{endpoint}" if endpoint.startswith("/") else endpoint

        frappe.logger().debug(f"Ponto POST: {url} (mTLS: {self._use_mtls})")

        try:
            # Build request kwargs
            request_kwargs = {
                "headers": self._get_headers(),
                "json": data,
                "timeout": timeout,
            }
            # Add client certificate for mTLS
            if self._use_mtls and self._cert_files:
                request_kwargs["cert"] = self._cert_files

            response = self._session.post(url, **request_kwargs)
        except requests.RequestException as e:
            frappe.logger().error(f"Ponto request failed: {e}")
            user_message = _sanitize_error_message(
                f"Failed to connect to Ponto API: {str(e)}",
                "Unable to connect to the bank service. Please try again later.",
            )
            raise PontoAPIError(
                user_message,
                details={"endpoint": endpoint, "error": str(e)},
            )

        if not response.ok:
            self._handle_error_response(response, endpoint)

        # POST may return 201 with empty body
        if response.status_code == 201 and not response.text:
            return {}

        return response.json()

    @with_circuit_breaker("ponto_api", DEFAULT_CIRCUIT_CONFIG)
    @with_retry(DEFAULT_RETRY_CONFIG, "ponto_request")
    def delete(
        self,
        endpoint: str,
        timeout: int = 30,
    ) -> bool:
        """
        Make DELETE request to Ponto API.

        Args:
            endpoint: API endpoint
            timeout: Request timeout in seconds

        Returns:
            True if successful (204 No Content)

        Raises:
            PontoAPIError: For API errors
        """
        url = f"{self.BASE_URL}{endpoint}" if endpoint.startswith("/") else endpoint

        frappe.logger().debug(f"Ponto DELETE: {url} (mTLS: {self._use_mtls})")

        try:
            # Build request kwargs
            request_kwargs = {
                "headers": self._get_headers(),
                "timeout": timeout,
            }
            # Add client certificate for mTLS
            if self._use_mtls and self._cert_files:
                request_kwargs["cert"] = self._cert_files

            response = self._session.delete(url, **request_kwargs)
        except requests.RequestException as e:
            frappe.logger().error(f"Ponto request failed: {e}")
            user_message = _sanitize_error_message(
                f"Failed to connect to Ponto API: {str(e)}",
                "Unable to connect to the bank service. Please try again later.",
            )
            raise PontoAPIError(
                user_message,
                details={"endpoint": endpoint, "error": str(e)},
            )

        if not response.ok:
            self._handle_error_response(response, endpoint)

        return True

    def get_paginated(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        max_pages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch all pages from a paginated endpoint.

        Uses cursor-based pagination via JSON:API links.

        Args:
            endpoint: API endpoint
            params: Initial query parameters
            limit: Items per page (default 100)
            max_pages: Maximum pages to fetch (None for unlimited)

        Returns:
            List of all data items across all pages

        Raises:
            PontoAPIError: For API errors
        """
        results = []
        current_url = endpoint
        current_params = params.copy() if params else {}
        current_params["limit"] = limit
        page_count = 0

        while current_url:
            if max_pages and page_count >= max_pages:
                frappe.logger().debug(f"Reached max pages ({max_pages}) for {endpoint}")
                break

            # First request uses params, subsequent use full URL from links.next
            if page_count == 0:
                data = self.get(current_url, params=current_params)
            else:
                # links.next includes all params
                data = self.get(current_url)

            results.extend(data.get("data", []))
            page_count += 1

            # Get next page URL from JSON:API links
            links = data.get("links", {})
            current_url = links.get("next")

            frappe.logger().debug(
                f"Fetched page {page_count}, items: {len(data.get('data', []))}, "
                f"total so far: {len(results)}"
            )

        return results


def get_ponto_client() -> PontoClient:
    """
    Factory function to get PontoClient instance.

    Returns:
        PontoClient: Client instance ready for API calls
    """
    return PontoClient()
