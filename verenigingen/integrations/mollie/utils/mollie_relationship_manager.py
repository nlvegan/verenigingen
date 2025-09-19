"""
Mollie Relationship Manager

Manages relationships between Mollie entities and local records.
Provides proper customer-member mapping and webhook queue management.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import now_datetime


class MollieRelationshipManager:
    """
    Manages relationships between Mollie customers/subscriptions and local records.
    """

    def __init__(self):
        self.cache = {}

    def find_member_by_customer_id(self, customer_id: str) -> Optional[str]:
        """Find member name by Mollie customer ID."""
        if not customer_id:
            return None

        # Check cache first
        cache_key = f"customer_{customer_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Query database
        member_name = frappe.db.get_value("Member", {"mollie_customer_id": customer_id}, "name")

        if member_name:
            self.cache[cache_key] = member_name

        return member_name

    def find_donor_by_customer_id(self, customer_id: str) -> Optional[str]:
        """Find donor name by Mollie customer ID."""
        if not customer_id:
            return None

        cache_key = f"donor_customer_{customer_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        donor_name = frappe.db.get_value("Donor", {"mollie_customer_id": customer_id}, "name")

        if donor_name:
            self.cache[cache_key] = donor_name

        return donor_name

    def find_donation_by_payment_id(self, payment_id: str) -> Optional[str]:
        """Find donation by Mollie payment ID."""
        if not payment_id:
            return None

        return frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")

    def link_customer_to_member(self, customer_id: str, member_name: str):
        """Link Mollie customer to member record."""
        member = frappe.get_doc("Member", member_name)
        member.mollie_customer_id = customer_id
        member.save(ignore_permissions=True)

        # Update cache
        self.cache[f"customer_{customer_id}"] = member_name

    def link_customer_to_donor(self, customer_id: str, donor_name: str):
        """Link Mollie customer to donor record."""
        donor = frappe.get_doc("Donor", donor_name)
        donor.mollie_customer_id = customer_id
        donor.save(ignore_permissions=True)

        # Update cache
        self.cache[f"donor_customer_{customer_id}"] = donor_name


class MollieWebhookQueue:
    """
    Manages webhook processing queue to prevent race conditions.
    """

    def __init__(self):
        self.processing = set()

    def is_processing(self, payment_id: str) -> bool:
        """Check if payment is currently being processed."""
        return payment_id in self.processing

    def start_processing(self, payment_id: str):
        """Mark payment as being processed."""
        self.processing.add(payment_id)

    def finish_processing(self, payment_id: str):
        """Mark payment processing as complete."""
        self.processing.discard(payment_id)

    def with_lock(self, payment_id: str):
        """Context manager for processing with lock."""

        class ProcessingLock:
            def __init__(self, queue, pid):
                self.queue = queue
                self.payment_id = pid

            def __enter__(self):
                if self.queue.is_processing(self.payment_id):
                    raise frappe.ValidationError(f"Payment {self.payment_id} is already being processed")
                self.queue.start_processing(self.payment_id)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                self.queue.finish_processing(self.payment_id)

        return ProcessingLock(self, payment_id)
