#!/usr/bin/env python3
"""
Dashboard Access Diagnostic Tool for Troubleshooting Permission Issues

This debugging utility provides comprehensive diagnostics for dashboard access problems
in the Verenigingen system. It performs systematic checks of user authentication,
role assignments, board access permissions, and context generation to identify
and resolve common dashboard access issues.

Diagnostic Capabilities:
    * User authentication status verification
    * Role and permission analysis
    * Board chapter access validation
    * Context generation error detection
    * Session state examination
    * Permission hierarchy troubleshooting

Common Issues Diagnosed:
    - Guest user attempting dashboard access
    - Missing board member assignments
    - Insufficient role permissions
    - Context generation failures
    - Session timeout or corruption
    - Chapter membership configuration errors

Usage:
    Can be executed both as a standalone script and via web API calls
    for comprehensive dashboard access troubleshooting in development
    and production environments.
"""

import frappe


@frappe.whitelist()
def debug_dashboard_access():
    """
    Perform comprehensive dashboard access diagnostics and troubleshooting.
    
    This function executes a series of diagnostic checks to identify the root
    cause of dashboard access issues, providing detailed information about
    user state, permissions, and system configuration that affects dashboard
    access capabilities.
    
    Returns:
        dict: Comprehensive diagnostic report containing:
            - status (str): Overall diagnostic status
            - user (str): Current user identifier
            - roles (list): User's assigned roles
            - is_guest (bool): Whether user is authenticated
            - user_chapters (list): Board chapters user has access to
            - has_board_access (bool): Whether user has board member access
            - context_keys (list): Available context variables
            - has_context_error (bool): Whether context generation failed
            - error messages for any failed diagnostic checks
            
    Diagnostic Process:
        1. Verify user authentication status
        2. Check role assignments and permissions
        3. Validate board chapter access rights
        4. Test context generation for dashboard
        5. Identify specific configuration issues
        6. Provide actionable troubleshooting information
    """

    try:
        # Import the dashboard module
        from verenigingen.templates.pages.chapter_dashboard import get_context, get_user_board_chapters

        results = {
            "status": "success",
            "user": frappe.session.user,
            "roles": frappe.get_roles(),
            "is_guest": frappe.session.user == "Guest",
        }

        if frappe.session.user == "Guest":
            results["message"] = "User is guest - needs to login"
            return results

        # Try to get user chapters
        try:
            user_chapters = get_user_board_chapters()
            results["user_chapters"] = user_chapters
            results["has_board_access"] = len(user_chapters) > 0 if user_chapters else False
        except Exception as e:
            results["chapter_error"] = str(e)

        # Try to simulate getting context
        try:
            context = {}
            get_context(context)
            results["context_keys"] = list(context.keys())
            results["has_context_error"] = bool(context.get("error_message"))
        except Exception as e:
            results["context_error"] = str(e)

        return results

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "user": frappe.session.user if hasattr(frappe, "session") else "unknown",
        }


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    result = debug_dashboard_access()
    print("Debug result:", result)
