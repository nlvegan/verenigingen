# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

from dataclasses import dataclass
from functools import cached_property
from typing import Dict, List, Optional, Set

import frappe


@dataclass
class UserPermissionContext:
    """Immutable user permission context"""

    user: str
    roles: Set[str]
    member_id: Optional[str] = None
    permission_level: str = "none"  # admin, manager, member, none


class SEPAPermissionResolverClean:
    """
    Clean permission resolver with single-path logic

    Eliminates complex fallbacks and provides simple, cacheable permission resolution
    """

    def __init__(self, user: str = None):
        self.user = user or frappe.session.user
        self._permission_cache = {}

    @cached_property
    def user_context(self) -> UserPermissionContext:
        """Resolve user permissions once and cache - single path logic"""
        roles = set(frappe.get_roles(self.user))

        # Single-path hierarchy - no complex fallbacks
        if "System Manager" in roles:
            return UserPermissionContext(user=self.user, roles=roles, permission_level="admin")

        if "Verenigingen Manager" in roles:
            return UserPermissionContext(user=self.user, roles=roles, permission_level="manager")

        if "Verenigingen Member" in roles:
            # Single member resolution - no email fallback
            member_id = frappe.db.get_value("Member", {"user": self.user}, "name")
            return UserPermissionContext(
                user=self.user, roles=roles, member_id=member_id, permission_level="member"
            )

        return UserPermissionContext(user=self.user, roles=roles, permission_level="none")

    def can_access_member(self, member_id: str) -> bool:
        """
        Single method for member access determination
        No fallbacks, no complex logic, cacheable result
        """
        # Use cache for repeated checks
        cache_key = f"{self.user}:{member_id}"
        if cache_key in self._permission_cache:
            return self._permission_cache[cache_key]

        context = self.user_context

        # Simple, single-path logic
        if context.permission_level == "admin":
            result = True
        elif context.permission_level == "manager":
            result = True
        elif context.permission_level == "member":
            result = context.member_id == member_id
        else:
            result = False

        self._permission_cache[cache_key] = result
        return result

    def validate_bulk_operations(self, member_ids: List[str]) -> Dict[str, bool]:
        """Efficient bulk permission validation"""
        return {member_id: self.can_access_member(member_id) for member_id in member_ids}

    def get_permission_summary(self, member_ids: List[str]) -> Dict[str, any]:
        """Clear permission summary for user feedback"""
        permissions = self.validate_bulk_operations(member_ids)
        authorized = [mid for mid, allowed in permissions.items() if allowed]
        blocked = [mid for mid, allowed in permissions.items() if not allowed]

        return {
            "user": self.user,
            "permission_level": self.user_context.permission_level,
            "total_requested": len(member_ids),
            "authorized_count": len(authorized),
            "blocked_count": len(blocked),
            "authorized_members": authorized,
            "blocked_members": blocked,
            "all_authorized": len(blocked) == 0,
        }

    def clear_cache(self):
        """Clear permission cache"""
        self._permission_cache.clear()
        # Clear cached property
        if hasattr(self, "_user_context"):
            delattr(self, "_user_context")


def get_clean_sepa_permission_resolver(user: str = None) -> SEPAPermissionResolverClean:
    """Factory function for clean permission resolver"""
    return SEPAPermissionResolverClean(user)
