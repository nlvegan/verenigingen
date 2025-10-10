"""
Team Role Profile Hooks

Hooks for Team DocType events that trigger role profile recalculation.
Detects removed team members by comparing child table state.

Author: Verenigingen Development Team
Last Updated: 2025-10-09
"""

import frappe


def invalidate_team_profile_cache(doc, method):
    """
    Hook called when Team is updated.

    Invalidates profile configuration cache for this team.

    Args:
        doc: Team document
        method: Hook method name
    """
    from verenigingen.utils.user_role_profile_calculator import invalidate_profile_config_cache

    # Invalidate this team's profile config cache
    invalidate_profile_config_cache(entity_type="team", entity_name=doc.name)


def on_team_lead_change(doc, method):
    """
    Hook called when Team is updated.

    Triggers role profile recalculation when team_lead changes.

    Args:
        doc: Team document
        method: Hook method name
    """
    # Only recalculate if team_lead changed
    if doc.has_value_changed("team_lead"):
        old_lead = doc.get_db_value("team_lead")
        new_lead = doc.team_lead

        from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

        # Recalculate for old team lead (may lose Team Leader profile)
        if old_lead:
            auto_sync_on_role_change(old_lead)

        # Recalculate for new team lead (may gain Team Leader profile)
        if new_lead:
            auto_sync_on_role_change(new_lead)


def on_team_members_change(doc, method):
    """
    Hook called when Team is updated.

    Detects removed team members AND status changes by comparing old vs new state.
    Child table 'after_delete' hooks are unreliable, so we detect changes here.

    Args:
        doc: Team document
        method: Hook method name
    """
    # Only process if team_members changed
    if not doc.has_value_changed("team_members"):
        return

    from verenigingen.utils.user_role_profile_calculator import auto_sync_on_role_change

    # Get old active team member identifiers
    old_active_members = set()
    if hasattr(doc, "_doc_before_save") and doc._doc_before_save:
        for tm in doc._doc_before_save.team_members or []:
            if tm.volunteer and tm.status == "Active":
                old_active_members.add(tm.volunteer)

    # Get current active team member identifiers
    current_active_members = set()
    for tm in doc.team_members or []:
        if tm.volunteer and tm.status == "Active":
            current_active_members.add(tm.volunteer)

    # Detect members who LOST active status (deleted OR status changed from Active)
    members_lost_active = old_active_members - current_active_members

    # Detect members who GAINED active status (added OR status changed to Active)
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
                            f"Recalculating role profile for inactive/removed team member: {volunteer_name} (user: {user})"
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
                    f"Error recalculating role profile for inactive/removed team member {volunteer_name}: {str(e)}"
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
                            f"Recalculating role profile for new/reactivated team member: {volunteer_name} (user: {user})"
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
                    f"Error recalculating role profile for new/reactivated team member {volunteer_name}: {str(e)}"
                )
                # Continue processing other members
                continue
