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

from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor

from ..core.client import MollieClient
from ..exceptions import MolliePaymentError, MollieValidationError, MollieWebhookError
from ..utils.common_helpers import (
    create_error_response,
    create_success_response,
    format_mollie_amount,
    format_mollie_amount_string,
    get_member_by_customer_id,
    merge_metadata_safely,
    validate_mollie_amount,
)
from .webhook_wrapper_service_unified import UnifiedWebhookWrapperService


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
        self.webhook_service = UnifiedWebhookWrapperService()

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
                "info": "You will be redirected to complete your payment securely",
            }

        except Exception as e:
            error_msg = f"Failed to create payment for donation {donation_doc.name}: {e}"
            frappe.log_error(error_msg, "Payment Creation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def create_recurring_donation_payment(
        self, donation_doc: Any, form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a recurring donation payment following the legacy pattern.

        Args:
            donation_doc: The Donation document
            form_data: Payment form data from frontend

        Returns:
            Dict with payment creation results
        """
        try:
            frappe.logger().info(f"🔄 Creating recurring donation payment for {donation_doc.name}")

            # Validate donation and form data
            self._validate_donation_payment_data(donation_doc, form_data)

            # Create or get customer first (critical for recurring payments)
            customer_data = {
                "email": form_data.get("donor_email", ""),
                "name": form_data.get("donor_name", ""),
                "locale": form_data.get("locale", "nl_NL"),
            }

            customer_result = self._create_or_get_customer(customer_data)

            if not customer_result.get("customer_id"):
                raise MolliePaymentError(
                    f"Failed to create customer for recurring payment: {customer_result.get('error')}"
                )

            # Prepare payment data for first payment in subscription
            payment_data = self._prepare_payment_data(donation_doc, form_data)

            # Add customer ID and subscription setup flag
            payment_data["customerId"] = customer_result["customer_id"]
            payment_data["sequenceType"] = "first"  # This creates the mandate

            # Add subscription metadata like legacy system
            payment_data["metadata"].update(
                {
                    "subscription_setup": "true",
                    "subscription_interval": form_data.get("subscription_interval", "1 month"),
                    "subscription_amount": format_mollie_amount_string(donation_doc.amount),
                    "customer_id": customer_result["customer_id"],
                }
            )

            # Create payment in Mollie
            mollie_payment = self.client.create_payment(payment_data)

            # Update donation with payment and customer details
            self._update_donation_with_payment(donation_doc, mollie_payment)

            # Store customer ID on donation for future reference
            donation_doc.db_set("mollie_customer_id", customer_result["customer_id"])

            frappe.logger().info(
                f"✅ Recurring payment created: {mollie_payment.id} with customer {customer_result['customer_id']}"
            )

            return {
                "status": "subscription_redirect_required",
                "payment_id": mollie_payment.id,
                "payment_url": mollie_payment.checkout_url,
                "checkout_url": mollie_payment.checkout_url,  # For compatibility
                "customer_id": customer_result["customer_id"],
                "message": "Setting up recurring donation",
                "info": "After this payment, you'll be charged automatically each period",
            }

        except Exception as e:
            error_msg = f"Failed to create recurring payment for donation {donation_doc.name}: {e}"
            frappe.log_error(error_msg, "Recurring Payment Creation Error")
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

            # Subscriptions must be enabled in Mollie Settings. Enforced here -
            # inside the standardised create contract - so that no caller wired
            # straight to this service can bypass the gate.
            if not frappe.db.get_single_value("Mollie Settings", "enable_subscriptions"):
                raise MollieValidationError("Subscriptions are not enabled in Mollie Settings")

            # Validate input data
            self._validate_subscription_data(customer_data, subscription_data)

            # Create or get customer
            customer_result = self._create_or_get_customer(customer_data)

            if not customer_result.get("customer_id"):
                raise MolliePaymentError(
                    f"Failed to create customer for subscription: {customer_result.get('error')}"
                )

            customer_id = customer_result["customer_id"]

            # Opt-in mandate provisioning: when an IBAN is supplied via
            # `consumerAccount`, provision a SEPA direct-debit mandate before
            # creating the subscription. This replaces the legacy
            # MollieSettings.create_subscription path (which always did this)
            # and keeps mandate provisioning an explicit, requested step
            # rather than a hidden side effect of "create subscription".
            consumer_account = subscription_data.get("consumerAccount")
            if consumer_account:
                mandate_data = {
                    "method": "directdebit",
                    "consumerName": customer_data.get("name", ""),
                    "consumerAccount": consumer_account,
                    "signatureDate": frappe.utils.today(),
                    "mandateReference": f"MANDATE-{frappe.utils.random_string(8)}",
                }
                self.client.create_mandate(customer_id, mandate_data)

            # consumerAccount is mandate-only input; Mollie's subscription API
            # does not accept it, so strip it before creating the subscription
            # (always - including the falsy "no IBAN" case).
            if "consumerAccount" in subscription_data:
                subscription_data = {k: v for k, v in subscription_data.items() if k != "consumerAccount"}

            # Create subscription. Without a mandate (no consumerAccount and
            # none established via a sequenceType="first" payment) Mollie
            # rejects this with "No suitable mandates found".
            try:
                mollie_subscription = self.client.create_subscription(customer_id, subscription_data)
            except Exception as e:
                if "No suitable mandates found" in str(e):
                    raise MolliePaymentError(
                        "Cannot create subscription: No mandate exists for customer. "
                        "For recurring donations, use create_recurring_donation_payment() "
                        "to establish mandate first with sequenceType='first' payment.",
                        original_error=e,
                    )
                raise

            frappe.logger().info(f"✅ Subscription created: {mollie_subscription.id}")

            return {
                "status": "success",
                "customer_id": customer_result["customer_id"],
                "subscription_id": mollie_subscription.id,
                "subscription_status": mollie_subscription.status,
                "next_payment_date": getattr(mollie_subscription, "next_payment_date", None),
                "message": "Subscription created successfully",
            }

        except MolliePaymentError:
            # Already a specific Mollie error (e.g. mandate provisioning or the
            # subscription create itself) - propagate it without relabelling it
            # as a generic "Failed to create subscription".
            raise
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

        # Use validate_mollie_amount for proper validation and error handling
        if not form_data.get("amount"):
            raise MollieValidationError("Amount is required")

        try:
            validate_mollie_amount(form_data["amount"])
        except ValueError as e:
            raise MollieValidationError(f"Invalid amount: {e}") from e

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

        # Mollie's subscription API requires `amount` as a {"value", "currency"}
        # dict, so callers pass that shape. Validate the numeric value out of it
        # (a bare scalar is also accepted for backward compatibility).
        amount = subscription_data["amount"]
        if isinstance(amount, dict):
            if "value" not in amount:
                raise MollieValidationError("Subscription amount dict must contain a 'value' key")
            amount_value = amount["value"]
        else:
            amount_value = amount
        try:
            validate_mollie_amount(amount_value)
        except (ValueError, TypeError) as e:
            raise MollieValidationError(f"Invalid subscription amount: {e}") from e

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
        # Core metadata (whitelisted, non-PII)
        base_metadata = {
            # Webhook handler expects donation-first flow format
            "reference_doctype": "Donation",
            "reference_docname": donation_doc.name,
            # Keep original fields for backward compatibility
            "donation_id": donation_doc.name,
            "donation_type": getattr(donation_doc, "donation_type", "general"),
        }

        # Safely merge any additional metadata from form_data
        # This applies key whitelisting and PII filtering
        sanitized_metadata = merge_metadata_safely(base_metadata, form_data.get("metadata"))

        payment_data = {
            "amount": format_mollie_amount(form_data["amount"], form_data["currency"]),
            "description": f"Donation {donation_doc.name}",
            "redirectUrl": form_data["return_url"],
            "webhookUrl": self.client.get_webhook_url(),
            "metadata": sanitized_metadata,
        }

        # Add optional payment method restrictions
        if form_data.get("method"):
            payment_data["method"] = form_data["method"]

        # Add sequence type for recurring payments (mandate creation)
        if form_data.get("sequenceType"):
            payment_data["sequenceType"] = form_data["sequenceType"]

        return payment_data

    def _create_or_get_customer(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new customer or get existing one with race condition protection.

        Uses SELECT FOR UPDATE to prevent duplicate customer creation when
        concurrent requests arrive for the same donor.
        """
        email = customer_data["email"]

        # First check without lock for quick path (most common case)
        existing_donors = frappe.get_all(
            "Donor", filters={"donor_email": email}, fields=["name", "mollie_customer_id"]
        )

        if not existing_donors:
            # No donor exists, create customer without lock (no race condition risk)
            # This is safe because we can't have a race condition for a non-existent donor
            return self._create_mollie_customer_only(customer_data)

        donor_name = existing_donors[0]["name"]

        # ===== ROW LOCKING FOR RACE CONDITION PREVENTION =====
        #
        # PROBLEM: Without locking, two concurrent requests for the same donor could both:
        #   1. Check mollie_customer_id (both see None)
        #   2. Create new Mollie customers (duplicate!)
        #   3. Save their customer ID (one gets overwritten)
        #
        # SOLUTION: Use SELECT ... FOR UPDATE to acquire an exclusive row lock
        #   - First request acquires lock, second request WAITS
        #   - After first request commits, second request sees the updated value
        #   - No duplicate Mollie customers created
        #
        # TRANSACTION SEMANTICS:
        #   - begin() starts transaction and creates savepoint
        #   - commit() persists changes AND releases the row lock
        #   - rollback() undoes changes AND releases the row lock
        #   - ALL exit paths must either commit() or rollback() to release the lock
        #
        frappe.db.begin()
        try:
            # Acquire row lock - other requests will wait here
            locked_row = frappe.db.sql(
                """
                SELECT mollie_customer_id FROM `tabDonor`
                WHERE name = %s FOR UPDATE
                """,
                donor_name,
                as_dict=True,
            )

            if not locked_row:
                frappe.db.commit()
                return self._create_mollie_customer_only(customer_data)

            existing_customer_id = locked_row[0].get("mollie_customer_id")

            # Check if customer already exists (may have been created by concurrent request)
            if existing_customer_id:
                try:
                    customer = self.client.get_customer(existing_customer_id)
                    frappe.db.commit()  # Release lock
                    frappe.logger().info(
                        f"Found existing Mollie customer {customer.id} for donor {donor_name}"
                    )
                    return {"status": "found", "customer_id": customer.id}
                except Exception as e:
                    frappe.logger().warning(
                        f"Existing customer ID {existing_customer_id} not found in Mollie: {e}"
                    )
                    # Continue to create new customer (stale ID case)

            # Create new customer in Mollie while holding the lock
            mollie_customer_data = {"name": customer_data.get("name", ""), "email": email}
            if customer_data.get("locale"):
                mollie_customer_data["locale"] = customer_data["locale"]
            if customer_data.get("metadata"):
                mollie_customer_data["metadata"] = customer_data["metadata"]

            customer = self.client.create_customer(mollie_customer_data)
            frappe.logger().info(f"Created new Mollie customer {customer.id}")

            # Update donor with new customer ID (still holding lock)
            frappe.db.set_value("Donor", donor_name, "mollie_customer_id", customer.id, update_modified=False)
            frappe.db.commit()  # Commit and release lock
            frappe.logger().info(f"Saved customer ID {customer.id} to donor {donor_name}")

            return {"status": "created", "customer_id": customer.id}

        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Failed to create or get Mollie customer: {e}"
            frappe.log_error(error_msg, "Mollie Customer Error")
            return create_error_response(error_msg)

    def _create_mollie_customer_only(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create Mollie customer without updating any Frappe document."""
        try:
            mollie_customer_data = {
                "name": customer_data.get("name", ""),
                "email": customer_data["email"],
            }
            if customer_data.get("locale"):
                mollie_customer_data["locale"] = customer_data["locale"]
            if customer_data.get("metadata"):
                mollie_customer_data["metadata"] = customer_data["metadata"]

            customer = self.client.create_customer(mollie_customer_data)
            frappe.logger().info(f"Created new Mollie customer {customer.id} (no donor)")
            return {"status": "created", "customer_id": customer.id}

        except Exception as e:
            error_msg = f"Failed to create Mollie customer: {e}"
            frappe.log_error(error_msg, "Mollie Customer Error")
            return create_error_response(error_msg)

    def _update_donation_with_payment(self, donation_doc: Any, mollie_payment: Any) -> None:
        """Update donation document with Mollie payment details."""
        donation_doc.db_set("payment_id", mollie_payment.id)
        # Note: payment_status and payment_url fields don't exist in current Donation DocType schema
        # The payment_id is sufficient for tracking and webhook processing

        # Save payment amount in case it differs from requested amount (use centralized extractor)
        extractor = get_payment_data_extractor()
        payment_amount = extractor.extract_amount(mollie_payment, allow_zero=False)
        # Use Decimal for precise comparison to avoid floating-point issues
        payment_decimal = Decimal(str(payment_amount))
        donation_decimal = Decimal(str(donation_doc.amount))
        if abs(payment_decimal - donation_decimal) > Decimal("0.01"):
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
