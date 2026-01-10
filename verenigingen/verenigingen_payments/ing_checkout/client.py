# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Pay.nl API Client for ING Checkout Integration

This client handles all HTTP communication with the Pay.nl API,
including authentication, request signing, and error handling.

API Documentation: https://developer.pay.nl/docs/platform
"""

import base64
import json
from typing import Any, Optional

import frappe
import requests
from frappe import _
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from verenigingen.verenigingen_payments.core.resilience import (
    CircuitBreakerConfig,
    with_circuit_breaker,
)


class PayNLError(Exception):
    """Base exception for Pay.nl API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[dict] = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class PayNLAuthenticationError(PayNLError):
    """Authentication failed with Pay.nl API."""

    pass


class PayNLValidationError(PayNLError):
    """Validation error from Pay.nl API."""

    pass


class PayNLClient:
    """
    HTTP client for Pay.nl API (ING Checkout).

    Handles:
    - HTTP Basic Authentication with AT code and API token
    - Request/response JSON serialization
    - Error handling and retry logic
    - Sandbox/production environment switching

    Usage:
        client = PayNLClient()
        order = client.create_order({
            "serviceId": "SL-1234-5678",
            "amount": {"value": 2500, "currency": "EUR"},
            ...
        })
    """

    # API endpoints
    TGU_BASE_URL = "https://connect.pay.nl"  # Transaction Gateway (orders)
    GMS_BASE_URL = "https://rest.pay.nl"  # Global Management (refunds, mandates)

    # API versions
    TGU_VERSION = "v3"
    GMS_VERSION = "v2"

    # Timeout settings
    DEFAULT_TIMEOUT = 30  # seconds
    MAX_RETRIES = 3

    def __init__(self, settings: Optional["INGCheckoutSettings"] = None):
        """
        Initialize the Pay.nl API client.

        Args:
            settings: Optional INGCheckoutSettings document.
                      If not provided, will be fetched from database.
        """
        self._settings = settings
        self._session = None

    @property
    def settings(self):
        """Lazy load settings if not provided."""
        if self._settings is None:
            from verenigingen.verenigingen_payments.doctype.ing_checkout_settings.ing_checkout_settings import (
                get_ing_checkout_settings,
            )

            self._settings = get_ing_checkout_settings()
        return self._settings

    @property
    def session(self) -> requests.Session:
        """Get or create a requests session with authentication and retry logic."""
        if self._session is None:
            self._session = requests.Session()

            # Configure retry strategy for transient failures
            retry_strategy = Retry(
                total=self.MAX_RETRIES,
                backoff_factor=1,  # 1s, 2s, 4s exponential backoff
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST", "PUT", "DELETE"],
                raise_on_status=False,  # We handle status codes ourselves
            )
            adapter = HTTPAdapter(max_retries=retry_strategy)
            self._session.mount("https://", adapter)
            self._session.mount("http://", adapter)

            self._session.headers.update(
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "Verenigingen-INGCheckout/1.0",
                }
            )
            # Set up HTTP Basic Auth
            credentials = self.settings.get_api_credentials()
            auth_string = f"{credentials['token_code']}:{credentials['api_token']}"
            auth_bytes = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
            self._session.headers["Authorization"] = f"Basic {auth_bytes}"

        return self._session

    def _make_request(
        self,
        method: str,
        url: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> dict:
        """
        Make an HTTP request to the Pay.nl API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            url: Full URL to request
            data: Request body data (will be JSON encoded)
            params: Query parameters
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            PayNLError: On API errors
            PayNLAuthenticationError: On authentication failures
            PayNLValidationError: On validation errors
        """
        timeout = timeout or self.DEFAULT_TIMEOUT

        try:
            response = self.session.request(
                method=method,
                url=url,
                json=data,
                params=params,
                timeout=timeout,
            )

            # Log request/response for debugging
            self._log_request(method, url, data, response)

            # Handle response
            return self._handle_response(response)

        except requests.exceptions.Timeout:
            raise PayNLError(_("Request to Pay.nl timed out"))
        except requests.exceptions.ConnectionError:
            raise PayNLError(_("Failed to connect to Pay.nl API"))
        except requests.exceptions.RequestException as e:
            raise PayNLError(_("Request to Pay.nl failed: {0}").format(str(e)))

    def _handle_response(self, response: requests.Response) -> dict:
        """
        Handle API response and raise appropriate exceptions.

        Args:
            response: requests Response object

        Returns:
            Parsed JSON response data

        Raises:
            PayNLError: On API errors
        """
        try:
            data = response.json() if response.text else {}
        except json.JSONDecodeError:
            data = {"raw_response": response.text}

        if response.status_code == 401:
            raise PayNLAuthenticationError(
                _("Authentication failed. Check your API credentials."),
                status_code=401,
                response=data,
            )

        if response.status_code == 403:
            raise PayNLAuthenticationError(
                _("Access denied. Check your permissions."),
                status_code=403,
                response=data,
            )

        if response.status_code == 422:
            # Validation error
            error_message = data.get("message", _("Validation error"))
            if "violations" in data:
                violations = data["violations"]
                error_details = ", ".join(
                    f"{v.get('propertyPath', 'unknown')}: {v.get('message', 'invalid')}" for v in violations
                )
                error_message = f"{error_message}: {error_details}"
            raise PayNLValidationError(error_message, status_code=422, response=data)

        if response.status_code >= 400:
            error_message = data.get("message") or data.get("error") or _("API request failed")
            raise PayNLError(error_message, status_code=response.status_code, response=data)

        return data

    def _log_request(
        self,
        method: str,
        url: str,
        data: Optional[dict],
        response: requests.Response,
    ):
        """Log API request for debugging."""
        # Only log in development/debug mode
        if not frappe.conf.get("developer_mode"):
            return

        frappe.log_error(
            title="Pay.nl API Request",
            message=json.dumps(
                {
                    "method": method,
                    "url": url,
                    "request_data": data,
                    "status_code": response.status_code,
                    "response_text": response.text[:1000] if response.text else None,
                },
                indent=2,
                default=str,
            ),
        )

    # ==========================================
    # Order API (TGU - connect.pay.nl)
    # ==========================================

    @with_circuit_breaker("paynl_orders", CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60))
    def create_order(self, order_data: dict) -> dict:
        """
        Create a new payment order.

        Protected by circuit breaker to prevent cascading failures.

        Args:
            order_data: Order data including:
                - serviceId: Service ID (SL-xxxx-xxxx)
                - amount: {"value": int (cents), "currency": "EUR"}
                - description: Payment description
                - reference: Merchant order reference
                - returnUrl: URL to redirect after payment
                - exchangeUrl: Webhook URL for status updates
                - paymentMethod: {"id": int} (10 = iDEAL)

        Returns:
            Order response with id, status, and links

        Example:
            order = client.create_order({
                "serviceId": "SL-1234-5678",
                "amount": {"value": 2500, "currency": "EUR"},
                "description": "Membership fee",
                "reference": "INV-2025-001",
                "returnUrl": "https://example.com/thanks",
                "exchangeUrl": "https://example.com/webhook",
                "paymentMethod": {"id": 10}
            })
            # Redirect user to order["links"]["redirect"]
        """
        url = f"{self.TGU_BASE_URL}/{self.TGU_VERSION}/orders"
        return self._make_request("POST", url, data=order_data)

    def get_order(self, order_id: str) -> dict:
        """
        Get order details by ID.

        Args:
            order_id: Pay.nl order ID (EX-xxxx-xxxx-xxxx)

        Returns:
            Order details including status
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/orders/{order_id}"
        return self._make_request("GET", url)

    # ==========================================
    # Direct Debit API (GMS - rest.pay.nl)
    # ==========================================

    @with_circuit_breaker("paynl_mandates", CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60))
    def create_mandate(self, mandate_data: dict) -> dict:
        """
        Create a SEPA Direct Debit mandate.

        Protected by circuit breaker to prevent cascading failures.

        Args:
            mandate_data: Mandate data including:
                - serviceId: Service ID
                - type: "single", "recurring", or "flexible"
                - amount: {"value": int, "currency": "EUR"}
                - description: Mandate description
                - debtor: {"iban": str, "name": str, "email": str}
                - termsAndConditionsUrl: URL to T&C page
                - exchangeUrl: Webhook URL

        Returns:
            Mandate response with mandateId and status
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits/mandates"
        return self._make_request("POST", url, data=mandate_data)

    def get_mandate(self, mandate_id: str) -> dict:
        """
        Get mandate details by ID.

        Args:
            mandate_id: Pay.nl mandate ID (IO-xxxx-xxxx-xxxx)

        Returns:
            Mandate details including status
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits/mandates/{mandate_id}"
        return self._make_request("GET", url)

    def list_mandates(self, service_id: str = None, status: str = None, limit: int = 50) -> dict:
        """
        List mandates with optional filtering.

        Args:
            service_id: Optional service ID filter
            status: Optional status filter (pending, active, cancelled, etc.)
            limit: Maximum number of results

        Returns:
            List of mandates
        """
        params = {"limit": limit}
        if service_id:
            params["serviceId"] = service_id
        if status:
            params["status"] = status

        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits/mandates"
        return self._make_request("GET", url, params=params)

    def cancel_mandate(self, mandate_id: str) -> dict:
        """
        Cancel an active mandate.

        Args:
            mandate_id: Pay.nl mandate ID (IO-xxxx-xxxx-xxxx)

        Returns:
            Cancellation confirmation
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits/mandates/{mandate_id}/cancel"
        return self._make_request("POST", url)

    @with_circuit_breaker("paynl_directdebits", CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60))
    def create_direct_debit(self, debit_data: dict) -> dict:
        """
        Execute a direct debit on an existing mandate.

        Protected by circuit breaker to prevent cascading failures.

        Args:
            debit_data: Direct debit data including:
                - mandateId: Mandate ID (IO-xxxx)
                - amount: {"value": int, "currency": "EUR"}
                - description: Debit description
                - processDate: Optional date to process (YYYY-MM-DD)

        Returns:
            Direct debit response with referenceId and status
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits"
        return self._make_request("POST", url, data=debit_data)

    def get_direct_debit(self, reference_id: str) -> dict:
        """
        Get direct debit details by reference ID.

        Args:
            reference_id: Pay.nl direct debit reference (IL-xxxx)

        Returns:
            Direct debit details including status
        """
        url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/directdebits/{reference_id}"
        return self._make_request("GET", url)

    # ==========================================
    # Utility Methods
    # ==========================================

    def test_connection(self) -> dict:
        """
        Test the API connection and credentials.

        Returns:
            dict with success status and message
        """
        try:
            # Try to fetch service config to validate credentials
            credentials = self.settings.get_api_credentials()
            url = f"{self.GMS_BASE_URL}/{self.GMS_VERSION}/services/{credentials['service_id']}/config"
            result = self._make_request("GET", url)
            return {
                "success": True,
                "message": _("Connection successful"),
                "service_name": result.get("name", "Unknown"),
            }
        except PayNLAuthenticationError as e:
            return {
                "success": False,
                "message": _("Authentication failed: {0}").format(str(e)),
            }
        except PayNLError as e:
            return {
                "success": False,
                "message": _("Connection failed: {0}").format(str(e)),
            }


def get_client(settings: Optional["INGCheckoutSettings"] = None) -> PayNLClient:
    """
    Get a configured Pay.nl API client.

    Args:
        settings: Optional settings document

    Returns:
        Configured PayNLClient instance
    """
    return PayNLClient(settings=settings)
