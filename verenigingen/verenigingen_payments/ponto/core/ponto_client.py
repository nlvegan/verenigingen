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

import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

import frappe
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from verenigingen.integrations.mollie.utils.error_recovery import (
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
from verenigingen.verenigingen_payments.ponto.utils.token_manager import PontoTokenManager


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

    # Default retry configuration
    DEFAULT_RETRY_CONFIG = RetryConfig(
        max_attempts=3,
        base_delay=1.0,
        max_delay=30.0,
    )

    # Default circuit breaker configuration
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

        # mTLS configuration
        self._use_mtls = False
        self._cert_files: Optional[Tuple[str, str]] = None
        self._temp_cert_file: Optional[str] = None
        self._temp_key_file: Optional[str] = None

        # Check if mTLS is enabled
        self._setup_mtls()

    def _prepare_private_key(self, key_pem: str, passphrase: Optional[str] = None) -> bytes:
        """
        Prepare private key for use with requests library.

        If the key is encrypted and a passphrase is provided, decrypt it.
        The requests library cannot handle encrypted keys directly.

        Args:
            key_pem: PEM-encoded private key (possibly encrypted)
            passphrase: Passphrase for encrypted key (optional)

        Returns:
            bytes: Decrypted PEM-encoded private key
        """
        key_bytes = key_pem.encode("utf-8")

        # Check if key is encrypted (contains ENCRYPTED in header)
        if b"ENCRYPTED" in key_bytes and passphrase:
            # Decrypt the key
            password = passphrase.encode("utf-8") if passphrase else None
            private_key = load_pem_private_key(key_bytes, password=password)
            # Serialize back to unencrypted PEM
            return private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )

        # Key is not encrypted or no passphrase provided
        return key_bytes

    def _setup_mtls(self):
        """
        Set up mTLS certificate authentication if enabled.

        Reads certificate and private key from Ponto Settings and writes
        them to temporary files for use with requests library.
        """
        try:
            settings = frappe.get_single("Ponto Settings")
            if not settings.use_ibanity_mtls:
                return

            if not settings.ibanity_certificate or not settings.ibanity_private_key:
                frappe.logger().warning("mTLS enabled but certificate/key not configured")
                return

            self._use_mtls = True

            # Update base URL to Ibanity Ponto Connect API
            # The Ponto Connect endpoints are under /ponto-connect/ on api.ibanity.com
            ibanity_base = settings.ibanity_api_url or "https://api.ibanity.com"
            self.BASE_URL = f"{ibanity_base.rstrip('/')}/ponto-connect"

            # Write certificate and key to temporary files
            # (requests library requires file paths for client certificates)
            self._temp_cert_file = tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".pem",
                delete=False,
                prefix="ponto_cert_",
            )
            self._temp_cert_file.write(settings.ibanity_certificate.encode("utf-8"))
            self._temp_cert_file.close()

            self._temp_key_file = tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".pem",
                delete=False,
                prefix="ponto_key_",
            )
            # Decrypt passphrase-protected key if needed
            # requests library cannot handle encrypted keys directly
            key_content = self._prepare_private_key(
                settings.ibanity_private_key,
                settings.get_password("ibanity_key_passphrase"),
            )
            self._temp_key_file.write(key_content)
            self._temp_key_file.close()

            self._cert_files = (self._temp_cert_file.name, self._temp_key_file.name)

            frappe.logger().info(f"Ponto mTLS enabled, using {self.BASE_URL}")

        except Exception as e:
            frappe.logger().error(f"Failed to setup mTLS: {e}")
            self._use_mtls = False

    def __del__(self):
        """Clean up temporary certificate files on object destruction."""
        self._cleanup_temp_files()

    def _cleanup_temp_files(self):
        """Remove temporary certificate and key files."""
        for filepath in [self._temp_cert_file, self._temp_key_file]:
            if filepath:
                try:
                    name = filepath.name if hasattr(filepath, "name") else filepath
                    if isinstance(name, str) and os.path.exists(name):
                        os.unlink(name)
                except Exception as e:
                    frappe.logger().debug(f"Failed to cleanup temp file: {e}")

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
        error_message = f"Ponto API error on {endpoint}"

        try:
            data = response.json()
            if "errors" in data and data["errors"]:
                error = data["errors"][0]
                error_code = error.get("code")
                error_message = error.get("detail") or error.get("title") or error_message
                error_data = error
        except (ValueError, KeyError):
            error_message = response.text[:200] if response.text else error_message

        if status_code == 401:
            # Invalidate token and raise auth error
            self._token_manager.invalidate_token()
            raise PontoAuthenticationError(
                f"Ponto authentication failed: {error_message}",
                details={"endpoint": endpoint, "error": error_data},
            )

        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after and retry_after.isdigit() else None
            raise PontoRateLimitError(
                f"Ponto rate limit exceeded on {endpoint}",
                retry_after=retry_seconds,
                details={"endpoint": endpoint},
            )

        raise PontoAPIError(
            error_message,
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
            raise PontoAPIError(
                f"Failed to connect to Ponto API: {str(e)}",
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
            raise PontoAPIError(
                f"Failed to connect to Ponto API: {str(e)}",
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
            raise PontoAPIError(
                f"Failed to connect to Ponto API: {str(e)}",
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
                frappe.logger().info(f"Reached max pages ({max_pages}) for {endpoint}")
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
