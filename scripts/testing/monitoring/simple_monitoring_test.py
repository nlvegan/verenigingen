#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple monitoring system test - no complex imports
"""

def test_monitoring():
    import frappe
    from datetime import datetime
    
    print("\n" + "="*60)
    print("MONITORING SYSTEM VALIDATION")
    print("="*60)
    print(f"Test Time: {datetime.now()}\n")
    
    results = []
    
    # Test 1: Check DocTypes
    print("1. Checking DocTypes...")
    doctypes = ["SEPA Audit Log", "System Alert"]
    for dt in doctypes:
        exists = frappe.db.exists("DocType", dt)
        status = "✓" if exists else "✗"
        results.append((dt, exists))
        print(f"   {status} {dt}: {'Installed' if exists else 'Missing'}")
    
    # Test 2: Check Utils modules exist
    print("\n2. Checking Python Modules...")
    try:
        # Import directly
        from vereinigingen.utils.alert_manager import AlertManager
        print("   ✓ Alert Manager: Found")
        results.append(("Alert Manager", True))
    except:
        print("   ✗ Alert Manager: Not found")
        results.append(("Alert Manager", False))
    
    try:
        from vereinigingen.utils.resource_monitor import ResourceMonitor
        print("   ✓ Resource Monitor: Found")
        results.append(("Resource Monitor", True))
    except:
        print("   ✗ Resource Monitor: Not found")
        results.append(("Resource Monitor", False))
    
    try:
        from vereinigingen.utils.analytics_engine import AnalyticsEngine
        print("   ✓ Analytics Engine: Found")
        results.append(("Analytics Engine", True))
    except:
        print("   ✗ Analytics Engine: Not found")
        results.append(("Analytics Engine", False))
    
    try:
        from vereinigingen.utils.performance_optimizer import PerformanceOptimizer
        print("   ✓ Performance Optimizer: Found")
        results.append(("Performance Optimizer", True))
    except:
        print("   ✗ Performance Optimizer: Not found")
        results.append(("Performance Optimizer", False))
    
    # Test 3: Basic functionality test
    print("\n3. Testing Basic Functionality...")
    
    # Try to create a test alert
    try:
        from vereinigingen.utils.alert_manager import AlertManager
        am = AlertManager()
        alert_id = am.create_alert(
            error_type="TestValidation",
            message="Monitoring system validation test",
            severity="low",
            source="simple_test"
        )
        print("   ✓ Alert creation: Success")
        results.append(("Alert Creation", True))
        
        # Try to retrieve it
        recent = am.get_recent_alerts(hours=1)
        found = any(a.get("error_type") == "TestValidation" for a in recent)
        if found:
            print("   ✓ Alert retrieval: Success")
            results.append(("Alert Retrieval", True))
        else:
            print("   ✗ Alert retrieval: Failed")
            results.append(("Alert Retrieval", False))
    except Exception as e:
        print(f"   ✗ Alert functionality: {str(e)}")
        results.append(("Alert Functionality", False))
    
    # Test 4: Check APIs
    print("\n4. Testing API Endpoints...")
    try:
        from vereinigingen.api.monitoring_dashboard import get_system_metrics
        metrics = get_system_metrics()
        print("   ✓ System Metrics API: Working")
        results.append(("System Metrics API", True))
    except Exception as e:
        print(f"   ✗ System Metrics API: {str(e)}")
        results.append(("System Metrics API", False))
    
    try:
        from vereinigingen.api.monitoring_dashboard import get_recent_errors
        errors = get_recent_errors()
        print("   ✓ Recent Errors API: Working")
        results.append(("Recent Errors API", True))
    except Exception as e:
        print(f"   ✗ Recent Errors API: {str(e)}")
        results.append(("Recent Errors API", False))
    
    # Test 5: Check dashboard page
    print("\n5. Checking Dashboard...")
    dashboard = frappe.db.exists("Web Page", {"route": "monitoring_dashboard"})
    if dashboard:
        print("   ✓ Monitoring Dashboard: Available")
        results.append(("Dashboard Page", True))
    else:
        print("   ✗ Monitoring Dashboard: Not found")
        results.append(("Dashboard Page", False))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY:")
    total = len(results)
    passed = sum(1 for _, status in results if status)
    failed = total - passed
    
    print(f"  Total checks: {total}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"  Success rate: {(passed/total*100):.1f}%")
    
    if passed == total:
        print("\n✓ ALL TESTS PASSED - System is ready!")
    elif passed >= total * 0.8:
        print("\n⚠ MOSTLY WORKING - Some components need attention")
    else:
        print("\n✗ CRITICAL ISSUES - System needs configuration")
    
    print("\nDetailed Results:")
    for name, status in results:
        print(f"  {name}: {'PASS' if status else 'FAIL'}")
    
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "results": results
    }

if __name__ == "__main__":
    # This will be run via bench execute
    test_monitoring()