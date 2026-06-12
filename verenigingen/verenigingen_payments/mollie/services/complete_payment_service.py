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
from frappe.query_builder import DocType

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
    mollie_signature_date,
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

            customer_result = self._resolve_customer_by_email(customer_data)

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

            owner_doctype = customer_data.get("owner_doctype")
            owner_name = customer_data.get("owner_name")
            if owner_doctype and owner_name:
                return self._create_owner_subscription(
                    owner_doctype, owner_name, customer_data, subscription_data
                )
            return self._create_unowned_subscription(customer_data, subscription_data)

        except (MolliePaymentError, MollieValidationError):
            # Already a specific, well-typed Mollie error (mandate provisioning,
            # the subscription create itself, the enable_subscriptions gate, or
            # input validation) - propagate it with its own type and message so
            # callers like unified_payment_api can distinguish a validation
            # failure from a payment failure. Do not relabel or re-log it.
            raise
        except Exception as e:
            error_msg = f"Failed to create subscription: {e}"
            frappe.log_error(error_msg, "Subscription Creation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def _create_owner_subscription(
        self,
        owner_doctype: str,
        owner_name: str,
        customer_data: Dict[str, Any],
        subscription_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Create a subscription owned by a Member/Donor, holding a FOR UPDATE
        lock on the owner row for the whole operation.

        The lock blocks a concurrent create for the same owner: the second
        request waits, then sees the subscription the first one wrote and
        returns it instead of provisioning a duplicate at Mollie. An owner
        that already has a live subscription is likewise returned as-is.
        """
        if owner_doctype not in ("Member", "Donor"):
            raise MollieValidationError(f"Unsupported subscription owner doctype: {owner_doctype}")

        # Existence is checked before begin() so a "not found" raises cleanly
        # without a transaction having to be opened and torn down.
        if not frappe.db.exists(owner_doctype, owner_name):
            raise MollieValidationError(f"{owner_doctype} {owner_name} not found")

        # begin()/commit() bracket the row lock; every exit path commits or
        # rolls back so the lock is always released. The lock is held across
        # the Mollie API calls below - that is intentional: it only ever
        # blocks a concurrent create for the *same* owner, which is exactly
        # the duplicate this prevents.
        frappe.db.begin()
        try:
            owner = DocType(owner_doctype)
            locked_row = (
                frappe.qb.from_(owner)
                .select(owner.mollie_customer_id, owner.mollie_subscription_id)
                .where(owner.name == owner_name)
                .for_update()
                .run(as_dict=True)
            )
            if not locked_row:
                # Raced with a delete between the exists-check and the lock.
                raise MollieValidationError(f"{owner_doctype} {owner_name} not found")

            stored_customer_id = locked_row[0].get("mollie_customer_id")
            stored_subscription_id = locked_row[0].get("mollie_subscription_id")

            # Idempotent: an owner that already has a live (active/pending)
            # subscription gets that subscription back - no duplicate is
            # provisioned. Both ids must be present: a subscription id is only
            # usable together with its customer id.
            if stored_subscription_id and stored_customer_id:
                existing = self._get_active_subscription(stored_customer_id, stored_subscription_id)
                if existing is not None:
                    frappe.db.commit()
                    frappe.logger().info(
                        f"{owner_doctype} {owner_name} already has subscription {existing.id}"
                    )
                    return self._subscription_result(
                        stored_customer_id, existing, message="Subscription already exists"
                    )
            elif stored_subscription_id:
                # Subscription id without a customer id - the stored
                # subscription cannot be looked up. Surface it and provision
                # a fresh one rather than billing against an unknown customer.
                frappe.log_error(
                    f"{owner_doctype} {owner_name} has mollie_subscription_id "
                    f"{stored_subscription_id} but no mollie_customer_id; "
                    f"provisioning a fresh subscription.",
                    "Mollie Subscription Create",
                )

            customer_id = self._resolve_customer_id_locked(stored_customer_id, customer_data)
            mollie_subscription = self._provision_and_create_subscription(
                customer_id, customer_data, subscription_data
            )

            # The service owns the owning-DocType update.
            owner_values = {
                "mollie_customer_id": customer_id,
                "mollie_subscription_id": mollie_subscription.id,
                "subscription_status": mollie_subscription.status,
                "next_payment_date": getattr(mollie_subscription, "next_payment_date", None),
            }
            # Persist the pinned mandate so portal self-service (bank-account
            # update) can revoke it later. Only when present: a subscription
            # created without an IBAN pins no mandate, and overwriting an
            # existing value with NULL would lose information.
            mandate_id = getattr(mollie_subscription, "mandate_id", None)
            if mandate_id:
                owner_values["mollie_mandate_id"] = mandate_id
            self._update_owner_record(owner_doctype, owner_name, owner_values)
            frappe.db.commit()
            frappe.logger().info(f"✅ Subscription created: {mollie_subscription.id}")
            return self._subscription_result(customer_id, mollie_subscription)

        except (MolliePaymentError, MollieValidationError):
            frappe.db.rollback()
            raise
        except Exception as e:
            frappe.db.rollback()
            error_msg = f"Failed to create subscription: {e}"
            frappe.log_error(error_msg, "Subscription Creation Error")
            raise MolliePaymentError(error_msg, original_error=e)

    def _create_unowned_subscription(
        self, customer_data: Dict[str, Any], subscription_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a subscription with no explicit owner record (donation flow).

        The Mollie customer is resolved by Donor email; nothing is written
        back to a Frappe record here.
        """
        customer_result = self._resolve_customer_by_email(customer_data)
        if not customer_result.get("customer_id"):
            raise MolliePaymentError(
                f"Failed to create customer for subscription: {customer_result.get('error')}"
            )
        customer_id = customer_result["customer_id"]
        mollie_subscription = self._provision_and_create_subscription(
            customer_id, customer_data, subscription_data
        )
        frappe.logger().info(f"✅ Subscription created: {mollie_subscription.id}")
        return self._subscription_result(customer_id, mollie_subscription)

    def _provision_and_create_subscription(
        self, customer_id: str, customer_data: Dict[str, Any], subscription_data: Dict[str, Any]
    ) -> Any:
        """
        Provision a SEPA mandate from an IBAN (when `consumerAccount` is given)
        and create the Mollie subscription.

        A mandate is only provisioned when the customer does not already have
        a usable directdebit mandate for that IBAN - so a re-subscribe after a
        cancellation reuses the existing mandate instead of stacking a
        duplicate one at Mollie.

        The mandate is then pinned on the subscription via `mandateId`, so
        Mollie does not auto-select a different mandate the customer may
        still hold (e.g. an older one for a previous bank account).

        `consumerAccount` is mandate-only input - Mollie's subscription API
        does not accept it - so it is always stripped before the create.
        """
        consumer_account = subscription_data.get("consumerAccount")
        mandate_id = None
        if consumer_account:
            existing_mandate = self._find_usable_directdebit_mandate(customer_id, consumer_account)
            if existing_mandate is None:
                # No usable mandate for this IBAN - provision one. A mandate
                # created via the Mandates API with directdebit details is
                # valid immediately, so its id is safe to pin below.
                created = self.client.create_mandate(
                    customer_id,
                    {
                        "method": "directdebit",
                        "consumerName": customer_data.get("name", ""),
                        "consumerAccount": consumer_account,
                        # UTC date (see mollie_signature_date): Mollie 422s a future
                        # signature date, which site-local today() can produce east
                        # of Mollie's timezone.
                        "signatureDate": mollie_signature_date(),
                        "mandateReference": f"MANDATE-{frappe.utils.random_string(8)}",
                    },
                )
                mandate_id = getattr(created, "id", None)
                if mandate_id is None:
                    # Mollie returning a mandate object without an id should
                    # not happen, but if it does the subscription would fall
                    # through to no-pin and re-introduce the auto-select
                    # risk. Surface it loudly rather than silently degrade.
                    frappe.logger().warning(
                        f"Mollie created a mandate for customer {customer_id} "
                        f"without an id; subscription will be created without "
                        f"mandateId and risks auto-selecting a stale mandate."
                    )
            else:
                # Reuse the existing mandate. Both `valid` and `pending` are
                # pinned: pinning `pending` does not bill yet, but it prevents
                # Mollie from auto-selecting an older valid mandate that may
                # exist for a previous IBAN (the bank-change wrong-account
                # risk). Mollie either accepts the pending mandate and waits
                # for it to become valid, or rejects the create with a clear
                # error - both beat silent wrong-account billing.
                mandate_id = getattr(existing_mandate, "id", None)

        if "consumerAccount" in subscription_data:
            subscription_data = {k: v for k, v in subscription_data.items() if k != "consumerAccount"}

        # Pin the mandate so Mollie cannot auto-select a different one (an
        # older mandate for a previous IBAN would otherwise bill the wrong
        # account). A caller-supplied mandateId is left untouched.
        if mandate_id and not subscription_data.get("mandateId"):
            subscription_data = {**subscription_data, "mandateId": mandate_id}

        # Without a mandate (no consumerAccount and none established via a
        # sequenceType="first" payment) Mollie rejects the create.
        try:
            return self.client.create_subscription(customer_id, subscription_data)
        except Exception as e:
            if "No suitable mandates found" in str(e):
                raise MolliePaymentError(
                    "Cannot create subscription: No mandate exists for customer. "
                    "For recurring donations, use create_recurring_donation_payment() "
                    "to establish mandate first with sequenceType='first' payment.",
                    original_error=e,
                )
            raise

    def _find_usable_directdebit_mandate(self, customer_id: str, iban: str) -> Optional[Any]:
        """
        Return the customer's SEPA directdebit mandate for this IBAN, or None.

        A `valid` mandate is preferred and returned as soon as one is found.
        A `pending` mandate (still being established) is returned only if no
        valid one exists. Both block provisioning a duplicate AND are pinned
        by the caller - pinning a pending mandate prevents Mollie from
        falling back to a stale valid mandate for a different IBAN.

        IBAN comparison ignores spacing and case. Fails open: if the mandate
        list cannot be retrieved, returns None so the caller still provisions
        a mandate rather than risking a subscription create with no mandate.
        """
        target = iban.replace(" ", "").upper()
        try:
            mandates = self.client.list_mandates(customer_id)
        except Exception as e:
            frappe.logger().warning(
                f"Could not list mandates for customer {customer_id}; " f"provisioning a mandate anyway: {e}"
            )
            return None

        pending_match = None
        for mandate in mandates:
            if getattr(mandate, "method", None) != "directdebit":
                continue
            status = getattr(mandate, "status", None)
            if status not in ("valid", "pending"):
                continue
            details = getattr(mandate, "details", None) or {}
            if isinstance(details, dict):
                existing = details.get("consumerAccount")
            else:
                existing = getattr(details, "consumerAccount", None)
            if not existing or existing.replace(" ", "").upper() != target:
                continue
            if status == "valid":
                return mandate
            pending_match = pending_match or mandate
        return pending_match

    def _resolve_customer_id_locked(
        self, stored_customer_id: Optional[str], customer_data: Dict[str, Any]
    ) -> str:
        """
        Resolve the Mollie customer id while the owner row is already locked:
        reuse the stored id if it still resolves at Mollie, otherwise create a
        fresh customer. No transaction control - the caller owns the lock.
        """
        if stored_customer_id:
            try:
                return self.client.get_customer(stored_customer_id).id
            except Exception as e:
                frappe.logger().warning(f"Stored Mollie customer {stored_customer_id} not retrievable: {e}")
                # Stale id - fall through and create a fresh customer.
        return self.client.create_customer(self._mollie_customer_payload(customer_data)).id

    def _get_active_subscription(self, customer_id: Optional[str], subscription_id: str) -> Optional[Any]:
        """
        Return the Mollie subscription if it still exists and is active or
        pending; otherwise None (so the caller provisions a fresh one).
        """
        try:
            subscription = self.client.get_subscription(customer_id, subscription_id)
        except Exception as e:
            frappe.logger().warning(f"Stored subscription {subscription_id} not retrievable: {e}")
            return None
        if getattr(subscription, "status", None) in ("active", "pending"):
            return subscription
        return None

    def _subscription_result(
        self,
        customer_id: Optional[str],
        mollie_subscription: Any,
        message: str = "Subscription created successfully",
    ) -> Dict[str, Any]:
        """Build the standard create-subscription result dict."""
        return {
            "status": "success",
            "customer_id": customer_id,
            "subscription_id": mollie_subscription.id,
            "subscription_status": mollie_subscription.status,
            "next_payment_date": getattr(mollie_subscription, "next_payment_date", None),
            "message": message,
        }

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
        self,
        customer_id: str,
        subscription_id: str,
        reason: str = "Customer request",
        owner_doctype: Optional[str] = None,
        owner_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel a subscription.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Subscription to cancel
            reason: Cancellation reason
            owner_doctype: Owning DocType ("Member"/"Donor"). When given with
                owner_name, the owning record is updated directly instead of
                being reverse-resolved from the (non-unique) subscription id.
            owner_name: Owning record name

        Returns:
            Dict with cancellation results
        """
        try:
            frappe.logger().info(f"❌ Cancelling subscription {subscription_id}")

            # Cancel in Mollie
            self.client.cancel_subscription(customer_id, subscription_id)

            # Flip the owning Member/Donor onto the cancelled status.
            self._update_subscription_status(subscription_id, "canceled", reason, owner_doctype, owner_name)

            frappe.logger().info(f"✅ Subscription cancelled: {subscription_id}")

            # Standard cancel result shape.
            return {
                "status": "success",
                "subscription_id": subscription_id,
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

    def _resolve_customer_by_email(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve the Mollie customer by Donor email - the fallback for donation
        flows that do not name an explicit owner record.

        Uses SELECT ... FOR UPDATE on the Donor row so concurrent requests for
        the same donor cannot create duplicate Mollie customers.
        """
        email = customer_data["email"]

        # Quick path: no Donor with this email -> no race, create without a lock.
        existing_donors = frappe.get_all(
            "Donor", filters={"donor_email": email}, fields=["name", "mollie_customer_id"]
        )
        if not existing_donors:
            return self._create_mollie_customer_only(customer_data)

        donor_name = existing_donors[0]["name"]

        # begin()/commit() bracket the row lock: commit()/rollback() release it.
        frappe.db.begin()
        try:
            donor = DocType("Donor")
            locked_row = (
                frappe.qb.from_(donor)
                .select(donor.mollie_customer_id)
                .where(donor.name == donor_name)
                .for_update()
                .run(as_dict=True)
            )

            if not locked_row:
                frappe.db.commit()
                return self._create_mollie_customer_only(customer_data)

            existing_customer_id = locked_row[0].get("mollie_customer_id")
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
                    # Stale id - fall through and create a fresh customer.

            customer = self.client.create_customer(self._mollie_customer_payload(customer_data))
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
        """Create a Mollie customer without recording it on any Frappe document."""
        try:
            customer = self.client.create_customer(self._mollie_customer_payload(customer_data))
            frappe.logger().info(f"Created new Mollie customer {customer.id} (no owner record)")
            return {"status": "created", "customer_id": customer.id}
        except Exception as e:
            error_msg = f"Failed to create Mollie customer: {e}"
            frappe.log_error(error_msg, "Mollie Customer Error")
            return create_error_response(error_msg)

    def _mollie_customer_payload(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """Build the customer dict passed to the Mollie SDK (name/email/locale/metadata)."""
        payload = {
            "name": customer_data.get("name", ""),
            "email": customer_data["email"],
        }
        if customer_data.get("locale"):
            payload["locale"] = customer_data["locale"]
        if customer_data.get("metadata"):
            payload["metadata"] = customer_data["metadata"]
        return payload

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

    def _update_subscription_status(
        self,
        subscription_id: str,
        status: str,
        reason: str = "",
        owner_doctype: Optional[str] = None,
        owner_name: Optional[str] = None,
    ) -> None:
        """
        Flip the owning Member/Donor's subscription status after a cancel.

        When the owner is known (the caller had the record in hand) it is used
        directly. Otherwise the owner is reverse-resolved by
        `mollie_subscription_id` - Member before Donor - which is best-effort:
        `mollie_subscription_id` carries no uniqueness constraint, so a missing
        match is logged as an error rather than passing silently.
        """
        cancel_values = {
            "subscription_status": status,
            "subscription_cancelled_date": frappe.utils.today(),
        }

        if owner_doctype and owner_name:
            self._update_owner_record(owner_doctype, owner_name, cancel_values)
            frappe.logger().info(
                f"{owner_doctype} {owner_name}: subscription {subscription_id} -> {status} ({reason})"
            )
            return

        for candidate_doctype in ("Member", "Donor"):
            candidate_name = frappe.db.get_value(
                candidate_doctype, {"mollie_subscription_id": subscription_id}, "name"
            )
            if candidate_name:
                self._update_owner_record(candidate_doctype, candidate_name, cancel_values)
                frappe.logger().info(
                    f"{candidate_doctype} {candidate_name}: subscription "
                    f"{subscription_id} -> {status} ({reason})"
                )
                return

        # The Mollie-side cancel succeeded but no local record was updated -
        # surface it so the inconsistency can be reconciled.
        frappe.log_error(
            f"Cancelled Mollie subscription {subscription_id} but found no owning "
            f"Member/Donor to update (reason: {reason})",
            "Mollie Subscription Cancel",
        )

    def _update_owner_record(self, owner_doctype: str, owner_name: str, values: Dict[str, Any]) -> None:
        """
        Write subscription fields onto a Member/Donor record.

        Any field the DocType does not define is skipped - Donor, unlike
        Member, has no subscription_status / next_payment_date fields.
        """
        meta = frappe.get_meta(owner_doctype)
        payload = {key: value for key, value in values.items() if meta.has_field(key)}
        if payload:
            frappe.db.set_value(owner_doctype, owner_name, payload, update_modified=False)

    def get_client_info(self) -> Dict[str, Any]:
        """Get information about the Mollie client configuration."""
        return {
            "is_test_mode": self.client.is_test_mode(),
            "webhook_url": self.client.get_webhook_url(),
            "api_key_type": "test" if self.client.is_test_mode() else "live",
        }
