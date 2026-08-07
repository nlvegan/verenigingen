#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chapter Access and Permission Utilities for Verenigingen
========================================================

Standardized utilities for chapter access control and permission management.
Consolidates complex permission logic scattered across reports and pages.

Key Features:
- User chapter access determination based on board positions
- Role-based permission checking for chapter operations
- National chapter access management
- Consistent error handling and security logging

Usage:
    from verenigingen.services.chapter.chapter_utils import (
        get_user_accessible_chapters,
        has_chapter_access_permission,
        get_user_board_positions
    )

    chapters = get_user_accessible_chapters()  # Current user
    chapters = get_user_accessible_chapters(user_email="user@example.com")  # Specific user
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.member_utils import get_member_name_for_user, get_volunteer_for_member
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


def get_user_accessible_chapters(
    user_email: Optional[str] = None, required_permission_levels: Optional[List[str]] = None
) -> Optional[List[str]]:
    """
    Get chapters accessible to a user based on their board positions and permissions.

    Args:
        user_email: User email (defaults to current user)
        required_permission_levels: List of permission levels required (defaults to ["Admin", "Financial"])

    Returns:
        None: User has admin access (can see all chapters)
        List[str]: List of chapter names user can access
        []: Empty list if user has no chapter access

    Raises:
        Any database error raised while resolving the user's identity or board
        positions. See Error Handling below.

    Permission Logic:
        1. System/Admin roles → Full access (returns None)
        2. Board positions with required permission levels → Chapter access
        3. National chapter access if configured and user has permissions
        4. No member record or board positions → No access (returns [])

    Error Handling:
        `[]` means "this user is on no board that grants the required level" and
        nothing else. A database error PROPAGATES rather than becoming `[]`.

        This is an authorization primitive: permissions.py builds Expense Claim
        query conditions from the returned list, and every chapter-scoped report
        filters on it. `[]` there IS the access-control answer, so swallowing an
        outage silently downgrades every board member to "no chapters" -
        indistinguishable from a genuine empty result, and invisible because the
        caller sees a well-formed empty report rather than an error. It is also
        unsafe after a deadlock (1213), which kills the transaction and makes any
        further query on it meaningless.

        This is the same bug class as `get_member_name_for_user` (which this
        function calls) one layer up; both now propagate. The error is logged to
        disk first, because a deadlock rolls back frappe.log_error()'s Error Log
        row and would leave no trace.

        The narrower excepts INSIDE this function are deliberately kept: a single
        missing Chapter Role, or a failure resolving the optional national chapter,
        must not deny access that the user's other board positions already grant.

    Performance:
        Optimized queries with proper filtering and minimal database hits.
        Critical for report loading and dashboard operations.
    """
    # Use current user if not specified
    if user_email is None:
        user_email = frappe.session.user

    # Set default required permission levels.
    # Chapter Role.permissions_level only allows Basic/Financial/Admin, so the
    # legacy ["Admin", "Membership", "Finance"] strings never matched any role,
    # silently denying access to every Financial board member.
    if required_permission_levels is None:
        required_permission_levels = ["Admin", "Financial"]

    if not user_email:
        frappe.logger().warning("get_user_accessible_chapters called with empty user_email")
        return []

    try:
        # Check for admin roles - these users see all chapters
        admin_roles = Roles.ADMIN_ROLES
        user_roles = frappe.get_roles(user_email)

        if any(role in user_roles for role in admin_roles):
            return None  # None means no filter - see all chapters

        # Get user's member record
        member_name = get_member_name_for_user(user_email)
        if not member_name:
            frappe.logger().debug(f"No member record found for user {user_email}")
            return []  # No access if not a member

        # Get user's volunteer record(s)
        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            frappe.logger().debug(f"No volunteer record found for member {member_name}")
            return []  # No board access if not a volunteer

        # Get all board positions for the volunteer
        board_positions = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_name, "is_active": 1},
            fields=["parent", "chapter_role"],
            order_by="parent",  # Consistent ordering
        )

        if not board_positions:
            frappe.logger().debug(f"No active board positions found for volunteer {volunteer_name}")
            return []

        # Filter positions by permission level
        accessible_chapters = []

        for position in board_positions:
            try:
                # Get role permissions
                role_doc = frappe.get_cached_doc("Chapter Role", position.chapter_role)

                if role_doc.permissions_level in required_permission_levels:
                    if position.parent not in accessible_chapters:
                        accessible_chapters.append(position.parent)

            except frappe.DoesNotExistError:
                frappe.logger().warning(
                    f"Chapter Role {position.chapter_role} not found for position in {position.parent}"
                )
                continue
            except Exception as e:
                frappe.logger().error(
                    f"Error checking role permissions for {position.chapter_role}: {str(e)}"
                )
                continue

        # Check national chapter access if configured.
        # The national chapter is stored in Verenigingen Settings.national_board_chapter;
        # board members of that chapter (with the required permission level) get access
        # to it in addition to their own chapter(s).
        try:
            national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")

            if national_chapter and national_chapter not in accessible_chapters:
                # Check if user has board position in national chapter
                national_positions = frappe.get_all(
                    "Chapter Board Member",
                    filters={"parent": national_chapter, "volunteer": volunteer_name, "is_active": 1},
                    fields=["chapter_role"],
                    limit=1,  # We only need to know if any exist
                )

                for position in national_positions:
                    try:
                        role_doc = frappe.get_cached_doc("Chapter Role", position.chapter_role)
                        if role_doc.permissions_level in required_permission_levels:
                            accessible_chapters.append(national_chapter)
                            break
                    except Exception as e:
                        frappe.logger().error(
                            f"Error checking national role {position.chapter_role}: {str(e)}"
                        )
                        continue

        except Exception as e:
            frappe.logger().error(f"Error checking national chapter access: {str(e)}")
            # Don't fail the entire function for national chapter issues
            pass

        frappe.logger().debug(f"User {user_email} has access to chapters: {accessible_chapters}")
        return accessible_chapters

    except Exception as e:
        # Log, then re-raise: returning [] here would report "no chapter access" for
        # what is actually a failure to determine it. See Error Handling above.
        frappe.logger().error(f"Error determining chapter access for user {user_email}: {str(e)}")
        raise


def has_chapter_access_permission(
    chapter_name: str,
    user_email: Optional[str] = None,
    required_permission_levels: Optional[List[str]] = None,
) -> bool:
    """
    Check if a user has access permission for a specific chapter.

    Args:
        chapter_name: Chapter document name
        user_email: User email (defaults to current user)
        required_permission_levels: List of permission levels required

    Returns:
        True if user has access permission, False otherwise

    Performance:
        More efficient than get_user_accessible_chapters for single chapter checks.
    """
    if not chapter_name:
        return False

    # Get accessible chapters
    accessible_chapters = get_user_accessible_chapters(user_email, required_permission_levels)

    # None means admin access (can access all chapters)
    if accessible_chapters is None:
        return True

    # Check if chapter is in accessible list
    return chapter_name in accessible_chapters


def get_user_board_positions(
    user_email: Optional[str] = None, chapter_name: Optional[str] = None, active_only: bool = True
) -> List[Dict[str, Any]]:
    """
    Get board positions for a user with detailed information.

    Args:
        user_email: User email (defaults to current user)
        chapter_name: Specific chapter to filter by (optional)
        active_only: Whether to only return active positions (default: True)

    Returns:
        List of dictionaries with board position information:
        - chapter: Chapter name
        - chapter_role: Role name
        - permissions_level: Permission level of the role
        - is_active: Whether position is active
        - start_date: Position start date
        - end_date: Position end date (if applicable)

    Raises:
        Any database error raised while resolving the user's identity or positions.

    Error Handling:
        `[]` means "this user holds no matching board position". A database error
        PROPAGATES rather than becoming `[]` - see get_user_accessible_chapters for
        the full rationale. It matters here too: is_chapter_board_member() is built
        on this function, and a swallowed error there reads as "not a board member".

        That failure mode has already bitten this function once, for a different
        reason: it selected phantom `start_date`/`end_date` columns, frappe.get_all
        raised, and the broad except returned [] for every real board member (see the
        aliasing comment on the query below). The column bug was fixed; leaving the
        swallow in place would let the next such fault hide exactly as quietly.

    Use Cases:
        - User profile displays
        - Permission auditing
        - Chapter administration interfaces
    """
    # Use current user if not specified
    if user_email is None:
        user_email = frappe.session.user

    if not user_email:
        frappe.logger().warning("get_user_board_positions called with empty user_email")
        return []

    try:
        # Get user's member and volunteer records
        member_name = get_member_name_for_user(user_email)
        if not member_name:
            return []

        volunteer_name = get_volunteer_for_member(member_name)
        if not volunteer_name:
            return []

        # Build filters
        filters = {"volunteer": volunteer_name}
        if chapter_name:
            filters["parent"] = chapter_name
        if active_only:
            filters["is_active"] = 1

        # Get board positions with role information.
        # Chapter Board Member stores dates in `from_date`/`to_date` (NOT
        # start_date/end_date). Selecting/ordering on the phantom columns made
        # frappe.get_all raise, which the broad except below swallowed — so this
        # function (and is_chapter_board_member, which depends on it) silently
        # returned [] for every real board member. Alias the real columns back to
        # the documented `start_date`/`end_date` output keys.
        positions = frappe.get_all(
            "Chapter Board Member",
            filters=filters,
            fields=[
                "parent as chapter",
                "chapter_role",
                "is_active",
                "from_date as start_date",
                "to_date as end_date",
            ],
            order_by="parent, from_date desc",
        )

        # Enrich with role permission information
        enriched_positions = []
        for position in positions:
            try:
                role_doc = frappe.get_cached_doc("Chapter Role", position.chapter_role)
                position["permissions_level"] = role_doc.permissions_level
                position["role_description"] = getattr(role_doc, "description", "")
                enriched_positions.append(position)
            except frappe.DoesNotExistError:
                frappe.logger().warning(f"Chapter Role {position.chapter_role} not found")
                # Include position without role details
                position["permissions_level"] = None
                position["role_description"] = None
                enriched_positions.append(position)
            except Exception as e:
                frappe.logger().error(f"Error getting role details for {position.chapter_role}: {str(e)}")
                # Include position without role details
                position["permissions_level"] = None
                position["role_description"] = None
                enriched_positions.append(position)

        return enriched_positions

    except Exception as e:
        # Log, then re-raise - see Error Handling in the docstring.
        frappe.logger().error(f"Error getting board positions for user {user_email}: {str(e)}")
        raise


def is_chapter_board_member(
    chapter_name: str,
    user_email: Optional[str] = None,
    required_permission_levels: Optional[List[str]] = None,
) -> bool:
    """
    Check if a user is a board member of a specific chapter.

    Args:
        chapter_name: Chapter document name
        user_email: User email (defaults to current user)
        required_permission_levels: List of permission levels required (optional)

    Returns:
        True if user is a board member with required permissions, False otherwise

    Use Cases:
        - Permission checks in DocType controllers
        - Conditional UI rendering
        - API access control
    """
    if not chapter_name:
        return False

    positions = get_user_board_positions(user_email, chapter_name, active_only=True)

    if not positions:
        return False

    # If no specific permission levels required, any board position is sufficient
    if not required_permission_levels:
        return True

    # Check if any position has required permission level
    return any(pos.get("permissions_level") in required_permission_levels for pos in positions)


def get_chapters_with_permission(permission_level: str, user_email: Optional[str] = None) -> List[str]:
    """
    Get chapters where user has a specific permission level.

    Args:
        permission_level: Required permission level ("Basic", "Financial", "Admin")
        user_email: User email (defaults to current user)

    Returns:
        List of chapter names where user has the required permission level

    Use Cases:
        - Feature-specific access control
        - Reporting with granular permissions
        - Administrative interfaces
    """
    return get_user_accessible_chapters(user_email, [permission_level]) or []


def invalidate_chapter_access_cache(user_email: Optional[str] = None):
    """
    Invalidate cached chapter access data for a user.
    Call this when user's board positions or chapter roles change.

    Args:
        user_email: User email (defaults to current user)

    Use Cases:
        - After board position changes
        - After role permission updates
        - Manual cache refresh operations
    """
    if user_email is None:
        user_email = frappe.session.user

    try:
        cache_keys = [
            f"user_accessible_chapters:{user_email}",
            f"user_board_positions:{user_email}",
            f"chapter_permissions:{user_email}",
        ]

        for key in cache_keys:
            try:
                frappe.cache().delete_key(key)
            except (ConnectionError, TimeoutError) as cache_error:
                frappe.logger().warning(f"Cache delete failed for '{key}': {cache_error}")
            except Exception as e:
                frappe.logger().error(f"Unexpected cache error for '{key}': {e}")

        frappe.logger().info(f"Chapter access cache cleared for user {user_email}")

    except Exception as e:
        frappe.logger().error(f"Error clearing chapter access cache for {user_email}: {str(e)}")


def get_member_primary_chapter(member_name: str) -> Optional[str]:
    """
    Get the primary (first active) chapter for a member.

    Args:
        member_name: Name of the Member document

    Returns:
        Chapter name or None if member has no active chapter membership

    Note:
        For members with multiple chapters, returns the first active one.
        Most members will only belong to one chapter.
    """
    if not member_name:
        return None

    # Query Chapter Member child table to find active chapter memberships
    # Note: Chapter Member is a child table, so `parent` field contains the Chapter name
    chapters = frappe.db.sql(
        """
        SELECT cm.parent as chapter
        FROM `tabChapter` c
        INNER JOIN `tabChapter Member` cm ON cm.parent = c.name
        WHERE cm.member = %(member)s
            AND cm.enabled = 1
            AND cm.status = 'Active'
            AND c.status = 'Active'
        ORDER BY cm.chapter_join_date DESC
        LIMIT 1
        """,
        {"member": member_name},
        as_dict=True,
    )

    return chapters[0].chapter if chapters else None


def get_chapter_split_percentage(chapter_name: str) -> float:
    """
    Get the chapter split percentage for a given chapter.

    DEPRECATED: Use verenigingen.verenigingen.domain.chapter_dues.SplitPercentage.from_chapter() instead.
    This wrapper is maintained for backward compatibility.

    Args:
        chapter_name: Name of the Chapter document

    Returns:
        Chapter split percentage (0-100)

    Logic:
        1. If chapter has custom chapter_split_percentage, use that
        2. Otherwise, use default from Verenigingen Settings
        3. Default to 60% if no configuration exists
    """
    # Use domain model for consistent logic
    from verenigingen.verenigingen.domain.chapter_dues import SplitPercentage

    split = SplitPercentage.from_chapter(chapter_name)
    return float(split.chapter_percentage)


def calculate_dues_split(total_amount: float, chapter_name: str) -> Dict[str, float]:
    """
    Calculate the split of dues income between chapter and national.

    DEPRECATED: Use verenigingen.verenigingen.domain.chapter_dues.DuesAllocationService instead.
    This wrapper is maintained for backward compatibility.

    Args:
        total_amount: Total dues amount to split
        chapter_name: Name of the Chapter

    Returns:
        Dictionary with:
            - chapter_amount: Amount allocated to chapter
            - national_amount: Amount allocated to national
            - chapter_percentage: Percentage used for chapter
            - national_percentage: Percentage used for national
    """
    # Use domain service for consistent calculation logic
    from verenigingen.verenigingen.domain.chapter_dues import DuesAllocationService

    service = DuesAllocationService()
    allocation = service.calculate_allocation(total_amount, chapter_name)
    return allocation.to_dict()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.UTILITY)
def get_chapter_split_info(chapter_name: str) -> Dict:
    """
    Get chapter split configuration info (whitelisted for client calls).

    Args:
        chapter_name: Name of the Chapter

    Returns:
        Dictionary with chapter split configuration
    """
    chapter_pct = get_chapter_split_percentage(chapter_name)

    return {
        "chapter_name": chapter_name,
        "chapter_percentage": chapter_pct,
        "national_percentage": 100.0 - chapter_pct,
        "uses_default": not bool(frappe.db.get_value("Chapter", chapter_name, "chapter_split_percentage")),
    }
