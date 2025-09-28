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
    from verenigingen.utils.chapter_utils import (
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

from verenigingen.utils.member_utils import get_member_name_for_user, get_volunteer_for_member


def get_user_accessible_chapters(
    user_email: Optional[str] = None, required_permission_levels: Optional[List[str]] = None
) -> Optional[List[str]]:
    """
    Get chapters accessible to a user based on their board positions and permissions.

    Args:
        user_email: User email (defaults to current user)
        required_permission_levels: List of permission levels required (defaults to ["Admin", "Membership", "Finance"])

    Returns:
        None: User has admin access (can see all chapters)
        List[str]: List of chapter names user can access
        []: Empty list if user has no chapter access

    Permission Logic:
        1. System/Admin roles → Full access (returns None)
        2. Board positions with required permission levels → Chapter access
        3. National chapter access if configured and user has permissions
        4. No member record or board positions → No access (returns [])

    Performance:
        Optimized queries with proper filtering and minimal database hits.
        Critical for report loading and dashboard operations.
    """
    # Use current user if not specified
    if user_email is None:
        user_email = frappe.session.user

    # Set default required permission levels
    if required_permission_levels is None:
        required_permission_levels = ["Admin", "Membership", "Finance"]

    if not user_email:
        frappe.logger().warning("get_user_accessible_chapters called with empty user_email")
        return []

    try:
        # Check for admin roles - these users see all chapters
        admin_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Staff"]
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
            "Verenigingen Chapter Board Member",
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

        # Check national chapter access if configured
        try:
            settings = frappe.get_cached_single("Verenigingen Settings")
            national_chapter = getattr(settings, "national_chapter", None)

            if national_chapter and national_chapter not in accessible_chapters:
                # Check if user has board position in national chapter
                national_positions = frappe.get_all(
                    "Verenigingen Chapter Board Member",
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
        frappe.logger().error(f"Error determining chapter access for user {user_email}: {str(e)}")
        return []


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

        # Get board positions with role information
        positions = frappe.get_all(
            "Verenigingen Chapter Board Member",
            filters=filters,
            fields=["parent as chapter", "chapter_role", "is_active", "start_date", "end_date"],
            order_by="parent, start_date desc",
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
        frappe.logger().error(f"Error getting board positions for user {user_email}: {str(e)}")
        return []


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
        permission_level: Required permission level ("Admin", "Membership", "Finance", etc.)
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
