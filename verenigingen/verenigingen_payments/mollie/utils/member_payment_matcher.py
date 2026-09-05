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
from datetime import datetime
from typing import Optional, Tuple

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
        self._loaded_signature: Optional[Tuple[str, int, Optional[datetime]]] = None

    def _current_signature(self) -> Tuple[str, int, Optional[datetime]]:
        """Cheap fingerprint of the Member rows this matcher cares about.

        (site, count, max(modified)) over Members carrying a mollie_customer_id.

        mollie_customer_id is NOT indexed, so this is a full scan of tabMember
        -- but it reads two aggregates instead of materialising every row's
        fields into Python dicts, measured 0.75ms vs 27.8ms for the reload it
        guards (748 members, 536 in set, veg11 2026-09-05). It is O(total
        members): if Member grows an order of magnitude, add an index on
        mollie_customer_id rather than assuming this stays cheap.

        The site is part of the fingerprint because this matcher is a
        module-level singleton (see get_member_payment_matcher below) and RQ
        worker processes are multi-tenant: queues are namespaced by bench, not
        by site (frappe.utils.background_jobs.generate_qname), so one worker
        process can serve several sites' jobs in turn via frappe.init(site).
        Without the site in the key, two sites whose (count, max(modified))
        happened to coincide could serve one site's cached members to another.

        Known blind spot: a write with update_modified=False that does not
        change the row count (e.g. changing mollie_customer_id/status/email on
        a member already in the set) is invisible to this fingerprint --
        verified on test_site_1 2026-09-05. All current production writers of
        Member.mollie_customer_id go through doc.save(), which bumps modified,
        so this is latent, not live. If a set_value(..., update_modified=False)
        writer is ever added for a cached field (name, full_name,
        mollie_customer_id, email, status), call
        reset_member_payment_matcher() alongside it.
        """
        row = frappe.db.sql(
            """
            SELECT COUNT(*), MAX(modified)
            FROM `tabMember`
            WHERE mollie_customer_id IS NOT NULL AND mollie_customer_id != ''
            """
        )
        count, max_modified = row[0]
        return (frappe.local.site, count, max_modified)

    def _load_lookups(self) -> None:
        """Load member lookup tables from database.

        The process-global singleton (see get_member_payment_matcher below) can
        stay alive for the lifetime of a worker process, spanning many separate
        payment runs. A member created -- or one that only gets its
        mollie_customer_id set -- after the first load must still be visible on
        the next lookup, so a cached-and-still-fresh signature is required, not
        just "have we ever loaded" (#255).

        A doc_events hook on Member cannot fix this on its own: Members are
        written from web request processes, but matching runs in RQ worker
        processes (frappe.enqueue in mollie_bulk_run_service.py /
        bulk_payment_admin_service.py), and a hook fired in the web process
        would only clear that process's copy of this module global, leaving
        every worker's singleton untouched. A signature derived from the
        database itself is the one invalidation source visible to every
        process.
        """
        current_signature = self._current_signature()
        if self._loaded and current_signature == self._loaded_signature:
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
        self._loaded_signature = current_signature

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
        self._loaded_signature = None


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
