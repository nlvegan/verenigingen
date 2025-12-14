"""
Mollie Subscription Service

Business logic for managing recurring payments and subscriptions through Mollie.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import add_months, getdate, now_datetime

from ..core.client import MollieClient
from ..core.mollie_models import Money, Subscription
from ..exceptions import MollieIntegrationError, MollieValidationError
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

    def create_membership_subscription(
        self, member_id: str, monthly_fee: Union[Decimal, float], start_date: Optional[str] = None
    ) -> Subscription:
        """
        Create a recurring subscription for membership dues.

        Args:
            member_id: Frappe member document ID
            monthly_fee: Monthly membership fee in EUR
            start_date: Optional start date (defaults to next month)

        Returns:
            Created subscription object

        Raises:
            MollieValidationError: If subscription data is invalid
            MollieIntegrationError: If subscription creation fails
        """
        # Validate member and fee
        member = frappe.get_doc("Member", member_id)
        if not self.validator.validate_amount(monthly_fee):
            raise MollieValidationError(f"Invalid monthly fee: {monthly_fee}")

        # Ensure member has Mollie customer ID
        customer_id = self._ensure_customer_exists(member)

        # Validate SEPA mandate if required
        if not self._has_valid_mandate(member):
            raise MollieValidationError(f"Member {member_id} does not have a valid SEPA mandate")

        # Create subscription
        money = Money(amount=Decimal(str(monthly_fee)), currency="EUR")
        subscription = self.client.create_subscription(
            customer_id=customer_id,
            amount=money,
            interval="1 month",
            description=f"Membership dues - {member.first_name} {member.last_name}",
            webhook_url=self._get_webhook_url(),
            metadata={
                "member_id": member_id,
                "subscription_type": "membership_dues",
                "start_date": start_date or str(getdate()),
            },
        )

        # Update member record
        self._update_member_subscription_info(member, subscription)

        return subscription

    def create_donation_subscription(
        self, donor_id: str, monthly_amount: Union[Decimal, float], interval: str = "1 month"
    ) -> Subscription:
        """
        Create a recurring subscription for donations.

        Args:
            donor_id: Frappe donor document ID
            monthly_amount: Monthly donation amount in EUR
            interval: Payment interval (e.g., "1 month", "3 months")

        Returns:
            Created subscription object
        """
        # Validate donor and amount
        donor = frappe.get_doc("Donor", donor_id)
        if not self.validator.validate_amount(monthly_amount):
            raise MollieValidationError(f"Invalid donation amount: {monthly_amount}")

        # Ensure donor has Mollie customer ID
        customer_id = self._ensure_donor_customer_exists(donor)

        # Create subscription
        money = Money(amount=Decimal(str(monthly_amount)), currency="EUR")
        subscription = self.client.create_subscription(
            customer_id=customer_id,
            amount=money,
            interval=interval,
            description=f"Recurring donation - {donor.donor_name}",
            webhook_url=self._get_webhook_url(),
            metadata={"donor_id": donor_id, "subscription_type": "recurring_donation", "interval": interval},
        )

        # Update donor record
        self._update_donor_subscription_info(donor, subscription)

        return subscription

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

    def _ensure_customer_exists(self, member) -> str:
        """Ensure member has a Mollie customer ID."""
        if member.mollie_customer_id:
            return member.mollie_customer_id

        # Create new customer
        customer = self.client.create_customer(
            name=f"{member.first_name} {member.last_name}".strip(),
            email=member.email,
            metadata={"member_id": member.name},
        )

        # Update member record
        member.mollie_customer_id = customer.id
        member.save(ignore_permissions=True)

        return customer.id

    def _ensure_donor_customer_exists(self, donor) -> str:
        """Ensure donor has a Mollie customer ID."""
        if donor.mollie_customer_id:
            return donor.mollie_customer_id

        # Create new customer
        customer = self.client.create_customer(
            name=donor.donor_name or "",
            email=donor.donor_email,
            metadata={"donor_id": donor.name},
        )

        # Update donor record
        donor.mollie_customer_id = customer.id
        donor.save(ignore_permissions=True)

        return customer.id

    def _has_valid_mandate(self, member) -> bool:
        """Check if member has a valid SEPA mandate."""
        # This would integrate with existing SEPA mandate validation
        return bool(member.get("sepa_mandate_reference"))

    def _get_webhook_url(self) -> str:
        """Get webhook URL for subscription notifications."""
        mollie_settings = frappe.get_single("Mollie Settings")
        return (
            mollie_settings.webhook_url
            or f"{frappe.utils.get_url()}/api/method/verenigingen.integrations.mollie.api.webhooks.handle_subscription_webhook"
        )

    def _update_member_subscription_info(self, member, subscription: Subscription):
        """Update member record with subscription information."""
        member.mollie_subscription_id = subscription.id
        member.subscription_status = subscription.status
        member.next_payment_date = subscription.next_payment_date
        member.save(ignore_permissions=True)

    def _update_donor_subscription_info(self, donor, subscription: Subscription):
        """Update donor record with subscription information."""
        donor.mollie_subscription_id = subscription.id
        donor.subscription_status = subscription.status
        donor.next_payment_date = subscription.next_payment_date
        donor.save(ignore_permissions=True)

    def _update_member_subscription_canceled(self, member_id: str, subscription_id: str, reason: str):
        """Update member record when subscription is canceled."""
        member = frappe.get_doc("Member", member_id)
        member.subscription_status = "canceled"
        member.subscription_cancel_reason = reason
        member.subscription_canceled_at = now_datetime()
        member.save(ignore_permissions=True)

    def _update_donor_subscription_canceled(self, donor_id: str, subscription_id: str, reason: str):
        """Update donor record when subscription is canceled."""
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
