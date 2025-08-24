"""
Enhanced Session Cleanup Utility

This module provides utilities to clean up corrupted sessions that could cause
"User None is disabled" errors and other authentication issues.

These utilities are designed to be safe to run in production and include
comprehensive logging for monitoring and debugging.
"""

from datetime import datetime, timedelta

import frappe
from frappe import _


def cleanup_corrupted_sessions():
    """
    Clean up corrupted sessions from the database

    This function safely removes sessions with invalid user values that could
    cause "User None is disabled" errors.

    Returns:
        dict: Summary of cleanup results
    """
    try:
        frappe.logger().info("Starting session cleanup process")

        # Count invalid sessions before cleanup
        invalid_sessions = frappe.db.sql(
            """
            SELECT sid, user, creation, modified
            FROM tabSessions
            WHERE user IS NULL
               OR user = ''
               OR user = 'None'
               OR user = 'null'
               OR user = 'undefined'
               OR LENGTH(TRIM(user)) = 0
        """,
            as_dict=True,
        )

        invalid_count = len(invalid_sessions)

        if invalid_count > 0:
            frappe.logger().warning(f"Found {invalid_count} corrupted sessions")

            # Log details of corrupted sessions for debugging
            for session in invalid_sessions[:5]:  # Log first 5 for analysis
                frappe.logger().warning(
                    f"Corrupted session: sid={session.sid}, user={repr(session.user)}, created={session.creation}"
                )

            # Delete invalid sessions
            frappe.db.sql(
                """
                DELETE FROM tabSessions
                WHERE user IS NULL
                   OR user = ''
                   OR user = 'None'
                   OR user = 'null'
                   OR user = 'undefined'
                   OR LENGTH(TRIM(user)) = 0
            """
            )

            frappe.logger().info(f"Deleted {invalid_count} corrupted sessions")
        else:
            frappe.logger().info("No corrupted sessions found")

        # Clean up old sessions (older than 7 days) to prevent accumulation
        cutoff_date = datetime.now() - timedelta(days=7)
        old_sessions_count = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM tabSessions
            WHERE creation < %s
        """,
            (cutoff_date,),
        )[0][0]

        if old_sessions_count > 0:
            frappe.db.sql(
                """
                DELETE FROM tabSessions
                WHERE creation < %s
            """,
                (cutoff_date,),
            )

            frappe.logger().info(f"Deleted {old_sessions_count} old sessions")

        frappe.db.commit()

        result = {
            "success": True,
            "invalid_sessions_deleted": invalid_count,
            "old_sessions_deleted": old_sessions_count,
            "total_deleted": invalid_count + old_sessions_count,
        }

        frappe.logger().info(f"Session cleanup completed: {result}")
        return result

    except Exception as e:
        frappe.logger().error(f"Error during session cleanup: {str(e)}")
        return {"success": False, "error": str(e)}


def validate_current_session():
    """
    Validate the current session and log any issues

    This is a diagnostic function to help identify session problems
    before they cause "User None is disabled" errors.

    Returns:
        dict: Session validation results
    """
    try:
        issues = []
        warnings = []

        # Check if session exists
        if not hasattr(frappe, "session") or not frappe.session:
            issues.append("frappe.session is not available")
            return {"valid": False, "issues": issues, "warnings": warnings}

        # Check if user attribute exists
        if not hasattr(frappe.session, "user"):
            issues.append("frappe.session.user attribute missing")
            return {"valid": False, "issues": issues, "warnings": warnings}

        user = frappe.session.user

        # Validate user value
        if user is None:
            issues.append("Session user is None")
        elif not isinstance(user, str):
            issues.append(f"Session user is not string: {type(user)} = {repr(user)}")
        elif user in ["", "None", "null", "undefined"]:
            issues.append(f"Session user has invalid value: {repr(user)}")
        elif len(user.strip()) == 0:
            issues.append("Session user is empty string")
        else:
            # User looks valid, check if it exists in database
            if user != "Guest" and user not in ["Administrator"] and not frappe.db.exists("User", user):
                warnings.append(f"Session user '{user}' does not exist in database")

        # Check session ID
        if hasattr(frappe.session, "sid"):
            if not frappe.session.sid:
                warnings.append("Session has no sid")
        else:
            warnings.append("Session has no sid attribute")

        is_valid = len(issues) == 0

        result = {
            "valid": is_valid,
            "user": repr(user) if "user" in locals() else "Not available",
            "issues": issues,
            "warnings": warnings,
        }

        if issues:
            frappe.logger().error(f"Session validation failed: {result}")
        elif warnings:
            frappe.logger().warning(f"Session validation warnings: {result}")
        else:
            frappe.logger().debug(f"Session validation passed: {result}")

        return result

    except Exception as e:
        frappe.logger().error(f"Error during session validation: {str(e)}")
        return {"valid": False, "error": str(e)}


@frappe.whitelist()
def run_session_cleanup():
    """
    API endpoint to run session cleanup

    This can be called from the UI or via API to clean up corrupted sessions.
    Only users with System Manager role can execute this.
    """
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("You don't have permission to run session cleanup"))

    result = cleanup_corrupted_sessions()

    if result["success"]:
        frappe.msgprint(
            _(
                "Session cleanup completed successfully. Deleted {0} invalid sessions and {1} old sessions."
            ).format(result["invalid_sessions_deleted"], result["old_sessions_deleted"])
        )
    else:
        frappe.throw(_("Session cleanup failed: {0}").format(result.get("error", "Unknown error")))

    return result


def scheduled_session_cleanup():
    """
    Scheduled task function to automatically clean up sessions

    This can be added to the hooks.py scheduler_events to run automatically.
    Recommended frequency: weekly
    """
    try:
        result = cleanup_corrupted_sessions()

        # Only log warnings if there were actually corrupted sessions found
        if result["success"] and result["total_deleted"] > 0:
            frappe.logger().warning(f"Scheduled session cleanup: deleted {result['total_deleted']} sessions")

        return result

    except Exception as e:
        frappe.logger().error(f"Scheduled session cleanup failed: {str(e)}")
        return {"success": False, "error": str(e)}


def emergency_session_reset():
    """
    Emergency function to clear all sessions except Administrator

    WARNING: This will log out all users! Only use in emergencies.
    """
    if not frappe.has_permission("System Settings", "write"):
        frappe.throw(_("You don't have permission to perform emergency session reset"))

    try:
        frappe.logger().warning("EMERGENCY: Starting complete session reset")

        # Count total sessions before reset
        total_before = frappe.db.sql("SELECT COUNT(*) FROM tabSessions")[0][0]

        # Keep only Administrator sessions
        frappe.db.sql(
            """
            DELETE FROM tabSessions
            WHERE user != 'Administrator'
        """
        )

        total_after = frappe.db.sql("SELECT COUNT(*) FROM tabSessions")[0][0]
        deleted = total_before - total_after

        frappe.db.commit()

        frappe.logger().warning(
            f"EMERGENCY: Session reset complete. Deleted {deleted} sessions, kept {total_after}"
        )

        return {"success": True, "sessions_deleted": deleted, "sessions_remaining": total_after}

    except Exception as e:
        frappe.logger().error(f"Emergency session reset failed: {str(e)}")
        return {"success": False, "error": str(e)}
