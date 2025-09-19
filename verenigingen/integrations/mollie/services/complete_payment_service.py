"""
Complete Mollie Payment Service

A comprehensive service layer that provides all payment operations needed by the
Verenigingen application. This service encapsulates the business logic for:
- Single payment creation
- Subscription management
- Customer management
- Payment processing and reconciliation

This replaces the scattered payment handling logic with a clean, testable service.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import frappe

from ..core.client import MollieClient
from ..exceptions import MolliePaymentError, MollieValidationError, MollieWebhookError
from .webhook_wrapper_service import WebhookWrapperService


class CompletePaymentService:
    """
    Complete payment service that handles all Mollie operations for the Verenigingen app.

    This service provides a clean interface for:
    - Creating payments for donations
    - Managing customer subscriptions
    - Processing webhooks
    - Handling payment reconciliation
    """

    def __init__(self, client: Optional[MollieClient] = None):
        """
        Initialize the payment service.

        Args:
            client: Optional MollieClient (for dependency injection in tests)
        """
        self.client = client or MollieClient()
        self.webhook_service = WebhookWrapperService()

    def create_donation_payment(self, donation_doc: Any, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single payment for a donation.

        Args:
            donation_doc: The Donation document
            form_data: Payment form data from frontend

        Returns:
            Dict with payment creation results

        Raises:
            MolliePaymentError: When payment creation fails
        """
        try:
            frappe.logger().info(f"💰 Creating payment for donation {donation_doc.name}")

            # Validate donation and form data
            self._validate_donation_payment_data(donation_doc, form_data)

            # Prepare payment data for Mollie
            payment_data = self._prepare_payment_data(donation_doc, form_data)

            # Create payment in Mollie
            mollie_payment = self.client.create_payment(payment_data)

            # Update donation with Mollie payment details
            self._update_donation_with_payment(donation_doc, mollie_payment)

            frappe.logger().info(f"✅ Payment created: {mollie_payment.id}")

            return {
                "status": "redirect_required",
                "payment_id": mollie_payment.id,
                "payment_url": mollie_payment.checkout_url,
                "checkout_url": mollie_payment.checkout_url,  # For compatibility
                "message": "Payment created successfully",
            }

        except Exception as e:
            error_msg = f"Failed to create payment for donation {donation_doc.name}: {e}"
            frappe.log_error(error_msg, "Payment Creation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def create_customer_subscription(
        self, customer_data: Dict[str, Any], subscription_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a customer and subscription for recurring payments.

        Args:
            customer_data: Customer information
            subscription_data: Subscription configuration

        Returns:
            Dict with customer and subscription details

        Raises:
            MolliePaymentError: When customer or subscription creation fails
        """
        try:
            frappe.logger().info(f"🔄 Creating customer subscription for {customer_data.get('email')}")

            # Validate input data
            self._validate_subscription_data(customer_data, subscription_data)

            # Create or get customer
            mollie_customer = self._create_or_get_customer(customer_data)

            # Create subscription
            mollie_subscription = self.client.create_subscription(mollie_customer.id, subscription_data)

            frappe.logger().info(f"✅ Subscription created: {mollie_subscription.id}")

            return {
                "status": "success",
                "customer_id": mollie_customer.id,
                "subscription_id": mollie_subscription.id,
                "subscription_status": mollie_subscription.status,
                "next_payment_date": getattr(mollie_subscription, "next_payment_date", None),
                "message": "Subscription created successfully",
            }

        except Exception as e:
            error_msg = f"Failed to create subscription: {e}"
            frappe.log_error(error_msg, "Subscription Creation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def process_webhook(self, payment_id: str, payment_data: Optional[Any] = None) -> Dict[str, Any]:
        """
        Process a webhook notification from Mollie.

        Args:
            payment_id: The Mollie payment ID
            payment_data: Optional payment object from webhook

        Returns:
            Dict with processing results
        """
        return self.webhook_service.process_webhook(payment_id, payment_data)

    def cancel_subscription(
        self, customer_id: str, subscription_id: str, reason: str = "Customer request"
    ) -> Dict[str, Any]:
        """
        Cancel a subscription.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Subscription to cancel
            reason: Cancellation reason

        Returns:
            Dict with cancellation results
        """
        try:
            frappe.logger().info(f"❌ Cancelling subscription {subscription_id}")

            # Cancel in Mollie
            cancelled_subscription = self.client.cancel_subscription(customer_id, subscription_id)

            # Update related documents
            self._update_subscription_status(subscription_id, "cancelled", reason)

            frappe.logger().info(f"✅ Subscription cancelled: {subscription_id}")

            return {
                "status": "success",
                "subscription_id": subscription_id,
                "cancelled_at": getattr(cancelled_subscription, "cancelled_at", None),
                "message": "Subscription cancelled successfully",
            }

        except Exception as e:
            error_msg = f"Failed to cancel subscription {subscription_id}: {e}"
            frappe.log_error(error_msg, "Subscription Cancellation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def get_payment_status(self, payment_id: str) -> Dict[str, Any]:
        """
        Get the current status of a payment.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Dict with payment status information
        """
        try:
            mollie_payment = self.client.get_payment(payment_id)

            return {
                "payment_id": payment_id,
                "status": mollie_payment.status,
                "amount": {
                    "value": mollie_payment.amount["value"],
                    "currency": mollie_payment.amount["currency"],
                },
                "description": mollie_payment.description,
                "created_at": mollie_payment.created_at,
                "paid_at": getattr(mollie_payment, "paid_at", None),
            }

        except Exception as e:
            error_msg = f"Failed to get payment status for {payment_id}: {e}"
            frappe.log_error(error_msg, "Payment Status Error")
            raise MolliePaymentError(error_msg, payment_id=payment_id, original_error=e)

    def _validate_donation_payment_data(self, donation_doc: Any, form_data: Dict[str, Any]) -> None:
        """Validate donation and form data for payment creation."""
        if not donation_doc:
            raise MollieValidationError("Donation document is required")

        if not form_data.get("amount") or float(form_data["amount"]) <= 0:
            raise MollieValidationError("Valid amount is required")

        if not form_data.get("currency"):
            raise MollieValidationError("Currency is required")

        if not form_data.get("return_url"):
            raise MollieValidationError("Return URL is required")

    def _validate_subscription_data(
        self, customer_data: Dict[str, Any], subscription_data: Dict[str, Any]
    ) -> None:
        """Validate customer and subscription data."""
        if not customer_data.get("email"):
            raise MollieValidationError("Customer email is required")

        if not subscription_data.get("amount"):
            raise MollieValidationError("Subscription amount is required")

        if not subscription_data.get("interval"):
            raise MollieValidationError("Subscription interval is required")

        # Validate interval format (should be like "1 month", "3 months", "1 day")
        interval = subscription_data["interval"]
        if not self._is_valid_interval(interval):
            raise MollieValidationError(f"Invalid interval format: {interval}")

    def _is_valid_interval(self, interval: str) -> bool:
        """Validate subscription interval format."""
        valid_units = ["day", "days", "week", "weeks", "month", "months"]
        parts = interval.lower().split()

        if len(parts) != 2:
            return False

        try:
            int(parts[0])  # Number part
            return parts[1] in valid_units  # Unit part
        except ValueError:
            return False

    def _prepare_payment_data(self, donation_doc: Any, form_data: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare payment data for Mollie API."""
        amount_str = f"{float(form_data['amount']):.2f}"

        payment_data = {
            "amount": {"currency": form_data["currency"], "value": amount_str},
            "description": f"Donation {donation_doc.name}",
            "redirectUrl": form_data["return_url"],
            "webhookUrl": self.client.get_webhook_url(),
            "metadata": {
                # Webhook handler expects donation-first flow format
                "reference_doctype": "Donation",
                "reference_docname": donation_doc.name,
                # Keep original fields for backward compatibility
                "donation_id": donation_doc.name,
                "donor_email": getattr(donation_doc, "donor_email", ""),
                "donation_type": getattr(donation_doc, "donation_type", "general"),
            },
        }

        # Add optional payment method restrictions
        if form_data.get("method"):
            payment_data["method"] = form_data["method"]

        # Add sequence type for recurring payments (mandate creation)
        if form_data.get("sequenceType"):
            payment_data["sequenceType"] = form_data["sequenceType"]

        # Merge any additional metadata from form_data
        if form_data.get("metadata"):
            payment_data["metadata"].update(form_data["metadata"])

        return payment_data

    def _create_or_get_customer(self, customer_data: Dict[str, Any]) -> Any:
        """Create a new customer or get existing one."""
        # For now, always create a new customer
        # TODO: Add logic to check for existing customers by email
        mollie_customer_data = {"name": customer_data.get("name", ""), "email": customer_data["email"]}

        if customer_data.get("locale"):
            mollie_customer_data["locale"] = customer_data["locale"]

        return self.client.create_customer(mollie_customer_data)

    def _update_donation_with_payment(self, donation_doc: Any, mollie_payment: Any) -> None:
        """Update donation document with Mollie payment details."""
        donation_doc.db_set("payment_id", mollie_payment.id)
        # Note: payment_status and payment_url fields don't exist in current Donation DocType schema
        # The payment_id is sufficient for tracking and webhook processing

        # Save payment amount in case it differs from requested amount
        payment_amount = float(mollie_payment.amount["value"])
        if abs(payment_amount - float(donation_doc.amount)) > 0.01:
            frappe.logger().warning(
                f"Payment amount {payment_amount} differs from donation amount {donation_doc.amount}"
            )

    def _update_subscription_status(self, subscription_id: str, status: str, reason: str = "") -> None:
        """Update subscription status in related documents."""
        # TODO: Implement updating Member, Donor, or other relevant documents
        # that track subscription status
        frappe.logger().info(f"Subscription {subscription_id} status updated to {status}: {reason}")

    def get_client_info(self) -> Dict[str, Any]:
        """Get information about the Mollie client configuration."""
        return {
            "is_test_mode": self.client.is_test_mode(),
            "webhook_url": self.client.get_webhook_url(),
            "api_key_type": "test" if self.client.is_test_mode() else "live",
        }
