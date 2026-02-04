"""
Monitoring Dashboard Web Page Controller

Provides the web interface for the system monitoring dashboard with real-time
metrics, security monitoring, and compliance tracking.

This controller delegates business logic to:
- MonitoringMetricsService: System metrics and performance data
- ComplianceMetricsService: Compliance and audit metrics
- AnalyticsEngine: Advanced analytics and forecasting
- SecurityMonitor: Security metrics and incident tracking
"""

import frappe
from frappe.utils import now

from verenigingen.api.security_monitoring_dashboard import get_security_dashboard_data
from verenigingen.services.monitoring.compliance_metrics_service import (
    ComplianceMetricsService,
)
from verenigingen.services.monitoring.monitoring_metrics_service import (
    MonitoringMetricsService,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    standard_api,
)
from verenigingen.utils.security.security_monitoring import get_security_monitor


def get_context(context):
    """Get context for monitoring dashboard page."""
    # Require System Manager or Verenigingen Administrator permissions
    user_roles = frappe.get_roles()
    if not ("System Manager" in user_roles or "Verenigingen Administrator" in user_roles):
        frappe.throw(
            "Access Denied: System Manager or Verenigingen Administrator role required",
            frappe.PermissionError,
        )

    metrics_service = MonitoringMetricsService()
    compliance_service = ComplianceMetricsService()

    try:
        context.update(
            {
                "system_metrics": metrics_service.get_system_metrics(),
                "recent_errors": metrics_service.get_recent_errors(),
                "audit_summary": metrics_service.get_audit_summary(),
                "alerts": metrics_service.get_active_alerts(),
                "performance_metrics": metrics_service.get_performance_metrics(),
                # Analytics
                "analytics_summary": get_analytics_summary(),
                "trend_forecasts": get_trend_forecasts(),
                "compliance_metrics": compliance_service.get_compliance_metrics(),
                "optimization_insights": get_optimization_insights(),
                "executive_summary": get_executive_summary(),
                # Security
                "security_dashboard": get_security_metrics_for_dashboard(),
                "security_framework_health": get_security_framework_health(),
            }
        )
    except Exception as e:
        frappe.log_error(f"Error loading monitoring dashboard: {str(e)}")
        _set_fallback_context(context)


def _set_fallback_context(context):
    """Set fallback values when data loading fails."""
    context.update(
        {
            "system_metrics": {"error": "Failed to load metrics"},
            "recent_errors": [],
            "audit_summary": [],
            "alerts": [],
            "performance_metrics": {"error": "Failed to load performance data"},
            "analytics_summary": {"error": "Failed to load analytics"},
            "trend_forecasts": {"error": "Failed to load forecasts"},
            "compliance_metrics": {"error": "Failed to load compliance data"},
            "optimization_insights": {"error": "Failed to load insights"},
            "executive_summary": {"error": "Failed to load executive summary"},
            "security_dashboard": {"error": "Failed to load security metrics"},
            "security_framework_health": {"error": "Failed to load security framework health"},
        }
    )


# ===== API ENDPOINTS =====


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_system_metrics():
    """Get real-time system metrics."""
    return MonitoringMetricsService().get_system_metrics()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_recent_errors():
    """Get recent error summary."""
    return MonitoringMetricsService().get_recent_errors()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_audit_summary():
    """Get audit trail summary."""
    return MonitoringMetricsService().get_audit_summary()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_active_alerts():
    """Get active system alerts."""
    return MonitoringMetricsService().get_active_alerts()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_performance_metrics():
    """Get performance metrics."""
    return MonitoringMetricsService().get_performance_metrics()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def refresh_dashboard_data():
    """Refresh all dashboard data."""
    try:
        metrics_service = MonitoringMetricsService()
        return {
            "system_metrics": metrics_service.get_system_metrics(),
            "recent_errors": metrics_service.get_recent_errors(),
            "audit_summary": metrics_service.get_audit_summary(),
            "alerts": metrics_service.get_active_alerts(),
            "performance_metrics": metrics_service.get_performance_metrics(),
            "security_dashboard": get_security_metrics_for_dashboard(),
            "security_framework_health": get_security_framework_health(),
            "timestamp": now(),
        }
    except Exception as e:
        frappe.log_error(f"Error refreshing dashboard data: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def test_monitoring_system():
    """Test the monitoring system functionality."""
    try:
        from verenigingen.verenigingen.doctype.system_alert.system_alert import SystemAlert

        test_alert = SystemAlert.create_alert(
            alert_type="TEST_MONITORING",
            severity="LOW",
            message="Test alert generated from monitoring dashboard",
            details={"test": True, "timestamp": now()},
        )

        return {
            "status": "success",
            "message": "Test alert created successfully",
            "alert_name": test_alert.name if test_alert else None,
        }
    except Exception as e:
        frappe.log_error(f"Test monitoring system failed: {str(e)}")
        return {"status": "error", "message": str(e)}


# ===== SECURITY MONITORING =====


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_security_metrics_for_dashboard():
    """Get security metrics optimized for main dashboard display."""
    try:
        security_monitor = get_security_monitor()
        dashboard_data = security_monitor.get_security_dashboard()

        current_metrics = dashboard_data.get("current_metrics")
        active_incidents = dashboard_data.get("active_incidents", [])
        threat_summary = dashboard_data.get("threat_summary", {})

        return {
            "security_score": current_metrics.get("security_score", 85.0) if current_metrics else 85.0,
            "active_incidents_count": len(active_incidents),
            "critical_incidents": threat_summary.get("critical", 0),
            "high_incidents": threat_summary.get("high", 0),
            "auth_failures_1h": current_metrics.get("auth_failures", 0) if current_metrics else 0,
            "rate_violations_1h": current_metrics.get("rate_limit_violations", 0) if current_metrics else 0,
            "csrf_failures_1h": current_metrics.get("csrf_failures", 0) if current_metrics else 0,
            "validation_errors_1h": current_metrics.get("validation_errors", 0) if current_metrics else 0,
            "api_calls_5m": current_metrics.get("api_calls_total", 0) if current_metrics else 0,
            "response_time_avg": current_metrics.get("response_time_avg", 0) if current_metrics else 0,
            "last_updated": now(),
        }
    except Exception as e:
        frappe.log_error(f"Error getting security metrics for dashboard: {str(e)}")
        return _get_fallback_security_metrics(str(e))


def _get_fallback_security_metrics(error_msg=None):
    """Get fallback security metrics when data loading fails."""
    result = {
        "security_score": 85.0,
        "active_incidents_count": 0,
        "critical_incidents": 0,
        "high_incidents": 0,
        "auth_failures_1h": 0,
        "rate_violations_1h": 0,
        "csrf_failures_1h": 0,
        "validation_errors_1h": 0,
        "api_calls_5m": 0,
        "response_time_avg": 0,
        "last_updated": now(),
    }
    if error_msg:
        result["error"] = error_msg
    return result


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_security_framework_health():
    """Get security framework health status."""
    try:
        security_data = get_security_dashboard_data(hours_back=1)

        if security_data.get("success"):
            framework_health = security_data.get("data", {}).get("framework_health", {})
            return {
                "overall_status": framework_health.get("overall_status", "UNKNOWN"),
                "components": framework_health.get("components", {}),
                "last_checked": now(),
            }
        else:
            return {
                "overall_status": "ERROR",
                "components": {},
                "last_checked": now(),
                "error": security_data.get("error", "Unknown error"),
            }
    except Exception as e:
        frappe.log_error(f"Error getting security framework health: {str(e)}")
        return {"overall_status": "ERROR", "components": {}, "last_checked": now(), "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_unified_security_summary():
    """Get unified security summary combining security monitoring with SEPA security."""
    return ComplianceMetricsService().get_unified_security_summary()


# ===== ANALYTICS =====


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_analytics_summary():
    """Get analytics summary for dashboard."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        engine = AnalyticsEngine()
        error_patterns = engine.analyze_error_patterns(days=7)
        hotspots = engine.identify_error_hotspots(days=7)

        return {
            "error_patterns": {
                "total_errors": error_patterns.get("total_errors", 0),
                "trend_direction": error_patterns.get("patterns", {})
                .get("daily_trends", {})
                .get("trend", "unknown"),
                "peak_hour": error_patterns.get("patterns", {})
                .get("hourly_patterns", {})
                .get("peak_hour", 0),
                "most_common_category": error_patterns.get("patterns", {})
                .get("error_types", {})
                .get("most_common_category", "unknown"),
            },
            "hotspots": {
                "critical_count": len(hotspots.get("critical_hotspots", [])),
                "total_hotspots": sum(
                    len(spots) if isinstance(spots, list) else 0
                    for spots in hotspots.get("hotspots", {}).values()
                ),
                "severity_scores": hotspots.get("severity_scores", {}),
            },
            "last_updated": now(),
        }
    except Exception as e:
        frappe.log_error(f"Error getting analytics summary: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_trend_forecasts():
    """Get trend forecasts for dashboard."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        engine = AnalyticsEngine()
        forecasts = engine.forecast_performance_trends(days_back=14, forecast_days=3)

        summary = {
            "confidence_score": forecasts.get("confidence_score", 0),
            "trend_alerts": len(forecasts.get("trend_alerts", [])),
            "capacity_recommendations": len(forecasts.get("capacity_planning", [])),
            "forecast_period": forecasts.get("forecast_period", "3 days"),
        }

        forecast_data = forecasts.get("forecasts", {})
        highlights = []
        for category, data in forecast_data.items():
            if data.get("status") == "success":
                trend = data.get("trend_direction", "stable")
                if trend != "stable":
                    highlights.append(f"{category}: {trend} trend")

        summary["highlights"] = highlights[:5]
        return summary
    except Exception as e:
        frappe.log_error(f"Error getting trend forecasts: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_compliance_metrics():
    """Get comprehensive compliance metrics for dashboard."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        engine = AnalyticsEngine()
        compliance = engine.identify_compliance_gaps()
        compliance_service = ComplianceMetricsService()

        return {
            "overall_score": compliance.get("overall_compliance_score", 0),
            "critical_gaps": len(compliance.get("critical_gaps", [])),
            "sepa_compliance_rate": compliance_service.get_sepa_compliance_rate(),
            "audit_completeness": compliance_service.calculate_audit_completeness(),
            "regulatory_violations": len(compliance_service.get_regulatory_violations()),
            "data_retention_status": compliance_service.check_data_retention_compliance(),
            "last_assessment": compliance.get("assessment_date", now()),
        }
    except Exception as e:
        frappe.log_error(f"Error getting compliance metrics: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_optimization_insights():
    """Get performance optimization insights for dashboard."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        engine = AnalyticsEngine()
        recommendations = engine.get_performance_recommendations()

        rec_counts = {}
        for category, items in recommendations.get("recommendations", {}).items():
            rec_counts[category] = len(items) if isinstance(items, list) else 0

        return {
            "total_recommendations": sum(rec_counts.values()),
            "high_priority_count": len(recommendations.get("prioritized_actions", [])[:5]),
            "categories": rec_counts,
            "potential_impact": recommendations.get("impact_analysis", {}),
            "implementation_phases": len(recommendations.get("implementation_roadmap", {})),
            "generated_at": recommendations.get("generated_at", now()),
        }
    except Exception as e:
        frappe.log_error(f"Error getting optimization insights: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_executive_summary():
    """Get executive summary for dashboard."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        engine = AnalyticsEngine()
        insights = engine.generate_insights_report()
        exec_summary = insights.get("executive_summary", {})

        return {
            "overall_status": exec_summary.get("overall_system_status", "unknown"),
            "business_impact": exec_summary.get("business_impact_assessment", "unknown"),
            "critical_issues_count": len(exec_summary.get("critical_issues", [])),
            "key_findings_count": len(exec_summary.get("key_findings", [])),
            "priority_actions_count": len(exec_summary.get("priority_actions", [])),
            "top_critical_issue": (
                exec_summary.get("critical_issues", ["None"])[0]
                if exec_summary.get("critical_issues")
                else "None"
            ),
            "top_priority_action": (
                insights.get("priority_actions", [{}])[0].get("action", "None")
                if insights.get("priority_actions")
                else "None"
            ),
            "report_period": insights.get("report_period", "Unknown"),
            "generated_at": insights.get("generated_at", now()),
        }
    except Exception as e:
        frappe.log_error(f"Error getting executive summary: {str(e)}")
        return {"error": str(e)}


# ===== DETAILED REPORTS =====


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_detailed_analytics_report():
    """Get detailed analytics report (full report)."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        return AnalyticsEngine().generate_insights_report()
    except Exception as e:
        frappe.log_error(f"Error getting detailed analytics report: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_performance_optimization_report():
    """Get detailed performance optimization report."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        return AnalyticsEngine().get_performance_recommendations()
    except Exception as e:
        frappe.log_error(f"Error getting performance optimization report: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def get_compliance_audit_report():
    """Get detailed compliance audit report."""
    try:
        from verenigingen.utils.analytics_engine import AnalyticsEngine

        return AnalyticsEngine().identify_compliance_gaps()
    except Exception as e:
        frappe.log_error(f"Error getting compliance audit report: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def refresh_advanced_dashboard_data():
    """Refresh all advanced dashboard data including analytics."""
    try:
        metrics_service = MonitoringMetricsService()
        compliance_service = ComplianceMetricsService()

        return {
            # Original data
            "system_metrics": metrics_service.get_system_metrics(),
            "recent_errors": metrics_service.get_recent_errors(),
            "audit_summary": metrics_service.get_audit_summary(),
            "alerts": metrics_service.get_active_alerts(),
            "performance_metrics": metrics_service.get_performance_metrics(),
            # Analytics data
            "analytics_summary": get_analytics_summary(),
            "trend_forecasts": get_trend_forecasts(),
            "compliance_metrics": compliance_service.get_compliance_metrics(),
            "optimization_insights": get_optimization_insights(),
            "executive_summary": get_executive_summary(),
            # Security monitoring
            "security_dashboard": get_security_metrics_for_dashboard(),
            "security_framework_health": get_security_framework_health(),
            "unified_security_summary": compliance_service.get_unified_security_summary(),
            "timestamp": now(),
        }
    except Exception as e:
        frappe.log_error(f"Error refreshing advanced dashboard data: {str(e)}")
        return {"error": str(e)}


# ===== DEVELOPMENT UTILITIES =====


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def cleanup_test_data():
    """Clean up test data created during comprehensive tests."""
    from verenigingen.tests.integration.test_monitoring_system_comprehensive import (
        cleanup_test_data as cleanup_impl,
    )

    return cleanup_impl()
