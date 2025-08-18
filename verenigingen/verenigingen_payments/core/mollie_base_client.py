"""
Mollie API Base Client
Foundation client for all Mollie backend API operations

Features:
- Authentication management
- Request signing
- Response validation
- Error handling
- API versioning
"""

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import frappe
import requests
from frappe import _

from .compliance.audit_trail import AuditEventType, AuditSeverity, get_audit_trail
from .compliance.financial_validator import FinancialValidator
from .http_client import ResilientHTTPClient
from .security.mollie_security_manager import MollieSecurityManager


class MollieAPIError(Exception):
    """Custom exception for Mollie API errors"""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[Dict] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


class MollieBaseClient:
    """
    Base client for Mollie backend API operations

    Provides:
    - Authenticated API requests
    - Automatic pagination handling
    - Response validation
    - Error mapping
    - Audit logging
    """

    # API endpoints
    BASE_URL = "https://api.mollie.com/v2/"

    # API versions
    API_VERSION = "v2"

    def __init__(self, api_key: Optional[str] = None, test_mode: bool = False, use_backend_api: bool = True):
        """
        Initialize Mollie base client

        Args:
            api_key: Mollie API key (if not provided, fetched from settings)
            test_mode: Whether to use test mode (only applies to payment API, not backend API)
            use_backend_api: If True, use Organization Access Token for backend features
        """
        # Get settings (singleton)
        self.mollie_settings = frappe.get_single("Mollie Settings")

        # Get API key from settings if not provided
        if not api_key:
            if use_backend_api:
                api_key = self._get_backend_api_key()
            else:
                api_key = self._get_api_key_from_settings(test_mode)

        self.api_key = api_key
        self.test_mode = test_mode
        self.use_backend_api = use_backend_api

        # Initialize components
        self.http_client = ResilientHTTPClient(
            base_url=self.BASE_URL,
            timeout=30,
            max_retries=3,
            rate_limit=10,  # Mollie rate limit
            circuit_breaker_threshold=5,
        )

        self.security_manager = MollieSecurityManager(self.mollie_settings)
        self.financial_validator = FinancialValidator()
        self.audit_trail = get_audit_trail()

        # Set authentication header
        self.http_client.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _get_api_key_from_settings(self, test_mode: bool) -> str:
        """
        Get API key from Mollie Settings (for payment API, not backend API)

        Args:
            test_mode: Whether to use test mode

        Returns:
            API key string
        """
        try:
            # Use the settings we already loaded
            settings = self.mollie_settings

            if not settings:
                raise frappe.ValidationError(_("Mollie Settings not configured"))

            # Get the appropriate key
            if test_mode:
                # Use test key (should start with test_)
                api_key = settings.get_password("test_api_key", raise_exception=False)
                if not api_key:
                    api_key = settings.get_password("secret_key", raise_exception=False)
            else:
                # Use live key (should start with live_)
                api_key = settings.get_password("live_api_key", raise_exception=False)
                if not api_key:
                    api_key = settings.get_password("secret_key", raise_exception=False)

            if not api_key:
                raise frappe.ValidationError(_("Mollie API key not configured"))

            # Validate key format only for payment API (not backend API)
            if not self.use_backend_api:
                if test_mode and not api_key.startswith("test_"):
                    frappe.msgprint(_("Warning: Using non-test API key in test mode"))
                elif not test_mode and not api_key.startswith("live_"):
                    raise frappe.ValidationError(_("Live API key required for production mode"))

            return api_key

        except Exception as e:
            frappe.log_error(f"Failed to get Mollie API key: {str(e)}", "Mollie API")
            raise

    def _get_backend_api_key(self) -> str:
        """
        Get Organization Access Token for backend API operations

        Returns:
            Organization Access Token string
        """
        try:
            settings = self.mollie_settings
            if not settings:
                raise frappe.ValidationError(_("Mollie Settings not configured"))

            # Check if backend API is enabled
            if not settings.get("enable_backend_api"):
                raise frappe.ValidationError(
                    _("Mollie Backend API is not enabled. Please enable it in Mollie Settings.")
                )

            # Get Organization Access Token
            api_key = settings.get_password("organization_access_token", raise_exception=False)
            if not api_key:
                raise frappe.ValidationError(
                    _(
                        "Organization Access Token not configured. Please configure it in Mollie Settings for backend API access."
                    )
                )

            # OAT tokens don't follow test_/live_ format - they're always live tokens
            return api_key

        except Exception as e:
            frappe.log_error(f"Failed to get Mollie Backend API key: {str(e)}", "Mollie Backend API")
            raise

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        paginated: bool = False,
    ) -> Any:
        """
        Make authenticated request to Mollie API

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request payload
            paginated: Whether to handle pagination automatically

        Returns:
            API response data
        """
        try:
            # Validate request data if present
            if data:
                self._validate_request_data(endpoint, data)

            # Make request
            if paginated:
                result = self._request_paginated(method, endpoint, params, data)
                return result
            else:
                response, status_code = self.http_client.request(
                    method=method, endpoint=endpoint, params=params, json_data=data
                )

                # Validate response
                self._validate_response(response, status_code)

                # Log successful API call
                self._log_api_call(method, endpoint, status_code)

                return response

        except requests.RequestException as e:
            self._handle_request_error(e, method, endpoint)
        except Exception as e:
            self._handle_general_error(e, method, endpoint)

    def _request_paginated(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Handle paginated API requests

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            data: Request payload

        Returns:
            List of all items from paginated response
        """
        all_items = []
        params = params or {}

        # Set initial pagination parameters
        params["limit"] = 250  # Max limit for Mollie

        while True:
            # Make request
            response, status_code = self.http_client.request(
                method=method, endpoint=endpoint, params=params, json_data=data
            )

            # Debug logging - only log on error or if needed for debugging
            if status_code >= 400:
                frappe.log_error(
                    f"[MOLLIE ERROR] MollieBaseClient._request_paginated: Error response (status {status_code}): {response}",
                    "Mollie Error",
                )

            # Validate response
            self._validate_response(response, status_code)

            # Extract items based on response structure
            if "_embedded" in response:
                # Mollie uses _embedded for collections
                for key in response["_embedded"]:
                    items = response["_embedded"][key]
                    if isinstance(items, list):
                        all_items.extend(items)
            elif "data" in response and isinstance(response["data"], list):
                all_items.extend(response["data"])
            else:
                # Single item response
                all_items.append(response)
                break

            # Check for next page
            if "_links" in response and "next" in response["_links"] and response["_links"]["next"]:
                next_url = response["_links"]["next"]["href"]
                # Extract cursor or from parameter
                if "from" in next_url:
                    import re

                    match = re.search(r"from=([^&]+)", next_url)
                    if match:
                        params["from"] = match.group(1)
                    else:
                        break
                else:
                    break
            else:
                break

        return all_items

    def _validate_request_data(self, endpoint: str, data: Dict[str, Any]):
        """
        Validate request data based on endpoint

        Args:
            endpoint: API endpoint
            data: Request data
        """
        # Validate amounts if present
        if "amount" in data:
            amount_data = data["amount"]
            if isinstance(amount_data, dict):
                # Validate amount value
                if "value" in amount_data:
                    valid, error = self.financial_validator.validate_amount(
                        amount_data["value"], min_amount=0.01, precision=2
                    )
                    if not valid:
                        raise frappe.ValidationError(f"Invalid amount: {error}")

                # Validate currency
                if "currency" in amount_data:
                    valid, error = self.financial_validator.validate_currency(amount_data["currency"])
                    if not valid:
                        raise frappe.ValidationError(f"Invalid currency: {error}")

        # Validate IBAN if present
        if "iban" in data:
            valid, error = self.financial_validator.validate_iban(data["iban"])
            if not valid:
                raise frappe.ValidationError(f"Invalid IBAN: {error}")

    def _validate_response(self, response: Optional[Dict[str, Any]], status_code: int):
        """
        Validate API response

        Args:
            response: Response data
            status_code: HTTP status code
        """
        # Check for error status codes
        if status_code >= 400:
            self._handle_api_error(response, status_code)

        # Validate response structure
        if response and "resource" in response:
            # Validate based on resource type
            resource_type = response["resource"]

            if resource_type == "payment":
                validation_result = self.financial_validator.validate_payment_data(response)
                if not validation_result["valid"]:
                    frappe.msgprint(_(f"Payment validation warnings: {validation_result['warnings']}"))

            elif resource_type == "settlement":
                validation_result = self.financial_validator.validate_settlement_data(response)
                if not validation_result["valid"]:
                    raise frappe.ValidationError(
                        f"Settlement validation failed: {validation_result['errors']}"
                    )

    def _handle_api_error(self, response: Optional[Dict[str, Any]], status_code: int):
        """
        Handle API error response with enhanced parameter validation

        Args:
            response: Error response data
            status_code: HTTP status code
        """
        # Extract error details
        error_message = "Unknown API error"
        error_code = None
        error_details = {}

        if response:
            # Mollie error format
            if "detail" in response:
                error_message = response["detail"]
            elif "title" in response:
                error_message = response["title"]
            elif "message" in response:
                error_message = response["message"]

            if "type" in response:
                error_code = response["type"]

            if "field" in response:
                error_details["field"] = response["field"]

            if "_links" in response and "documentation" in response["_links"]:
                error_details["documentation"] = response["_links"]["documentation"]["href"]

        # Enhanced logging for parameter-related errors
        if status_code == 400 and error_message:
            frappe.logger().error(f"Mollie API 400 error: {error_message}")
            # Check for unsupported parameter errors
            if (
                "parameter" in error_message.lower()
                or "from" in error_message.lower()
                or "until" in error_message.lower()
            ):
                frappe.logger().warning(f"Possible unsupported parameter error: {error_message}")

        # Map to appropriate exception
        if status_code == 401:
            raise frappe.AuthenticationError(_("Invalid API key"))
        elif status_code == 403:
            raise frappe.PermissionError(_("Access denied to this resource"))
        elif status_code == 404:
            raise frappe.DoesNotExistError(_("Resource not found"))
        elif status_code == 422:
            raise frappe.ValidationError(f"Validation error: {error_message}")
        elif status_code == 429:
            raise frappe.ValidationError(_("Rate limit exceeded"))
        elif status_code >= 500:
            raise frappe.ValidationError(f"Mollie API error: {error_message}")
        else:
            raise MollieAPIError(
                message=error_message, error_code=error_code, status_code=status_code, details=error_details
            )

    def _handle_request_error(self, error: Exception, method: str, endpoint: str):
        """Handle request exception"""
        self.audit_trail.log_event(
            AuditEventType.ERROR_OCCURRED,
            AuditSeverity.ERROR,
            f"Mollie API request failed: {method} {endpoint}",
            details={"error_type": type(error).__name__, "error_message": str(error)},
        )

        raise frappe.ValidationError(f"Failed to connect to Mollie API: {str(error)}")

    def _handle_general_error(self, error: Exception, method: str, endpoint: str):
        """Handle general exception"""
        self.audit_trail.log_event(
            AuditEventType.ERROR_OCCURRED,
            AuditSeverity.CRITICAL,
            f"Unexpected error in Mollie API call: {method} {endpoint}",
            details={"error_type": type(error).__name__, "error_message": str(error)},
        )

        frappe.log_error(f"Mollie API Error: {str(error)}", "Mollie Backend")
        raise

    def _log_api_call(self, method: str, endpoint: str, status_code: int):
        """Log successful API call"""
        self.audit_trail.log_event(
            AuditEventType.API_KEY_ROTATION,  # Would have specific event type
            AuditSeverity.INFO,
            f"Mollie API call: {method} {endpoint}",
            details={"status_code": status_code, "test_mode": self.test_mode},
        )

    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None, paginated: bool = False) -> Any:
        """Make GET request"""
        return self.request("GET", endpoint, params=params, paginated=paginated)

    def post(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """Make POST request"""
        return self.request("POST", endpoint, data=data)

    def patch(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """Make PATCH request"""
        return self.request("PATCH", endpoint, data=data)

    def delete(self, endpoint: str) -> Any:
        """Make DELETE request"""
        return self.request("DELETE", endpoint)

    def get_metrics(self) -> Dict[str, Any]:
        """Get client performance metrics"""
        return self.http_client.get_metrics()

    def test_endpoint_parameter_support(self, endpoint: str, test_params: Dict[str, str]) -> Dict[str, bool]:
        """
        Test which parameters are supported by an endpoint

        Args:
            endpoint: API endpoint to test
            test_params: Dictionary of parameter names and test values

        Returns:
            Dictionary mapping parameter names to support status (True/False)
        """
        support_status = {}

        for param_name, param_value in test_params.items():
            try:
                # Test with minimal parameters plus the test parameter
                test_request_params = {"limit": 1, param_name: param_value}
                response, status_code = self.http_client.request(
                    method="GET", endpoint=endpoint, params=test_request_params
                )

                if status_code == 200:
                    support_status[param_name] = True
                    frappe.logger().info(f"Parameter '{param_name}' is supported by {endpoint}")
                else:
                    support_status[param_name] = False
                    frappe.logger().info(
                        f"Parameter '{param_name}' returned status {status_code} for {endpoint}"
                    )

            except Exception as e:
                if "400" in str(e) and (param_name in str(e).lower() or "parameter" in str(e).lower()):
                    support_status[param_name] = False
                    frappe.logger().info(f"Parameter '{param_name}' is not supported by {endpoint}: {str(e)}")
                else:
                    # Other error types don't necessarily mean parameter unsupported
                    support_status[param_name] = "unknown"
                    frappe.logger().warning(
                        f"Could not test parameter '{param_name}' for {endpoint}: {str(e)}"
                    )

        return support_status

    def close(self):
        """Close client connections"""
        self.http_client.close()

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()
