"""
Session Cleanup Utilities

Provides safe session cleanup functions that don't interfere with Frappe's
core session management. These can be called from background jobs or
administrative functions as needed.
"""

from datetime import timedelta

import frappe
from frappe.utils import now_datetime


def cleanup_corrupted_sessions():
    """
    Clean up corrupted sessions from the database

    This should be run as a background job, not during request processing,
    to avoid interfering with active session creation.

    Returns:
        dict: Cleanup statistics
    """
    try:
        stats = {"deleted_invalid": 0, "deleted_old": 0, "errors": []}

        # Delete sessions with clearly invalid users
        invalid_deleted = frappe.db.sql(
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

        stats["deleted_invalid"] = invalid_deleted[0] if invalid_deleted else 0

        # Delete old sessions (older than 7 days)
        week_ago = (now_datetime() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        old_deleted = frappe.db.sql(
            """
            DELETE FROM `tabSessions`
            WHERE creation < %s
        """,
            week_ago,
        )

        stats["deleted_old"] = old_deleted[0] if old_deleted else 0

        # Commit the changes
        frappe.db.commit()

        # Log the cleanup
        frappe.logger().info(f"Session cleanup completed: {stats}")

        return stats

    except Exception as e:
        error_msg = f"Session cleanup error: {str(e)}"
        frappe.logger().error(error_msg)
        return {"error": error_msg}


def validate_current_session():
    """
    Safely validate the current session without interfering with request processing

    Returns:
        dict: Session validation info
    """
    try:
        info = {"valid": True, "user": None, "warnings": []}

        # Check if session exists
        if not hasattr(frappe, "session") or not frappe.session:
            info["valid"] = False
            info["warnings"].append("No session object")
            return info

        # Get user safely
        user = getattr(frappe.session, "user", None)
        info["user"] = user

        # Check for obviously invalid users
        if user and isinstance(user, str) and user.strip() == "None":
            info["valid"] = False
            info["warnings"].append("User is string 'None'")

        if not user or not isinstance(user, str):
            info["warnings"].append(f"User is not a valid string: {repr(user)}")

        return info

    except Exception as e:
        return {"valid": False, "error": str(e), "warnings": ["Exception during validation"]}


@frappe.whitelist(allow_guest=True)
def get_session_debug_info():
    """
    API endpoint to get session debugging information
    Safe to call without interfering with session state
    """
    try:
        info = validate_current_session()

        # Add additional debug info
        info["session_exists"] = hasattr(frappe, "session") and bool(frappe.session)
        info["local_exists"] = hasattr(frappe, "local")

        if hasattr(frappe, "session") and frappe.session:
            info["session_sid"] = getattr(frappe.session, "sid", "No SID")

        return info

    except Exception as e:
        return {"error": str(e)}


def schedule_session_cleanup():
    """
    Schedule regular session cleanup as a background job
    This is the safe way to handle session maintenance
    """
    try:
        # Enqueue cleanup job to run in background
        frappe.enqueue(
            "verenigingen.utils.session_cleanup.cleanup_corrupted_sessions",
            timeout=300,  # 5 minutes
            is_async=True,
            job_name="session_cleanup",
        )

        return {"status": "scheduled", "message": "Session cleanup job scheduled"}

    except Exception as e:
        frappe.logger().error(f"Failed to schedule session cleanup: {e}")
        return {"status": "error", "message": str(e)}
