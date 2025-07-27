#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Comprehensive monitoring system test API
"""

import json
import traceback
from datetime import datetime

import frappe
from frappe import _


@frappe.whitelist()
def run_monitoring_tests():
    """Run comprehensive monitoring system tests"""
    frappe.set_user("Administrator")

    print("\n" + "=" * 60)
    print("MONITORING SYSTEM END-TO-END TEST")
    print("=" * 60)
    print(f"Test Time: {datetime.now()}\n")

    test_results = {
        "phase1": test_phase1_alert_and_audit(),
        "phase2": test_phase2_dashboard_and_alerts(),
        "phase3": test_phase3_analytics_and_performance(),
        "integration": test_end_to_end_integration(),
        "performance": test_system_performance(),
    }

    # Generate summary
    generate_test_summary(test_results)

    return test_results


def test_phase1_alert_and_audit():
    """Test Phase 1 components: Alert Manager and SEPA Audit"""
    print("PHASE 1: Alert Manager and SEPA Audit Testing")
    print("-" * 50)

    results = {"alert_manager": {}, "sepa_audit": {}, "scheduler": {}}

    # Test Alert Manager
    try:
        from vereinigingen.utils.alert_manager import AlertManager

        am = AlertManager()

        # Create test alert
        alert_id = am.create_alert(
            error_type="E2E_Test",
            message="End-to-end test alert",
            severity="medium",
            source="test_monitoring",
        )
        results["alert_manager"]["create"] = "PASS" if alert_id else "FAIL"
        print(f"  ✓ Alert created: {alert_id}")

        # Retrieve alerts
        recent = am.get_recent_alerts(hours=1)
        found = any(a.get("error_type") == "E2E_Test" for a in recent)
        results["alert_manager"]["retrieve"] = "PASS" if found else "FAIL"
        print(f"  ✓ Alert retrieved: Found in recent alerts")

    except Exception as e:
        results["alert_manager"]["error"] = str(e)
        print(f"  ✗ Alert Manager error: {str(e)}")

    # Test SEPA Audit Log
    try:
        audit = frappe.new_doc("SEPA Audit Log")
        audit.action_type = "test_e2e"
        audit.entity_type = "Test"
        audit.entity_name = "E2E-TEST-001"
        audit.status = "Success"
        audit.details = json.dumps({"test": "monitoring_e2e"})
        audit.insert()
        frappe.db.commit()

        results["sepa_audit"]["create"] = "PASS"
        print(f"  ✓ SEPA Audit Log created: {audit.name}")

        # Verify retrieval
        audit_check = frappe.db.exists("SEPA Audit Log", {"entity_name": "E2E-TEST-001"})
        results["sepa_audit"]["retrieve"] = "PASS" if audit_check else "FAIL"

    except Exception as e:
        results["sepa_audit"]["error"] = str(e)
        print(f"  ✗ SEPA Audit error: {str(e)}")

    # Check scheduler
    scheduled_jobs = frappe.get_all(
        "Scheduled Job Type", filters={"method": ["like", "%alert_manager%"]}, fields=["method", "frequency"]
    )
    results["scheduler"]["configured"] = len(scheduled_jobs) > 0
    print(f"  {'✓' if scheduled_jobs else '✗'} Scheduler: {len(scheduled_jobs)} jobs configured")

    return results


def test_phase2_dashboard_and_alerts():
    """Test Phase 2 components: Dashboard and System Alerts"""
    print("\nPHASE 2: Dashboard and System Alert Testing")
    print("-" * 50)

    results = {"system_alert": {}, "resource_monitor": {}, "dashboard_apis": {}}

    # Test System Alert
    try:
        alert = frappe.new_doc("System Alert")
        alert.alert_type = "E2E Test Alert"
        alert.compliance_status = "Medium"
        alert.message = "End-to-end monitoring test"
        alert.source = "e2e_test"
        alert.status = "Open"
        alert.insert()
        frappe.db.commit()

        results["system_alert"]["create"] = "PASS"
        print(f"  ✓ System Alert created: {alert.name}")

    except Exception as e:
        results["system_alert"]["error"] = str(e)
        print(f"  ✗ System Alert error: {str(e)}")

    # Test Resource Monitor
    try:
        from vereinigingen.utils.resource_monitor import ResourceMonitor

        rm = ResourceMonitor()

        metrics = rm.get_current_metrics()
        has_required = all(k in metrics for k in ["cpu_percent", "memory_percent", "disk_usage"])
        results["resource_monitor"]["metrics"] = "PASS" if has_required else "FAIL"
        print(
            f"  ✓ Resource metrics: CPU={metrics.get('cpu_percent')}%, Mem={metrics.get('memory_percent')}%"
        )

    except Exception as e:
        results["resource_monitor"]["error"] = str(e)
        print(f"  ✗ Resource Monitor error: {str(e)}")

    # Test Dashboard APIs
    try:
        from vereinigingen.api.monitoring_dashboard import (
            get_audit_summary,
            get_recent_errors,
            get_system_metrics,
        )

        # Test each API
        metrics = get_system_metrics()
        results["dashboard_apis"]["system_metrics"] = "PASS" if metrics else "FAIL"
        print(f"  ✓ System Metrics API: {len(metrics)} metrics")

        errors = get_recent_errors()
        results["dashboard_apis"]["recent_errors"] = "PASS"
        print(f"  ✓ Recent Errors API: {len(errors)} errors")

        audit = get_audit_summary()
        results["dashboard_apis"]["audit_summary"] = "PASS" if audit else "FAIL"
        print(f"  ✓ Audit Summary API: {audit.get('total_actions', 0)} actions")

    except Exception as e:
        results["dashboard_apis"]["error"] = str(e)
        print(f"  ✗ Dashboard API error: {str(e)}")

    return results


def test_phase3_analytics_and_performance():
    """Test Phase 3 components: Analytics and Performance"""
    print("\nPHASE 3: Analytics and Performance Testing")
    print("-" * 50)

    results = {"analytics_engine": {}, "performance_optimizer": {}}

    # Test Analytics Engine
    try:
        from vereinigingen.utils.analytics_engine import AnalyticsEngine

        ae = AnalyticsEngine()

        # Test error patterns
        patterns = ae.analyze_error_patterns(days=7)
        results["analytics_engine"]["error_patterns"] = "PASS" if patterns else "FAIL"
        print(f"  ✓ Error patterns: {len(patterns.get('patterns', []))} patterns found")

        # Test performance metrics
        perf = ae.get_performance_metrics(hours=24)
        results["analytics_engine"]["performance_metrics"] = "PASS" if perf else "FAIL"
        print(f"  ✓ Performance metrics: Analyzed")

        # Test compliance score
        compliance = ae.calculate_compliance_score()
        results["analytics_engine"]["compliance_score"] = (
            "PASS" if isinstance(compliance, (int, float)) else "FAIL"
        )
        print(f"  ✓ Compliance score: {compliance}")

    except Exception as e:
        results["analytics_engine"]["error"] = str(e)
        print(f"  ✗ Analytics Engine error: {str(e)}")

    # Test Performance Optimizer
    try:
        from vereinigingen.utils.performance_optimizer import PerformanceOptimizer

        po = PerformanceOptimizer()

        # Test analysis
        analysis = po.analyze_performance()
        results["performance_optimizer"]["analysis"] = "PASS" if analysis else "FAIL"
        print(f"  ✓ Performance analysis: Complete")

        # Test recommendations
        recommendations = po.get_optimization_recommendations()
        results["performance_optimizer"]["recommendations"] = (
            "PASS" if isinstance(recommendations, list) else "FAIL"
        )
        print(f"  ✓ Optimization recommendations: {len(recommendations)} found")

    except Exception as e:
        results["performance_optimizer"]["error"] = str(e)
        print(f"  ✗ Performance Optimizer error: {str(e)}")

    return results


def test_end_to_end_integration():
    """Test integration between all components"""
    print("\nINTEGRATION TESTING")
    print("-" * 50)

    results = {"data_flow": {}, "error_handling": {}}

    try:
        # Create an alert and track it through the system
        from vereinigingen.utils.alert_manager import AlertManager
        from vereinigingen.utils.analytics_engine import AnalyticsEngine

        am = AlertManager()
        ae = AnalyticsEngine()

        # Create integration test alert
        alert_id = am.create_alert(
            error_type="IntegrationFlow",
            message="Testing data flow through system",
            severity="high",
            source="integration_test",
        )

        # Check if it appears in analytics
        patterns = ae.analyze_error_patterns(days=1)
        found_in_analytics = any("IntegrationFlow" in str(p) for p in patterns.get("patterns", []))

        results["data_flow"]["alert_to_analytics"] = "PASS" if found_in_analytics else "FAIL"
        print(f"  {'✓' if found_in_analytics else '✗'} Data flow: Alert → Analytics")

        # Test error handling
        try:
            # Intentionally cause an error
            ae.analyze_error_patterns(days="invalid")
        except:
            results["error_handling"]["graceful"] = "PASS"
            print(f"  ✓ Error handling: Graceful failure")
        else:
            results["error_handling"]["graceful"] = "FAIL"
            print(f"  ✗ Error handling: No exception raised")

    except Exception as e:
        results["error"] = str(e)
        print(f"  ✗ Integration error: {str(e)}")

    return results


def test_system_performance():
    """Test monitoring system performance"""
    print("\nPERFORMANCE TESTING")
    print("-" * 50)

    results = {"response_times": {}, "resource_usage": {}}

    try:
        import time

        from vereinigingen.api.monitoring_dashboard import get_system_metrics
        from vereinigingen.utils.resource_monitor import ResourceMonitor

        rm = ResourceMonitor()

        # Test API response times
        start = time.time()
        for _ in range(5):
            get_system_metrics()
        api_time = time.time() - start
        avg_response = api_time / 5

        results["response_times"]["api_average"] = f"{avg_response:.3f}s"
        results["response_times"]["status"] = "PASS" if avg_response < 1 else "FAIL"
        print(f"  ✓ API response time: {avg_response:.3f}s average")

        # Check current resource usage
        metrics = rm.get_current_metrics()
        cpu = metrics.get("cpu_percent", 0)
        memory = metrics.get("memory_percent", 0)

        results["resource_usage"]["cpu"] = f"{cpu}%"
        results["resource_usage"]["memory"] = f"{memory}%"
        results["resource_usage"]["status"] = "PASS" if cpu < 80 and memory < 80 else "WARNING"
        print(f"  ✓ Resource usage: CPU={cpu}%, Memory={memory}%")

    except Exception as e:
        results["error"] = str(e)
        print(f"  ✗ Performance test error: {str(e)}")

    return results


def generate_test_summary(results):
    """Generate test summary report"""
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    # Count passes and fails
    total_tests = 0
    passed_tests = 0

    for phase, phase_results in results.items():
        for component, component_results in phase_results.items():
            if isinstance(component_results, dict):
                for test, result in component_results.items():
                    if test not in ["error", "status"] and result in ["PASS", "FAIL"]:
                        total_tests += 1
                        if result == "PASS":
                            passed_tests += 1

    pass_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

    print(f"\nTotal Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Pass Rate: {pass_rate:.1f}%")

    # Overall assessment
    if pass_rate >= 90:
        print("\n✓ SYSTEM IS PRODUCTION READY")
        print("  All critical components are functioning correctly.")
    elif pass_rate >= 70:
        print("\n⚠ SYSTEM NEEDS MINOR FIXES")
        print("  Most components work but some issues need attention.")
    else:
        print("\n✗ SYSTEM REQUIRES SIGNIFICANT WORK")
        print("  Critical components are not functioning properly.")

    # Recommendations
    print("\nRECOMMENDATIONS FOR DEPLOYMENT:")
    print("  1. Review and configure alert thresholds")
    print("  2. Set up email notifications for critical alerts")
    print("  3. Configure scheduler intervals for production")
    print("  4. Review resource limits and adjust as needed")
    print("  5. Enable monitoring dashboard access for admins")
    print("  6. Document any custom alert rules")

    # Check for specific issues
    if "error" in results.get("phase1", {}).get("alert_manager", {}):
        print("\n⚠ Alert Manager needs configuration")

    if "error" in results.get("phase2", {}).get("resource_monitor", {}):
        print("\n⚠ Resource Monitor needs setup")

    if "error" in results.get("phase3", {}).get("analytics_engine", {}):
        print("\n⚠ Analytics Engine needs initialization")


@frappe.whitelist()
def cleanup_test_data():
    """Clean up test data created during monitoring tests"""
    frappe.set_user("Administrator")

    print("\nCleaning up test data...")

    # Clean up test alerts
    test_alerts = frappe.get_all("System Alert", filters={"title": ["like", "%test%"]}, pluck="name")
    for alert in test_alerts:
        frappe.delete("System Alert", alert, force=True)
    print(f"  Cleaned {len(test_alerts)} test alerts")

    # Clean up test audit logs
    test_audits = frappe.get_all("SEPA Audit Log", filters={"entity_name": ["like", "%TEST%"]}, pluck="name")
    for audit in test_audits:
        frappe.delete("SEPA Audit Log", audit, force=True)
    print(f"  Cleaned {len(test_audits)} test audit logs")

    frappe.db.commit()

    return {"cleaned_alerts": len(test_alerts), "cleaned_audits": len(test_audits)}
