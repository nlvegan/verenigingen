"""
Session Validation Fix Patch

This patch prevents the "User None is disabled" error by adding
defensive session handling in the authentication hooks.
"""

import frappe
from frappe.patches.utils import execute_patch


def execute():
    """Execute the session validation fix patch"""

    # Add a custom method to handle session validation more gracefully
    setup_session_validation_hook()

    # Clean up any existing corrupted sessions
    cleanup_corrupted_sessions()

    print("✅ Session validation fix patch applied successfully")


def setup_session_validation_hook():
    """Set up custom session validation hook"""

    # Add a before_request hook to catch and handle session validation errors
    from verenigingen import hooks

    # Ensure our session validation runs early
    if "before_request" not in hooks.__dict__:
        hooks.before_request = []

    # Add our session validation function if not already present
    session_validator = "verenigingen.auth_hooks.validate_session_before_request"
    if session_validator not in hooks.before_request:
        hooks.before_request.append(session_validator)
        print("   ✅ Added session validation hook")


def cleanup_corrupted_sessions():
    """Clean up any corrupted sessions from the database"""

    try:
        # Delete sessions with invalid users
        deleted_count = frappe.db.sql(
            """
            DELETE FROM `tabSessions`
            WHERE user IS NULL
               OR user = ''
               OR user = 'None'
               OR user = 'null'
               OR user = 'undefined'
               OR LENGTH(TRIM(user)) = 0
        """
        )

        # Delete old sessions (older than 7 days)
        old_deleted = frappe.db.sql(
            """
            DELETE FROM `tabSessions`
            WHERE modified < DATE_SUB(NOW(), INTERVAL 7 DAY)
        """
        )

        frappe.db.commit()

        print(f"   ✅ Cleaned up corrupted sessions (deleted: {deleted_count + old_deleted})")

    except Exception as e:
        print(f"   ⚠️ Session cleanup warning: {e}")
        # Don't fail the patch if session cleanup has issues
