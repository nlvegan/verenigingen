"""
Mollie SDK Integration Connector
Bridges Frappe framework with Mollie Python SDK
"""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _

try:
    from mollie.api.client import Client as MollieClient
    from mollie.api.error import Error as MollieError

    MOLLIE_AVAILABLE = True
except ImportError:
    MOLLIE_AVAILABLE = False
    MollieClient = None
    MollieError = Exception


class MollieIntegrationError(Exception):
    """Base exception for Mollie integration errors"""

    pass


class MollieConnector:
    """
    Production-ready Mollie SDK connector
    Provides actual API connectivity with proper error handling
    """

    def __init__(self):
        """Initialize Mollie connector with settings"""
        if not MOLLIE_AVAILABLE:
            raise MollieIntegrationError("Mollie SDK not installed. Run: pip install mollie-api-python")

        self.settings = self._load_settings()
        self.client = self._initialize_client()
        self._test_connectivity()

    def _load_settings(self) -> Dict:
        """Load Mollie settings from database"""
        try:
            doc = frappe.get_single("Mollie Settings")

            # Decrypt API key
            api_key = doc.get_password(fieldname="secret_key", raise_exception=False)

            if not api_key:
                raise MollieIntegrationError("Mollie API key not configured")

            return {
                "api_key": api_key,
                "profile_id": doc.profile_id,
                "test_mode": api_key.startswith("test_"),
                "webhook_url": doc.webhook_url,
                "webhook_secret": doc.get_password(fieldname="webhook_secret", raise_exception=False),
            }

        except frappe.DoesNotExistError:
            raise MollieIntegrationError(f"Mollie Settings '{self.settings_name}' not found")

    def _initialize_client(self) -> MollieClient:
        """Initialize Mollie API client"""
        client = MollieClient()
        client.set_api_key(self.settings["api_key"])
        return client

    def _test_connectivity(self):
        """Test API connectivity"""
        try:
            # Test with a simple API call
            self.client.methods.list(limit=1)
        except MollieError as e:
            raise MollieIntegrationError(f"Mollie API connection failed: {str(e)}")

    # Balance Operations

    def get_balance(self, balance_id: str = "primary") -> Dict:
        """
        Get balance information

        Args:
            balance_id: Balance identifier (default: primary)

        Returns:
            Dict with balance information
        """
        try:
            balance = self.client.balances.get(balance_id)

            return {
                "id": balance.id,
                "currency": balance.currency,
                "available": {
                    "amount": str(balance.available_amount.value),
                    "currency": balance.available_amount.currency,
                },
                "pending": {
                    "amount": str(balance.pending_amount.value),
                    "currency": balance.pending_amount.currency,
                },
                "created_at": balance.created_at,
                "status": "active",
            }

        except MollieError as e:
            frappe.log_error(f"Failed to get balance: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get balance: {str(e)}")

    def list_balances(self) -> List[Dict]:
        """
        List all balances

        Returns:
            List of balance dictionaries
        """
        try:
            balances = self.client.balances.list()

            return [
                {
                    "id": balance.id,
                    "currency": balance.currency,
                    "available": str(balance.available_amount.value),
                    "pending": str(balance.pending_amount.value),
                }
                for balance in balances
            ]

        except MollieError as e:
            frappe.log_error(f"Failed to list balances: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to list balances: {str(e)}")

    # Settlement Operations

    def get_settlement(self, settlement_id: str) -> Dict:
        """
        Get settlement details

        Args:
            settlement_id: Settlement identifier

        Returns:
            Dict with settlement information
        """
        try:
            settlement = self.client.settlements.get(settlement_id)

            return {
                "id": settlement.id,
                "reference": settlement.reference,
                "amount": {"amount": str(settlement.amount.value), "currency": settlement.amount.currency},
                "status": settlement.status,
                "created_at": settlement.created_at,
                "settled_at": settlement.settled_at,
                "periods": settlement.periods if hasattr(settlement, "periods") else [],
            }

        except MollieError as e:
            frappe.log_error(f"Failed to get settlement: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get settlement: {str(e)}")

    def list_settlements(self, from_date: datetime = None, until_date: datetime = None) -> List[Dict]:
        """
        List settlements within date range

        Args:
            from_date: Start date
            until_date: End date

        Returns:
            List of settlement dictionaries
        """
        try:
            params = {}

            if from_date:
                params["from"] = from_date.strftime("%Y-%m-%d")

            if until_date:
                params["until"] = until_date.strftime("%Y-%m-%d")

            settlements = self.client.settlements.list(**params)

            return [
                {
                    "id": settlement.id,
                    "reference": settlement.reference,
                    "amount": str(settlement.amount.value),
                    "currency": settlement.amount.currency,
                    "status": settlement.status,
                    "settled_at": settlement.settled_at,
                }
                for settlement in settlements
            ]

        except MollieError as e:
            frappe.log_error(f"Failed to list settlements: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to list settlements: {str(e)}")

    def get_settlement_payments(self, settlement_id: str) -> List[Dict]:
        """
        Get payments for a settlement

        Args:
            settlement_id: Settlement identifier

        Returns:
            List of payment dictionaries
        """
        try:
            settlement = self.client.settlements.get(settlement_id)
            payments = settlement.payments.list()

            return [
                {
                    "id": payment.id,
                    "amount": str(payment.amount.value),
                    "currency": payment.amount.currency,
                    "status": payment.status,
                    "method": payment.method,
                    "created_at": payment.created_at,
                }
                for payment in payments
            ]

        except MollieError as e:
            frappe.log_error(f"Failed to get settlement payments: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get settlement payments: {str(e)}")

    # Payment Operations

    def create_payment(
        self,
        amount: Decimal,
        currency: str,
        description: str,
        redirect_url: str = None,
        webhook_url: str = None,
        metadata: Dict = None,
    ) -> Dict:
        """
        Create a payment

        Args:
            amount: Payment amount
            currency: Currency code
            description: Payment description
            redirect_url: URL to redirect after payment
            webhook_url: Webhook URL for notifications
            metadata: Additional metadata

        Returns:
            Dict with payment information
        """
        try:
            payment_data = {
                "amount": {"currency": currency, "value": str(amount)},
                "description": description,
                "redirectUrl": redirect_url or frappe.utils.get_url("/payment-success"),
                "webhookUrl": webhook_url or self.settings.get("webhook_url"),
                "metadata": metadata or {},
            }

            payment = self.client.payments.create(payment_data)

            return {
                "id": payment.id,
                "status": payment.status,
                "amount": str(payment.amount.value),
                "currency": payment.amount.currency,
                "checkout_url": payment.checkout_url,
                "created_at": payment.created_at,
            }

        except MollieError as e:
            frappe.log_error(f"Failed to create payment: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to create payment: {str(e)}")

    def get_payment(self, payment_id: str) -> Dict:
        """
        Get payment details

        Args:
            payment_id: Payment identifier

        Returns:
            Dict with payment information
        """
        try:
            payment = self.client.payments.get(payment_id)

            return {
                "id": payment.id,
                "status": payment.status,
                "amount": str(payment.amount.value),
                "currency": payment.amount.currency,
                "method": payment.method,
                "created_at": payment.created_at,
                "paid_at": payment.paid_at,
                "metadata": payment.metadata,
            }

        except MollieError as e:
            frappe.log_error(f"Failed to get payment: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get payment: {str(e)}")

    # Subscription Operations

    def create_subscription(
        self, customer_id: str, amount: Decimal, interval: str, description: str, start_date: datetime = None
    ) -> Dict:
        """
        Create a subscription

        Args:
            customer_id: Customer identifier
            amount: Subscription amount
            interval: Payment interval (e.g., "1 month")
            description: Subscription description
            start_date: Start date for subscription

        Returns:
            Dict with subscription information
        """
        try:
            customer = self.client.customers.get(customer_id)

            subscription_data = {
                "amount": {"currency": "EUR", "value": str(amount)},
                "interval": interval,
                "description": description,
            }

            if start_date:
                subscription_data["startDate"] = start_date.strftime("%Y-%m-%d")

            subscription = customer.subscriptions.create(subscription_data)

            return {
                "id": subscription.id,
                "status": subscription.status,
                "amount": str(subscription.amount.value),
                "interval": subscription.interval,
                "description": subscription.description,
                "created_at": subscription.created_at,
                "next_payment_date": subscription.next_payment_date,
            }

        except MollieError as e:
            frappe.log_error(f"Failed to create subscription: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to create subscription: {str(e)}")

    def cancel_subscription(self, customer_id: str, subscription_id: str) -> bool:
        """
        Cancel a subscription

        Args:
            customer_id: Customer identifier
            subscription_id: Subscription identifier

        Returns:
            True if cancelled successfully
        """
        try:
            customer = self.client.customers.get(customer_id)
            subscription = customer.subscriptions.get(subscription_id)
            subscription.delete()

            return True

        except MollieError as e:
            frappe.log_error(f"Failed to cancel subscription: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to cancel subscription: {str(e)}")

    # Chargeback Operations

    def get_chargebacks(self, payment_id: str = None) -> List[Dict]:
        """
        Get chargebacks for a payment or all chargebacks

        Args:
            payment_id: Optional payment identifier

        Returns:
            List of chargeback dictionaries
        """
        try:
            if payment_id:
                payment = self.client.payments.get(payment_id)
                chargebacks = payment.chargebacks.list()
            else:
                chargebacks = self.client.chargebacks.list()

            return [
                {
                    "id": chargeback.id,
                    "payment_id": chargeback.payment_id,
                    "amount": str(chargeback.amount.value),
                    "currency": chargeback.amount.currency,
                    "reason": chargeback.reason if hasattr(chargeback, "reason") else None,
                    "reversed_at": chargeback.reversed_at if hasattr(chargeback, "reversed_at") else None,
                    "created_at": chargeback.created_at,
                }
                for chargeback in chargebacks
            ]

        except MollieError as e:
            frappe.log_error(f"Failed to get chargebacks: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get chargebacks: {str(e)}")

    # Invoice Operations

    def list_invoices(self) -> List[Dict]:
        """
        List all invoices

        Returns:
            List of invoice dictionaries
        """
        try:
            invoices = self.client.invoices.list()

            return [
                {
                    "id": invoice.id,
                    "reference": invoice.reference,
                    "amount": {
                        "net": str(invoice.net_amount.value),
                        "vat": str(invoice.vat_amount.value),
                        "gross": str(invoice.gross_amount.value),
                        "currency": invoice.gross_amount.currency,
                    },
                    "status": invoice.status,
                    "issued_at": invoice.issued_at,
                    "due_at": invoice.due_at,
                }
                for invoice in invoices
            ]

        except MollieError as e:
            frappe.log_error(f"Failed to list invoices: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to list invoices: {str(e)}")

    def get_invoice(self, invoice_id: str) -> Dict:
        """
        Get invoice details

        Args:
            invoice_id: Invoice identifier

        Returns:
            Dict with invoice information
        """
        try:
            invoice = self.client.invoices.get(invoice_id)

            return {
                "id": invoice.id,
                "reference": invoice.reference,
                "amount": {
                    "net": str(invoice.net_amount.value),
                    "vat": str(invoice.vat_amount.value),
                    "gross": str(invoice.gross_amount.value),
                    "currency": invoice.gross_amount.currency,
                },
                "status": invoice.status,
                "issued_at": invoice.issued_at,
                "due_at": invoice.due_at,
                "lines": [
                    {
                        "description": line.description,
                        "quantity": line.quantity,
                        "amount": str(line.amount.value),
                        "vat_rate": line.vat_rate,
                    }
                    for line in invoice.lines
                ]
                if hasattr(invoice, "lines")
                else [],
            }

        except MollieError as e:
            frappe.log_error(f"Failed to get invoice: {str(e)}", "Mollie Connector")
            raise MollieIntegrationError(f"Failed to get invoice: {str(e)}")


# Singleton instance management
_connector_instances = {}


def get_mollie_connector(settings_name: str = None) -> MollieConnector:
    """
    Get or create Mollie connector instance

    Args:
        settings_name: Optional settings name

    Returns:
        MollieConnector instance
    """
    global _connector_instances

    key = settings_name or "default"

    if key not in _connector_instances:
        _connector_instances[key] = MollieConnector(settings_name)

    return _connector_instances[key]


# Frappe whitelisted methods for API access


@frappe.whitelist()
def test_mollie_connection(settings_name: str = None) -> Dict:
    """Test Mollie API connection"""
    try:
        connector = get_mollie_connector(settings_name)
        balances = connector.list_balances()

        return {
            "status": "success",
            "message": "Mollie API connection successful",
            "balances_count": len(balances),
            "test_mode": connector.settings["test_mode"],
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_account_balance(balance_id: str = "primary") -> Dict:
    """Get account balance"""
    try:
        connector = get_mollie_connector()
        return connector.get_balance(balance_id)

    except Exception as e:
        frappe.throw(str(e))


@frappe.whitelist()
def list_recent_settlements(days: int = 30) -> List[Dict]:
    """List recent settlements"""
    try:
        connector = get_mollie_connector()
        from_date = datetime.now() - timedelta(days=days)

        return connector.list_settlements(from_date=from_date)

    except Exception as e:
        frappe.throw(str(e))
