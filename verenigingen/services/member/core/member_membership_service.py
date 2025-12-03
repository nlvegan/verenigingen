# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberMembershipService - Membership query and status operations

This service handles membership-related queries for members, including
active membership lookup and membership status operations.

Extracted from member.py:
- get_active_membership() - lines 1631-1647 (17 LOC)

Architecture:
- Static methods for membership queries
- Delegates to member_utils for field-validated queries
- Returns full Membership documents when needed
- Proper error handling and logging
"""

from typing import TYPE_CHECKING, List, Optional

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.member_utils import get_active_membership_for_member

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberMembershipService(StatelessService):
    """
    Service for membership-related queries and operations.

    This service provides a clean interface for membership queries,
    including active membership lookup and status checking.
    """

    def __init__(self):
        super().__init__(service_name="MemberMembershipService")

    def get_active_membership(
        self, member_name: str, fields: Optional[List[str]] = None
    ) -> Optional["Document"]:
        """
        Get the currently active membership for a member.

        Delegates to the existing utility in member_utils for consistent
        membership lookup with field validation and error handling.

        Args:
            member_name: Member document name/ID
            fields: List of fields to retrieve (defaults to standard fields)

        Returns:
            Membership document if found, None otherwise

        Example:
            membership = MemberMembershipService().get_active_membership(
                "Member-001",
                fields=["name", "membership_type", "start_date", "renewal_date", "status"]
            )
        """

        def _get_active_membership_logic():
            # Use default fields if none specified
            if fields is None:
                _fields = ["name", "membership_type", "start_date", "renewal_date", "status"]
            else:
                _fields = fields

            # Use the utility function for field-validated lookup
            membership_data = get_active_membership_for_member(member_name, fields=_fields)

            if membership_data:
                try:
                    return frappe.get_doc("Membership", membership_data["name"])
                except Exception as e:
                    self.handle_error(
                        e,
                        "get_active_membership",
                        {"member_name": member_name, "membership_data_name": membership_data.get("name")},
                        raise_error=False,
                    )
                    return None
            return None

        return self.execute_operation(_get_active_membership_logic)

    def get_active_membership_for_member_doc(self, member_doc: "Document") -> Optional["Document"]:
        """
        Get the currently active membership for a member document.

        Convenience method that accepts a Member document instead of member name.

        Args:
            member_doc: Member document object

        Returns:
            Membership document if found, None otherwise
        """
        return self.get_active_membership(member_doc.name)
