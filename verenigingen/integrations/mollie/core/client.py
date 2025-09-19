"""
Mollie Client - Core API Integration

A simple, robust wrapper around the Mollie API that focuses on the operations
actually needed by the Verenigingen application. This replaces the complex
mollie_client.py with a focused implementation.
"""

from typing import Any, Dict, Optional

import frappe

from ..exceptions import MolliePaymentError, MollieWebhookError
from ..utils.error_recovery import CircuitBreakerConfig, RetryConfig, with_circuit_breaker, with_retry


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
        except Exception as e:
            raise MolliePaymentError(f"Failed to get Mollie API key: {e}")

    def _get_mollie_client(self):
        """Get or create the underlying Mollie API client."""
        if self._mollie_client is None:
            try:
                mollie_settings = frappe.get_single("Mollie Settings")
                self._mollie_client = mollie_settings.get_mollie_client()
            except Exception as e:
                raise MolliePaymentError(f"Failed to initialize Mollie client: {e}")
        return self._mollie_client

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

    def is_test_mode(self) -> bool:
        """
        Check if the client is in test mode.

        Returns:
            True if in test mode, False if in live mode
        """
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

    def get_webhook_url(self, endpoint: str = "mollie_payment_webhook") -> str:
        """
        Get the webhook URL for this site.

        Args:
            endpoint: The webhook endpoint name

        Returns:
            Full webhook URL
        """
        site_url = frappe.utils.get_url()
        return f"{site_url}/api/method/verenigingen.utils.payment_gateways.{endpoint}"
