# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberLookupService - Cascade member matching for imports.

Provides configurable cascade matching strategies to find existing
members during bulk import operations. This service consolidates the
member lookup logic from VIP Import and MijnRood CSV Import into a
reusable component.

Usage:
    from verenigingen.services.member.member_lookup_service import (
        get_member_lookup_service,
        LookupStrategy,
    )

    service = get_member_lookup_service()

    # Use VIP strategies (default)
    member = service.find_member(row_data)

    # Use MijnRood strategies
    member = service.find_member(row_data, strategies=service.MIJNROOD_STRATEGIES)

    # Custom strategies
    member = service.find_member(
        row_data,
        strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL],
    )
"""

from enum import Enum
from typing import Any, Dict, List, Optional

import frappe
from frappe.model.document import Document

from verenigingen.services.infrastructure.base_service import StatelessService


class LookupStrategy(Enum):
    """Available member lookup strategies.

    Each strategy corresponds to a specific field that can be used
    to identify an existing member during import operations.

    Attributes:
        MEMBER_ID: Match by member_id field (primary identifier)
        PROCURIOS_ID: Match by procurios_id, stored in member_id field
        EMAIL: Match by email field (generic)
        PERSONAL_EMAIL: Match by personal_email against email field
        ORGANIZATION_EMAIL: Match by organization_email against email field
    """

    MEMBER_ID = "member_id"
    PROCURIOS_ID = "procurios_id"
    EMAIL = "email"
    PERSONAL_EMAIL = "personal_email"
    ORGANIZATION_EMAIL = "organization_email"


class MemberLookupService(StatelessService):
    """
    Service for finding existing members using cascade matching.

    Tries multiple lookup strategies in order until a match is found.
    Supports different strategy sets for different import sources.

    The cascade approach ensures that the most reliable identifier
    (member_id) is tried first, falling back to less specific
    identifiers (email addresses) only when needed.

    Attributes:
        VIP_STRATEGIES: Default strategies for VIP Import (4-step cascade)
        MIJNROOD_STRATEGIES: Default strategies for MijnRood Import (2-step cascade)
    """

    # Default strategies for VIP Import (4-step cascade)
    # Order: member_id -> procurios_id -> personal_email -> org_email
    VIP_STRATEGIES: List[LookupStrategy] = [
        LookupStrategy.MEMBER_ID,
        LookupStrategy.PROCURIOS_ID,
        LookupStrategy.PERSONAL_EMAIL,
        LookupStrategy.ORGANIZATION_EMAIL,
    ]

    # Default strategies for MijnRood Import (2-step cascade)
    # Order: member_id -> email
    MIJNROOD_STRATEGIES: List[LookupStrategy] = [
        LookupStrategy.MEMBER_ID,
        LookupStrategy.EMAIL,
    ]

    def __init__(self):
        """Initialize the MemberLookupService."""
        super().__init__(service_name="MemberLookupService")

    def find_member(
        self,
        row_data: Dict[str, Any],
        strategies: Optional[List[LookupStrategy]] = None,
    ) -> Optional[Document]:
        """
        Find existing member using cascade matching.

        Tries each strategy in order until a match is found.
        Returns the first matching member document, or None if
        no match is found with any strategy.

        Args:
            row_data: Dictionary with lookup field values. Expected keys
                depend on the strategies used (e.g., 'member_id', 'email',
                'personal_email', 'organization_email', 'procurios_id')
            strategies: Ordered list of strategies to try. Defaults to
                VIP_STRATEGIES if not specified.

        Returns:
            Member document if found, None otherwise

        Example:
            >>> service = MemberLookupService()
            >>> member = service.find_member(
            ...     {'member_id': '12345', 'email': 'test@example.com'},
            ...     strategies=[LookupStrategy.MEMBER_ID, LookupStrategy.EMAIL]
            ... )
        """
        if strategies is None:
            strategies = self.VIP_STRATEGIES

        for strategy in strategies:
            member = self._find_by_strategy(strategy, row_data)
            if member:
                self.logger.debug(f"Found member {member.name} via {strategy.value}")
                return member

        return None

    def _find_by_strategy(
        self,
        strategy: LookupStrategy,
        row_data: Dict[str, Any],
    ) -> Optional[Document]:
        """
        Find member using a specific strategy.

        Routes to the appropriate lookup method based on the strategy.

        Args:
            strategy: The lookup strategy to use
            row_data: Dictionary with lookup field values

        Returns:
            Member document if found, None otherwise
        """
        if strategy == LookupStrategy.MEMBER_ID:
            return self._find_by_member_id(row_data.get("member_id"))
        elif strategy == LookupStrategy.PROCURIOS_ID:
            # Procurios ID is stored in the member_id field
            return self._find_by_member_id(row_data.get("procurios_id"))
        elif strategy == LookupStrategy.EMAIL:
            return self._find_by_email(row_data.get("email"))
        elif strategy == LookupStrategy.PERSONAL_EMAIL:
            return self._find_by_email(row_data.get("personal_email"))
        elif strategy == LookupStrategy.ORGANIZATION_EMAIL:
            return self._find_by_email(row_data.get("organization_email"))
        return None

    def _find_by_member_id(self, member_id: Optional[str]) -> Optional[Document]:
        """
        Find member by member_id field.

        Args:
            member_id: The member_id to search for

        Returns:
            Member document if found, None otherwise
        """
        if not member_id:
            return None
        member_name = frappe.db.get_value("Member", {"member_id": member_id}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)
        return None

    def _find_by_email(self, email: Optional[str]) -> Optional[Document]:
        """
        Find member by email field.

        Args:
            email: The email address to search for

        Returns:
            Member document if found, None otherwise
        """
        if not email:
            return None
        member_name = frappe.db.get_value("Member", {"email": email}, "name")
        if member_name:
            return frappe.get_doc("Member", member_name)
        return None


# Module-level singleton accessor
_service_instance: Optional[MemberLookupService] = None


def get_member_lookup_service() -> MemberLookupService:
    """
    Get singleton instance of MemberLookupService.

    Returns:
        MemberLookupService: The singleton instance

    Example:
        >>> service = get_member_lookup_service()
        >>> member = service.find_member({'member_id': '12345'})
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = MemberLookupService()
    return _service_instance
