"""
Authentication Monitoring Utilities

This module provides monitoring and alerting for authentication issues,
particularly the "User None is disabled" error that was affecting the system.
"""

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.notification_helpers import resolve_admin_recipients
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


def log_auth_error(error_type, details, user=None):
    """
    Log authentication errors for monitoring and debugging

    Args:
        error_type (str): Type of error (e.g., "user_none_disabled", "session_corruption")
        details (str): Detailed error information
        user (str): User involved (if any)
    """
    try:
        frappe.logger().error(f"AUTH_MONITOR: {error_type} - {details} - User: {repr(user)}")

        # Create a system-level log entry for tracking
        error_log = frappe.new_doc("Error Log")
        error_log.error = (
            f"Authentication Monitor: {error_type}\n{details}\nUser: {repr(user)}\nTime: {now_datetime()}"
        )
        error_log.method = "auth_monitoring"
        # Security: System monitoring - must log auth errors regardless of user permissions
        error_log.save(ignore_permissions=True)

    except Exception as e:
        # Don't let monitoring break the system
        frappe.logger().error(f"AUTH_MONITOR: Failed to log error: {str(e)}")


def check_recent_auth_errors():
    """
    Check for recent "User None is disabled" errors and return summary

    Returns:
        dict: Summary of recent authentication errors
    """
    try:
        # Look for the specific error pattern in recent error logs
        # Site-tz clock: `Error Log.creation` is written by Frappe on the SITE
        # clock, so a process-clock cutoff makes this "last 24 hours" window the
        # full clock offset too long or too short -- at EVERY instant, not only
        # across a day boundary (#637).
        recent_time = now_datetime() - timedelta(hours=24)

        error_logs = frappe.get_all(
            "Error Log",
            filters={
                "creation": [">", recent_time.strftime("%Y-%m-%d %H:%M:%S")],
                "error": ["like", "%User None is disabled%"],
            },
            fields=["name", "creation", "error"],
            order_by="creation desc",
            limit=10,
        )

        return {
            "success": True,
            "error_count": len(error_logs),
            "recent_errors": error_logs,
            "last_24_hours": len(error_logs),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.ADMIN)
def get_auth_health_status():
    """
    Get the current authentication system health status

    Returns comprehensive health information for authentication system.
    Only accessible to users with System Manager role.
    """
    if not frappe.has_permission("System Settings", "read"):
        frappe.throw("You don't have permission to check authentication health")

    try:
        # Check recent errors
        error_summary = check_recent_auth_errors()

        # Check session health
        from verenigingen.utils.session_cleanup_enhanced import validate_current_session

        current_session = validate_current_session()

        # Check total session count
        session_count = frappe.db.sql("SELECT COUNT(*) FROM tabSessions")[0][0]

        # Check for invalid sessions
        invalid_sessions = frappe.db.sql(
            """
            SELECT COUNT(*) FROM tabSessions
            WHERE user IS NULL
               OR user = ''
               OR user = 'None'
               OR user = 'null'
               OR user = 'undefined'
               OR LENGTH(TRIM(user)) = 0
        """
        )[0][0]

        # Determine overall health status
        health_status = "healthy"
        warnings = []

        if error_summary["error_count"] > 0:
            health_status = "warning"
            warnings.append(f"{error_summary['error_count']} 'User None is disabled' errors in last 24h")

        if invalid_sessions > 0:
            health_status = "warning"
            warnings.append(f"{invalid_sessions} corrupted sessions found")

        if not current_session["valid"]:
            health_status = "error"
            warnings.append("Current session is invalid")

        return {
            "success": True,
            "health_status": health_status,
            "current_session": current_session,
            "total_sessions": session_count,
            "invalid_sessions": invalid_sessions,
            "recent_errors": error_summary,
            "warnings": warnings,
            "timestamp": now_datetime().isoformat(),
        }

    except Exception as e:
        return {"success": False, "error": str(e), "health_status": "error"}


AUTH_ALERT_KEY = "auth_monitoring_alert"

# The critical alert is a failed-login RATE across all users (maintainer ruling on #2285). The check runs
# daily, so the window is a day; Frappe itself locks one user out after a handful of failures, so a
# site-wide count this high is a spray across users or addresses, not one person's typos.
FAILED_LOGIN_WINDOW_HOURS = 24
FAILED_LOGIN_ALERT_THRESHOLD = 25
AUTH_ALERT_PROFILE = "Verenigingen System Administrator"


def get_auth_alert_recipients():
    """Who the critical authentication alert goes to (maintainer ruling on #2254).

    The key's own row in Verenigingen Email Configuration decides when someone has configured one.
    The seeded row is Custom (it names nobody), so the default audience is the enabled holders of the
    Verenigingen System Administrator role PROFILE, passed as the caller's own list. A ROLE filter would be
    wrong: System Manager or Verenigingen Administrator alone is not that profile. The Administrator user
    is never a recipient. With no holder the admin roles still get the alert, so it cannot vanish.
    """
    return resolve_admin_recipients(
        notification_key=AUTH_ALERT_KEY,
        extra_emails=_profile_holder_emails(AUTH_ALERT_PROFILE),
        exclude_users=("Administrator",),
        key_first=True,
    )


def _profile_holder_emails(profile):
    """Emails of enabled users holding ``profile``, recorded in the ``role_profiles`` child table or in the
    deprecated ``role_profile_name`` column (which mirrors only a user's FIRST profile)."""
    holders = set(frappe.get_all("User", filters={"role_profile_name": profile}, pluck="name"))
    if frappe.get_meta("User").has_field("role_profiles"):
        holders.update(
            frappe.get_all(
                "User Role Profile", filters={"role_profile": profile, "parenttype": "User"}, pluck="parent"
            )
        )
    if not holders:
        return []
    return frappe.get_all(
        "User",
        filters={"name": ["in", sorted(holders)], "enabled": 1, "email": ["is", "set"]},
        pluck="email",
        order_by="email asc",
    )


def count_recent_failed_logins():
    """Failed logins of every user in the last FAILED_LOGIN_WINDOW_HOURS, from Frappe's Activity Log.

    Frappe writes one ``operation=Login, status=Failed`` row per refused attempt (measured: also for a
    username that is no User). ``creation`` is stamped on the SITE clock, so the cutoff is
    ``now_datetime()``, not SQL ``NOW()`` (which is the server's zone).
    """
    cutoff = now_datetime() - timedelta(hours=FAILED_LOGIN_WINDOW_HOURS)
    return frappe.db.count(
        "Activity Log",
        {"operation": "Login", "status": "Failed", "creation": [">=", cutoff]},
    )


def alert_if_auth_issues():
    """Mail the critical authentication alert when failed logins across ALL users reach the threshold.

    Scheduled daily. This used to key on ``get_auth_health_status`` reporting ``"error"``, which only
    means the CURRENT session (the scheduler's own) is invalid, so it could not fire (#2285).
    """
    try:
        failed_logins = count_recent_failed_logins()
        if failed_logins < FAILED_LOGIN_ALERT_THRESHOLD:
            return
        _send_failed_login_alert(failed_logins)
    except Exception:
        frappe.log_error(title="auth_monitoring: failed-login alert crashed", message=frappe.get_traceback())


def _send_failed_login_alert(failed_logins):
    subject = "CRITICAL: High rate of failed logins detected"
    message = (
        f"{failed_logins} failed login attempts in the last {FAILED_LOGIN_WINDOW_HOURS} hours "
        f"on {frappe.local.site} (alert threshold: {FAILED_LOGIN_ALERT_THRESHOLD}).\n\n"
        "See the Activity Log (Operation: Login, Status: Failed) for the users and IP addresses involved."
    )
    recipients = get_auth_alert_recipients()
    if not recipients:
        frappe.log_error(
            title="auth_monitoring: failed-login alert has no recipient",
            message=f"{subject}\n{message}",
        )
        return

    result = get_email_service().send_simple_email(
        recipients=recipients,
        subject=subject,
        message=message,
        delayed=False,
        notification_key=AUTH_ALERT_KEY,
    )
    if not result.success:
        frappe.log_error(
            title="auth_monitoring: failed-login alert was not sent",
            message=f"{subject}\n{message}\n{result.error_message}",
        )
