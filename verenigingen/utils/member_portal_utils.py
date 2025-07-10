"""
Utility functions for member portal home page management
"""

import frappe
from frappe import _


@frappe.whitelist()
def set_member_home_page(user_email=None, home_page="/member_portal"):
    """
    Set the home page for a member user
    This updates the User doctype's home_page field
    """
    if not user_email:
        user_email = frappe.session.user

    if user_email == "Guest":
        return {"success": False, "message": "Cannot set home page for Guest user"}

    try:
        # Check if user exists
        if not frappe.db.exists("User", user_email):
            return {"success": False, "message": "User {user_email} not found"}

        # Update user's home page
        user_doc = frappe.get_doc("User", user_email)
        user_doc.home_page = home_page
        user_doc.save(ignore_permissions=True)

        frappe.logger().info(f"Set home page for {user_email} to {home_page}")

        return {"success": True, "message": "Home page set to {home_page}", "home_page": home_page}

    except Exception as e:
        frappe.logger().error(f"Error setting home page for {user_email}: {str(e)}")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def set_all_members_home_page(home_page="/member_portal"):
    """
    Set the home page for all users with Member role
    This is a bulk operation for initial setup
    """
    try:
        if not frappe.has_permission("User", "write"):
            frappe.throw(_("Insufficient permissions to update user home pages"))

        # Get all users with Member role
        member_users = frappe.db.sql(
            """
            SELECT DISTINCT u.name, u.email, u.full_name
            FROM `tabUser` u
            JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role = 'Member'
            AND u.enabled = 1
            AND u.name != 'Guest'
        """,
            as_dict=True,
        )

        updated_count = 0
        errors = []

        for user in member_users:
            try:
                user_doc = frappe.get_doc("User", user.name)

                # Only update if home page is not already set to member portal
                if user_doc.home_page != home_page:
                    user_doc.home_page = home_page
                    user_doc.save(ignore_permissions=True)
                    updated_count += 1

            except Exception as e:
                errors.append(f"Error updating {user.email}: {str(e)}")

        result = {
            "success": True,
            "updated_count": updated_count,
            "total_members": len(member_users),
            "home_page": home_page,
        }

        if errors:
            result["errors"] = errors

        frappe.logger().info(f"Updated home page for {updated_count} member users")

        return result

    except Exception as e:
        frappe.logger().error(f"Error in bulk home page update: {str(e)}")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_member_portal_stats():
    """
    Get statistics about member portal usage and home page settings
    """
    try:
        # Count members with member portal as home page
        members_with_portal = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabUser` u
            JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role = 'Member'
            AND u.enabled = 1
            AND u.home_page = '/member_portal'
        """
        )[0][0]

        # Count all members
        total_members = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT u.name) as count
            FROM `tabUser` u
            JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role = 'Member'
            AND u.enabled = 1
            AND u.name != 'Guest'
        """
        )[0][0]

        # Count members with linked member records
        linked_members = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabMember` m
            WHERE m.user IS NOT NULL
        """
        )[0][0]

        return {
            "total_member_users": total_members,
            "members_with_portal_home": members_with_portal,
            "members_with_linked_records": linked_members,
            "portal_adoption_rate": round((members_with_portal / total_members) * 100, 2)
            if total_members > 0
            else 0,
        }

    except Exception as e:
        frappe.logger().error(f"Error getting member portal stats: {str(e)}")
        return {"error": str(e)}


def sync_member_user_home_pages():
    """
    Background job to sync home pages for new members
    This can be called from a scheduled job or manually
    """
    try:
        # Find users with Member role but no home page set
        users_to_update = frappe.db.sql(
            """
            SELECT DISTINCT u.name, u.email
            FROM `tabUser` u
            JOIN `tabHas Role` hr ON hr.parent = u.name
            WHERE hr.role = 'Member'
            AND u.enabled = 1
            AND (u.home_page IS NULL OR u.home_page = '' OR u.home_page = '/app')
            AND u.name != 'Guest'
        """,
            as_dict=True,
        )

        updated_count = 0

        for user in users_to_update:
            try:
                result = set_member_home_page(user.email, "/member_portal")
                if result.get("success"):
                    updated_count += 1
            except Exception as e:
                frappe.logger().error(f"Error updating home page for {user.email}: {str(e)}")

        frappe.logger().info(f"Synced home pages for {updated_count} member users")
        return updated_count

    except Exception as e:
        frappe.logger().error(f"Error in sync_member_user_home_pages: {str(e)}")
        return 0


@frappe.whitelist()
def get_user_appropriate_home_page():
    """
    Get the appropriate home page for the current user
    """
    user = frappe.session.user

    if user == "Guest":
        return "/web"

    # Check user roles
    user_roles = frappe.get_roles(user)

    # Check if user is linked to a member record
    member_record = frappe.db.get_value("Member", {"user": user}, "name")

    if member_record or "Member" in user_roles:
        return "/member_portal"

    # Check if user is a volunteer
    volunteer_record = frappe.db.get_value("Volunteer", {"user": user}, "name")
    volunteer_roles = ["Verenigingen Volunteer", "Volunteer", "Chapter Board Member"]

    if volunteer_record or any(role in user_roles for role in volunteer_roles):
        return "/member_portal"  # Could be a volunteer-specific portal later

    # System users get the app
    system_roles = ["System Manager", "Verenigingen Administrator", "Verenigingen Manager"]
    if any(role in user_roles for role in system_roles):
        return "/app"

    # Default fallback
    return "/web"
