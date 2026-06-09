"""
Mollie Subscription Service

Business logic for managing recurring payments and subscriptions through Mollie.
"""

import logging
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
    AuditEventType,
    AuditSeverity,
    get_audit_trail,
)

from ..core.client import MollieClient
from ..exceptions import MollieIntegrationError
from ..utils.amount_helpers import extract_amount_currency, extract_amount_float
from ..utils.common_helpers import create_success_response, format_mollie_response_amount
from ..utils.validators import PaymentDataValidator


class SubscriptionService:
    """
    Service for managing Mollie subscriptions and recurring payments.

    Handles:
    - Subscription creation and management
    - Recurring donation processing
    - Membership dues automation
    - Subscription status tracking
    """

    def __init__(self, client: Optional[MollieClient] = None):
        """
        Initialize subscription service.

        Args:
            client: Optional Mollie client (for dependency injection/testing)
        """
        self.client = client or MollieClient()
        self.validator = PaymentDataValidator()
        # Audit trail + logger for operator/portal-initiated subscription mutations
        # (list, cancel, mandate switch) relocated here from MollieDebugService so
        # production callers no longer depend on the debug-named service.
        self.audit_trail = get_audit_trail()
        self.logger = logging.getLogger("verenigingen.services.MollieSubscriptionService")

    def get_subscription_status(self, customer_id: str, subscription_id: str) -> Dict[str, Any]:
        """
        Get current subscription status from Mollie.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID

        Returns:
            Subscription status information
        """
        subscription = self.client.get_subscription(customer_id, subscription_id)

        return {
            "id": subscription.id,
            "customer_id": subscription.customer_id,
            "status": subscription.status,
            "amount": extract_amount_float(subscription.amount),
            "currency": extract_amount_currency(subscription.amount),
            "interval": subscription.interval,
            "next_payment_date": subscription.next_payment_date,
            "is_active": subscription.status == "active",
            "is_canceled": subscription.status in ["canceled", "suspended", "completed"],
            "description": subscription.description,
            "metadata": subscription.metadata,
        }

    def cancel_subscription(self, customer_id: str, subscription_id: str, reason: str = "") -> Dict[str, Any]:
        """
        Cancel a subscription.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID
            reason: Optional cancellation reason

        Returns:
            Standard cancel result dict: {status, subscription_id, message}
        """
        subscription = self.client.cancel_subscription(customer_id, subscription_id)

        # Update related records based on subscription type
        subscription_type = subscription.metadata.get("subscription_type")

        if subscription_type == "membership_dues":
            member_id = subscription.metadata.get("member_id")
            if member_id:
                self._update_member_subscription_canceled(member_id, subscription_id, reason)

        elif subscription_type == "recurring_donation":
            donor_id = subscription.metadata.get("donor_id")
            if donor_id:
                self._update_donor_subscription_canceled(donor_id, subscription_id, reason)

        return {
            "status": "success",
            "subscription_id": subscription_id,
            "message": "Subscription cancelled successfully",
        }

    def process_subscription_payment(self, payment_id: str) -> Dict[str, Any]:
        """
        Process a payment from a subscription.

        Args:
            payment_id: Mollie payment ID from subscription

        Returns:
            Processing result
        """
        payment = self.client.get_payment(payment_id)

        if payment.status != "paid":
            raise MollieIntegrationError(f"Subscription payment {payment_id} is not paid")

        # Determine subscription type from metadata or customer
        customer_id = payment.customer_id
        if not customer_id:
            raise MollieIntegrationError(f"No customer ID in payment {payment_id}")

        # Find the subscription this payment belongs to
        subscription_info = self._find_subscription_for_payment(customer_id, payment)

        if subscription_info["type"] == "membership_dues":
            return self._process_membership_subscription_payment(payment, subscription_info)
        elif subscription_info["type"] == "recurring_donation":
            return self._process_donation_subscription_payment(payment, subscription_info)
        else:
            raise MollieIntegrationError(f"Unknown subscription type: {subscription_info['type']}")

    def list_member_subscriptions(self, member_id: str) -> List[Dict[str, Any]]:
        """
        List all subscriptions for a member.

        Args:
            member_id: Frappe member document ID

        Returns:
            List of subscription information
        """
        member = frappe.get_doc("Member", member_id)

        if not member.mollie_customer_id:
            return []

        # This would need to be implemented with proper API pagination
        # For now, return basic info from member record
        subscriptions = []

        if member.mollie_subscription_id:
            try:
                subscription = self.client.get_subscription(
                    member.mollie_customer_id, member.mollie_subscription_id
                )
                subscriptions.append(
                    {
                        "id": subscription.id,
                        "type": "membership_dues",
                        "status": subscription.status,
                        "amount": extract_amount_float(subscription.amount),
                        "next_payment_date": subscription.next_payment_date,
                    }
                )
            except Exception as e:
                frappe.log_error(f"Failed to get subscription {member.mollie_subscription_id}: {e}")

        return subscriptions

    def list_subscriptions(self, customer_id: str, limit: int = 50, active_only: bool = True):
        """
        List subscriptions for a specific customer with optional status filtering.

        Args:
            customer_id: Mollie customer ID (required)
            limit: Maximum number of subscriptions to return (1-250, default 50)
            active_only: If True, only return active subscriptions (default True)

        Returns:
            Dict containing:
                - subscriptions: List of subscription details. Each carries a
                  structured ``amount_value`` (float) + ``currency`` (str) as well
                  as a human-readable ``amount`` string ("EUR 25.00") for display.
                - total_found: Number of subscriptions returned
                - customer_id: Customer ID queried
                - error: Error message if failed

        Raises:
            ValueError: If customer_id is empty.

        Note:
            Filtering by active_only happens client-side after fetching from Mollie API,
            as the Mollie subscriptions.list() endpoint doesn't support status filtering.
        """
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        # Validate and sanitize limit
        try:
            limit = int(limit)
            if not 1 <= limit <= 250:
                limit = 50
        except (ValueError, TypeError):
            limit = 50

        result = {
            "test_mode": self.client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customer_id": customer_id,
            "active_only": active_only,
            "limit": limit,
            "subscriptions": [],
            "total_found": 0,
            "error": None,
        }

        try:
            client = self.client.sdk_client

            # List subscriptions for specific customer
            customer = client.customers.get(customer_id)
            subscriptions = customer.subscriptions.list(limit=limit)

            # Process and filter subscriptions
            for sub in subscriptions:
                # Filter by status if active_only
                if active_only and sub.status != "active":
                    continue

                result["subscriptions"].append(
                    {
                        "id": sub.id,
                        "customer_id": (
                            getattr(sub, "_links", {}).get("customer", {}).get("href", "").split("/")[-1]
                            if hasattr(sub, "_links")
                            else customer_id
                        ),
                        "status": sub.status,
                        # Structured amount for programmatic callers (no string round-trip)...
                        "amount_value": extract_amount_float(sub.amount),
                        "currency": extract_amount_currency(sub.amount),
                        # ...plus a human-readable string for logs/debug display.
                        "amount": format_mollie_response_amount(sub.amount),
                        "interval": sub.interval,
                        "description": sub.description,
                        "created_at": str(sub.created_at),
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

                # Respect limit
                if len(result["subscriptions"]) >= limit:
                    break

            result["total_found"] = len(result["subscriptions"])

        except Exception as e:
            error_msg = str(e)

            # Provide helpful context for "customer not found" errors
            if "No customer exists" in error_msg:
                current_mode = "test" if self.client.is_test_mode() else "live"
                sanitized_error = (
                    f"Customer {customer_id} not found in {current_mode} mode. "
                    f"This may indicate: 1) Customer ID from different Mollie account, "
                    f"2) Customer deleted in Mollie dashboard, or 3) Wrong API credentials configured."
                )
            else:
                sanitized_error = self._sanitize_error_message(error_msg)

            result["error"] = sanitized_error
            self.logger.error(
                f"Mollie list subscriptions error for customer {customer_id}: {error_msg}. "
                f"Mode: {self.client.is_test_mode()} (Mollie Customer Error)"
            )

        return result

    def admin_cancel_subscription(self, customer_id, subscription_id, reason="Administrative cancellation"):
        """Cancel a subscription on behalf of an operator/portal action, with audit trail.

        Distinct from ``cancel_subscription`` (which derives member/donor updates from
        Mollie metadata): this performs a plain cancel + structured audit logging and
        gracefully reports already-cancelled subscriptions. Callers own any local
        record updates.
        """
        if not customer_id or not subscription_id:
            raise ValueError(_("Customer ID and Subscription ID are required"))

        if not reason:
            raise ValueError(_("Cancellation reason is required"))

        try:
            # Route through the standardised MollieClient wrapper rather than
            # the raw SDK, so this path cannot drift from the contract.
            # cancel_subscription raises MolliePaymentError on failure; the
            # except block below inspects its message for "already cancelled".
            self.client.cancel_subscription(customer_id, subscription_id)

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.WARNING,
                f"Cancelled subscription {subscription_id} for customer {customer_id}",
                details={
                    "action": "subscription_cancellation",
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "reason": reason,
                    "cancelled_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription_id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"SUBSCRIPTION CANCELLATION: User {frappe.session.user} cancelled subscription "
                f"{subscription_id} for customer {customer_id}. Reason: {reason}"
            )

            return create_success_response(
                "Subscription cancelled successfully",
                {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "cancelled_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            # Handle various "already cancelled" scenarios
            if any(
                phrase in error_message.lower()
                for phrase in [
                    "not found",
                    "does not exist",
                    "has been cancelled",
                    "already cancelled",
                    "cannot be cancelled",
                ]
            ):
                self.logger.info(
                    f"SUBSCRIPTION CANCELLATION ATTEMPT: User {frappe.session.user} attempted to cancel "
                    f"already-cancelled subscription {subscription_id} for customer {customer_id}. Reason: {reason}"
                )

                return {
                    "status": "warning",
                    "message": _("Subscription is already cancelled or cannot be cancelled"),
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": error_message,
                }
            else:
                raise api_error

    def update_subscription_mandate(
        self, customer_id, subscription_id, new_mandate_id, reason="Bank account update"
    ):
        """
        Update the mandate (bank account) for a subscription via Mollie PATCH API.

        Args:
            customer_id: Mollie customer ID (cst_xxx)
            subscription_id: Mollie subscription ID (sub_xxx)
            new_mandate_id: Mollie mandate ID to switch to (mdt_xxx)
            reason: Reason for the update (for audit trail)

        Returns:
            Dict with success/error status (via create_success_response)
        """
        if not customer_id or not subscription_id:
            raise ValueError(_("Customer ID and Subscription ID are required"))

        if not new_mandate_id:
            raise ValueError(_("New Mandate ID is required"))

        try:
            client = self.client.sdk_client
            customer_obj = client.customers.get(customer_id)

            # Verify subscription exists and capture old mandate ID
            current_subscription = customer_obj.subscriptions.get(subscription_id)
            old_mandate_id = getattr(current_subscription, "mandateId", None)

            # PATCH the subscription with the new mandate
            customer_obj.subscriptions.update(subscription_id, {"mandateId": new_mandate_id})

            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.INFO,
                f"Updated mandate for subscription {subscription_id}",
                details={
                    "action": "subscription_mandate_update",
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_mandate_id": old_mandate_id,
                    "new_mandate_id": new_mandate_id,
                    "reason": reason,
                    "updated_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription_id,
            )

            self.logger.info(
                f"MANDATE UPDATE: User {frappe.session.user} updated mandate for subscription "
                f"{subscription_id} (customer {customer_id}). Old: {old_mandate_id}, New: {new_mandate_id}"
            )

            return create_success_response(
                "Subscription mandate updated successfully",
                {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_mandate_id": old_mandate_id,
                    "new_mandate_id": new_mandate_id,
                    "updated_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            self.logger.error(
                f"MANDATE UPDATE FAILED: User {frappe.session.user} failed to update mandate for "
                f"subscription {subscription_id} (customer {customer_id}): {error_message}"
            )
            raise api_error

    def _sanitize_error_message(self, error_msg: str) -> str:
        """
        Sanitize error messages to prevent information disclosure.

        Uses centralized sanitize_error_for_audit utility with keyword filtering
        enabled to catch API keys, internal system info, and database details.
        """
        return (
            sanitize_error_for_audit(
                error_msg,
                max_length=500,
                remove_stack_trace=True,
                redact_pii=True,
                filter_sensitive_keywords=True,
                fallback_message="Internal error - contact administrator",
            )
            or error_msg
        )

    def _update_member_subscription_canceled(self, member_id: str, subscription_id: str, reason: str):
        """Update member record when subscription is canceled.

        Security: ignore_permissions acceptable - called from authenticated webhook or role-restricted sync API.
        """
        member = frappe.get_doc("Member", member_id)
        member.subscription_status = "canceled"
        member.subscription_cancel_reason = reason
        member.subscription_canceled_at = now_datetime()
        member.save(ignore_permissions=True)

    def _update_donor_subscription_canceled(self, donor_id: str, subscription_id: str, reason: str):
        """Update donor record when subscription is canceled.

        Security: ignore_permissions acceptable - called from authenticated webhook or role-restricted sync API.
        """
        donor = frappe.get_doc("Donor", donor_id)
        donor.subscription_status = "canceled"
        donor.subscription_cancel_reason = reason
        donor.subscription_canceled_at = now_datetime()
        donor.save(ignore_permissions=True)

    def _find_subscription_for_payment(self, customer_id: str, payment) -> Dict[str, Any]:
        """Find which subscription a payment belongs to."""
        # This is a simplified implementation
        # In reality, you'd need to match payments to subscriptions properly

        # Check if payment metadata indicates subscription type
        if "subscription_type" in payment.metadata:
            return {
                "type": payment.metadata["subscription_type"],
                "id": payment.metadata.get("subscription_id"),
                "customer_id": customer_id,
            }

        # Fallback: try to determine from customer metadata
        customer = self.client.get_customer(customer_id)
        if "member_id" in customer.metadata:
            return {"type": "membership_dues", "customer_id": customer_id}
        elif "donor_id" in customer.metadata:
            return {"type": "recurring_donation", "customer_id": customer_id}

        raise MollieIntegrationError(f"Cannot determine subscription type for payment {payment.id}")

    def _process_membership_subscription_payment(self, payment, subscription_info) -> Dict[str, Any]:
        """Process a membership subscription payment."""
        # This would integrate with existing membership payment processing
        return {
            "type": "membership_subscription",
            "payment_id": payment.id,
            "amount": extract_amount_float(payment.amount),
            "processed": True,
        }

    def _process_donation_subscription_payment(self, payment, subscription_info) -> Dict[str, Any]:
        """Process a donation subscription payment."""
        # This would integrate with existing donation processing
        return {
            "type": "donation_subscription",
            "payment_id": payment.id,
            "amount": extract_amount_float(payment.amount),
            "processed": True,
        }
