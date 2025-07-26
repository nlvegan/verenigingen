#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick validation script for monitoring system components
"""

import frappe
from frappe import _

@frappe.whitelist()
def validate_monitoring_components():
    """Validate that all monitoring components are properly installed"""
    results = {
        "components": {},
        "status": "success"
    }
    
    print("Validating Monitoring System Components...")
    print("=" * 60)
    
    # 1. Check DocTypes
    print("\n1. Checking DocTypes...")
    doctypes = ["SEPA Audit Log", "System Alert"]
    for dt in doctypes:
        exists = frappe.db.exists("DocType", dt)
        results["components"][f"doctype_{dt}"] = exists
        print(f"  {'✓' if exists else '✗'} {dt}: {'Installed' if exists else 'Missing'}")
    
    # 2. Check Python modules
    print("\n2. Checking Python Modules...")
    modules = [
        ("Alert Manager", "vereinigingen.utils.alert_manager", "AlertManager"),
        ("Resource Monitor", "vereinigingen.utils.resource_monitor", "ResourceMonitor"),
        ("Analytics Engine", "vereinigingen.utils.analytics_engine", "AnalyticsEngine"),
        ("Performance Optimizer", "vereinigingen.utils.performance_optimizer", "PerformanceOptimizer")
    ]
    
    for name, module_path, class_name in modules:
        try:
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            instance = cls()
            results["components"][f"module_{name}"] = True
            print(f"  ✓ {name}: Loaded successfully")
        except Exception as e:
            results["components"][f"module_{name}"] = False
            results["status"] = "partial"
            print(f"  ✗ {name}: {str(e)}")
    
    # 3. Check APIs
    print("\n3. Checking API Endpoints...")
    apis = [
        ("System Metrics", "vereinigingen.api.monitoring_dashboard.get_system_metrics"),
        ("Recent Errors", "vereinigingen.api.monitoring_dashboard.get_recent_errors"),
        ("Audit Summary", "vereinigingen.api.monitoring_dashboard.get_audit_summary"),
        ("System Health", "vereinigingen.api.monitoring_dashboard.get_system_health")
    ]
    
    for name, api_path in apis:
        try:
            parts = api_path.split('.')
            module_path = '.'.join(parts[:-1])
            func_name = parts[-1]
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)
            # Test call
            result = func()
            results["components"][f"api_{name}"] = True
            print(f"  ✓ {name}: Responding correctly")
        except Exception as e:
            results["components"][f"api_{name}"] = False
            results["status"] = "partial"
            print(f"  ✗ {name}: {str(e)}")
    
    # 4. Check scheduled jobs
    print("\n4. Checking Scheduled Jobs...")
    scheduled_methods = [
        "vereinigingen.utils.alert_manager.check_system_alerts",
        "vereinigingen.utils.alert_manager.daily_alert_summary"
    ]
    
    for method in scheduled_methods:
        exists = frappe.db.exists("Scheduled Job Type", {"method": method})
        results["components"][f"scheduler_{method}"] = exists
        print(f"  {'✓' if exists else '✗'} {method}: {'Configured' if exists else 'Not configured'}")
    
    # 5. Check monitoring dashboard
    print("\n5. Checking Monitoring Dashboard...")
    dashboard_exists = frappe.db.exists("Web Page", {"route": "monitoring_dashboard"})
    results["components"]["monitoring_dashboard"] = dashboard_exists
    print(f"  {'✓' if dashboard_exists else '✗'} Monitoring Dashboard: {'Available' if dashboard_exists else 'Missing'}")
    
    # Summary
    print("\n" + "=" * 60)
    total = len(results["components"])
    passed = sum(1 for v in results["components"].values() if v)
    
    print(f"\nValidation Summary:")
    print(f"  Total checks: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {total - passed}")
    print(f"  Status: {results['status'].upper()}")
    
    if results["status"] == "success":
        print("\n✓ All monitoring components are properly installed!")
    else:
        print("\n⚠ Some components need attention. Please review the failed items.")
    
    return results

@frappe.whitelist()
def test_monitoring_functionality():
    """Test basic monitoring functionality"""
    print("\nTesting Monitoring Functionality...")
    print("=" * 60)
    
    tests_passed = 0
    tests_total = 0
    
    # Test 1: Create and retrieve alert
    print("\n1. Testing Alert Creation and Retrieval...")
    tests_total += 1
    try:
        from vereinigingen.utils.alert_manager import AlertManager
        am = AlertManager()
        
        # Create test alert
        alert_id = am.create_alert(
            error_type="FunctionalTest",
            message="Testing monitoring functionality",
            severity="low",
            source="test_script"
        )
        
        # Retrieve alerts
        recent = am.get_recent_alerts(hours=1)
        found = any(a.get("error_type") == "FunctionalTest" for a in recent)
        
        if found:
            print("  ✓ Alert created and retrieved successfully")
            tests_passed += 1
        else:
            print("  ✗ Alert created but not found in recent alerts")
    except Exception as e:
        print(f"  ✗ Alert test failed: {str(e)}")
    
    # Test 2: Resource monitoring
    print("\n2. Testing Resource Monitoring...")
    tests_total += 1
    try:
        from vereinigingen.utils.resource_monitor import ResourceMonitor
        rm = ResourceMonitor()
        
        metrics = rm.get_current_metrics()
        if all(k in metrics for k in ["cpu_percent", "memory_percent", "disk_usage"]):
            print(f"  ✓ Resource metrics retrieved: CPU={metrics['cpu_percent']}%, Memory={metrics['memory_percent']}%")
            tests_passed += 1
        else:
            print("  ✗ Resource metrics incomplete")
    except Exception as e:
        print(f"  ✗ Resource monitoring failed: {str(e)}")
    
    # Test 3: Analytics
    print("\n3. Testing Analytics Engine...")
    tests_total += 1
    try:
        from vereinigingen.utils.analytics_engine import AnalyticsEngine
        ae = AnalyticsEngine()
        
        patterns = ae.analyze_error_patterns(days=1)
        if isinstance(patterns, dict):
            print(f"  ✓ Analytics working: {len(patterns.get('patterns', []))} patterns found")
            tests_passed += 1
        else:
            print("  ✗ Analytics returned unexpected format")
    except Exception as e:
        print(f"  ✗ Analytics test failed: {str(e)}")
    
    # Test 4: Performance optimization
    print("\n4. Testing Performance Optimizer...")
    tests_total += 1
    try:
        from vereinigingen.utils.performance_optimizer import PerformanceOptimizer
        po = PerformanceOptimizer()
        
        analysis = po.analyze_performance()
        if analysis:
            print("  ✓ Performance analysis completed")
            tests_passed += 1
        else:
            print("  ✗ Performance analysis returned empty")
    except Exception as e:
        print(f"  ✗ Performance optimizer test failed: {str(e)}")
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Functionality Test Summary:")
    print(f"  Tests passed: {tests_passed}/{tests_total}")
    print(f"  Success rate: {(tests_passed/tests_total*100):.1f}%")
    
    return {
        "passed": tests_passed,
        "total": tests_total,
        "success_rate": tests_passed/tests_total
    }

if __name__ == "__main__":
    print("Run via bench execute:")
    print("  Validate: bench --site dev.veganisme.net execute verenigingen.scripts.testing.monitoring.validate_monitoring.validate_monitoring_components")
    print("  Test: bench --site dev.veganisme.net execute verenigingen.scripts.testing.monitoring.validate_monitoring.test_monitoring_functionality")