"""
Authentication and Session Management Hooks

This module provides comprehensive authentication and session management capabilities
for the Verenigingen association management system. It handles user-specific routing,
role-based access control, member portal redirections, and security enforcement
to ensure proper user experience and system security.

Key Features:
- Intelligent session routing based on user roles and member status
- Member portal integration with automatic redirection
- Role-based access control with security enforcement
- Volunteer and chapter management integration
- System security with restricted area protection
- API endpoints for programmatic authentication management

Business Context:
The association operates a multi-tier user system with distinct access patterns:
- Members: Access to member portal with dues, donations, and personal information
- Volunteers: Access to volunteer tools and chapter management features
- Administrators: Full system access for operational management
- System Users: Backend access for technical operations

Architecture:
This module integrates with:
- Frappe's authentication and session management framework
- Member DocType for member identification and validation
- Volunteer DocType for volunteer access management
- Role management system for permission enforcement
- Portal systems for user experience customization
- Security monitoring for access control enforcement

Authentication Flow:
1. Session Creation:
   - Identify user type (member, volunteer, administrator)
   - Determine appropriate home page and portal access
   - Set session-specific configurations and permissions
   - Log authentication events for audit purposes

2. Access Control:
   - Validate role-based permissions for system areas
   - Enforce member portal restrictions for non-system users
   - Redirect unauthorized access attempts appropriately
   - Maintain security audit trails

3. User Experience:
   - Customize home page based on user role and context
   - Provide seamless navigation between system areas
   - Support programmatic redirection and routing
   - Ensure consistent user interface experience

Security Features:
- Prevents unauthorized access to administrative areas
- Enforces member portal boundaries for security
- Logs authentication events for audit compliance
- Validates user permissions before system access
- Protects sensitive administrative functions

Integration Points:
- Member management for portal access validation
- Volunteer systems for specialized tool access
- Chapter management for regional administration
- Role management for permission enforcement
- Portal systems for customized user experience

Author: Development Team
Date: 2025-08-02
Version: 1.0
"""

import frappe
from frappe import _

from verenigingen.utils.security_wrappers import safe_get_roles

# REMOVED: validate_session_before_request function (August 21, 2025)
#
# This function was causing "User None is disabled" errors because it interfered
# with Frappe's core session initialization process. The function attempted to
# validate and "fix" sessions by checking if frappe.session.user was None and
# setting it to "Guest", but this created a race condition where normal session
# initialization was interrupted.
#
# KEY DISTINCTION: This is different from the enforce_member_portal_access()
# function below, which handles portal access rules without session validation.
#
# PROPER ALTERNATIVES:
# - Session validation: Use on_session_creation hook (runs after session setup)
# - Session cleanup: Use utils/session_cleanup.py background jobs
# - Role checking: Use security_wrappers.py safe functions
# - Portal access: Use enforce_member_portal_access() function


def on_session_creation(login_manager):
    """
    Hook called when a user session is created (login)
    Redirects members to the member portal

    CRITICAL: This hook runs AFTER Frappe's session initialization is complete,
    preventing the "User None is disabled" error that occurs during session setup.
    """
    try:
        # Enhanced validation to prevent "User None is disabled" errors
        if not login_manager:
            frappe.logger().debug("Auth hook: No login_manager provided, skipping")
            return

        # Ensure session object exists and is properly initialized
        if not hasattr(frappe, "session") or not frappe.session:
            frappe.logger().error("Auth hook: frappe.session is not available")
            return

        if not hasattr(frappe.session, "user"):
            frappe.logger().error("Auth hook: frappe.session.user attribute missing")
            return

        user = frappe.session.user

        # CRITICAL: Comprehensive user validation to prevent None user errors
        if user is None:
            frappe.logger().error("Auth hook: User is None - session may be corrupted")
            return

        if not isinstance(user, str):
            frappe.logger().error(f"Auth hook: User is not a string: {type(user)} = {repr(user)}")
            return

        if user in ["", "None", "null", "undefined"]:
            frappe.logger().error(f"Auth hook: User has invalid string value: {repr(user)}")
            return

        if len(user.strip()) == 0:
            frappe.logger().error("Auth hook: User is empty string after trim")
            return

        # Skip for Guest users (this is normal)
        if user == "Guest":
            frappe.logger().debug("Auth hook: Guest user detected, skipping member portal redirect")
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
        # CRITICAL: Validate user before checking roles
        if not user or not isinstance(user, str) or user in ["", "None", "Guest"]:
            return False

        user_roles = safe_get_roles(user)
        return "Member" in user_roles
    except Exception as e:
        frappe.logger().error(f"Error checking member role for user {repr(user)}: {str(e)}")
        return False


def has_volunteer_role(user):
    """Check if user has Volunteer-related roles"""
    try:
        # CRITICAL: Validate user before checking roles
        if not user or not isinstance(user, str) or user in ["", "None", "Guest"]:
            return False

        user_roles = safe_get_roles(user)
        volunteer_roles = [
            "Volunteer",
            "Chapter Board Member",
        ]
        return any(role in user_roles for role in volunteer_roles)
    except Exception as e:
        frappe.logger().error(f"Error checking volunteer role for user {repr(user)}: {str(e)}")
        return False


def get_default_home_page(user=None):
    """
    Get the default home page for a user
    This can be called from other parts of the application
    """
    if not user:
        user = frappe.session.user

    # CRITICAL: Validate user parameter
    if not user or not isinstance(user, str) or user in ["", "None", None]:
        return "/web"

    if user == "Guest":
        return "/web"

    # Check if user is a member
    try:
        member_record = frappe.db.get_value("Member", {"user": user}, "name")
    except Exception as e:
        frappe.logger().error(f"Error getting member record for user {repr(user)}: {str(e)}")
        member_record = None

    if member_record or has_member_role(user):
        return "/member_portal"

    # Check if user is a volunteer
    try:
        volunteer_record = frappe.db.get_value("Volunteer", {"user": user}, "name")
    except Exception as e:
        frappe.logger().error(f"Error getting volunteer record for user {repr(user)}: {str(e)}")
        volunteer_record = None

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


def enforce_member_portal_access():
    """
    Hook called before each request to enforce member portal access rules

    This function is different from the REMOVED validate_session_before_request()
    function. This one handles portal access enforcement, while the removed one
    was attempting session validation and causing race conditions.

    IMPORTANT: This function does NOT validate sessions - it only handles access control.
    Session validation must be complete before this function runs.
    """
    try:
        # Skip for non-web requests to avoid interfering with system operations
        if not hasattr(frappe, "local") or not frappe.local:
            return

        if not hasattr(frappe.local, "request") or not frappe.local.request:
            return

        # Skip for API requests to avoid breaking API functionality
        request_path = getattr(frappe.local.request, "path", "")
        if request_path.startswith("/api/"):
            return

        # CRITICAL: Enhanced session validation to prevent "User None is disabled" errors
        if not hasattr(frappe, "session") or not frappe.session:
            frappe.logger().debug("Portal access: No session available, skipping")
            return

        user = getattr(frappe.session, "user", None)

        # Comprehensive user validation - similar to on_session_creation but more defensive
        if user is None:
            frappe.logger().debug(
                "Portal access: User is None, skipping (may be during session initialization)"
            )
            return

        if not isinstance(user, str):
            frappe.logger().error(f"Portal access: User is not string: {type(user)} = {repr(user)}")
            return

        if user in ["", "None", "null", "undefined"]:
            frappe.logger().error(f"Portal access: User has invalid value: {repr(user)}")
            return

        if len(user.strip()) == 0:
            frappe.logger().error("Portal access: User is empty string")
            return

        # Skip for admin/system users (this is normal and expected)
        if user in ["Administrator", "Guest"]:
            return

        # Check if member is trying to access restricted areas

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
        # CRITICAL: Validate user before checking roles (prevents security bypass)
        if not user or not isinstance(user, str) or user in ["", "None", "Guest"]:
            return False

        user_roles = safe_get_roles(user)
        system_roles = [
            "System Manager",
            "Verenigingen Administrator",
            "Verenigingen Manager",
            "Verenigingen Governance Auditor",
        ]
        return any(role in user_roles for role in system_roles)
    except Exception as e:
        frappe.logger().error(f"Error checking system access for user {repr(user)}: {str(e)}")
        return False
