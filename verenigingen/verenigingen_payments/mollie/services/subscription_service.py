"""
Mollie Subscription Service

Business logic for managing recurring payments and subscriptions through Mollie.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from ..core.client import MollieClient
from ..core.mollie_models import Subscription
from ..exceptions import MollieIntegrationError
from ..utils.amount_helpers import extract_amount_currency, extract_amount_float
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

    def cancel_subscription(self, customer_id: str, subscription_id: str, reason: str = "") -> Subscription:
        """
        Cancel a subscription.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID
            reason: Optional cancellation reason

        Returns:
            Canceled subscription object
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

        return subscription

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
