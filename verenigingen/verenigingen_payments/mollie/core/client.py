"""
Mollie Client - Core API Integration

A simple, robust wrapper around the Mollie API that focuses on the operations
actually needed by the Verenigingen application. This replaces the complex
mollie_client.py with a focused implementation.

Uses MollieConfigurationService for cached configuration access where appropriate.
API keys are NOT cached for security reasons - retrieved directly from Mollie Settings.
"""

from typing import Any, Dict, Optional

import frappe

from verenigingen.verenigingen_payments.core.resilience import (
    CircuitBreakerConfig,
    RetryConfig,
    with_circuit_breaker,
    with_retry,
)

# Import configuration service for cached settings access
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config

from ..exceptions import MolliePaymentError, MollieWebhookError


class MollieClient:
    """
    Simple Mollie API client focused on payments and webhooks.

    This client provides a clean interface for the Mollie operations that
    the Verenigingen application actually uses, without unnecessary complexity.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Mollie client.

        Args:
            api_key: Optional API key (defaults to settings)
        """
        self.api_key = api_key or self._get_api_key()
        self._mollie_client = None

    def _get_api_key(self) -> str:
        """Get API key from Mollie Settings."""
        try:
            mollie_settings = frappe.get_single("Mollie Settings")

            # Use test_secret_key if in test mode, otherwise live_secret_key
            if mollie_settings.test_mode:
                api_key = mollie_settings.test_secret_key
                if not api_key:
                    raise MolliePaymentError("Mollie test API key not configured in Mollie Settings")
            else:
                api_key = mollie_settings.live_secret_key
                if not api_key:
                    raise MolliePaymentError("Mollie live API key not configured in Mollie Settings")

            return api_key
        except MolliePaymentError:
            # Re-raise our own exceptions without wrapping
            raise
        except Exception as e:
            raise MolliePaymentError(f"Failed to get Mollie API key: {e}", original_error=e) from e

    def _get_mollie_client(self):
        """Get or create the underlying Mollie API client."""
        if self._mollie_client is None:
            try:
                mollie_settings = frappe.get_single("Mollie Settings")
                self._mollie_client = mollie_settings.get_mollie_client()
            except Exception as e:
                raise MolliePaymentError(f"Failed to initialize Mollie client: {e}", original_error=e) from e
        return self._mollie_client

    @property
    def sdk_client(self):
        """
        Public property to access the underlying Mollie SDK client.

        This is provided for advanced operations that aren't wrapped
        by the MollieClient API (e.g., listing subscriptions, mandates).
        """
        return self._get_mollie_client()

    @with_circuit_breaker(
        "mollie_api_get_payment", CircuitBreakerConfig(failure_threshold=5, recovery_timeout=60)
    )
    @with_retry(RetryConfig(max_attempts=3, base_delay=1.0, max_delay=30.0), "get_payment")
    def get_payment(self, payment_id: str) -> Any:
        """
        Get payment details from Mollie with enhanced error recovery.

        Args:
            payment_id: The Mollie payment ID

        Returns:
            Mollie payment object

        Raises:
            MolliePaymentError: When payment cannot be retrieved after retries
        """
        try:
            client = self._get_mollie_client()
            return client.payments.get(payment_id)
        except Exception as e:
            # Check if this is a JSON parsing error
            if "Expecting value: line 1 column 1" in str(e):
                frappe.logger().error(f"🔍 JSON parsing error for payment {payment_id}: {e}")
                frappe.logger().error(f"🔍 Exception type: {type(e)}")
                # Try to get more details about the error (truncate response to avoid logging sensitive data)
                if hasattr(e, "response"):
                    frappe.logger().error(f"🔍 Response status: {getattr(e.response, 'status_code', 'N/A')}")
                    # Truncate response text to 200 chars to avoid logging sensitive data
                    response_text = getattr(e.response, "text", "N/A")
                    if response_text and len(response_text) > 200:
                        response_text = response_text[:200] + "... [truncated]"
                    frappe.logger().error(f"🔍 Response text (truncated): {response_text}")

            error_msg = f"Failed to get payment {payment_id} from Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    @with_circuit_breaker(
        "mollie_api_create_payment", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=120)
    )
    @with_retry(RetryConfig(max_attempts=2, base_delay=2.0, max_delay=30.0), "create_payment")
    def create_payment(self, payment_data: Dict[str, Any]) -> Any:
        """
        Create a new payment in Mollie with enhanced error recovery.

        Args:
            payment_data: Payment creation data

        Returns:
            Created Mollie payment object

        Raises:
            MolliePaymentError: When payment cannot be created after retries
        """
        try:
            client = self._get_mollie_client()
            return client.payments.create(payment_data)
        except Exception as e:
            error_msg = f"Failed to create payment in Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def get_customer(self, customer_id: str) -> Any:
        """
        Get customer details from Mollie.

        Args:
            customer_id: The Mollie customer ID

        Returns:
            Mollie customer object

        Raises:
            MolliePaymentError: When customer cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            return client.customers.get(customer_id)
        except Exception as e:
            error_msg = f"Failed to get customer {customer_id} from Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def create_customer(self, customer_data: Dict[str, Any]) -> Any:
        """
        Create a new customer in Mollie.

        Args:
            customer_data: Customer creation data

        Returns:
            Created Mollie customer object

        Raises:
            MolliePaymentError: When customer cannot be created
        """
        try:
            client = self._get_mollie_client()
            return client.customers.create(customer_data)
        except Exception as e:
            error_msg = f"Failed to create customer in Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def create_subscription(self, customer_id: str, subscription_data: Dict[str, Any]) -> Any:
        """
        Create a subscription for a customer.

        Args:
            customer_id: The Mollie customer ID
            subscription_data: Subscription creation data

        Returns:
            Created Mollie subscription object

        Raises:
            MolliePaymentError: When subscription cannot be created
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.subscriptions.create(subscription_data)
        except Exception as e:
            error_msg = f"Failed to create subscription for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def get_subscription(self, customer_id: str, subscription_id: str) -> Any:
        """
        Get subscription details from Mollie.

        Args:
            customer_id: The Mollie customer ID
            subscription_id: The subscription ID

        Returns:
            Mollie subscription object

        Raises:
            MolliePaymentError: When subscription cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.subscriptions.get(subscription_id)
        except Exception as e:
            error_msg = f"Failed to get subscription {subscription_id} for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def update_subscription(self, customer_id: str, subscription_id: str, update_data: Dict[str, Any]) -> Any:
        """
        PATCH fields on an existing subscription (amount, description,
        webhookUrl, ...) without replacing it.

        Args:
            customer_id: The Mollie customer ID
            subscription_id: The subscription ID
            update_data: Fields to update, in Mollie API shape

        Returns:
            The updated Mollie subscription object

        Raises:
            MolliePaymentError: When the subscription cannot be updated
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.subscriptions.update(subscription_id, update_data)
        except Exception as e:
            error_msg = f"Failed to update subscription {subscription_id}: {e}"
            frappe.log_error(error_msg, "Mollie Subscription Update")
            raise MolliePaymentError(error_msg, original_error=e)

    def cancel_subscription(self, customer_id: str, subscription_id: str) -> Any:
        """
        Cancel a subscription.

        Args:
            customer_id: The Mollie customer ID
            subscription_id: The subscription ID to cancel

        Returns:
            Cancelled Mollie subscription object

        Raises:
            MolliePaymentError: When subscription cannot be cancelled
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.subscriptions.delete(subscription_id)
        except Exception as e:
            error_msg = f"Failed to cancel subscription {subscription_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def create_mandate(self, customer_id: str, mandate_data: Dict[str, Any]) -> Any:
        """
        Create a payment mandate (e.g. SEPA direct debit) for a customer.

        Args:
            customer_id: The Mollie customer ID
            mandate_data: Mandate creation data

        Returns:
            Created Mollie mandate object

        Raises:
            MolliePaymentError: When the mandate cannot be created
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return customer.mandates.create(data=mandate_data)
        except Exception as e:
            error_msg = f"Failed to create mandate for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def list_mandates(self, customer_id: str) -> list:
        """
        List all payment mandates for a customer, across every page.

        Mollie's SDK returns a ``PaginationList`` whose iterator only yields
        the first page (50 results). Callers need the complete set, so this
        walks ``get_next()`` and returns a flat list.

        Args:
            customer_id: The Mollie customer ID

        Returns:
            List of Mollie mandate objects

        Raises:
            MolliePaymentError: When the mandates cannot be listed
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            mandates = []
            page = customer.mandates.list()
            while page is not None:
                mandates.extend(page)
                page = page.get_next()
            return mandates
        except Exception as e:
            error_msg = f"Failed to list mandates for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def list_customer_payments(self, customer_id: str, limit: int = 50) -> Any:
        """
        List payments for a customer.

        Args:
            customer_id: The Mollie customer ID
            limit: Maximum number of payments to return (default 50)

        Returns:
            List of Mollie payment objects

        Raises:
            MolliePaymentError: When payments cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            customer = client.customers.get(customer_id)
            return list(customer.payments.list(limit=limit))
        except Exception as e:
            error_msg = f"Failed to list payments for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, original_error=e)

    def is_test_mode(self) -> bool:
        """
        Check if the client is in test mode.

        Uses MollieConfigurationService for cached access to test_mode setting.
        Falls back to API key prefix check if configuration unavailable.

        Returns:
            True if in test mode, False if in live mode
        """
        try:
            return get_mollie_config().is_test_mode()
        except Exception:
            # Fallback to API key check if config service unavailable
            return self.api_key.startswith("test_") if self.api_key else False

    def get_refund(self, payment_id: str, refund_id: str) -> Any:
        """
        Get refund details from Mollie.

        Args:
            payment_id: The Mollie payment ID
            refund_id: The Mollie refund ID

        Returns:
            Mollie refund object

        Raises:
            MolliePaymentError: When refund cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            payment = client.payments.get(payment_id)
            return payment.refunds.get(refund_id)
        except Exception as e:
            error_msg = f"Failed to get refund {refund_id} for payment {payment_id} from Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    @with_circuit_breaker(
        "mollie_api_create_refund", CircuitBreakerConfig(failure_threshold=3, recovery_timeout=120)
    )
    @with_retry(RetryConfig(max_attempts=2, base_delay=2.0, max_delay=30.0), "create_refund")
    def create_refund(self, payment_id: str, refund_data: Dict[str, Any]) -> Any:
        """
        Create a refund for a payment with enhanced error recovery.

        Args:
            payment_id: The Mollie payment ID to refund
            refund_data: Refund creation data

        Returns:
            Created Mollie refund object

        Raises:
            MolliePaymentError: When refund cannot be created after retries
        """
        try:
            client = self._get_mollie_client()
            payment = client.payments.get(payment_id)
            return payment.refunds.create(refund_data)
        except Exception as e:
            error_msg = f"Failed to create refund for payment {payment_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    def get_chargeback(self, payment_id: str, chargeback_id: str) -> Any:
        """
        Get chargeback details from Mollie.

        Args:
            payment_id: The Mollie payment ID
            chargeback_id: The Mollie chargeback ID

        Returns:
            Mollie chargeback object

        Raises:
            MolliePaymentError: When chargeback cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            payment = client.payments.get(payment_id)
            return payment.chargebacks.get(chargeback_id)
        except Exception as e:
            error_msg = f"Failed to get chargeback {chargeback_id} for payment {payment_id} from Mollie: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    def list_payment_refunds(self, payment_id: str) -> Any:
        """
        List all refunds for a payment.

        Args:
            payment_id: The Mollie payment ID

        Returns:
            List of Mollie refund objects

        Raises:
            MolliePaymentError: When refunds cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            payment = client.payments.get(payment_id)
            return payment.refunds.list()
        except Exception as e:
            error_msg = f"Failed to list refunds for payment {payment_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    def list_payment_chargebacks(self, payment_id: str) -> Any:
        """
        List all chargebacks for a payment.

        Args:
            payment_id: The Mollie payment ID

        Returns:
            List of Mollie chargeback objects

        Raises:
            MolliePaymentError: When chargebacks cannot be retrieved
        """
        try:
            client = self._get_mollie_client()
            payment = client.payments.get(payment_id)
            return payment.chargebacks.list()
        except Exception as e:
            error_msg = f"Failed to list chargebacks for payment {payment_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    def get_webhook_url(self, endpoint: str = "mollie_payment_webhook", env: str = None) -> str:
        """
        Get the webhook URL for this site with environment parameter.

        Uses MollieConfigurationService for cached access to test_mode setting.

        Args:
            endpoint: The webhook endpoint name
            env: Environment parameter ("test" or "live"). If None, auto-detects from current mode.

        Returns:
            Full webhook URL with environment parameter
        """
        site_url = frappe.utils.get_url()
        base_url = f"{site_url}/api/method/verenigingen.verenigingen_payments.mollie.api.webhooks.{endpoint}"

        # Use explicit env parameter if provided, otherwise auto-detect
        if env is not None:
            env_param = env
        else:
            # Auto-detect environment using configuration service (cached)
            env_param = "test" if self.is_test_mode() else "live"

        return f"{base_url}?env={env_param}"

    # Debug and Administrative Methods

    @with_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    @with_circuit_breaker(CircuitBreakerConfig())
    def debug_customer(self, customer_id: str) -> Dict[str, Any]:
        """
        Get comprehensive customer debug information including subscriptions and mandates.

        Args:
            customer_id: Mollie customer ID

        Returns:
            Dict with customer data, subscriptions, mandates, and database records

        Raises:
            MolliePaymentError: If customer retrieval fails
        """
        try:
            result = {
                "customer_id": customer_id,
                "test_mode": self.is_test_mode(),
                "timestamp": frappe.utils.now(),
                "customer_found": False,
                "subscriptions": [],
                "mandates": [],
                "database_records": {"members": [], "donors": []},
                "error": None,
            }

            # Get customer data
            customer = self.get_customer(customer_id)
            result["customer_found"] = True
            result["customer_data"] = {
                "id": getattr(customer, "id", "Unknown"),
                "name": getattr(customer, "name", "Unknown"),
                "email": getattr(customer, "email", "Unknown"),
                "created_at": str(getattr(customer, "created_at", "Unknown")),
                "mode": getattr(customer, "mode", "Unknown"),
            }

            # Get subscriptions and mandates using raw client for list operations
            client = self._get_mollie_client()
            customer_obj = client.customers.get(customer_id)

            # Get subscriptions
            subscriptions = customer_obj.subscriptions.list()
            for sub in subscriptions:
                amount_str = "Unknown"
                try:
                    if hasattr(sub, "amount") and sub.amount:
                        if isinstance(sub.amount, dict):
                            amount_str = f"{sub.amount.get('value', '0')} {sub.amount.get('currency', 'EUR')}"
                        else:
                            amount_str = str(sub.amount)
                except Exception:
                    amount_str = "Error parsing amount"

                result["subscriptions"].append(
                    {
                        "id": getattr(sub, "id", "Unknown"),
                        "status": getattr(sub, "status", "Unknown"),
                        "amount": amount_str,
                        "interval": getattr(sub, "interval", "Unknown"),
                        "description": getattr(sub, "description", "Unknown"),
                        "created_at": str(getattr(sub, "created_at", "Unknown")),
                        "next_payment_date": (
                            str(getattr(sub, "next_payment_date", None))
                            if getattr(sub, "next_payment_date", None)
                            else None
                        ),
                        "canceled_at": (
                            str(getattr(sub, "canceled_at", None))
                            if getattr(sub, "canceled_at", None)
                            else None
                        ),
                    }
                )

            # Get mandates via list_mandates so every page is included
            # (the raw PaginationList iterator only yields the first).
            mandates = self.list_mandates(customer_id)
            for mandate in mandates:
                result["mandates"].append(
                    {
                        "id": getattr(mandate, "id", "Unknown"),
                        "status": getattr(mandate, "status", "Unknown"),
                        "method": getattr(mandate, "method", "Unknown"),
                        "created_at": str(getattr(mandate, "created_at", "Unknown")),
                        "mandate_reference": getattr(mandate, "mandate_reference", None),
                        "signature_date": (
                            str(getattr(mandate, "signature_date", None))
                            if getattr(mandate, "signature_date", None)
                            else None
                        ),
                    }
                )

            # Check database records
            members = frappe.get_all(
                "Member",
                filters={"mollie_customer_id": customer_id},
                fields=[
                    "name",
                    "full_name",
                    "mollie_subscription_id",
                    "subscription_status",
                    "payment_method",
                ],
            )
            result["database_records"]["members"] = members

            donors = frappe.get_all(
                "Donor", filters={"mollie_customer_id": customer_id}, fields=["name", "donor_name", "member"]
            )
            result["database_records"]["donors"] = donors

            return result

        except Exception as e:
            error_msg = f"Failed to debug customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client Debug")
            raise MolliePaymentError(error_msg, customer_id=customer_id, original_error=e)

    @with_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    @with_circuit_breaker(CircuitBreakerConfig())
    def debug_subscription(self, customer_id: str, subscription_id: str) -> Dict[str, Any]:
        """
        Get detailed subscription debug information.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID

        Returns:
            Dict with subscription details

        Raises:
            MolliePaymentError: If subscription retrieval fails
        """
        try:
            result = {
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "test_mode": self.is_test_mode(),
                "timestamp": frappe.utils.now(),
                "subscription_found": False,
                "error": None,
            }

            client = self._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
            subscription = customer_obj.subscriptions.get(subscription_id)

            result["subscription_found"] = True
            result["subscription_data"] = {
                "id": subscription.id,
                "customer_id": subscription.customer_id,
                "status": subscription.status,
                "amount": f"{subscription.amount['value']} {subscription.amount['currency']}",
                "interval": subscription.interval,
                "description": subscription.description,
                "created_at": subscription.created_at,
                "next_payment_date": getattr(subscription, "next_payment_date", None),
                "canceled_at": getattr(subscription, "canceled_at", None),
                "metadata": getattr(subscription, "metadata", {}),
            }

            return result

        except Exception as e:
            error_msg = f"Failed to debug subscription {subscription_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client Debug")
            raise MolliePaymentError(error_msg, subscription_id=subscription_id, original_error=e)

    @with_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    @with_circuit_breaker(CircuitBreakerConfig())
    def debug_mandate(self, customer_id: str, mandate_id: str) -> Dict[str, Any]:
        """
        Get detailed mandate debug information.

        Args:
            customer_id: Mollie customer ID
            mandate_id: Mollie mandate ID

        Returns:
            Dict with mandate details

        Raises:
            MolliePaymentError: If mandate retrieval fails
        """
        try:
            result = {
                "mandate_id": mandate_id,
                "customer_id": customer_id,
                "test_mode": self.is_test_mode(),
                "timestamp": frappe.utils.now(),
                "mandate_found": False,
                "error": None,
            }

            client = self._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
            mandate = customer_obj.mandates.get(mandate_id)

            result["mandate_found"] = True
            result["mandate_data"] = {
                "id": mandate.id,
                "status": mandate.status,
                "method": mandate.method,
                "created_at": mandate.created_at,
                "mandate_reference": getattr(mandate, "mandate_reference", None),
                "signature_date": getattr(mandate, "signature_date", None),
                "consumer_name": getattr(mandate, "consumer_name", None),
                "consumer_account": getattr(mandate, "consumer_account", None),
            }

            return result

        except Exception as e:
            error_msg = f"Failed to debug mandate {mandate_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client Debug")
            raise MolliePaymentError(error_msg, mandate_id=mandate_id, original_error=e)

    @with_retry(RetryConfig(max_attempts=2, base_delay=1.0))
    @with_circuit_breaker(CircuitBreakerConfig())
    def revoke_mandate(self, customer_id: str, mandate_id: str) -> Any:
        """
        Revoke a customer's mandate.

        Args:
            customer_id: Mollie customer ID
            mandate_id: Mandate ID to revoke

        Returns:
            Revoked mandate object

        Raises:
            MolliePaymentError: If mandate revocation fails
        """
        try:
            client = self._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
            revoked_mandate = customer_obj.mandates.delete(mandate_id)

            frappe.logger().info(f"Mandate {mandate_id} revoked for customer {customer_id}")
            return revoked_mandate

        except Exception as e:
            error_msg = f"Failed to revoke mandate {mandate_id} for customer {customer_id}: {e}"
            frappe.log_error(error_msg, "Mollie Client")
            raise MolliePaymentError(
                error_msg, customer_id=customer_id, mandate_id=mandate_id, original_error=e
            )
