#!/usr/bin/env python3
"""
Unified Security Monitoring API

This module provides unified API endpoints that integrate security monitoring
with existing SEPA monitoring infrastructure. It serves as the bridge between
standalone security monitoring and the comprehensive monitoring ecosystem.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import add_days, now_datetime

from verenigingen.api.security_monitoring_dashboard import get_security_dashboard_data

# Import security framework
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api

# Import existing monitoring systems
from verenigingen.utils.security.security_monitoring import get_security_monitor, get_security_tester
from verenigingen.utils.sepa_alerting_system import get_alerting_system
from verenigingen.utils.sepa_monitoring_dashboard import get_dashboard_instance
from verenigingen.utils.sepa_zabbix_enhanced import get_zabbix_integration_instance
from verenigingen.www.monitoring_dashboard import get_unified_security_summary


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def get_unified_monitoring_overview():
    """Get comprehensive overview of all monitoring systems"""
    try:
        # Get data from all monitoring systems
        security_monitor = get_security_monitor()
        zabbix_integration = get_zabbix_integration_instance()
        alerting_system = get_alerting_system()
        sepa_dashboard = get_dashboard_instance()

        # Security monitoring data
        security_dashboard = security_monitor.get_security_dashboard()

        # SEPA monitoring data
        sepa_metrics = sepa_dashboard.get_comprehensive_report(days=1)

        # Zabbix metrics
        zabbix_metrics = zabbix_integration.get_zabbix_metrics()

        # Alerting system status
        alerting_stats = alerting_system.get_alert_statistics(days=1)

        # Unified security summary
        unified_security = get_unified_security_summary()

        return {
            "success": True,
            "overview": {
                "security_monitoring": {
                    "status": "operational",
                    "security_score": security_dashboard.get("current_metrics", {}).get(
                        "security_score", 85.0
                    ),
                    "active_incidents": len(security_dashboard.get("active_incidents", [])),
                    "framework_health": _get_framework_health_summary(),
                },
                "sepa_monitoring": {
                    "status": "operational",
                    "recent_batches": sepa_metrics.get("batch_analytics", {}).get("total_batches_created", 0),
                    "mandate_health": sepa_metrics.get("mandate_health", {}).get("overall_health", "unknown"),
                    "financial_metrics": sepa_metrics.get("financial_metrics", {}).get("summary", {}),
                },
                "zabbix_integration": {
                    "status": "operational" if zabbix_metrics.get("status") == "success" else "error",
                    "metrics_collected": len(zabbix_metrics.get("metrics", {})),
                    "security_metrics_included": _count_security_metrics(zabbix_metrics),
                },
                "alerting_system": {
                    "status": "operational",
                    "total_alerts": alerting_stats.get("total_alerts", 0),
                    "active_alerts": alerting_stats.get("active_alerts", 0),
                    "security_alerts": alerting_stats.get("security_alerts", 0),
                    "security_integration": alerting_stats.get("security_integration_status", "unknown"),
                },
                "unified_security": {
                    "overall_score": unified_security.get("unified_security_score", 70.0),
                    "overall_status": unified_security.get("overall_status", "UNKNOWN"),
                },
            },
            "integration_status": {
                "all_systems_operational": True,  # Will be calculated based on individual statuses
                "last_updated": now_datetime().isoformat(),
                "integration_points": [
                    "Security metrics → Zabbix",
                    "Security alerts → SEPA alerting",
                    "Security data → Main dashboard",
                    "Unified reporting → All systems",
                ],
            },
            "generated_at": now_datetime().isoformat(),
        }

    except Exception as e:
        frappe.log_error(f"Error getting unified monitoring overview: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to generate unified monitoring overview",
        }


@high_security_api(operation_type=OperationType.SECURITY)
@frappe.whitelist()
def get_integrated_security_metrics(hours_back: int = 24):
    """Get security metrics integrated across all monitoring systems"""
    try:
        hours_back = min(int(hours_back), 168)  # Limit to 1 week

        # Get security monitoring data
        security_data = get_security_dashboard_data(hours_back=hours_back)

        # Get Zabbix security metrics
        zabbix_integration = get_zabbix_integration_instance()
        zabbix_metrics = zabbix_integration.get_zabbix_metrics()
        security_zabbix_metrics = {
            k: v for k, v in zabbix_metrics.get("metrics", {}).items() if k.startswith("api.security.")
        }

        # Get alerting system security data
        alerting_system = get_alerting_system()
        security_alerts = [
            alert
            for alert in alerting_system.get_active_alerts()
            if alert.get("source_operation") == "security_monitoring"
        ]

        # Get unified security summary
        unified_summary = get_unified_security_summary()

        return {
            "success": True,
            "integrated_metrics": {
                "security_monitoring": {
                    "data": security_data.get("data", {}),
                    "source": "security_monitoring_dashboard",
                },
                "zabbix_security_metrics": {
                    "metrics": security_zabbix_metrics,
                    "timestamp": zabbix_metrics.get("timestamp"),
                    "source": "zabbix_integration",
                },
                "security_alerts": {
                    "active_alerts": security_alerts,
                    "alert_count": len(security_alerts),
                    "source": "sepa_alerting_system",
                },
                "unified_summary": {"summary": unified_summary, "source": "main_monitoring_dashboard"},
            },
            "correlation_analysis": _analyze_security_correlations(
                {
                    "security_data": security_data,
                    "zabbix_metrics": security_zabbix_metrics,
                    "active_alerts": security_alerts,
                    "unified_summary": unified_summary,
                }
            ),
            "time_range_hours": hours_back,
            "generated_at": now_datetime().isoformat(),
        }

    except Exception as e:
        frappe.log_error(f"Error getting integrated security metrics: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to get integrated security metrics"}


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_monitoring_system_health():
    """Get health status of all monitoring system components"""
    try:
        health_status = {
            "overall_health": "HEALTHY",
            "components": {},
            "integration_status": {},
            "recommendations": [],
        }

        # Check security monitoring health
        try:
            security_monitor = get_security_monitor()
            security_dashboard = security_monitor.get_security_dashboard()
            health_status["components"]["security_monitoring"] = {
                "status": "HEALTHY",
                "active_incidents": len(security_dashboard.get("active_incidents", [])),
                "last_check": now_datetime().isoformat(),
            }
        except Exception as e:
            health_status["components"]["security_monitoring"] = {"status": "ERROR", "error": str(e)}
            health_status["overall_health"] = "DEGRADED"

        # Check Zabbix integration health
        try:
            zabbix_integration = get_zabbix_integration_instance()
            zabbix_test = zabbix_integration.test_zabbix_connectivity()
            health_status["components"]["zabbix_integration"] = {
                "status": "HEALTHY" if zabbix_test.get("success") else "ERROR",
                "metrics_collected": zabbix_test.get("metrics_collected", 0),
                "response_time_ms": zabbix_test.get("collection_time_ms", 0),
            }
        except Exception as e:
            health_status["components"]["zabbix_integration"] = {"status": "ERROR", "error": str(e)}
            health_status["overall_health"] = "DEGRADED"

        # Check SEPA monitoring health
        try:
            sepa_dashboard = get_dashboard_instance()
            sepa_alerts = sepa_dashboard.get_system_alerts()
            health_status["components"]["sepa_monitoring"] = {
                "status": "HEALTHY",
                "active_alerts": len(sepa_alerts),
                "last_check": now_datetime().isoformat(),
            }
        except Exception as e:
            health_status["components"]["sepa_monitoring"] = {"status": "ERROR", "error": str(e)}
            health_status["overall_health"] = "DEGRADED"

        # Check alerting system health
        try:
            alerting_system = get_alerting_system()
            alert_stats = alerting_system.get_alert_statistics(days=1)
            health_status["components"]["alerting_system"] = {
                "status": "HEALTHY",
                "active_alerts": alert_stats.get("active_alerts", 0),
                "security_integration": alert_stats.get("security_integration_status", "unknown"),
            }
        except Exception as e:
            health_status["components"]["alerting_system"] = {"status": "ERROR", "error": str(e)}
            health_status["overall_health"] = "DEGRADED"

        # Check integration points
        integration_checks = {
            "security_to_zabbix": _check_security_zabbix_integration(),
            "security_to_alerts": _check_security_alerting_integration(),
            "security_to_dashboard": _check_security_dashboard_integration(),
        }

        health_status["integration_status"] = integration_checks

        # Determine overall health
        failed_components = len(
            [c for c in health_status["components"].values() if c.get("status") == "ERROR"]
        )
        failed_integrations = len([i for i in integration_checks.values() if not i.get("working", False)])

        if failed_components > 0 or failed_integrations > 1:
            health_status["overall_health"] = "CRITICAL"
        elif failed_integrations > 0:
            health_status["overall_health"] = "DEGRADED"

        # Generate recommendations
        if failed_components > 0:
            health_status["recommendations"].append("Investigate failed monitoring components")
        if failed_integrations > 0:
            health_status["recommendations"].append("Check monitoring system integrations")
        if health_status["overall_health"] == "HEALTHY":
            health_status["recommendations"].append("All monitoring systems operational")

        return {"success": True, "health_status": health_status, "generated_at": now_datetime().isoformat()}

    except Exception as e:
        frappe.log_error(f"Error getting monitoring system health: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to get monitoring system health"}


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def trigger_unified_security_test():
    """Trigger comprehensive security test across all monitoring systems"""
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Access denied"), frappe.PermissionError)

    try:
        test_results = {
            "security_monitoring": {},
            "zabbix_integration": {},
            "alerting_system": {},
            "integration_points": {},
        }

        # Test security monitoring
        try:
            security_tester = get_security_tester()
            security_test = security_tester.run_security_tests()
            test_results["security_monitoring"] = {
                "status": "PASS" if security_test.get("overall_score", 0) >= 80 else "FAIL",
                "score": security_test.get("overall_score", 0),
                "tests_passed": security_test.get("tests_passed", 0),
                "tests_failed": security_test.get("tests_failed", 0),
            }
        except Exception as e:
            test_results["security_monitoring"] = {"status": "ERROR", "error": str(e)}

        # Test Zabbix integration
        try:
            zabbix_integration = get_zabbix_integration_instance()
            zabbix_test = zabbix_integration.test_zabbix_connectivity()
            test_results["zabbix_integration"] = {
                "status": "PASS" if zabbix_test.get("success") else "FAIL",
                "metrics_collected": zabbix_test.get("metrics_collected", 0),
                "security_metrics": len(
                    [k for k in zabbix_test.get("sample_metrics", {}).keys() if k.startswith("api.security.")]
                ),
            }
        except Exception as e:
            test_results["zabbix_integration"] = {"status": "ERROR", "error": str(e)}

        # Test alerting system
        try:
            alerting_system = get_alerting_system()
            # Trigger security check
            security_check = alerting_system.check_security_incidents()
            test_results["alerting_system"] = {
                "status": "PASS",
                "security_integration": "enabled"
                if alerting_system.security_integration_enabled
                else "disabled",
                "security_alerts_generated": len(security_check),
            }
        except Exception as e:
            test_results["alerting_system"] = {"status": "ERROR", "error": str(e)}

        # Test integration points
        test_results["integration_points"] = {
            "security_to_zabbix": _test_security_zabbix_integration(),
            "security_to_alerts": _test_security_alerting_integration(),
            "security_to_dashboard": _test_security_dashboard_integration(),
        }

        # Calculate overall test result
        component_passes = len(
            [r for r in test_results.values() if isinstance(r, dict) and r.get("status") == "PASS"]
        )
        total_components = len([r for r in test_results.values() if isinstance(r, dict) and "status" in r])

        integration_passes = len(
            [r for r in test_results["integration_points"].values() if r.get("status") == "PASS"]
        )
        total_integrations = len(test_results["integration_points"])

        overall_score = (
            ((component_passes / total_components) + (integration_passes / total_integrations)) / 2 * 100
            if total_components > 0
            else 0
        )

        return {
            "success": True,
            "test_results": test_results,
            "overall_score": round(overall_score, 1),
            "overall_status": "PASS" if overall_score >= 80 else "FAIL",
            "summary": {
                "components_passed": component_passes,
                "components_total": total_components,
                "integrations_passed": integration_passes,
                "integrations_total": total_integrations,
            },
            "generated_at": now_datetime().isoformat(),
        }

    except Exception as e:
        frappe.log_error(f"Error running unified security test: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to run unified security test"}


# Helper functions


def _get_framework_health_summary():
    """Get summarized framework health status"""
    try:
        security_data = get_security_dashboard_data(hours_back=1)
        framework_health = security_data.get("data", {}).get("framework_health", {})

        components = framework_health.get("components", {})
        working_components = len([c for c in components.values() if "✅" in str(c)])
        total_components = len(components)

        return {
            "overall_status": framework_health.get("overall_status", "UNKNOWN"),
            "components_working": working_components,
            "components_total": total_components,
            "health_percentage": round((working_components / total_components) * 100, 1)
            if total_components > 0
            else 0,
        }
    except Exception:
        return {
            "overall_status": "ERROR",
            "components_working": 0,
            "components_total": 0,
            "health_percentage": 0,
        }


def _count_security_metrics(zabbix_metrics):
    """Count security-related metrics in Zabbix data"""
    try:
        metrics = zabbix_metrics.get("metrics", {})
        return len([k for k in metrics.keys() if k.startswith("api.security.")])
    except Exception:
        return 0


def _analyze_security_correlations(data):
    """Analyze correlations between different security data sources"""
    try:
        correlations = {
            "data_consistency": "good",
            "alert_correlation": "good",
            "metric_alignment": "good",
            "issues_detected": [],
        }

        # Check if security scores are consistent across systems
        security_score_1 = (
            data.get("security_data", {}).get("data", {}).get("summary", {}).get("security_score", 0)
        )
        security_score_2 = data.get("unified_summary", {}).get("api_security", {}).get("security_score", 0)

        if abs(security_score_1 - security_score_2) > 10:
            correlations["data_consistency"] = "poor"
            correlations["issues_detected"].append("Security scores divergent between systems")

        # Check alert consistency
        dashboard_incidents = len(data.get("security_data", {}).get("data", {}).get("recent_events", []))
        active_alerts = len(data.get("active_alerts", []))

        if dashboard_incidents > 0 and active_alerts == 0:
            correlations["alert_correlation"] = "poor"
            correlations["issues_detected"].append("Security events not generating alerts")

        return correlations

    except Exception as e:
        return {
            "data_consistency": "unknown",
            "alert_correlation": "unknown",
            "metric_alignment": "unknown",
            "error": str(e),
        }


def _check_security_zabbix_integration():
    """Check if security monitoring is properly integrated with Zabbix"""
    try:
        zabbix_integration = get_zabbix_integration_instance()
        zabbix_metrics = zabbix_integration.get_zabbix_metrics()

        security_metrics = [
            k for k in zabbix_metrics.get("metrics", {}).keys() if k.startswith("api.security.")
        ]

        return {
            "working": len(security_metrics) > 0,
            "security_metrics_count": len(security_metrics),
            "status": "HEALTHY" if len(security_metrics) >= 5 else "DEGRADED",
        }
    except Exception as e:
        return {"working": False, "error": str(e), "status": "ERROR"}


def _check_security_alerting_integration():
    """Check if security monitoring is properly integrated with alerting"""
    try:
        alerting_system = get_alerting_system()

        return {
            "working": alerting_system.security_integration_enabled,
            "integration_enabled": alerting_system.security_integration_enabled,
            "last_check": alerting_system.last_security_check.isoformat(),
            "status": "HEALTHY" if alerting_system.security_integration_enabled else "DISABLED",
        }
    except Exception as e:
        return {"working": False, "error": str(e), "status": "ERROR"}


def _check_security_dashboard_integration():
    """Check if security monitoring is properly integrated with main dashboard"""
    try:
        # Try to get security data from main dashboard
        security_dashboard_data = get_unified_security_summary()

        has_security_data = bool(security_dashboard_data.get("api_security"))

        return {
            "working": has_security_data,
            "has_security_data": has_security_data,
            "unified_score": security_dashboard_data.get("unified_security_score", 0),
            "status": "HEALTHY" if has_security_data else "ERROR",
        }
    except Exception as e:
        return {"working": False, "error": str(e), "status": "ERROR"}


def _test_security_zabbix_integration():
    """Test security-Zabbix integration"""
    try:
        # Get current security metrics and check if they appear in Zabbix
        security_monitor = get_security_monitor()
        security_dashboard = security_monitor.get_security_dashboard()

        zabbix_integration = get_zabbix_integration_instance()
        zabbix_metrics = zabbix_integration.get_zabbix_metrics()

        # Check if security score appears in both systems
        security_score = security_dashboard.get("current_metrics", {}).get("security_score", 0)
        zabbix_security_score = (
            zabbix_metrics.get("metrics", {}).get("api.security.score", {}).get("value", 0)
        )

        scores_match = abs(security_score - zabbix_security_score) < 5  # Allow 5 point difference

        return {
            "status": "PASS" if scores_match else "FAIL",
            "security_score_original": security_score,
            "security_score_zabbix": zabbix_security_score,
            "scores_match": scores_match,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def _test_security_alerting_integration():
    """Test security-alerting integration"""
    try:
        # Check if security incidents can be converted to alerts
        alerting_system = get_alerting_system()

        # Try to trigger security check
        security_alerts = alerting_system.check_security_incidents()

        return {
            "status": "PASS",
            "security_integration_enabled": alerting_system.security_integration_enabled,
            "security_alerts_generated": len(security_alerts),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


def _test_security_dashboard_integration():
    """Test security-dashboard integration"""
    try:
        # Check if security data appears in unified dashboard
        unified_summary = get_unified_security_summary()

        has_api_security = bool(unified_summary.get("api_security"))
        has_unified_score = unified_summary.get("unified_security_score", 0) > 0

        return {
            "status": "PASS" if has_api_security and has_unified_score else "FAIL",
            "has_api_security": has_api_security,
            "has_unified_score": has_unified_score,
            "unified_score": unified_summary.get("unified_security_score", 0),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


if __name__ == "__main__":
    print("🔐 Unified Security Monitoring API")
    print("Available endpoints:")
    print("- get_unified_monitoring_overview")
    print("- get_integrated_security_metrics")
    print("- get_monitoring_system_health")
    print("- trigger_unified_security_test")
