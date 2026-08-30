"""
Authentication Monitoring Utilities

This module provides monitoring and alerting for authentication issues,
particularly the "User None is disabled" error that was affecting the system.
"""

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from verenigingen.services.communication.email_service import get_email_service
from verenigingen.utils.constants import Roles
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


def alert_if_auth_issues():
    """
    Check for authentication issues and send alerts if necessary

    This can be called from scheduled tasks to monitor authentication health.
    """
    try:
        health_status = get_auth_health_status()

        if not health_status["success"]:
            frappe.logger().error(f"AUTH_MONITOR: Health check failed: {health_status.get('error')}")
            return

        if health_status["health_status"] == "error":
            # Send critical alert
            subject = "CRITICAL: Authentication System Issues Detected"
            message = f"""
            Critical authentication issues detected on {frappe.local.site}:

            Warnings: {health_status['warnings']}
            Invalid Sessions: {health_status['invalid_sessions']}
            Recent Errors: {health_status['recent_errors']['error_count']}

            Please check the system immediately.
            """

            # Send to system administrators
            recipients = frappe.get_all(
                "User", filters={"role_profile_name": Roles.SYSTEM_MANAGER, "enabled": 1}, pluck="email"
            )

            if recipients:
                email_service = get_email_service()
                email_service.send_simple_email(
                    recipients=recipients,
                    subject=subject,
                    message=message,
                    delayed=False,
                    notification_key="auth_monitoring_alert",
                )

            frappe.logger().error(f"AUTH_MONITOR: Critical alert sent to {len(recipients)} administrators")

        elif (
            health_status["health_status"] == "warning" and health_status["recent_errors"]["error_count"] > 5
        ):
            # Send warning for frequent errors
            frappe.logger().warning(
                f"AUTH_MONITOR: High frequency of auth errors detected: {health_status['recent_errors']['error_count']} in 24h"
            )

    except Exception as e:
        frappe.logger().error(f"AUTH_MONITOR: Alert system failed: {str(e)}")
