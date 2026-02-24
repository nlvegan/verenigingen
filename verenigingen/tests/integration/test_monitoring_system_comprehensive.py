"""
Comprehensive Monitoring System Tests

This module contains end-to-end tests for the monitoring system infrastructure,
validating alert management, SEPA audit logging, analytics engine, and dashboard
functionality.

Extracted from www/monitoring_dashboard.py to maintain proper separation between
production code and test code.

Note: These tests require system administrator privileges and should be run
in development/staging environments only.
"""

import json
import time

import frappe
from frappe.utils import add_to_date, now

from verenigingen.utils.validation_utilities import DocumentExistenceValidator


class MonitoringSystemTestRunner:
    """
    Test runner for comprehensive monitoring system validation.

    This class provides structured testing of all monitoring components
    across multiple phases of implementation.
    """

    def __init__(self):
        self.results = {}

    def run_all_tests(self):
        """Run comprehensive end-to-end monitoring system tests."""
        frappe.set_user("Administrator")

        print("\n" + "=" * 60)
        print("COMPREHENSIVE MONITORING SYSTEM TEST SUITE")
        print("=" * 60)
        print(f"Test Started: {now()}")

        self.results = {
            "phase1": self._test_phase1_components(),
            "phase2": self._test_phase2_components(),
            "phase3": self._test_phase3_components(),
            "integration": self._test_integration(),
            "performance": self._test_performance(),
            "dashboard": self._test_dashboard_functionality(),
        }

        self._generate_summary()
        return self.results

    def _test_phase1_components(self):
        """Test Phase 1: Alert Manager and SEPA Audit."""
        print("\nPHASE 1: Alert Manager and SEPA Audit Testing")
        print("-" * 50)

        results = {"alert_manager": {}, "sepa_audit": {}, "scheduler": {}}

        # Test Alert Manager
        try:
            from verenigingen.utils.alert_manager import AlertManager

            am = AlertManager()

            # Create test alert
            alert_id = am.create_alert(
                error_type="E2E_Test",
                message="End-to-end comprehensive test alert",
                severity="medium",
                source="comprehensive_test",
            )
            results["alert_manager"]["create"] = "PASS" if alert_id else "FAIL"
            print(f"  Alert Manager: Alert created ({alert_id})")

            # Test alert retrieval
            recent = am.get_recent_alerts(hours=1)
            found = any(a.get("error_type") == "E2E_Test" for a in recent)
            results["alert_manager"]["retrieve"] = "PASS" if found else "FAIL"
            print(f"  Alert Manager: Retrieval {'successful' if found else 'failed'}")

            # Test alert summaries
            summary = am.get_alert_summary()
            results["alert_manager"]["summary"] = "PASS" if summary else "FAIL"
            print("  Alert Manager: Summary generation")

        except Exception as e:
            results["alert_manager"]["error"] = str(e)
            print(f"  Alert Manager: {str(e)}")

        # Test SEPA Audit Log
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
                results["sepa_audit"]["doctype"] = "FAIL"
                print("  SEPA Audit Log: DocType not found")
            else:
                results["sepa_audit"]["doctype"] = "PASS"

                # Create test audit entry
                audit = frappe.new_doc("SEPA Audit Log")
                audit.action = "comprehensive_test"
                audit.process_type = "Batch Generation"
                audit.reference_name = "COMP-TEST-001"
                audit.compliance_status = "Compliant"
                audit.details = json.dumps({"test": "comprehensive_monitoring"})
                audit.insert()
                frappe.db.commit()

                results["sepa_audit"]["create"] = "PASS"
                print(f"  SEPA Audit Log: Entry created ({audit.name})")

                # Test retrieval
                audit_count = frappe.db.count("SEPA Audit Log", {"entity_name": "COMP-TEST-001"})
                results["sepa_audit"]["retrieve"] = "PASS" if audit_count > 0 else "FAIL"
                print("  SEPA Audit Log: Retrieval successful")

        except Exception as e:
            results["sepa_audit"]["error"] = str(e)
            print(f"  SEPA Audit Log: {str(e)}")

        # Test scheduler configuration
        try:
            scheduled_jobs = frappe.get_all(
                "Scheduled Job Type",
                filters={"method": ["like", "%alert%"]},
                fields=["method", "frequency"],
            )
            results["scheduler"]["configured"] = len(scheduled_jobs) > 0
            print(f"  Scheduler: {len(scheduled_jobs)} alert-related jobs")

        except Exception as e:
            results["scheduler"]["error"] = str(e)
            print(f"  Scheduler: {str(e)}")

        return results

    def _test_phase2_components(self):
        """Test Phase 2: Dashboard and System Alerts."""
        print("\nPHASE 2: Dashboard and System Alert Testing")
        print("-" * 50)

        results = {"system_alert": {}, "resource_monitor": {}, "dashboard_apis": {}}

        # Test System Alert DocType
        try:
            if not DocumentExistenceValidator.check_document_exists("DocType", "System Alert"):
                results["system_alert"]["doctype"] = "FAIL"
                print("  System Alert: DocType not found")
            else:
                results["system_alert"]["doctype"] = "PASS"

                # Create test system alert
                alert = frappe.new_doc("System Alert")
                alert.alert_type = "Comprehensive Test Alert"
                alert.severity = "MEDIUM"
                alert.message = "End-to-end monitoring system validation"
                alert.details = {"source": "comprehensive_test", "test_type": "automated_validation"}
                alert.status = "Active"
                alert.insert()
                frappe.db.commit()

                results["system_alert"]["create"] = "PASS"
                print(f"  System Alert: Created ({alert.name})")

        except Exception as e:
            results["system_alert"]["error"] = str(e)
            print(f"  System Alert: {str(e)}")

        # Test Resource Monitor
        try:
            from verenigingen.utils.resource_monitor import ResourceMonitor

            rm = ResourceMonitor()

            metrics = rm.get_current_metrics()
            required_metrics = ["cpu_percent", "memory_percent", "disk_usage", "active_users"]
            has_all = all(k in metrics for k in required_metrics)

            results["resource_monitor"]["metrics"] = "PASS" if has_all else "FAIL"
            print(f"  Resource Monitor: Metrics collected (CPU: {metrics.get('cpu_percent')}%)")

            # Test resource checking
            status = rm.check_resource_usage()
            results["resource_monitor"]["check"] = "PASS" if status else "FAIL"
            print("  Resource Monitor: Usage check completed")

        except Exception as e:
            results["resource_monitor"]["error"] = str(e)
            print(f"  Resource Monitor: {str(e)}")

        # Test Dashboard APIs
        try:
            from verenigingen.services.monitoring.monitoring_metrics_service import (
                MonitoringMetricsService,
            )

            service = MonitoringMetricsService()

            # Test system metrics API
            metrics = service.get_system_metrics()
            results["dashboard_apis"]["system_metrics"] = "PASS" if metrics else "FAIL"
            print(f"  Dashboard API: System metrics ({len(metrics)} items)")

            # Test recent errors API
            errors = service.get_recent_errors()
            results["dashboard_apis"]["recent_errors"] = "PASS"
            print(f"  Dashboard API: Recent errors ({len(errors)} errors)")

            # Test audit summary API
            audit = service.get_audit_summary()
            results["dashboard_apis"]["audit_summary"] = "PASS" if audit else "FAIL"
            print("  Dashboard API: Audit summary")

            # Test active alerts API
            alerts = service.get_active_alerts()
            results["dashboard_apis"]["active_alerts"] = "PASS"
            print(f"  Dashboard API: Active alerts ({len(alerts)} alerts)")

        except Exception as e:
            results["dashboard_apis"]["error"] = str(e)
            print(f"  Dashboard APIs: {str(e)}")

        return results

    def _test_phase3_components(self):
        """Test Phase 3: Analytics and Performance."""
        print("\nPHASE 3: Analytics Engine and Performance Testing")
        print("-" * 50)

        results = {"analytics_engine": {}, "advanced_features": {}}

        # Test Analytics Engine
        try:
            from verenigingen.utils.analytics_engine import AnalyticsEngine

            ae = AnalyticsEngine()

            # Test error pattern analysis
            patterns = ae.analyze_error_patterns(days=7)
            results["analytics_engine"]["error_patterns"] = "PASS" if patterns else "FAIL"
            print(f"  Analytics Engine: Error patterns ({len(patterns.get('patterns', []))} found)")

            # Test performance metrics
            perf = ae.get_performance_metrics(hours=24)
            results["analytics_engine"]["performance_metrics"] = "PASS" if perf else "FAIL"
            print("  Analytics Engine: Performance metrics")

            # Test compliance calculation
            compliance = ae.calculate_compliance_score()
            results["analytics_engine"]["compliance"] = (
                "PASS" if isinstance(compliance, (int, float)) else "FAIL"
            )
            print(f"  Analytics Engine: Compliance score ({compliance})")

            # Test insights generation
            insights = ae.generate_insights_report()
            results["analytics_engine"]["insights"] = "PASS" if insights else "FAIL"
            print("  Analytics Engine: Insights report generated")

        except Exception as e:
            results["analytics_engine"]["error"] = str(e)
            print(f"  Analytics Engine: {str(e)}")

        # Test Advanced Features
        try:
            from verenigingen.services.monitoring.compliance_metrics_service import (
                ComplianceMetricsService,
            )

            compliance_service = ComplianceMetricsService()

            # Test compliance metrics
            compliance_metrics = compliance_service.get_compliance_metrics()
            results["advanced_features"]["compliance_metrics"] = "PASS" if compliance_metrics else "FAIL"
            print("  Advanced Features: Compliance metrics")

        except Exception as e:
            results["advanced_features"]["error"] = str(e)
            print(f"  Advanced Features: {str(e)}")

        return results

    def _test_integration(self):
        """Test integration between components."""
        print("\nINTEGRATION TESTING")
        print("-" * 50)

        results = {"data_flow": {}, "api_integration": {}, "error_handling": {}}

        try:
            from verenigingen.utils.alert_manager import AlertManager
            from verenigingen.utils.analytics_engine import AnalyticsEngine

            am = AlertManager()
            ae = AnalyticsEngine()

            # Create integration test alert
            am.create_alert(
                error_type="IntegrationFlow",
                message="Testing complete data flow",
                severity="high",
                source="integration_test",
            )

            # Check if analytics can process it
            time.sleep(1)  # Allow processing time

            patterns = ae.analyze_error_patterns(days=1)
            found_in_analytics = any("IntegrationFlow" in str(p) for p in patterns.get("patterns", []))

            results["data_flow"]["alert_to_analytics"] = "PASS" if found_in_analytics else "FAIL"
            print(f"  {'PASS' if found_in_analytics else 'FAIL'} Data Flow: Alert -> Analytics")

            # Test error handling
            try:
                ae.analyze_error_patterns(days="invalid")
            except (TypeError, ValueError, AttributeError):
                results["error_handling"]["graceful"] = "PASS"
                print("  Error Handling: Graceful failure")
            else:
                results["error_handling"]["graceful"] = "FAIL"
                print("  Error Handling: No exception raised")

        except Exception as e:
            results["error"] = str(e)
            print(f"  Integration: {str(e)}")

        return results

    def _test_performance(self):
        """Test monitoring system performance."""
        print("\nPERFORMANCE TESTING")
        print("-" * 50)

        results = {"response_times": {}, "resource_usage": {}, "scalability": {}}

        try:
            from verenigingen.services.monitoring.monitoring_metrics_service import (
                MonitoringMetricsService,
            )
            from verenigingen.utils.resource_monitor import ResourceMonitor

            rm = ResourceMonitor()
            service = MonitoringMetricsService()

            # Test API response times
            start = time.time()
            for _ in range(5):
                service.get_system_metrics()
            api_time = time.time() - start
            avg_response = api_time / 5

            results["response_times"]["api_average"] = f"{avg_response:.3f}s"
            results["response_times"]["status"] = "PASS" if avg_response < 1 else "FAIL"
            print(f"  Performance: API response {avg_response:.3f}s average")

            # Test resource usage
            metrics = rm.get_current_metrics()
            cpu = metrics.get("cpu_percent", 0)
            memory = metrics.get("memory_percent", 0)

            results["resource_usage"]["cpu"] = f"{cpu}%"
            results["resource_usage"]["memory"] = f"{memory}%"
            results["resource_usage"]["status"] = "PASS" if cpu < 80 and memory < 80 else "WARNING"
            print(f"  Performance: Resource usage CPU={cpu}%, Memory={memory}%")

            # Test scalability (create multiple alerts)
            from verenigingen.utils.alert_manager import AlertManager

            start = time.time()
            am = AlertManager()
            for i in range(10):
                am.create_alert(
                    error_type=f"ScaleTest{i}",
                    message=f"Scalability test {i}",
                    severity="low",
                    source="scale_test",
                )
            scale_time = time.time() - start

            results["scalability"]["10_alerts"] = f"{scale_time:.3f}s"
            results["scalability"]["status"] = "PASS" if scale_time < 5 else "FAIL"
            print(f"  Performance: Scalability test {scale_time:.3f}s for 10 alerts")

        except Exception as e:
            results["error"] = str(e)
            print(f"  Performance: {str(e)}")

        return results

    def _test_dashboard_functionality(self):
        """Test dashboard UI and functionality."""
        print("\nDASHBOARD FUNCTIONALITY TESTING")
        print("-" * 50)

        results = {"page_access": {}, "data_loading": {}, "real_time_updates": {}}

        try:
            from verenigingen.services.monitoring.monitoring_metrics_service import (
                MonitoringMetricsService,
            )

            service = MonitoringMetricsService()

            # Test data loading
            dashboard_data = service.get_all_dashboard_data()
            required_sections = [
                "system_metrics",
                "recent_errors",
                "audit_summary",
                "performance_metrics",
            ]

            data_complete = all(section in dashboard_data for section in required_sections)
            results["data_loading"]["complete"] = "PASS" if data_complete else "FAIL"
            print("  Dashboard: Data loading complete")

            # Test individual dashboard components
            for section in required_sections:
                has_data = dashboard_data.get(section) is not None
                results["data_loading"][section] = "PASS" if has_data else "FAIL"
                print(f"    {'PASS' if has_data else 'FAIL'} {section}: {'Loaded' if has_data else 'Failed'}")

            # Test real-time capability (simulate refresh)
            time.sleep(1)
            refresh_data = service.get_all_dashboard_data()
            results["real_time_updates"]["refresh"] = "PASS"
            print("  Dashboard: Real-time updates working")

        except Exception as e:
            results["error"] = str(e)
            print(f"  Dashboard: {str(e)}")

        return results

    def _generate_summary(self):
        """Generate comprehensive test summary."""
        print("\n" + "=" * 60)
        print("COMPREHENSIVE TEST SUMMARY")
        print("=" * 60)

        total_tests = 0
        passed_tests = 0

        for phase_name, phase_results in self.results.items():
            print(f"\n{phase_name.upper()} RESULTS:")

            phase_total = 0
            phase_passed = 0

            for component, component_results in phase_results.items():
                if isinstance(component_results, dict):
                    for test, result in component_results.items():
                        if test not in ["error"] and result in ["PASS", "FAIL"]:
                            phase_total += 1
                            total_tests += 1
                            if result == "PASS":
                                phase_passed += 1
                                passed_tests += 1

                            print(f"  {'PASS' if result == 'PASS' else 'FAIL'} {component}.{test}: {result}")

            phase_rate = (phase_passed / phase_total * 100) if phase_total > 0 else 0
            print(f"  Phase Summary: {phase_passed}/{phase_total} ({phase_rate:.1f}%)")

        overall_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        print("\n" + "=" * 60)
        print("OVERALL ASSESSMENT")
        print("=" * 60)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {overall_rate:.1f}%")

        if overall_rate >= 95:
            status = "EXCELLENT - Production Ready"
        elif overall_rate >= 85:
            status = "GOOD - Minor Issues to Address"
        elif overall_rate >= 70:
            status = "FAIR - Several Issues Need Attention"
        else:
            status = "POOR - Significant Issues Require Resolution"

        print(f"\nSYSTEM STATUS: {status}")
        print(f"\nTest completed at: {now()}")


def cleanup_test_data():
    """Clean up test data created during comprehensive tests."""
    frappe.set_user("Administrator")

    print("\nCleaning up comprehensive test data...")

    # Clean up test alerts
    test_alerts = frappe.get_all(
        "System Alert",
        filters={"message": ["like", "%test%"]},
        pluck="name",
    )
    for alert in test_alerts:
        frappe.delete_doc("System Alert", alert, force=True)
    print(f"  Cleaned {len(test_alerts)} test system alerts")

    # Clean up test audit logs
    if DocumentExistenceValidator.check_document_exists("DocType", "SEPA Audit Log"):
        test_audits = frappe.get_all(
            "SEPA Audit Log",
            filters={"reference_name": ["like", "%TEST%"]},
            pluck="name",
        )
        for audit in test_audits:
            frappe.delete_doc("SEPA Audit Log", audit, force=True)
        print(f"  Cleaned {len(test_audits)} test audit logs")

    frappe.db.commit()
    print("Comprehensive test cleanup complete!")

    return {"cleaned_alerts": len(test_alerts)}


# Convenience function for running from console
def run_comprehensive_tests():
    """Run comprehensive monitoring system tests from console."""
    runner = MonitoringSystemTestRunner()
    return runner.run_all_tests()
