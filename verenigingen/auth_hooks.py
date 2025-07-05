"""
Authentication hooks for Verenigingen app
Handles login redirects and home page settings for members
"""

import frappe
from frappe import _


def on_session_creation(login_manager):
    """
    Hook called when a user session is created (login)
    Redirects members to the member portal
    """
    try:
        user = frappe.session.user

        # Skip for Guest users
        if user == "Guest":
            return

        # Check if user is a member by looking for linked member record
        member_record = frappe.db.get_value("Member", {"user": user}, "name")

        if member_record:
            # User is a member - redirect to member portal
            frappe.local.response["home_page"] = "/member_portal"
            frappe.local.response["message"] = _("Welcome to the Member Portal")

            frappe.logger().info(f"Member {user} redirected to member portal")

        elif has_member_role(user):
            # User has Member role but no linked member record - still redirect to portal
            frappe.local.response["home_page"] = "/member_portal"
            frappe.local.response["message"] = _("Welcome to the Member Portal")

            frappe.logger().info(f"User {user} with Member role redirected to member portal")

        else:
            # Check if user has volunteer role
            if has_volunteer_role(user):
                # User is a volunteer - could redirect to volunteer portal
                volunteer_record = frappe.db.get_value("Volunteer", {"user": user}, "name")
                if volunteer_record:
                    # Could redirect to volunteer dashboard if it exists
                    # For now, keep default behavior
                    pass

            # Default behavior for other users (system users, admins, etc.)
            # Let Frappe handle the default redirect

    except Exception as e:
        # Log error but don't break login process
        frappe.logger().error(f"Error in member portal redirect: {str(e)}")


def has_member_role(user):
    """Check if user has Member role"""
    try:
        user_roles = frappe.get_roles(user)
        return "Member" in user_roles
    except Exception:
        return False


def has_volunteer_role(user):
    """Check if user has Volunteer-related roles"""
    try:
        user_roles = frappe.get_roles(user)
        volunteer_roles = ["Verenigingen Volunteer", "Volunteer", "Chapter Board Member"]
        return any(role in user_roles for role in volunteer_roles)
    except Exception:
        return False


def get_default_home_page(user=None):
    """
    Get the default home page for a user
    This can be called from other parts of the application
    """
    if not user:
        user = frappe.session.user

    if user == "Guest":
        return "/web"

    # Check if user is a member
    member_record = frappe.db.get_value("Member", {"user": user}, "name")

    if member_record or has_member_role(user):
        return "/member_portal"

    # Check if user is a volunteer
    volunteer_record = frappe.db.get_value("Volunteer", {"user": user}, "name")

    if volunteer_record or has_volunteer_role(user):
        # Could return volunteer-specific dashboard
        return "/member_portal"  # For now, use member portal

    # Default for system users
    return "/app"


@frappe.whitelist()
def get_member_home_page():
    """
    API method to get the home page for the current user
    Can be called from JavaScript to programmatically redirect
    """
    return get_default_home_page(frappe.session.user)


def on_logout(login_manager):
    """
    Hook called when user logs out
    Can be used for cleanup or redirect logic
    """
    try:
        # Clear any member-specific session data if needed
        # For now, just use default logout behavior
        pass
    except Exception as e:
        frappe.logger().error(f"Error in logout hook: {str(e)}")


def validate_auth_via_api(user, password):
    """
    Custom authentication validation if needed
    This can be used to add additional auth checks for members
    """
    # For now, use default Frappe authentication
    # Could add member-specific validation here if needed
    return True


def before_request():
    """
    Hook called before each request
    Can be used to enforce member portal access rules
    """
    try:
        # Skip for non-web requests
        if not hasattr(frappe.local, "request") or not frappe.local.request:
            return

        # Skip for API requests
        if frappe.local.request.path.startswith("/api/"):
            return

        # Skip for admin/system users
        if frappe.session.user in ["Administrator", "Guest"]:
            return

        # Check if member is trying to access restricted areas
        user = frappe.session.user

        # If user is a member but trying to access /app (backend)
        # and doesn't have system roles, redirect to member portal
        if (
            frappe.local.request.path.startswith("/app")
            and has_member_role(user)
            and not has_system_access(user)
        ):
            frappe.local.response = frappe.utils.response.Response()
            frappe.local.response.status_code = 302
            frappe.local.response.headers["Location"] = "/member_portal"

    except Exception as e:
        # Don't break the request flow
        frappe.logger().error(f"Error in before_request hook: {str(e)}")


def has_system_access(user):
    """Check if user has roles that grant system access"""
    try:
        user_roles = frappe.get_roles(user)
        system_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Verenigingen Manager",
            "Chapter Manager",
            "Governance Auditor",
        ]
        return any(role in user_roles for role in system_roles)
    except Exception:
        return False
