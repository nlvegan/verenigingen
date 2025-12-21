"""
Donation Lookup Handler for Mollie Payment Processing

Extracts donation discovery and payment routing logic from payment_webhook.py
into a dedicated handler for better separation of concerns and maintainability.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import frappe
from frappe import _


class DonationLookup:
    """
    Handler for finding and matching donations to Mollie payments.

    This handler encapsulates the logic for:
    - Finding donations by payment ID
    - Finding donations for subscription payments
    - Checking payment processing status (idempotency)
    - Fallback matching by customer + timestamp
    """

    def find_for_subscription_payment(
        self, payment_id: str, payment: Optional[Any] = None, with_lock: bool = False
    ) -> Optional[Any]:
        """
        Find donation record for subscription payments by looking at payment metadata.

        Args:
            payment_id: Mollie payment ID
            payment: Full Mollie payment object (can be None if not available yet)
            with_lock: If True, acquire FOR UPDATE lock

        Returns:
            Donation document or None if not found
        """
        # If payment object is available, check if this is a subscription payment
        if payment and (not hasattr(payment, "subscription_id") or not payment.subscription_id):
            return None

        # If payment object is available, get donation_id from payment metadata
        if payment:
            metadata = getattr(payment, "metadata", {})
            donation_id = metadata.get("donation_id")

            if donation_id:
                frappe.logger().info(f"Found donation_id in subscription payment metadata: {donation_id}")
                try:
                    if with_lock:
                        # Acquire row-level lock
                        frappe.db.sql(
                            "SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE",
                            (donation_id,),
                        )
                    return frappe.get_doc("Donation", donation_id)
                except frappe.DoesNotExistError:
                    frappe.logger().error(f"Donation {donation_id} from metadata not found")
                    return None

            # Fallback: try to find by subscription_id (if donation has it stored)
            frappe.logger().info(f"Trying fallback lookup by subscription_id: {payment.subscription_id}")
            donation_name = frappe.db.get_value(
                "Donation", {"mollie_subscription_id": payment.subscription_id}, "name"
            )
            if donation_name:
                if with_lock:
                    frappe.db.sql(
                        "SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE",
                        (donation_name,),
                    )
                return frappe.get_doc("Donation", donation_name)

        # If no payment object or no subscription info found, return None
        # This is normal for first payments that haven't been processed yet
        return None

    def find_by_payment_id(self, payment_id: str, with_lock: bool = False) -> Optional[Any]:
        """
        Find donation record by payment_id (primary matching only).

        Args:
            payment_id: Mollie payment ID
            with_lock: If True, acquire FOR UPDATE lock to prevent race conditions

        Returns:
            Donation document or None if not found
        """
        donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
        if donation_name:
            if with_lock:
                # Acquire row-level lock to prevent concurrent webhook processing
                frappe.db.sql(
                    "SELECT name FROM `tabDonation` WHERE name = %s FOR UPDATE",
                    (donation_name,),
                )
            return frappe.get_doc("Donation", donation_name)
        return None

    def find_for_payment(self, payment_id: str, payment: Any) -> Optional[Any]:
        """
        Find donation record for the given payment.

        Matching strategy:
        1. Primary: Match by donation.payment_id
        2. Fallback: Match by customer + timestamp window (for edge cases)

        Args:
            payment_id: Mollie payment ID
            payment: Mollie payment object

        Returns:
            Donation document or None if not found
        """
        # Primary matching: by payment_id
        donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
        if donation_name:
            return frappe.get_doc("Donation", donation_name)

        # Fallback matching: by customer ID and time window
        customer_id = getattr(payment, "customer_id", None)
        if not customer_id:
            return None

        # Get payment creation time
        payment_created = getattr(payment, "created_at", None)
        if not payment_created:
            return None

        # Convert to datetime if it's a string
        if isinstance(payment_created, str):
            try:
                payment_created = datetime.fromisoformat(payment_created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        # Search for donations within 30-minute window
        time_window_start = payment_created - timedelta(minutes=30)
        time_window_end = payment_created + timedelta(minutes=30)

        donations = frappe.get_all(
            "Donation",
            filters={
                "mollie_customer_id": customer_id,
                "creation": ["between", [time_window_start, time_window_end]],
                "paid": 0,  # Only unpaid donations
            },
            order_by="creation desc",
            limit=1,
        )

        if donations:
            frappe.logger().info(f"Found donation via customer+timestamp fallback: {donations[0].name}")
            return frappe.get_doc("Donation", donations[0].name)

        return None

    def check_processing_status(self, donation: Any, payment_id: str) -> Dict[str, Any]:
        """
        Check the processing status of each component with isolated idempotency checks.

        Returns dict with status of:
        - payment_entry_created: Whether Payment Entry exists for this transaction ID
        - payment_history_exists: Whether payment history record exists for this transaction
        - donation_status_updated: Whether donation status is properly set
        - all_complete: Whether all components are processed

        Args:
            donation: Donation document
            payment_id: Mollie payment ID

        Returns:
            Dict with processing status details
        """
        # Check 1: Payment Entry using unified idempotency manager
        from verenigingen.verenigingen_payments.mollie.services.unified_idempotency_manager import (
            get_unified_idempotency_manager,
        )

        idempotency_manager = get_unified_idempotency_manager()
        payment_entry = idempotency_manager.payment_entry_exists(payment_id)
        payment_entry_created = bool(payment_entry)

        # Check 2: Payment History (isolated check - only looks for history with this transaction)
        payment_history_exists = False
        if hasattr(donation, "payments") and donation.payments:
            for payment_record in donation.payments:
                # Check multiple possible field names for transaction ID
                if (
                    getattr(payment_record, "mollie_payment_id", None) == payment_id
                    or getattr(payment_record, "payment_reference", None) == payment_id
                    or getattr(payment_record, "payment_id", None) == payment_id
                ):
                    payment_history_exists = True
                    break

        # Check 3: Donation Status (isolated check - only verifies status is not "Promised")
        donation_status_updated = donation.status in ["One-time", "Recurring"]

        all_complete = payment_entry_created and payment_history_exists and donation_status_updated

        return {
            "payment_entry_created": payment_entry_created,
            "payment_history_exists": payment_history_exists,
            "donation_status_updated": donation_status_updated,
            "payment_entry_name": payment_entry if payment_entry_created else None,
            "donation_history_updated": payment_history_exists,
            "all_complete": all_complete,
        }


# Standalone functions for backward compatibility


def find_donation_for_subscription_payment(
    payment_id: str, payment: Optional[Any] = None, with_lock: bool = False
) -> Optional[Any]:
    """
    Find donation record for subscription payments by looking at payment metadata.

    This is a standalone function for backward compatibility.
    """
    lookup = DonationLookup()
    return lookup.find_for_subscription_payment(payment_id, payment, with_lock)


def find_donation_for_payment_by_id(payment_id: str, with_lock: bool = False) -> Optional[Any]:
    """
    Find donation record by payment_id (primary matching only).

    This is a standalone function for backward compatibility.
    """
    lookup = DonationLookup()
    return lookup.find_by_payment_id(payment_id, with_lock)


def find_donation_for_payment(payment_id: str, payment: Any) -> Optional[Any]:
    """
    Find donation record for the given payment.

    This is a standalone function for backward compatibility.
    """
    lookup = DonationLookup()
    return lookup.find_for_payment(payment_id, payment)


def check_payment_processing_status(donation: Any, payment_id: str) -> Dict[str, Any]:
    """
    Check the processing status of each component with isolated idempotency checks.

    This is a standalone function for backward compatibility.
    """
    lookup = DonationLookup()
    return lookup.check_processing_status(donation, payment_id)
