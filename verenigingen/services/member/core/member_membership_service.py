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

from verenigingen.utils.member_utils import get_active_membership_for_member

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberMembershipService:
    """
    Service for membership-related queries and operations.

    This service provides a clean interface for membership queries,
    including active membership lookup and status checking.
    """

    @staticmethod
    def get_active_membership(member_name: str, fields: Optional[List[str]] = None) -> Optional["Document"]:
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
            membership = MemberMembershipService.get_active_membership(
                "Member-001",
                fields=["name", "membership_type", "start_date", "renewal_date", "status"]
            )
        """
        # Use default fields if none specified
        if fields is None:
            fields = ["name", "membership_type", "start_date", "renewal_date", "status"]

        # Use the utility function for field-validated lookup
        membership_data = get_active_membership_for_member(member_name, fields=fields)

        if membership_data:
            try:
                return frappe.get_doc("Membership", membership_data["name"])
            except Exception as e:
                frappe.logger().error(
                    f"Error loading Membership document {membership_data.get('name')} "
                    f"for member {member_name}: {str(e)}"
                )
                return None

        return None

    @staticmethod
    def get_active_membership_for_member_doc(member_doc: "Document") -> Optional["Document"]:
        """
        Get the currently active membership for a member document.

        Convenience method that accepts a Member document instead of member name.

        Args:
            member_doc: Member document object

        Returns:
            Membership document if found, None otherwise
        """
        return MemberMembershipService.get_active_membership(member_doc.name)


def get_member_membership_service() -> MemberMembershipService:
    """Get singleton instance of MemberMembershipService"""
    return MemberMembershipService()
