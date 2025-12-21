"""
Mollie API Client

DEPRECATED: This module is deprecated. Use client.py instead.

This module is kept for backward compatibility and will be removed in a future version.
Import MollieClient from verenigingen.verenigingen_payments.mollie.core.client instead.
"""

import json
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional

import frappe
import requests
from frappe import _

from ..exceptions import MollieAPIError, MollieConfigurationError
from .mollie_models import Customer, Money, Payment, Subscription

try:
    from mollie.api.client import Client as MollieSDKClient
    from mollie.api.error import Error as MollieSDKError

    MOLLIE_SDK_AVAILABLE = True
except ImportError:
    MollieSDKClient = None
    MollieSDKError = Exception
    MOLLIE_SDK_AVAILABLE = False


class MollieClient:
    """
    Unified Mollie API client providing both direct REST API access
    and Mollie SDK integration with proper error handling and validation.
    """

    BASE_URL = "https://api.mollie.com/v2/"
    API_VERSION = "v2"

    def __init__(self, api_key: Optional[str] = None, test_mode: Optional[bool] = None):
        """
        Initialize Mollie client.

        DEPRECATED: Use verenigingen.verenigingen_payments.mollie.core.client.MollieClient instead.

        Args:
            api_key: Mollie API key (if not provided, fetched from settings)
            test_mode: Whether to use test mode (if not provided, inferred from API key)
        """
        warnings.warn(
            "mollie_client.MollieClient is deprecated. "
            "Use verenigingen.verenigingen_payments.mollie.core.client.MollieClient instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.settings = self._load_settings()

        # Use provided API key or get from settings
        if api_key:
            self.api_key = api_key
            self.test_mode = api_key.startswith("test_") if test_mode is None else test_mode
        else:
            self.api_key = self.settings["api_key"]
            self.test_mode = self.settings["test_mode"]

        # Initialize session for direct API calls
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": f"Verenigingen/{frappe.__version__}",
            }
        )

        # Initialize SDK client if available
        self.sdk_client = None
        if MOLLIE_SDK_AVAILABLE:
            try:
                self.sdk_client = MollieSDKClient()
                self.sdk_client.set_api_key(self.api_key)
                self._test_connectivity()
            except Exception as e:
                frappe.log_error(f"Failed to initialize Mollie SDK: {e}", "Mollie Client")

    def _load_settings(self) -> Dict[str, Any]:
        """Load Mollie settings from database."""
        try:
            doc = frappe.get_single("Mollie Settings")
            api_key = doc.get_active_api_key()

            if not api_key:
                raise MollieConfigurationError("Mollie API key not configured")

            # Determine if we're in test mode based on API key
            test_mode = api_key.startswith("test_")

            # Use appropriate webhook URL based on mode
            webhook_url = doc.testing_webhook_url if test_mode else doc.live_webhook_url

            return {
                "api_key": api_key,
                "test_mode": test_mode,
                "profile_id": doc.profile_id,
                "webhook_url": webhook_url,
                "webhook_secret": doc.get_password(fieldname="webhook_secret", raise_exception=False),
            }
        except frappe.DoesNotExistError:
            raise MollieConfigurationError("Mollie Settings not found")

    def _test_connectivity(self):
        """Test API connectivity with a simple call."""
        try:
            if self.sdk_client:
                # Use methods.list() instead of organizations.get("me")
                # because organizations endpoint requires:
                # 1. Live mode (not test mode)
                # 2. Organization Access Token (not regular API key)
                # methods.list() works in both test and live mode
                self.sdk_client.methods.list()
        except Exception as e:
            frappe.log_error(f"Mollie connectivity test failed: {e}", "Mollie Client")

    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make direct API request to Mollie.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            data: Request data for POST/PATCH requests

        Returns:
            API response data

        Raises:
            MollieAPIError: If API request fails
        """
        url = f"{self.BASE_URL}{endpoint}"

        try:
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            elif method.upper() == "PATCH":
                response = self.session.patch(url, json=data)
            elif method.upper() == "DELETE":
                response = self.session.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if not response.ok:
                error_data = (
                    response.json()
                    if response.headers.get("content-type", "").startswith("application/json")
                    else {}
                )
                raise MollieAPIError(
                    message=error_data.get("detail", f"HTTP {response.status_code}"),
                    error_code=error_data.get("type"),
                    status_code=response.status_code,
                    details=error_data,
                )

            return response.json()

        except requests.RequestException as e:
            raise MollieAPIError(f"Network error: {e}")

    # Customer operations
    def create_customer(self, name: str, email: str, metadata: Optional[Dict] = None) -> Customer:
        """Create a new customer."""
        data = {"name": name, "email": email, "metadata": metadata or {}}

        if self.sdk_client:
            try:
                customer = self.sdk_client.customers.create(data)
                return Customer.from_mollie_api(customer)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to create customer: {e}")
        else:
            response = self._make_request("POST", "customers", data)
            return Customer.from_mollie_api(response)

    def get_customer(self, customer_id: str) -> Customer:
        """Get customer by ID."""
        if self.sdk_client:
            try:
                customer = self.sdk_client.customers.get(customer_id)
                return Customer.from_mollie_api(customer)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to get customer: {e}")
        else:
            response = self._make_request("GET", f"customers/{customer_id}")
            return Customer.from_mollie_api(response)

    # Payment operations
    def create_payment(
        self,
        amount: Money,
        description: str,
        redirect_url: str,
        webhook_url: Optional[str] = None,
        customer_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Payment:
        """Create a new payment."""
        data = {
            "amount": amount.to_dict(),
            "description": description,
            "redirectUrl": redirect_url,
            "metadata": metadata or {},
        }

        if webhook_url:
            data["webhookUrl"] = webhook_url
        if customer_id:
            data["customerId"] = customer_id

        if self.sdk_client:
            try:
                payment = self.sdk_client.payments.create(data)
                return Payment.from_mollie_api(payment)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to create payment: {e}")
        else:
            response = self._make_request("POST", "payments", data)
            return Payment.from_mollie_api(response)

    def get_payment(self, payment_id: str) -> Payment:
        """Get payment by ID."""
        if self.sdk_client:
            try:
                payment = self.sdk_client.payments.get(payment_id)
                return Payment.from_mollie_api(payment)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to get payment: {e}")
        else:
            response = self._make_request("GET", f"payments/{payment_id}")
            return Payment.from_mollie_api(response)

    # Subscription operations
    def create_subscription(
        self,
        customer_id: str,
        amount: Money,
        interval: str,
        description: str,
        webhook_url: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> Subscription:
        """Create a new subscription."""
        data = {
            "amount": amount.to_dict(),
            "interval": interval,
            "description": description,
            "metadata": metadata or {},
        }

        if webhook_url:
            data["webhookUrl"] = webhook_url

        if self.sdk_client:
            try:
                subscription = self.sdk_client.customer_subscriptions.with_parent_id(customer_id).create(data)
                return Subscription.from_mollie_api(subscription)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to create subscription: {e}")
        else:
            response = self._make_request("POST", f"customers/{customer_id}/subscriptions", data)
            return Subscription.from_mollie_api(response)

    def get_subscription(self, customer_id: str, subscription_id: str) -> Subscription:
        """Get subscription by ID."""
        if self.sdk_client:
            try:
                subscription = self.sdk_client.customer_subscriptions.with_parent_id(customer_id).get(
                    subscription_id
                )
                return Subscription.from_mollie_api(subscription)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to get subscription: {e}")
        else:
            response = self._make_request("GET", f"customers/{customer_id}/subscriptions/{subscription_id}")
            return Subscription.from_mollie_api(response)

    def cancel_subscription(self, customer_id: str, subscription_id: str) -> Subscription:
        """Cancel a subscription."""
        if self.sdk_client:
            try:
                subscription = self.sdk_client.customer_subscriptions.with_parent_id(customer_id).delete(
                    subscription_id
                )
                return Subscription.from_mollie_api(subscription)
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to cancel subscription: {e}")
        else:
            response = self._make_request(
                "DELETE", f"customers/{customer_id}/subscriptions/{subscription_id}"
            )
            return Subscription.from_mollie_api(response)

    def list_customer_payments(self, customer_id: str, limit: int = 50) -> List[Payment]:
        """List payments for a customer."""
        if self.sdk_client:
            try:
                payments = self.sdk_client.customer_payments.with_parent_id(customer_id).list(limit=limit)
                return [Payment.from_mollie_api(payment) for payment in payments]
            except MollieSDKError as e:
                raise MollieAPIError(f"Failed to list customer payments: {e}")
        else:
            response = self._make_request("GET", f"customers/{customer_id}/payments?limit={limit}")
            return [
                Payment.from_mollie_api(payment)
                for payment in response.get("_embedded", {}).get("payments", [])
            ]
