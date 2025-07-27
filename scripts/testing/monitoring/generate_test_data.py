#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generate test data for monitoring system testing
"""

import frappe
from frappe import _
import random
from datetime import datetime, timedelta
import json

@frappe.whitelist()
def generate_monitoring_test_data():
    """Generate various test data for monitoring system validation"""
    print("Generating test data for monitoring system...")
    
    # 1. Generate test errors for Alert Manager
    print("\n1. Generating test errors...")
    error_types = [
        ("ValidationError", "Member validation failed: Invalid email format", "high"),
        ("PermissionError", "Access denied to chapter data", "medium"),
        ("DataError", "SEPA mandate creation failed", "high"),
        ("SystemError", "Database connection timeout", "critical"),
        ("IntegrationError", "Payment gateway unreachable", "medium"),
        ("BusinessLogicError", "Duplicate membership detected", "low")
    ]
    
    from vereinigingen.utils.alert_manager import AlertManager
    alert_manager = AlertManager()
    
    for error_type, message, severity in error_types:
        try:
            alert_manager.create_alert(
                error_type=error_type,
                message=message,
                severity=severity,
                source=f"test_generator_{random.randint(1, 100)}"
            )
            print(f"  ✓ Created {error_type} alert")
        except Exception as e:
            print(f"  ✗ Failed to create {error_type}: {str(e)}")
    
    # 2. Generate SEPA Audit Log entries
    print("\n2. Generating SEPA audit logs...")
    audit_actions = [
        ("mandate_creation", "SEPA Mandate", "Success"),
        ("mandate_validation", "SEPA Mandate", "Failed"),
        ("batch_creation", "Direct Debit Batch", "Success"),
        ("payment_processing", "Payment Entry", "Success"),
        ("mandate_cancellation", "SEPA Mandate", "Success")
    ]
    
    for action, entity_type, status in audit_actions:
        try:
            audit = frappe.new_doc("SEPA Audit Log")
            audit.action_type = action
            audit.entity_type = entity_type
            audit.entity_name = f"TEST-{random.randint(1000, 9999)}"
            audit.status = status
            audit.details = json.dumps({
                "test": True,
                "generated_at": datetime.now().isoformat(),
                "random_value": random.randint(1, 100)
            })
            audit.insert()
            print(f"  ✓ Created {action} audit log")
        except Exception as e:
            print(f"  ✗ Failed to create audit log: {str(e)}")
    
    # 3. Generate System Alerts
    print("\n3. Generating system alerts...")
    alert_types = [
        ("Resource Warning", "High", "CPU usage above 80%"),
        ("Security Alert", "Critical", "Multiple failed login attempts detected"),
        ("Performance Alert", "Medium", "Database query taking >5 seconds"),
        ("Integration Alert", "Low", "Email queue backlog detected"),
        ("Compliance Alert", "High", "GDPR data retention limit approaching")
    ]
    
    for alert_type, severity, message in alert_types:
        try:
            alert = frappe.new_doc("System Alert")
            alert.alert_type = alert_type
            alert.severity = severity
            alert.message = message
            alert.source = "monitoring_test"
            alert.status = random.choice(["Open", "Acknowledged", "Resolved"])
            alert.insert()
            print(f"  ✓ Created {alert_type}")
        except Exception as e:
            print(f"  ✗ Failed to create system alert: {str(e)}")
    
    # 4. Simulate resource usage patterns
    print("\n4. Simulating resource usage...")
    from vereinigingen.utils.resource_monitor import ResourceMonitor
    monitor = ResourceMonitor()
    
    # Generate some load
    for i in range(5):
        metrics = monitor.get_current_metrics()
        monitor.check_resource_usage()
        print(f"  ✓ Resource check {i+1}: CPU={metrics.get('cpu_percent')}%, Memory={metrics.get('memory_percent')}%")
    
    # 5. Generate analytics data
    print("\n5. Generating analytics data...")
    from vereinigingen.utils.analytics_engine import AnalyticsEngine
    analytics = AnalyticsEngine()
    
    # Trigger analytics calculations
    patterns = analytics.analyze_error_patterns(days=7)
    perf_metrics = analytics.get_performance_metrics(hours=24)
    compliance_score = analytics.calculate_compliance_score()
    
    print(f"  ✓ Error patterns analyzed: {len(patterns.get('patterns', []))} patterns found")
    print(f"  ✓ Performance metrics calculated")
    print(f"  ✓ Compliance score: {compliance_score}")
    
    # 6. Test performance optimizer
    print("\n6. Testing performance optimizer...")
    from vereinigingen.utils.performance_optimizer import PerformanceOptimizer
    optimizer = PerformanceOptimizer()
    
    analysis = optimizer.analyze_performance()
    recommendations = optimizer.get_optimization_recommendations()
    
    print(f"  ✓ Performance analysis complete")
    print(f"  ✓ Generated {len(recommendations)} optimization recommendations")
    
    print("\n" + "="*60)
    print("Test data generation complete!")
    print("You can now run the comprehensive test suite.")
    
    return {
        "status": "success",
        "message": "Test data generated successfully",
        "summary": {
            "errors_created": len(error_types),
            "audit_logs_created": len(audit_actions),
            "system_alerts_created": len(alert_types),
            "analytics_processed": True,
            "performance_analyzed": True
        }
    }

@frappe.whitelist()
def cleanup_test_data():
    """Clean up test data after testing"""
    print("Cleaning up test data...")
    
    # Clean up test alerts
    test_alerts = frappe.get_all("System Alert", 
        filters={"title": ["like", "%test%"]},
        pluck="name"
    )
    for alert in test_alerts:
        frappe.delete_doc("System Alert", alert)
    print(f"  ✓ Cleaned up {len(test_alerts)} test alerts")
    
    # Clean up test audit logs
    test_audits = frappe.get_all("SEPA Audit Log",
        filters={"entity_name": ["like", "TEST-%"]},
        pluck="name"
    )
    for audit in test_audits:
        frappe.delete_doc("SEPA Audit Log", audit)
    print(f"  ✓ Cleaned up {len(test_audits)} test audit logs")
    
    frappe.db.commit()
    print("Test data cleanup complete!")
    
    return {
        "status": "success",
        "cleaned": {
            "alerts": len(test_alerts),
            "audit_logs": len(test_audits)
        }
    }

if __name__ == "__main__":
    print("Run via bench execute:")
    print("  Generate: bench --site dev.veganisme.net execute verenigingen.scripts.testing.monitoring.generate_test_data.generate_monitoring_test_data")
    print("  Cleanup: bench --site dev.veganisme.net execute verenigingen.scripts.testing.monitoring.generate_test_data.cleanup_test_data")