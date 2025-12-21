"""
Payment Context Resolver

Determines the payment context (donation, membership, etc.) from Mollie payment data
without being tied to any specific payment type.
"""

from typing import Any, Dict, Optional, Tuple

import frappe


class PaymentContext:
    """Container for payment context information"""

    def __init__(
        self, payment_type: str, target_doctype: str, target_name: str, metadata: Dict[str, Any] = None
    ):
        self.payment_type = payment_type  # 'donation', 'membership', etc.
        self.target_doctype = target_doctype  # 'Donation', 'Member', etc.
        self.target_name = target_name  # The document name
        self.metadata = metadata or {}

    def __str__(self):
        return f"PaymentContext(type={self.payment_type}, target={self.target_doctype}:{self.target_name})"


class PaymentContextResolver:
    """
    Resolves payment context from Mollie payment data.

    This class determines what type of payment we're dealing with and which
    document it relates to, without being tied to specific payment types.
    """

    def __init__(self):
        self.logger = frappe.logger()

    def resolve_context(self, payment_id: str, payment_data: Any) -> Optional[PaymentContext]:
        """
        Resolve the payment context from Mollie payment data.

        Args:
            payment_id: Mollie payment ID
            payment_data: Mollie payment object

        Returns:
            PaymentContext if resolved, None if no context found
        """
        try:
            # Extract metadata from payment
            mollie_metadata = self._extract_metadata(payment_data)

            # Try different resolution strategies in priority order

            # Strategy 1: Explicit metadata indicators
            context = self._resolve_from_metadata(payment_id, mollie_metadata)
            if context:
                return context

            # Strategy 2: Subscription payments (always member-related)
            context = self._resolve_subscription_payment(payment_id, payment_data)
            if context:
                return context

            # Strategy 3: Direct document lookups by payment_id
            context = self._resolve_from_document_lookup(payment_id)
            if context:
                return context

            # Strategy 4: Customer ID + timestamp fallback
            context = self._resolve_from_customer_fallback(payment_id, payment_data)
            if context:
                return context

            self.logger.warning(f"Could not resolve payment context for {payment_id}")
            return None

        except Exception as e:
            self.logger.error(f"Error resolving payment context for {payment_id}: {e}")
            return None

    def _extract_metadata(self, payment_data: Any) -> Dict[str, Any]:
        """Extract metadata from Mollie payment object"""
        if not payment_data:
            return {}

        metadata = getattr(payment_data, "metadata", {})
        if isinstance(metadata, dict):
            return metadata

        # Try to parse description as JSON metadata (legacy support)
        description = getattr(payment_data, "description", None)
        if description:
            try:
                import json

                desc_data = json.loads(description)
                if isinstance(desc_data, dict):
                    return desc_data
            except (json.JSONDecodeError, TypeError):
                pass

        return {}

    def _resolve_from_metadata(self, payment_id: str, metadata: Dict[str, Any]) -> Optional[PaymentContext]:
        """Resolve context from explicit metadata indicators"""

        # Check for explicit payment type in metadata
        payment_type = metadata.get("payment_type")
        record_id = metadata.get("record_id")

        if payment_type and record_id:
            if payment_type == "donation":
                if frappe.db.exists("Donation", record_id):
                    return PaymentContext("donation", "Donation", record_id, metadata)
            elif payment_type == "membership":
                if frappe.db.exists("Member", record_id):
                    return PaymentContext("membership", "Member", record_id, metadata)

        # Check for donation_id in metadata (legacy)
        donation_id = metadata.get("donation_id")
        if donation_id and frappe.db.exists("Donation", donation_id):
            return PaymentContext("donation", "Donation", donation_id, metadata)

        # Check for member_id in metadata
        member_id = metadata.get("member_id")
        if member_id and frappe.db.exists("Member", member_id):
            return PaymentContext("membership", "Member", member_id, metadata)

        return None

    def _resolve_subscription_payment(self, payment_id: str, payment_data: Any) -> Optional[PaymentContext]:
        """Resolve subscription payments (always membership-related)"""

        if not hasattr(payment_data, "subscription_id") or not payment_data.subscription_id:
            return None

        # Look for member with this subscription
        member_name = frappe.db.get_value(
            "Member", {"mollie_subscription_id": payment_data.subscription_id}, "name"
        )

        if member_name:
            return PaymentContext(
                "membership",
                "Member",
                member_name,
                {"subscription_id": payment_data.subscription_id, "is_subscription": True},
            )

        return None

    def _resolve_from_document_lookup(self, payment_id: str) -> Optional[PaymentContext]:
        """Resolve by looking up documents with this payment_id"""

        # Check donations first
        donation_name = frappe.db.get_value("Donation", {"payment_id": payment_id}, "name")
        if donation_name:
            return PaymentContext("donation", "Donation", donation_name)

        # Check members (for one-time member payments)
        member_name = frappe.db.get_value("Member", {"payment_id": payment_id}, "name")
        if member_name:
            return PaymentContext("membership", "Member", member_name)

        return None

    def _resolve_from_customer_fallback(self, payment_id: str, payment_data: Any) -> Optional[PaymentContext]:
        """Resolve using customer ID + timestamp window as fallback"""

        customer_id = getattr(payment_data, "customer_id", None)
        if not customer_id:
            return None

        # Get payment creation time
        payment_created = getattr(payment_data, "created_at", None)
        if not payment_created:
            return None

        # Convert to datetime if needed
        if isinstance(payment_created, str):
            try:
                from datetime import datetime

                payment_created = datetime.fromisoformat(payment_created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None

        from datetime import timedelta

        time_window_start = payment_created - timedelta(minutes=30)
        time_window_end = payment_created + timedelta(minutes=30)

        # Try donations first
        donations = frappe.get_all(
            "Donation",
            filters={
                "mollie_customer_id": customer_id,
                "creation": ["between", [time_window_start, time_window_end]],
                "paid": 0,
            },
            order_by="creation desc",
            limit=1,
        )

        if donations:
            return PaymentContext("donation", "Donation", donations[0].name)

        # Try members
        members = frappe.get_all(
            "Member",
            filters={
                "mollie_customer_id": customer_id,
                "creation": ["between", [time_window_start, time_window_end]],
            },
            order_by="creation desc",
            limit=1,
        )

        if members:
            return PaymentContext("membership", "Member", members[0].name)

        return None
