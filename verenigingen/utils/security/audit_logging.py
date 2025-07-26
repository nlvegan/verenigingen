"""
Comprehensive Audit Logging System for Verenigingen SEPA Operations

This module provides structured logging, audit trails, and security event
monitoring for all SEPA operations with configurable retention and alerting.
"""

import json
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.utils import add_days, now, today

from verenigingen.utils.error_handling import log_error


class AuditEventType(Enum):
    """Audit event types for categorization"""

    # SEPA Operations
    SEPA_BATCH_CREATED = "sepa_batch_created"
    SEPA_BATCH_VALIDATED = "sepa_batch_validated"
    SEPA_BATCH_PROCESSED = "sepa_batch_processed"
    SEPA_BATCH_CANCELLED = "sepa_batch_cancelled"
    SEPA_XML_GENERATED = "sepa_xml_generated"
    SEPA_INVOICE_LOADED = "sepa_invoice_loaded"
    SEPA_MANDATE_VALIDATED = "sepa_mandate_validated"

    # Security Events
    CSRF_VALIDATION_SUCCESS = "csrf_validation_success"
    CSRF_VALIDATION_FAILED = "csrf_validation_failed"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    UNAUTHORIZED_ACCESS_ATTEMPT = "unauthorized_access_attempt"
    PERMISSION_DENIED = "permission_denied"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"

    # Authentication Events
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    SESSION_EXPIRED = "session_expired"
    FAILED_LOGIN_ATTEMPT = "failed_login_attempt"

    # Data Events
    SENSITIVE_DATA_ACCESS = "sensitive_data_access"
    DATA_EXPORT = "data_export"
    DATA_IMPORT = "data_import"
    DATA_MODIFICATION = "data_modification"

    # System Events
    CONFIGURATION_CHANGE = "configuration_change"
    SYSTEM_ERROR = "system_error"
    PERFORMANCE_ALERT = "performance_alert"


class AuditSeverity(Enum):
    """Audit event severity levels"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class SEPAAuditLogger:
    """
    Comprehensive audit logging system for SEPA operations

    Provides structured logging with retention policies, alerting,
    and security event monitoring.
    """

    # Retention policies (days)
    RETENTION_POLICIES = {
        AuditSeverity.INFO: 30,
        AuditSeverity.WARNING: 90,
        AuditSeverity.ERROR: 365,
        AuditSeverity.CRITICAL: 2555,  # 7 years for critical events
    }

    # Alert thresholds
    ALERT_THRESHOLDS = {
        AuditEventType.CSRF_VALIDATION_FAILED: {"count": 5, "window_minutes": 15},
        AuditEventType.RATE_LIMIT_EXCEEDED: {"count": 10, "window_minutes": 60},
        AuditEventType.UNAUTHORIZED_ACCESS_ATTEMPT: {"count": 3, "window_minutes": 5},
        AuditEventType.FAILED_LOGIN_ATTEMPT: {"count": 5, "window_minutes": 30},
        AuditEventType.SUSPICIOUS_ACTIVITY: {"count": 1, "window_minutes": 1},
    }

    def __init__(self):
        """Initialize audit logger"""
        self.logger = frappe.logger("sepa_audit", allow_site=True, file_count=50)

    def log_event(
        self,
        event_type: Union[AuditEventType, str],
        severity: Union[AuditSeverity, str] = AuditSeverity.INFO,
        user: str = None,
        ip_address: str = None,
        details: Dict[str, Any] = None,
        sensitive_data: bool = False,
    ) -> str:
        """
        Log an audit event

        Args:
            event_type: Type of event (AuditEventType enum or string)
            severity: Event severity (AuditSeverity enum or string)
            user: User email (defaults to current user)
            ip_address: IP address (defaults to current request IP)
            details: Additional event details
            sensitive_data: Whether event contains sensitive data

        Returns:
            Event ID for tracking
        """
        # Convert enums to strings
        if isinstance(event_type, AuditEventType):
            event_type = event_type.value
        if isinstance(severity, AuditSeverity):
            severity = severity.value

        # Get default values
        if not user:
            user = getattr(frappe.session, "user", "System")
        if not ip_address:
            ip_address = getattr(frappe.local, "request_ip", "unknown")

        # Generate unique event ID
        event_id = f"audit_{int(time.time() * 1000)}_{hash(f'{user}{event_type}{time.time()}') % 100000:05d}"

        # Build audit event
        audit_event = {
            "event_id": event_id,
            "timestamp": now(),
            "event_type": event_type,
            "severity": severity,
            "user": user,
            "ip_address": ip_address,
            "user_agent": frappe.get_request_header("User-Agent") or "unknown",
            "referer": frappe.get_request_header("Referer") or "",
            "session_id": getattr(frappe.session, "sid", "unknown"),
            "site": getattr(frappe.local, "site", "unknown"),
            "details": details or {},
            "sensitive_data": sensitive_data,
        }

        # Add user context if available
        if user and user != "Guest":
            try:
                user_roles = frappe.get_roles(user)
                audit_event["user_roles"] = user_roles
            except:
                audit_event["user_roles"] = []

        try:
            # Store in audit log table
            self._store_audit_event(audit_event)

            # Log to file system
            self._log_to_file(audit_event)

            # Check for alert conditions
            self._check_alert_conditions(audit_event)

            return event_id

        except Exception as e:
            # Fallback logging if audit system fails
            frappe.log_error(f"Audit logging failed for event {event_type}: {str(e)}", "Audit System Error")
            return f"failed_{int(time.time())}"

    def _store_audit_event(self, audit_event: Dict[str, Any]):
        """Store audit event in database"""
        try:
            # Create audit log entry
            audit_doc = frappe.new_doc("SEPA Audit Log")
            audit_doc.update(
                {
                    "event_id": audit_event["event_id"],
                    "timestamp": audit_event["timestamp"],
                    "event_type": audit_event["event_type"],
                    "severity": audit_event["severity"],
                    "user": audit_event["user"],
                    "ip_address": audit_event["ip_address"],
                    "user_agent": audit_event["user_agent"][:500] if audit_event["user_agent"] else "",
                    "referer": audit_event["referer"][:500] if audit_event["referer"] else "",
                    "session_id": audit_event["session_id"],
                    "details": json.dumps(audit_event["details"], default=str),
                    "sensitive_data": audit_event["sensitive_data"],
                }
            )

            # Insert without triggering additional validation
            audit_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            # If database storage fails, log to error log
            frappe.log_error(
                f"Failed to store audit event in database: {str(e)}\nEvent: {json.dumps(audit_event, default=str)}",
                "Audit Database Error",
            )

    def _log_to_file(self, audit_event: Dict[str, Any]):
        """Log audit event to file system"""
        try:
            # Format log message
            log_message = (
                f"AUDIT: {audit_event['event_type']} | {audit_event['user']} | {audit_event['ip_address']}"
            )

            # Add details if not sensitive
            if not audit_event["sensitive_data"] and audit_event["details"]:
                details_str = json.dumps(audit_event["details"], default=str)[:200]
                log_message += f" | {details_str}"

            # Log based on severity
            if audit_event["severity"] == "critical":
                self.logger.critical(log_message, extra=audit_event)
            elif audit_event["severity"] == "error":
                self.logger.error(log_message, extra=audit_event)
            elif audit_event["severity"] == "warning":
                self.logger.warning(log_message, extra=audit_event)
            else:
                self.logger.info(log_message, extra=audit_event)

        except Exception as e:
            # Even file logging failed - use frappe's error log as last resort
            frappe.log_error(
                f"File audit logging failed: {str(e)}\nEvent: {json.dumps(audit_event, default=str)}",
                "Audit File Error",
            )

    def _check_alert_conditions(self, audit_event: Dict[str, Any]):
        """Check if event triggers alert conditions"""
        try:
            event_type = audit_event["event_type"]

            # Check if this event type has alert thresholds
            if event_type not in [et.value for et in AuditEventType]:
                return

            event_enum = AuditEventType(event_type)
            if event_enum not in self.ALERT_THRESHOLDS:
                return

            threshold_config = self.ALERT_THRESHOLDS[event_enum]

            # Count recent events of this type
            recent_events = self._count_recent_events(event_type, threshold_config["window_minutes"])

            # Check if threshold exceeded
            if recent_events >= threshold_config["count"]:
                self._trigger_security_alert(event_type, recent_events, threshold_config)

        except Exception as e:
            frappe.log_error(f"Alert checking failed: {str(e)}", "Audit Alert Error")

    def _count_recent_events(self, event_type: str, window_minutes: int) -> int:
        """Count recent events of specific type"""
        try:
            cutoff_time = add_days(now(), days=0, hours=0, minutes=-window_minutes)

            count = frappe.db.count(
                "SEPA Audit Log", filters={"event_type": event_type, "timestamp": [">", cutoff_time]}
            )

            return count

        except Exception:
            return 0

    def _trigger_security_alert(self, event_type: str, count: int, threshold: Dict[str, Any]):
        """Trigger security alert"""
        try:
            # Create security alert
            alert_message = _(
                "Security Alert: {0} events of type '{1}' in {2} minutes (threshold: {3})"
            ).format(count, event_type, threshold["window_minutes"], threshold["count"])

            # Log critical alert
            self.log_event(
                AuditEventType.SUSPICIOUS_ACTIVITY,
                AuditSeverity.CRITICAL,
                details={
                    "alert_type": "threshold_exceeded",
                    "triggered_event_type": event_type,
                    "event_count": count,
                    "threshold": threshold,
                    "alert_message": alert_message,
                },
            )

            # Send notification to administrators
            self._send_security_notification(alert_message, event_type, count)

        except Exception as e:
            frappe.log_error(f"Security alert failed: {str(e)}", "Security Alert Error")

    def _send_security_notification(self, message: str, event_type: str, count: int):
        """Send security notification to administrators"""
        try:
            # Get admin users
            admin_users = frappe.get_all("User", filters={"enabled": 1}, fields=["email", "full_name"])

            # Filter to users with security roles
            security_roles = ["System Manager", "Verenigingen Administrator"]
            admin_emails = []

            for user in admin_users:
                user_roles = frappe.get_roles(user.email)
                if any(role in security_roles for role in user_roles):
                    admin_emails.append(user.email)

            if admin_emails:
                # Send email notification
                frappe.sendmail(
                    recipients=admin_emails,
                    subject=f"Security Alert: {event_type}",
                    message=f"""
                    <h3>Security Alert Triggered</h3>
                    <p><strong>Event Type:</strong> {event_type}</p>
                    <p><strong>Count:</strong> {count}</p>
                    <p><strong>Message:</strong> {message}</p>
                    <p><strong>Time:</strong> {now()}</p>
                    <p><strong>Site:</strong> {frappe.local.site}</p>

                    <p>Please review the audit logs for more details.</p>
                    """,
                    now=True,
                )

        except Exception as e:
            frappe.log_error(f"Security notification failed: {str(e)}", "Security Notification Error")

    def search_audit_logs(
        self,
        event_types: List[str] = None,
        users: List[str] = None,
        start_date: str = None,
        end_date: str = None,
        severity: str = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Search audit logs with filters

        Args:
            event_types: List of event types to filter
            users: List of users to filter
            start_date: Start date for search
            end_date: End date for search
            severity: Severity level to filter
            limit: Maximum number of results

        Returns:
            List of audit log entries
        """
        try:
            filters = {}

            if event_types:
                filters["event_type"] = ["in", event_types]
            if users:
                filters["user"] = ["in", users]
            if start_date:
                filters["timestamp"] = [">=", start_date]
            if end_date:
                if "timestamp" in filters:
                    filters["timestamp"] = ["between", [filters["timestamp"][1], end_date]]
                else:
                    filters["timestamp"] = ["<=", end_date]
            if severity:
                filters["severity"] = severity

            logs = frappe.get_all(
                "SEPA Audit Log",
                filters=filters,
                fields=[
                    "event_id",
                    "timestamp",
                    "event_type",
                    "severity",
                    "user",
                    "ip_address",
                    "details",
                    "sensitive_data",
                ],
                order_by="timestamp desc",
                limit=limit,
            )

            # Parse details JSON
            for log in logs:
                try:
                    log["details"] = json.loads(log["details"]) if log["details"] else {}
                except:
                    log["details"] = {}

            return logs

        except Exception as e:
            log_error(e, context={"filters": locals()}, module="verenigingen.utils.security.audit_logging")
            return []

    def cleanup_old_logs(self):
        """Clean up old audit logs based on retention policies"""
        try:
            for severity, retention_days in self.RETENTION_POLICIES.items():
                cutoff_date = add_days(today(), -retention_days)

                # Delete old logs
                old_logs = frappe.get_all(
                    "SEPA Audit Log",
                    filters={"severity": severity.value, "timestamp": ["<", cutoff_date]},
                    pluck="name",
                )

                if old_logs:
                    for log_name in old_logs:
                        frappe.delete_doc("SEPA Audit Log", log_name, ignore_permissions=True)

                    frappe.db.commit()

                    self.log_event(
                        "audit_cleanup",
                        AuditSeverity.INFO,
                        details={
                            "severity": severity.value,
                            "deleted_count": len(old_logs),
                            "cutoff_date": str(cutoff_date),
                        },
                    )

        except Exception as e:
            log_error(
                e,
                context={"retention_policies": self.RETENTION_POLICIES},
                module="verenigingen.utils.security.audit_logging",
            )


# Global audit logger instance
_audit_logger = None


def get_audit_logger() -> SEPAAuditLogger:
    """Get global audit logger instance"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = SEPAAuditLogger()
    return _audit_logger


# Convenience functions for common audit events
def log_sepa_event(event_type: str, details: Dict[str, Any] = None, severity: str = "info"):
    """Log SEPA-specific audit event"""
    logger = get_audit_logger()
    return logger.log_event(event_type, severity, details=details)


def log_security_event(event_type: str, details: Dict[str, Any] = None, severity: str = "warning"):
    """Log security-related audit event"""
    logger = get_audit_logger()
    return logger.log_event(event_type, severity, details=details)


def log_data_access(resource: str, action: str, details: Dict[str, Any] = None):
    """Log data access event"""
    logger = get_audit_logger()
    return logger.log_event(
        AuditEventType.SENSITIVE_DATA_ACCESS,
        AuditSeverity.INFO,
        details={"resource": resource, "action": action, **(details or {})},
        sensitive_data=True,
    )


# Decorator for automatic audit logging
def audit_log(event_type: str, severity: str = "info", capture_args: bool = False):
    """
    Decorator to automatically log function calls

    Usage:
        @audit_log("sepa_batch_created", "info", capture_args=True)
        def create_sepa_batch(**kwargs):
            # Function implementation
    """

    def decorator(func):
        from functools import wraps

        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            logger = get_audit_logger()

            # Prepare audit details
            details = {"function": func.__name__, "module": func.__module__, "start_time": start_time}

            # Capture arguments if requested (be careful with sensitive data)
            if capture_args:
                details["args_count"] = len(args)
                details["kwargs_keys"] = list(kwargs.keys())
                # Don't capture actual values to avoid logging sensitive data

            try:
                result = func(*args, **kwargs)

                # Log successful execution
                execution_time = time.time() - start_time
                details.update({"status": "success", "execution_time_ms": round(execution_time * 1000, 2)})

                logger.log_event(event_type, severity, details=details)

                return result

            except Exception as e:
                # Log failed execution
                execution_time = time.time() - start_time
                details.update(
                    {
                        "status": "error",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "execution_time_ms": round(execution_time * 1000, 2),
                    }
                )

                logger.log_event(event_type, "error", details=details)

                # Re-raise the exception
                raise

        return wrapper

    return decorator


# API endpoints for audit log management
@frappe.whitelist()
def search_audit_logs(**filters):
    """
    API endpoint to search audit logs

    Returns:
        List of audit log entries
    """
    # Require admin permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access audit logs"), frappe.PermissionError)

    try:
        logger = get_audit_logger()
        logs = logger.search_audit_logs(**filters)

        return {"success": True, "logs": logs, "count": len(logs)}

    except Exception as e:
        log_error(e, context={"filters": filters}, module="verenigingen.utils.security.audit_logging")

        return {"success": False, "error": _("Failed to search audit logs"), "message": str(e)}


@frappe.whitelist()
def get_audit_statistics(days: int = 7):
    """
    Get audit log statistics

    Args:
        days: Number of days to analyze

    Returns:
        Dictionary with statistics
    """
    # Require admin permission
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only System Managers can access audit statistics"), frappe.PermissionError)

    try:
        start_date = add_days(today(), -days)

        # Get event type counts
        event_counts = frappe.db.sql(
            """
            SELECT event_type, COUNT(*) as count
            FROM `tabSEPA Audit Log`
            WHERE timestamp >= %s
            GROUP BY event_type
            ORDER BY count DESC
        """,
            [start_date],
            as_dict=True,
        )

        # Get severity counts
        severity_counts = frappe.db.sql(
            """
            SELECT severity, COUNT(*) as count
            FROM `tabSEPA Audit Log`
            WHERE timestamp >= %s
            GROUP BY severity
        """,
            [start_date],
            as_dict=True,
        )

        # Get user activity
        user_activity = frappe.db.sql(
            """
            SELECT user, COUNT(*) as count
            FROM `tabSEPA Audit Log`
            WHERE timestamp >= %s AND user != 'System'
            GROUP BY user
            ORDER BY count DESC
            LIMIT 10
        """,
            [start_date],
            as_dict=True,
        )

        # Get daily activity
        daily_activity = frappe.db.sql(
            """
            SELECT DATE(timestamp) as date, COUNT(*) as count
            FROM `tabSEPA Audit Log`
            WHERE timestamp >= %s
            GROUP BY DATE(timestamp)
            ORDER BY date
        """,
            [start_date],
            as_dict=True,
        )

        return {
            "success": True,
            "period_days": days,
            "event_types": event_counts,
            "severity_levels": severity_counts,
            "user_activity": user_activity,
            "daily_activity": daily_activity,
        }

    except Exception as e:
        log_error(e, context={"days": days}, module="verenigingen.utils.security.audit_logging")

        return {"success": False, "error": _("Failed to get audit statistics"), "message": str(e)}


def setup_audit_logging():
    """
    Setup audit logging during app initialization
    """
    # Initialize global audit logger
    global _audit_logger
    _audit_logger = SEPAAuditLogger()

    # Log setup completion
    _audit_logger.log_event(
        "audit_system_initialized",
        AuditSeverity.INFO,
        details={
            "retention_policies": {k.value: v for k, v in _audit_logger.RETENTION_POLICIES.items()},
            "alert_thresholds": {k.value: v for k, v in _audit_logger.ALERT_THRESHOLDS.items()},
        },
    )
