#!/usr/bin/env python3
"""
Security Monitoring Dashboard

Real-time security monitoring and alerting for the API Security Framework.
Provides comprehensive visibility into security events, violations, and system health.
"""

import json
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from verenigingen.utils.operation_result import OperationResult

# Security framework imports
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api
from verenigingen.utils.security.audit_logging import AuditEventType, AuditSeverity


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_security_dashboard_data(hours_back: int = 24) -> OperationResult[Dict[str, Any]]:
    """Get comprehensive security dashboard data"""

    try:
        hours_back = int(hours_back)
        if hours_back > 168:  # Limit to 1 week
            hours_back = 168

        cutoff_time = add_days(now_datetime(), -hours_back / 24)

        dashboard_data = {
            "summary": _get_security_summary(cutoff_time),
            "recent_events": _get_recent_security_events(cutoff_time, limit=50),
            "rate_limit_violations": _get_rate_limit_violations(cutoff_time),
            "authentication_failures": _get_authentication_failures(cutoff_time),
            "api_usage_stats": _get_api_usage_statistics(cutoff_time),
            "security_alerts": _get_active_security_alerts(),
            "framework_health": _get_framework_health_status(),
        }

        result = {
            "data": dashboard_data,
            "generated_at": now_datetime().isoformat(),
            "time_range_hours": hours_back,
        }

        return OperationResult.ok(result, message=_("Security dashboard data retrieved successfully"))

    except Exception as e:
        error_msg = f"Error generating security dashboard: {str(e)}"
        frappe.log_error(title="Security Dashboard Error", message=f"{error_msg}\n\n{traceback.format_exc()}")
        return OperationResult.fail(_("Failed to generate security dashboard data"), errors=[error_msg])


def _get_security_summary(cutoff_time):
    """Get high-level security metrics summary"""

    try:
        # Get audit log entries from the cutoff time
        audit_entries = frappe.get_all(
            "SEPA Audit Log",
            filters={"creation": [">=", cutoff_time]},
            fields=["process_type", "compliance_status", "creation"],
        )

        total_events = len(audit_entries)
        # Consider 'Failed' and 'Exception' statuses as failed events
        failed_events = len(
            [e for e in audit_entries if e.get("compliance_status") in ["Failed", "Exception"]]
        )
        # Consider 'Exception' status as critical
        critical_events = len([e for e in audit_entries if e.get("compliance_status") == "Exception"])

        return {
            "total_security_events": total_events,
            "failed_operations": failed_events,
            "critical_alerts": critical_events,
            "success_rate": (
                round((total_events - failed_events) / total_events * 100, 1) if total_events > 0 else 100
            ),
            "security_score": _calculate_security_score(audit_entries),
        }

    except Exception as e:
        frappe.log_error(f"Error getting security summary: {str(e)}")
        return {
            "total_security_events": 0,
            "failed_operations": 0,
            "critical_alerts": 0,
            "success_rate": 100,
            "security_score": 85,
        }


def _calculate_security_score(audit_entries):
    """Calculate overall security score based on recent events"""

    if not audit_entries:
        return 95  # High score if no events (quiet period)

    total_events = len(audit_entries)
    # Consider 'Failed' and 'Exception' statuses as failed events
    failed_events = len([e for e in audit_entries if e.get("compliance_status") in ["Failed", "Exception"]])
    # Consider 'Exception' status as critical
    critical_events = len([e for e in audit_entries if e.get("compliance_status") == "Exception"])

    # Base score
    score = 100

    # Deduct for failures
    failure_rate = failed_events / total_events if total_events > 0 else 0
    score -= failure_rate * 30  # Up to 30 points for failures

    # Deduct for critical events
    critical_rate = critical_events / total_events if total_events > 0 else 0
    score -= critical_rate * 20  # Up to 20 points for critical events

    return max(0, round(score, 1))


def _get_recent_security_events(cutoff_time, limit=50):
    """Get recent security events with details"""

    try:
        events = frappe.get_all(
            "SEPA Audit Log",
            filters={"creation": [">=", cutoff_time]},
            fields=[
                "name",
                "event_id",
                "timestamp",
                "process_type",
                "action",
                "compliance_status",
                "reference_doctype",
                "reference_name",
                "user",
                "trace_id",
                "details",
                "sensitive_data",
                "creation",
            ],
            order_by="creation desc",
            limit=limit,
        )

        formatted_events = []
        for event in events:
            # Map compliance_status to severity levels for display
            severity_map = {
                "Compliant": "info",
                "Exception": "critical",
                "Failed": "error",
                "Pending Review": "warning",
            }

            # Derive success from compliance_status
            success = event.get("compliance_status") == "Compliant"

            formatted_events.append(
                {
                    "timestamp": event.get("creation"),
                    "process_type": event.get("process_type"),
                    "severity": severity_map.get(event.get("compliance_status"), "info"),
                    "user": event.get("user"),
                    "description": f"{event.get('action', 'Unknown action')} - {event.get('compliance_status', 'Unknown status')}",
                    "success": success,
                    "ip_address": None,  # Field doesn't exist in schema
                    "details": json.loads(event.get("details", "{}")) if event.get("details") else {},
                }
            )

        return formatted_events

    except Exception as e:
        frappe.log_error(f"Error getting recent security events: {str(e)}")
        return []


def _unique_ips_from_rows(rows):
    """Collect distinct IPs from audit rows, preferring the ip_address column and
    falling back to an ip_address nested in the JSON details blob."""
    unique_ips = set()
    for row in rows:
        ip = row.get("ip_address")
        if not ip and row.get("details"):
            try:
                ip = json.loads(row.get("details") or "{}").get("ip_address")
            except (json.JSONDecodeError, TypeError, ValueError):
                ip = None
        if ip:
            unique_ips.add(ip)
    return unique_ips


def _get_rate_limit_violations(cutoff_time):
    """Get rate limiting violations"""

    try:
        # Rate-limit events are general API/security events, so the audit logger routes
        # them to API Audit Log (event_type), NOT SEPA Audit Log (process_type, whose
        # Select options are only the four SEPA workflow stages). Querying SEPA Audit
        # Log by process_type="rate_limit_exceeded" could never match — this panel was
        # permanently empty.
        violations = frappe.get_all(
            "API Audit Log",
            filters={"timestamp": [">=", cutoff_time], "event_type": "rate_limit_exceeded"},
            fields=["user", "ip_address", "timestamp", "details", "event_type"],
            order_by="timestamp desc",
        )

        unique_ips = _unique_ips_from_rows(violations)

        return {
            "total_violations": len(violations),
            "unique_users": len(set([v.get("user") for v in violations if v.get("user")])),
            "unique_ips": len(unique_ips),
            "recent_violations": violations[:10],  # Last 10 violations
        }

    except Exception as e:
        frappe.log_error(f"Error getting rate limit violations: {str(e)}")
        return {"total_violations": 0, "unique_users": 0, "unique_ips": 0, "recent_violations": []}


def _get_authentication_failures(cutoff_time):
    """Get authentication failure statistics"""

    try:
        # Authentication/authorization failures are general security events routed to
        # API Audit Log (event_type), not SEPA Audit Log. The prior query filtered SEPA
        # Audit Log by process_type in ("unauthorized_access_attempt",
        # "authentication_failed") — neither is a valid process_type Select option (and
        # "authentication_failed" is not a logged event type at all; the real login
        # failure event is "failed_login_attempt") — so it never matched.
        failures = frappe.get_all(
            "API Audit Log",
            filters={
                "timestamp": [">=", cutoff_time],
                "event_type": ["in", ["failed_login_attempt", "unauthorized_access_attempt"]],
            },
            fields=["user", "ip_address", "timestamp", "details", "event_type", "severity"],
            order_by="timestamp desc",
        )

        unique_ips = _unique_ips_from_rows(failures)

        return {
            "total_failures": len(failures),
            "unique_ips": len(unique_ips),
            "recent_failures": failures[:10],
        }

    except Exception as e:
        frappe.log_error(f"Error getting authentication failures: {str(e)}")
        return {"total_failures": 0, "unique_ips": 0, "recent_failures": []}


def _get_api_usage_statistics(cutoff_time):
    """Get API usage statistics"""

    try:
        # Get API usage from audit logs
        api_calls = frappe.get_all(
            "SEPA Audit Log",
            filters={"creation": [">=", cutoff_time]},
            fields=["process_type", "user", "creation"],
        )

        # Group by event type for popular endpoints
        endpoint_usage = {}
        for call in api_calls:
            process_type = call.get("process_type", "unknown")
            endpoint_usage[process_type] = endpoint_usage.get(process_type, 0) + 1

        # Sort by usage
        popular_endpoints = sorted(endpoint_usage.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_api_calls": len(api_calls),
            "unique_users": len(set([c.get("user") for c in api_calls if c.get("user")])),
            "popular_endpoints": [{"endpoint": ep, "calls": count} for ep, count in popular_endpoints],
            "avg_calls_per_hour": len(api_calls) / 24 if api_calls else 0,
        }

    except Exception as e:
        frappe.log_error(f"Error getting API usage statistics: {str(e)}")
        return {"total_api_calls": 0, "unique_users": 0, "popular_endpoints": [], "avg_calls_per_hour": 0}


def _get_active_security_alerts():
    """Get active security alerts that need attention"""

    alerts = []

    try:
        # Check for recent critical security events (Exception status)
        recent_critical = frappe.get_all(
            "SEPA Audit Log",
            filters={"creation": [">=", add_days(now_datetime(), -1)], "compliance_status": "Exception"},
            limit=5,
        )

        if recent_critical:
            alerts.append(
                {
                    "severity": "HIGH",
                    "type": "Critical Security Events",
                    "count": len(recent_critical),
                    "message": f"{len(recent_critical)} critical security events in the last 24 hours",
                    "action_required": "Review and investigate critical failures",
                }
            )

        # Check for high rate limit violations. Rate-limit events live in API Audit Log
        # (event_type), not SEPA Audit Log (process_type) — see _get_rate_limit_violations.
        rate_violations = frappe.get_all(
            "API Audit Log",
            filters={"timestamp": [">=", add_days(now_datetime(), -1)], "event_type": "rate_limit_exceeded"},
        )

        if len(rate_violations) > 10:
            alerts.append(
                {
                    "severity": "MEDIUM",
                    "type": "High Rate Limit Violations",
                    "count": len(rate_violations),
                    "message": f"{len(rate_violations)} rate limit violations detected",
                    "action_required": "Review user access patterns and adjust limits if needed",
                }
            )

        return alerts

    except Exception as e:
        frappe.log_error(f"Error getting security alerts: {str(e)}")
        return []


def _get_framework_health_status():
    """Get health status of security framework components"""

    try:
        health_status = {"overall_status": "HEALTHY", "components": {}}

        # Test each component
        try:
            from verenigingen.utils.security.api_security_framework import APISecurityFramework

            health_status["components"]["api_security_framework"] = "✅ OPERATIONAL"
        except Exception:
            health_status["components"]["api_security_framework"] = "❌ ERROR"
            health_status["overall_status"] = "DEGRADED"

        try:
            from verenigingen.utils.security.audit_logging import get_audit_logger

            # audit_logger = get_audit_logger()  # Unused variable
            health_status["components"]["audit_logging"] = "✅ OPERATIONAL"
        except Exception:
            health_status["components"]["audit_logging"] = "❌ ERROR"
            health_status["overall_status"] = "DEGRADED"

        try:
            # Rate limiting is now COR-based - check if COR DocType is accessible
            cor_count = frappe.db.count("Critical Operation Rule", {"enabled": 1})
            health_status["components"]["rate_limiting"] = f"✅ OPERATIONAL (COR-based, {cor_count} rules)"
        except Exception:
            health_status["components"]["rate_limiting"] = "❌ ERROR"
            health_status["overall_status"] = "DEGRADED"

        try:
            from verenigingen.utils.security.csrf_protection import CSRFProtection

            health_status["components"]["csrf_protection"] = "✅ OPERATIONAL"
        except Exception:
            health_status["components"]["csrf_protection"] = "❌ ERROR"
            health_status["overall_status"] = "DEGRADED"

        return health_status

    except Exception as e:
        frappe.log_error(f"Error checking framework health: {str(e)}")
        return {"overall_status": "ERROR", "components": {}, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_security_metrics_summary() -> OperationResult[Dict[str, Any]]:
    """Get quick security metrics for overview"""

    try:
        cutoff_time = add_days(now_datetime(), -1)  # Last 24 hours

        summary = _get_security_summary(cutoff_time)
        rate_violations = _get_rate_limit_violations(cutoff_time)
        auth_failures = _get_authentication_failures(cutoff_time)
        api_usage = _get_api_usage_statistics(cutoff_time)

        result = {
            "security_score": summary.get("security_score", 85),
            "total_events_24h": summary.get("total_security_events", 0),
            "rate_violations_24h": rate_violations.get("total_violations", 0),
            "auth_failures_24h": auth_failures.get("total_failures", 0),
            "api_calls_24h": api_usage.get("total_api_calls", 0),
            "framework_status": _get_framework_health_status().get("overall_status", "UNKNOWN"),
        }

        return OperationResult.ok(result, message=_("Security metrics summary retrieved successfully"))

    except Exception as e:
        error_msg = f"Error getting security metrics summary: {str(e)}"
        frappe.log_error(title="Security Metrics Error", message=f"{error_msg}\n\n{traceback.format_exc()}")
        return OperationResult.fail(_("Failed to retrieve security metrics summary"), errors=[error_msg])


if __name__ == "__main__":
    print("🔐 Security Monitoring Dashboard")
    print(
        "Access via: bench --site dev.veganisme.net execute verenigingen.api.security_monitoring_dashboard.get_security_dashboard_data"
    )
