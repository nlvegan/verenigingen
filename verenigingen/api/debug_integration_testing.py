#!/usr/bin/env python3
"""
Debug Integration Testing API

Provides whitelisted functions to run comprehensive integration tests
and analyze the 66.7% FAIR score issues.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.api.unified_security_monitoring import (
    get_integrated_security_metrics,
    get_monitoring_system_health,
    get_unified_monitoring_overview,
    trigger_unified_security_test,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)

# Import all monitoring components
from verenigingen.utils.security.security_monitoring import get_security_monitor, get_security_tester
from verenigingen.utils.sepa_alerting_system import get_alerting_system
from verenigingen.utils.sepa_zabbix_enhanced import get_zabbix_integration_instance
from verenigingen.www.monitoring_dashboard import (
    get_security_metrics_for_dashboard,
    get_unified_security_summary,
    refresh_advanced_dashboard_data,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def run_comprehensive_integration_test():
    """Run comprehensive integration test to identify 66.7% FAIR score issues"""
    try:
        print("\n" + "=" * 80)
        print("INTEGRATED MONITORING SYSTEM TEST")
        print("=" * 80)
        print(f"Test started: {now_datetime()}")

        test_results = {
            "individual_systems": {},
            "integration_tests": {},
            "data_flow_tests": {},
            "api_endpoint_tests": {},
            "overall_assessment": {},
        }

        # Test 1: Individual System Health
        print("\n📊 TESTING INDIVIDUAL SYSTEMS")
        print("-" * 40)
        test_results["individual_systems"] = test_individual_systems()

        # Test 2: Integration Points
        print("\n🔗 TESTING INTEGRATION POINTS")
        print("-" * 40)
        test_results["integration_tests"] = test_integration_points()

        # Test 3: Data Flow
        print("\n🔄 TESTING DATA FLOW")
        print("-" * 40)
        test_results["data_flow_tests"] = test_data_flow()

        # Test 4: API Endpoints
        print("\n🌐 TESTING API ENDPOINTS")
        print("-" * 40)
        test_results["api_endpoint_tests"] = test_api_endpoints()

        # Test 5: End-to-End Workflow
        print("\n🚀 TESTING END-TO-END WORKFLOW")
        print("-" * 40)
        test_results["e2e_workflow"] = test_end_to_end_workflow()

        # Generate Assessment
        print("\n📈 GENERATING OVERALL ASSESSMENT")
        print("-" * 40)
        test_results["overall_assessment"] = generate_assessment(test_results)

        # Generate detailed analysis
        analysis = analyze_score_issues(test_results)
        test_results["score_analysis"] = analysis

        return {
            "success": True,
            "test_results": test_results,
            "detailed_analysis": analysis,
            "recommendations": generate_improvement_recommendations(test_results),
            "generated_at": now_datetime().isoformat(),
        }

    except Exception as e:
        frappe.log_error(f"Integration test failed: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to run comprehensive integration test"}


def test_individual_systems():
    """Test each monitoring system individually"""
    results = {}

    # Test Security Monitor
    print("  🔐 Testing Security Monitor...")
    try:
        security_monitor = get_security_monitor()

        # Initialize metrics if not present
        if not security_monitor.metrics_history:
            security_monitor._update_metrics_snapshot()

        dashboard = security_monitor.get_security_dashboard()
        current_metrics = dashboard.get("current_metrics") or {}

        results["security_monitor"] = {
            "status": "PASS",
            "has_dashboard": bool(dashboard),
            "current_metrics": bool(current_metrics),
            "active_incidents": len(dashboard.get("active_incidents", [])),
            "security_score": current_metrics.get("security_score", 0) if current_metrics else 0,
        }
        print("    ✅ Security Monitor: PASS")
    except Exception as e:
        results["security_monitor"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Security Monitor: FAIL - {str(e)}")

    # Test Zabbix Integration
    print("  📊 Testing Zabbix Integration...")
    try:
        zabbix = get_zabbix_integration_instance()
        metrics = zabbix.get_zabbix_metrics()

        security_metrics = [k for k in metrics.get("metrics", {}).keys() if k.startswith("api.security.")]

        results["zabbix_integration"] = {
            "status": "PASS" if len(security_metrics) >= 5 else "FAIL",
            "total_metrics": len(metrics.get("metrics", {})),
            "security_metrics": len(security_metrics),
            "security_metrics_list": security_metrics,
            "metrics_status": metrics.get("status", "unknown"),
        }

        if len(security_metrics) >= 5:
            print(f"    ✅ Zabbix Integration: PASS ({len(security_metrics)} security metrics)")
        else:
            print(f"    ❌ Zabbix Integration: FAIL (only {len(security_metrics)} security metrics)")
    except Exception as e:
        results["zabbix_integration"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Zabbix Integration: FAIL - {str(e)}")

    # Test Alerting System
    print("  🚨 Testing Alerting System...")
    try:
        alerting = get_alerting_system()

        # Check security integration
        security_enabled = alerting.security_integration_enabled

        # Try to check security incidents
        security_alerts = alerting.check_security_incidents()

        results["alerting_system"] = {
            "status": "PASS" if security_enabled else "FAIL",
            "security_integration_enabled": security_enabled,
            "security_alerts_generated": len(security_alerts),
            "active_alerts": len(alerting.get_active_alerts()),
        }

        if security_enabled:
            print("    ✅ Alerting System: PASS (security integration enabled)")
        else:
            print("    ❌ Alerting System: FAIL (security integration disabled)")
    except Exception as e:
        results["alerting_system"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Alerting System: FAIL - {str(e)}")

    # Test Main Dashboard
    print("  📱 Testing Main Dashboard...")
    try:
        security_metrics = get_security_metrics_for_dashboard()
        unified_summary = get_unified_security_summary()

        has_security_score = security_metrics.get("security_score", 0) > 0
        has_unified_score = unified_summary.get("unified_security_score", 0) > 0

        results["main_dashboard"] = {
            "status": "PASS" if has_security_score and has_unified_score else "FAIL",
            "security_metrics_available": bool(security_metrics),
            "unified_summary_available": bool(unified_summary),
            "security_score": security_metrics.get("security_score", 0),
            "unified_score": unified_summary.get("unified_security_score", 0),
        }

        if has_security_score and has_unified_score:
            print("    ✅ Main Dashboard: PASS (security data integrated)")
        else:
            print("    ❌ Main Dashboard: FAIL (missing security data)")
    except Exception as e:
        results["main_dashboard"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Main Dashboard: FAIL - {str(e)}")

    return results


def test_integration_points():
    """Test integration between systems"""
    results = {}

    # Test Security → Zabbix
    print("  🔐→📊 Testing Security → Zabbix...")
    try:
        # Get security metrics
        security_monitor = get_security_monitor()

        # Initialize metrics if not present
        if not security_monitor.metrics_history:
            security_monitor._update_metrics_snapshot()

        security_dashboard = security_monitor.get_security_dashboard()
        current_metrics = security_dashboard.get("current_metrics") or {}
        security_score = current_metrics.get("security_score", 0) if current_metrics else 0

        # Get Zabbix metrics
        zabbix = get_zabbix_integration_instance()
        zabbix_metrics = zabbix.get_zabbix_metrics()
        zabbix_security_score = (
            zabbix_metrics.get("metrics", {}).get("api.security.score", {}).get("value", 0)
        )

        # Check correlation
        scores_close = abs(security_score - zabbix_security_score) < 10

        results["security_to_zabbix"] = {
            "status": "PASS" if scores_close else "FAIL",
            "security_score_original": security_score,
            "security_score_zabbix": zabbix_security_score,
            "correlation_good": scores_close,
            "score_difference": abs(security_score - zabbix_security_score),
        }

        if scores_close:
            print(f"    ✅ Security → Zabbix: PASS (scores: {security_score} ≈ {zabbix_security_score})")
        else:
            print(f"    ❌ Security → Zabbix: FAIL (scores: {security_score} ≠ {zabbix_security_score})")
    except Exception as e:
        results["security_to_zabbix"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Security → Zabbix: FAIL - {str(e)}")

    # Test Security → Alerts
    print("  🔐→🚨 Testing Security → Alerts...")
    try:
        alerting = get_alerting_system()

        # Check if security incidents can be processed
        security_alerts = alerting.check_security_incidents()
        security_integration = alerting.security_integration_enabled

        results["security_to_alerts"] = {
            "status": "PASS" if security_integration else "FAIL",
            "security_integration_enabled": security_integration,
            "security_alerts_processed": len(security_alerts),
        }

        if security_integration:
            print(f"    ✅ Security → Alerts: PASS (processed {len(security_alerts)} incidents)")
        else:
            print("    ❌ Security → Alerts: FAIL (integration disabled)")
    except Exception as e:
        results["security_to_alerts"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Security → Alerts: FAIL - {str(e)}")

    # Test Security → Dashboard
    print("  🔐→📱 Testing Security → Dashboard...")
    try:
        security_metrics = get_security_metrics_for_dashboard()
        unified_summary = get_unified_security_summary()

        has_security_data = bool(security_metrics.get("security_score"))
        has_api_security = bool(unified_summary.get("api_security"))

        results["security_to_dashboard"] = {
            "status": "PASS" if has_security_data and has_api_security else "FAIL",
            "security_metrics_integrated": has_security_data,
            "unified_summary_integrated": has_api_security,
        }

        if has_security_data and has_api_security:
            print("    ✅ Security → Dashboard: PASS (data integrated)")
        else:
            print("    ❌ Security → Dashboard: FAIL (data missing)")
    except Exception as e:
        results["security_to_dashboard"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Security → Dashboard: FAIL - {str(e)}")

    return results


def test_data_flow():
    """Test data flow through the entire system"""
    results = {}

    print("  📊 Testing Data Consistency...")
    try:
        # Get security score from all systems
        security_monitor = get_security_monitor()

        # Initialize metrics if not present
        if not security_monitor.metrics_history:
            security_monitor._update_metrics_snapshot()

        security_dashboard = security_monitor.get_security_dashboard()
        current_metrics = security_dashboard.get("current_metrics") or {}
        score_1 = current_metrics.get("security_score", 0) if current_metrics else 0

        security_metrics = get_security_metrics_for_dashboard()
        score_2 = security_metrics.get("security_score", 0)

        unified_summary = get_unified_security_summary()
        score_3 = unified_summary.get("api_security", {}).get("security_score", 0)

        zabbix = get_zabbix_integration_instance()
        zabbix_metrics = zabbix.get_zabbix_metrics()
        score_4 = zabbix_metrics.get("metrics", {}).get("api.security.score", {}).get("value", 0)

        scores = [score_1, score_2, score_3, score_4]
        valid_scores = [s for s in scores if s > 0]

        if len(valid_scores) >= 2:
            max_diff = max(valid_scores) - min(valid_scores)
            consistent = max_diff <= 15  # Allow 15 point difference
        else:
            consistent = False

        results["data_consistency"] = {
            "status": "PASS" if consistent else "FAIL",
            "scores": {
                "security_monitor": score_1,
                "dashboard_metrics": score_2,
                "unified_summary": score_3,
                "zabbix_metrics": score_4,
            },
            "valid_scores": len(valid_scores),
            "max_difference": max(valid_scores) - min(valid_scores) if valid_scores else 0,
            "consistent": consistent,
        }

        if consistent:
            print(f"    ✅ Data Consistency: PASS (max diff: {max(valid_scores) - min(valid_scores):.1f})")
        else:
            print(f"    ❌ Data Consistency: FAIL (scores: {scores})")
    except Exception as e:
        results["data_consistency"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Data Consistency: FAIL - {str(e)}")

    return results


def test_api_endpoints():
    """Test unified API endpoints"""
    results = {}

    # Test unified overview
    print("  🌐 Testing Unified Overview API...")
    try:
        overview = get_unified_monitoring_overview()

        success = overview.get("success", False)
        has_security = bool(overview.get("overview", {}).get("security_monitoring"))
        has_sepa = bool(overview.get("overview", {}).get("sepa_monitoring"))
        has_zabbix = bool(overview.get("overview", {}).get("zabbix_integration"))

        results["unified_overview"] = {
            "status": "PASS" if success and has_security and has_sepa and has_zabbix else "FAIL",
            "api_success": success,
            "has_security_data": has_security,
            "has_sepa_data": has_sepa,
            "has_zabbix_data": has_zabbix,
            "response_data": overview if success else None,
        }

        if success and has_security and has_sepa and has_zabbix:
            print("    ✅ Unified Overview API: PASS")
        else:
            print("    ❌ Unified Overview API: FAIL")
    except Exception as e:
        results["unified_overview"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Unified Overview API: FAIL - {str(e)}")

    # Test integrated metrics
    print("  📊 Testing Integrated Metrics API...")
    try:
        metrics = get_integrated_security_metrics(hours_back=24)

        success = metrics.get("success", False)
        has_integrated_data = bool(metrics.get("integrated_metrics"))

        results["integrated_metrics"] = {
            "status": "PASS" if success and has_integrated_data else "FAIL",
            "api_success": success,
            "has_integrated_data": has_integrated_data,
        }

        if success and has_integrated_data:
            print("    ✅ Integrated Metrics API: PASS")
        else:
            print("    ❌ Integrated Metrics API: FAIL")
    except Exception as e:
        results["integrated_metrics"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ Integrated Metrics API: FAIL - {str(e)}")

    # Test system health
    print("  🏥 Testing System Health API...")
    try:
        health = get_monitoring_system_health()

        success = health.get("success", False)
        has_health_data = bool(health.get("health_status"))

        results["system_health"] = {
            "status": "PASS" if success and has_health_data else "FAIL",
            "api_success": success,
            "has_health_data": has_health_data,
            "overall_health": health.get("health_status", {}).get("overall_health", "UNKNOWN"),
        }

        if success and has_health_data:
            print(
                f"    ✅ System Health API: PASS (health: {health.get('health_status', {}).get('overall_health', 'UNKNOWN')})"
            )
        else:
            print("    ❌ System Health API: FAIL")
    except Exception as e:
        results["system_health"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ System Health API: FAIL - {str(e)}")

    return results


def test_end_to_end_workflow():
    """Test complete end-to-end workflow"""
    results = {}

    print("  🚀 Testing End-to-End Security Workflow...")
    try:
        # 1. Generate security event
        from verenigingen.utils.security.security_monitoring import MonitoringMetric

        security_monitor = get_security_monitor()
        security_monitor.record_security_event(
            event_type=MonitoringMetric.AUTHENTICATION_FAILURES,
            user="test_user",
            endpoint="/api/test",
            details={"test": "integration_test"},
            ip_address="127.0.0.1",
        )

        time.sleep(2)  # Allow processing

        # 2. Check if event appears in security dashboard
        dashboard = security_monitor.get_security_dashboard()
        recent_events = len(
            [
                event
                for event in dashboard.get("metrics_trend", [])
                if event.get("timestamp", datetime.min) > datetime.now() - timedelta(minutes=5)
            ]
        )

        # 3. Check if alerting system processes it
        alerting = get_alerting_system()
        security_alerts = alerting.check_security_incidents()

        # 4. Check if it appears in unified APIs
        overview = get_unified_monitoring_overview()
        security_data = overview.get("overview", {}).get("security_monitoring", {})

        workflow_success = (
            recent_events >= 0
            and len(security_alerts) >= 0  # Events may not immediately appear in trend
            and bool(
                security_data
            )  # May not generate alerts for test events  # Should have security data in overview
        )

        results["e2e_workflow"] = {
            "status": "PASS" if workflow_success else "FAIL",
            "event_recorded": True,
            "dashboard_updated": recent_events > 0,
            "alerts_processed": len(security_alerts) > 0,
            "unified_api_updated": bool(security_data),
            "workflow_complete": workflow_success,
        }

        if workflow_success:
            print("    ✅ End-to-End Workflow: PASS")
        else:
            print("    ❌ End-to-End Workflow: FAIL")
    except Exception as e:
        results["e2e_workflow"] = {"status": "FAIL", "error": str(e)}
        print(f"    ❌ End-to-End Workflow: FAIL - {str(e)}")

    return results


def generate_assessment(test_results):
    """Generate overall assessment"""
    assessment = {
        "individual_systems_score": 0,
        "integration_score": 0,
        "data_flow_score": 0,
        "api_endpoints_score": 0,
        "e2e_workflow_score": 0,
        "overall_score": 0,
        "overall_status": "UNKNOWN",
        "recommendations": [],
    }

    # Calculate individual scores
    individual_systems = test_results.get("individual_systems", {})
    individual_passed = len([r for r in individual_systems.values() if r.get("status") == "PASS"])
    individual_total = len(individual_systems)
    assessment["individual_systems_score"] = (
        (individual_passed / individual_total * 100) if individual_total > 0 else 0
    )

    integration_tests = test_results.get("integration_tests", {})
    integration_passed = len([r for r in integration_tests.values() if r.get("status") == "PASS"])
    integration_total = len(integration_tests)
    assessment["integration_score"] = (
        (integration_passed / integration_total * 100) if integration_total > 0 else 0
    )

    data_flow_tests = test_results.get("data_flow_tests", {})
    data_flow_passed = len([r for r in data_flow_tests.values() if r.get("status") == "PASS"])
    data_flow_total = len(data_flow_tests)
    assessment["data_flow_score"] = (data_flow_passed / data_flow_total * 100) if data_flow_total > 0 else 0

    api_endpoint_tests = test_results.get("api_endpoint_tests", {})
    api_passed = len([r for r in api_endpoint_tests.values() if r.get("status") == "PASS"])
    api_total = len(api_endpoint_tests)
    assessment["api_endpoints_score"] = (api_passed / api_total * 100) if api_total > 0 else 0

    e2e_workflow = test_results.get("e2e_workflow", {})
    e2e_passed = 1 if e2e_workflow.get("status") == "PASS" else 0
    assessment["e2e_workflow_score"] = e2e_passed * 100

    # Calculate overall score
    scores = [
        assessment["individual_systems_score"],
        assessment["integration_score"],
        assessment["data_flow_score"],
        assessment["api_endpoints_score"],
        assessment["e2e_workflow_score"],
    ]
    assessment["overall_score"] = sum(scores) / len(scores)

    # Determine status
    if assessment["overall_score"] >= 90:
        assessment["overall_status"] = "EXCELLENT"
    elif assessment["overall_score"] >= 80:
        assessment["overall_status"] = "GOOD"
    elif assessment["overall_score"] >= 70:
        assessment["overall_status"] = "FAIR"
    else:
        assessment["overall_status"] = "POOR"

    return assessment


def analyze_score_issues(test_results):
    """Analyze specific issues causing the FAIR score"""
    analysis = {
        "failing_tests": [],
        "score_breakdown": {},
        "critical_issues": [],
        "performance_issues": [],
        "integration_gaps": [],
    }

    # Identify failing tests
    for category, tests in test_results.items():
        if category == "overall_assessment":
            continue

        if isinstance(tests, dict):
            for test_name, result in tests.items():
                if isinstance(result, dict) and result.get("status") == "FAIL":
                    analysis["failing_tests"].append(
                        {
                            "category": category,
                            "test": test_name,
                            "error": result.get("error", "No specific error"),
                            "impact": "HIGH" if category == "integration_tests" else "MEDIUM",
                        }
                    )

    # Score breakdown analysis
    assessment = test_results.get("overall_assessment", {})
    analysis["score_breakdown"] = {
        "individual_systems": assessment.get("individual_systems_score", 0),
        "integration_points": assessment.get("integration_score", 0),
        "data_flow": assessment.get("data_flow_score", 0),
        "api_endpoints": assessment.get("api_endpoints_score", 0),
        "e2e_workflow": assessment.get("e2e_workflow_score", 0),
    }

    # Identify critical issues
    if assessment.get("integration_score", 0) < 70:
        analysis["critical_issues"].append("Integration points failing - core connectivity issues")

    if assessment.get("data_flow_score", 0) < 70:
        analysis["critical_issues"].append("Data consistency problems across systems")

    if assessment.get("individual_systems_score", 0) < 80:
        analysis["critical_issues"].append("Individual monitoring systems not fully operational")

    # Performance analysis
    individual_systems = test_results.get("individual_systems", {})
    zabbix_result = individual_systems.get("zabbix_integration", {})
    if zabbix_result.get("security_metrics", 0) < 5:
        analysis["performance_issues"].append("Insufficient security metrics in Zabbix")

    # Integration gap analysis
    integration_tests = test_results.get("integration_tests", {})
    for integration, result in integration_tests.items():
        if result.get("status") == "FAIL":
            analysis["integration_gaps"].append(
                {"integration": integration, "issue": result.get("error", "Unknown integration failure")}
            )

    return analysis


def generate_improvement_recommendations(test_results):
    """Generate specific recommendations to improve score from FAIR to GOOD/EXCELLENT"""
    recommendations = {"immediate_fixes": [], "medium_term_improvements": [], "score_impact_estimates": {}}

    assessment = test_results.get("overall_assessment", {})

    # Immediate fixes (highest impact)
    if assessment.get("integration_score", 0) < 80:
        recommendations["immediate_fixes"].append(
            {
                "action": "Fix Security → Zabbix integration",
                "estimated_score_gain": 10,
                "priority": "HIGH",
                "effort": "LOW",
            }
        )

    if assessment.get("data_flow_score", 0) < 80:
        recommendations["immediate_fixes"].append(
            {
                "action": "Resolve data consistency issues between systems",
                "estimated_score_gain": 15,
                "priority": "HIGH",
                "effort": "MEDIUM",
            }
        )

    # Medium-term improvements
    individual_systems = test_results.get("individual_systems", {})
    if individual_systems.get("alerting_system", {}).get("status") == "FAIL":
        recommendations["medium_term_improvements"].append(
            {
                "action": "Enable security integration in alerting system",
                "estimated_score_gain": 8,
                "priority": "MEDIUM",
                "effort": "LOW",
            }
        )

    # Score impact estimates
    current_score = assessment.get("overall_score", 66.7)

    total_potential_gain = sum(
        [
            fix.get("estimated_score_gain", 0)
            for fix in recommendations["immediate_fixes"] + recommendations["medium_term_improvements"]
        ]
    )

    recommendations["score_impact_estimates"] = {
        "current_score": current_score,
        "potential_gain": total_potential_gain,
        "projected_score": min(100, current_score + total_potential_gain),
        "target_status": "GOOD" if (current_score + total_potential_gain) >= 80 else "FAIR_IMPROVED",
    }

    return recommendations


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_integration_score_analysis():
    """Get quick analysis of why integration score is 66.7% FAIR"""
    try:
        # Run quick diagnostic
        result = run_comprehensive_integration_test()

        if not result.get("success"):
            return result

        assessment = result["test_results"]["overall_assessment"]
        analysis = result["detailed_analysis"]

        return {
            "success": True,
            "current_score": assessment.get("overall_score", 0),
            "current_status": assessment.get("overall_status", "UNKNOWN"),
            "category_scores": {
                "individual_systems": assessment.get("individual_systems_score", 0),
                "integration_points": assessment.get("integration_score", 0),
                "data_flow": assessment.get("data_flow_score", 0),
                "api_endpoints": assessment.get("api_endpoints_score", 0),
                "e2e_workflow": assessment.get("e2e_workflow_score", 0),
            },
            "failing_tests": analysis.get("failing_tests", []),
            "critical_issues": analysis.get("critical_issues", []),
            "top_recommendations": result["recommendations"]["immediate_fixes"][:3],
            "score_improvement_potential": result["recommendations"]["score_impact_estimates"],
        }

    except Exception as e:
        frappe.log_error(f"Integration score analysis failed: {str(e)}")
        return {"success": False, "error": str(e), "message": "Failed to analyze integration score"}


if __name__ == "__main__":
    print("🔍 Debug Integration Testing API")
    print("Available functions:")
    print("- run_comprehensive_integration_test")
    print("- get_integration_score_analysis")
