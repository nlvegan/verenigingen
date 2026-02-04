"""
Member Payment Matcher

Provides efficient and consistent member matching for Mollie payment operations.
Used by both bulk retrieval modes to ensure aligned behavior.

Matching order:
1. customer_id lookup (all members, regardless of status)
2. Description parsing (Assoc-Member-XXXX-XX-XXXX pattern)

Note: subscription_id is NOT used for matching because subscriptions change
over time and historical payments would have outdated subscription IDs.
"""

import re
from typing import Optional

import frappe


class MemberPaymentMatcher:
    """
    Efficient member matching for bulk payment operations.

    Pre-loads lookup tables for O(1) customer_id matching.
    Falls back to description parsing for edge cases.

    Usage:
        matcher = MemberPaymentMatcher()
        member = matcher.find_member_for_payment(payment)
        if member:
            print(f"Found: {member['name']} (status: {member['status']})")
    """

    # Pattern for member IDs in payment descriptions
    # Format: Assoc-Member-YYYY-MM-NNNNNN (year-month-sequence)
    MEMBER_ID_PATTERN = re.compile(r"Assoc-Member-\d{4}-\d{2}-\d+")

    def __init__(self):
        self._customer_id_map: dict = {}
        self._all_members: list = []
        self._loaded: bool = False

    def _load_lookups(self) -> None:
        """Load member lookup tables from database."""
        if self._loaded:
            return

        # Load ALL members with mollie_customer_id (no status filter for bookkeeping)
        self._all_members = frappe.get_all(
            "Member",
            filters={"mollie_customer_id": ["!=", ""]},
            fields=["name", "full_name", "mollie_customer_id", "email", "status"],
        )

        # Build customer_id lookup map
        self._customer_id_map = {m.mollie_customer_id: m for m in self._all_members}

        self._loaded = True

    def find_member_for_payment(self, payment) -> Optional[dict]:
        """
        Find member for a Mollie payment.

        Args:
            payment: Mollie payment object with customer_id, description attributes

        Returns:
            Member dict with name, full_name, status, etc. or None if not found
        """
        self._load_lookups()

        customer_id = getattr(payment, "customer_id", None)
        description = getattr(payment, "description", "") or ""

        # Method 1: Customer ID match (O(1) lookup)
        if customer_id and customer_id in self._customer_id_map:
            return self._customer_id_map[customer_id]

        # Method 2: Parse member ID from description
        member = self._find_member_by_description(description)
        if member:
            return member

        return None

    def find_member_name_for_payment(self, payment) -> Optional[str]:
        """
        Find member name for a Mollie payment.

        Convenience method that returns just the member name string.

        Args:
            payment: Mollie payment object

        Returns:
            Member name string or None
        """
        member = self.find_member_for_payment(payment)
        return member["name"] if member else None

    def _find_member_by_description(self, description: str) -> Optional[dict]:
        """
        Try to find member by parsing member ID from payment description.

        Args:
            description: Payment description string

        Returns:
            Member dict or None
        """
        if not description or not isinstance(description, str):
            return None

        match = self.MEMBER_ID_PATTERN.search(description)
        if not match:
            return None

        potential_member_id = match.group(0)

        # Check if this member exists
        if not frappe.db.exists("Member", potential_member_id):
            return None

        # Fetch member details
        member = frappe.db.get_value(
            "Member",
            potential_member_id,
            ["name", "full_name", "mollie_customer_id", "email", "status"],
            as_dict=True,
        )

        return member

    def get_all_members_with_mollie_id(self) -> list:
        """
        Get all members with Mollie customer IDs.

        Used for pre-populating result structures in bulk operations.

        Returns:
            List of member dicts with name, full_name, customer_id, email, status
        """
        self._load_lookups()
        return self._all_members.copy()

    def get_member_count(self) -> int:
        """Get count of members with Mollie customer IDs."""
        self._load_lookups()
        return len(self._all_members)

    def is_customer_id_known(self, customer_id: str) -> bool:
        """Check if a customer_id belongs to any member."""
        self._load_lookups()
        return customer_id in self._customer_id_map

    def reset(self) -> None:
        """Reset cached lookups (useful for testing or after member changes)."""
        self._customer_id_map = {}
        self._all_members = []
        self._loaded = False


# Module-level singleton for reuse across calls
_matcher_instance: Optional[MemberPaymentMatcher] = None


def get_member_payment_matcher() -> MemberPaymentMatcher:
    """
    Get the singleton MemberPaymentMatcher instance.

    Returns cached instance for efficiency across multiple operations.
    """
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = MemberPaymentMatcher()
    return _matcher_instance


def reset_member_payment_matcher() -> None:
    """Reset the singleton matcher (useful after member data changes)."""
    global _matcher_instance
    if _matcher_instance:
        _matcher_instance.reset()
    _matcher_instance = None
