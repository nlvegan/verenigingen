"""
Chapter Role Profile Hooks

Hooks for Chapter DocType events that trigger role profile recalculation.
Detects removed board members by comparing child table state.

Author: Verenigingen Development Team
Last Updated: 2025-10-09
"""

import frappe


def invalidate_chapter_profile_cache(doc, method):
    """
    Hook called when Chapter is updated.

    Invalidates profile configuration cache for this chapter.

    Args:
        doc: Chapter document
        method: Hook method name
    """
    from verenigingen.utils.user_role_profile_calculator import invalidate_profile_config_cache

    # Invalidate this chapter's profile config cache
    invalidate_profile_config_cache(entity_type="chapter", entity_name=doc.name)


def on_chapter_board_members_change(doc, method):
    """
    Hook called when Chapter is updated.

    Detects removed board members AND is_active changes by comparing old vs new state.
    Child table 'after_delete' hooks are unreliable, so we detect changes here.

    Args:
        doc: Chapter document
        method: Hook method name
    """
    # Only process if board_members changed
    if not doc.has_value_changed("board_members"):
        return

    from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

    # Get old active board member identifiers
    old_active_members = set()
    if hasattr(doc, "_doc_before_save") and doc._doc_before_save:
        for bm in doc._doc_before_save.board_members or []:
            if bm.volunteer and bm.is_active:
                old_active_members.add(bm.volunteer)

    # Get current active board member identifiers
    current_active_members = set()
    for bm in doc.board_members or []:
        if bm.volunteer and bm.is_active:
            current_active_members.add(bm.volunteer)

    # Detect members who LOST active status (deleted OR is_active changed to 0)
    members_lost_active = old_active_members - current_active_members

    # Detect members who GAINED active status (added OR is_active changed to 1)
    members_gained_active = current_active_members - old_active_members

    # Recalculate for members who lost active status
    if members_lost_active:
        for volunteer_name in members_lost_active:
            try:
                # Get member and user for this volunteer
                member = frappe.db.get_value("Volunteer", volunteer_name, "member")
                if member:
                    user = frappe.db.get_value("Member", member, "user")
                    if user:
                        frappe.logger().info(
                            f"Recalculating role profile for inactive/removed board member: {volunteer_name} (user: {user})"
                        )
                        auto_sync_on_role_change(user)
                    else:
                        frappe.logger().debug(
                            f"Skipping role profile recalculation for {volunteer_name} - no user account"
                        )
                else:
                    frappe.logger().warning(
                        f"Skipping role profile recalculation for {volunteer_name} - no member record"
                    )
            except Exception as e:
                frappe.logger().error(
                    f"Error recalculating role profile for inactive/removed board member {volunteer_name}: {str(e)}"
                )
                # Continue processing other members
                continue

    # Recalculate for members who gained active status
    if members_gained_active:
        for volunteer_name in members_gained_active:
            try:
                # Get member and user for this volunteer
                member = frappe.db.get_value("Volunteer", volunteer_name, "member")
                if member:
                    user = frappe.db.get_value("Member", member, "user")
                    if user:
                        frappe.logger().info(
                            f"Recalculating role profile for new/reactivated board member: {volunteer_name} (user: {user})"
                        )
                        auto_sync_on_role_change(user)
                    else:
                        frappe.logger().debug(
                            f"Skipping role profile recalculation for {volunteer_name} - no user account"
                        )
                else:
                    frappe.logger().warning(
                        f"Skipping role profile recalculation for {volunteer_name} - no member record"
                    )
            except Exception as e:
                frappe.logger().error(
                    f"Error recalculating role profile for new/reactivated board member {volunteer_name}: {str(e)}"
                )
                # Continue processing other members
                continue
