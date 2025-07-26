#!/usr/bin/env python3
"""
SEPA Week 4 Monitoring and Analytics Testing Suite

Comprehensive tests for Week 4 SEPA monitoring, alerting, reporting,
and Zabbix integration components.

This test suite validates:
- SEPA monitoring dashboard functionality
- Advanced alerting system operations
- Admin reporting tools accuracy
- Enhanced Zabbix integration metrics
- Memory optimization and performance monitoring
"""

import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import frappe
from frappe.utils import get_datetime, now_datetime

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils.sepa_monitoring_dashboard import (
    SEPAMonitoringDashboard, get_dashboard_instance
)
from verenigingen.utils.sepa_alerting_system import (
    SEPAAlertingSystem, AlertSeverity, AlertStatus, get_alerting_system
)
from verenigingen.utils.sepa_admin_reporting import SEPAAdminReportGenerator
from verenigingen.utils.sepa_zabbix_enhanced import SEPAZabbixIntegration
from verenigingen.utils.sepa_memory_optimizer import SEPAMemoryMonitor


class TestSEPAMonitoringDashboard(VereningingenTestCase):
    """Test SEPA monitoring dashboard functionality"""
    
    def setUp(self):
        super().setUp()
        self.dashboard = SEPAMonitoringDashboard()
    
    def test_record_sepa_operation(self):
        """Test recording SEPA operation metrics"""
        # Record a successful operation
        self.dashboard.record_sepa_operation(
            operation_type="batch_creation",
            execution_time_ms=2500.0,
            success=True,
            record_count=50
        )
        
        # Verify metric was recorded
        self.assertTrue(len(self.dashboard.sepa_metrics) > 0)
        
        recorded_metric = list(self.dashboard.sepa_metrics)[-1]
        self.assertEqual(recorded_metric.operation_type, "batch_creation")
        self.assertEqual(recorded_metric.execution_time_ms, 2500.0)
        self.assertTrue(recorded_metric.success)
        self.assertEqual(recorded_metric.record_count, 50)
        self.assertIsInstance(recorded_metric.memory_usage_mb, float)
    
    def test_sepa_performance_summary(self):
        """Test SEPA performance summary generation"""
        # Record multiple operations
        operations = [
            ("batch_creation", 1500.0, True, 30),
            ("batch_creation", 3000.0, True, 45),
            ("mandate_validation", 500.0, True, 10),
            ("mandate_validation", 800.0, False, 5)
        ]
        
        for op_type, time_ms, success, count in operations:
            self.dashboard.record_sepa_operation(op_type, time_ms, success, count)
        
        # Generate summary
        summary = self.dashboard.get_sepa_performance_summary(hours=1)
        
        # Validate summary structure
        self.assertIn("total_operations", summary)
        self.assertIn("overall_success_rate", summary)
        self.assertIn("total_records_processed", summary)
        self.assertIn("operations", summary)
        
        # Validate operation-specific stats
        self.assertIn("batch_creation", summary["operations"])
        self.assertIn("mandate_validation", summary["operations"])
        
        batch_stats = summary["operations"]["batch_creation"]
        self.assertEqual(batch_stats["operation_count"], 2)
        self.assertEqual(batch_stats["success_rate"], 100.0)
        self.assertEqual(batch_stats["total_records"], 75)
        
        mandate_stats = summary["operations"]["mandate_validation"]
        self.assertEqual(mandate_stats["operation_count"], 2)
        self.assertEqual(mandate_stats["success_rate"], 50.0)
    
    def test_batch_analytics(self):
        """Test batch analytics generation"""
        # Create test batch data
        test_batch = self.create_test_direct_debit_batch()
        
        # Generate analytics
        analytics = self.dashboard.get_batch_analytics(days=1)
        
        # Validate analytics structure
        self.assertIn("time_period_days", analytics)
        self.assertIn("total_batches_created", analytics)
        self.assertIn("batch_status_distribution", analytics)
        self.assertIn("daily_statistics", analytics)
        
        # Should include our test batch
        self.assertGreaterEqual(analytics["total_batches_created"], 1)
    
    def test_mandate_health_report(self):
        """Test mandate health report generation"""
        # Create test mandate
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        
        # Generate health report
        health_report = self.dashboard.get_mandate_health_report()
        
        # Validate report structure
        self.assertIn("mandate_distribution", health_report)
        self.assertIn("mandate_ages", health_report)
        self.assertIn("recent_operations", health_report)
        self.assertIn("health_problems", health_report)
        self.assertIn("overall_health", health_report)
        
        # Should include our test mandate
        self.assertIn("Active", health_report["mandate_distribution"])
        self.assertGreaterEqual(health_report["mandate_distribution"]["Active"], 1)
    
    def test_financial_metrics(self):
        """Test financial metrics calculation"""
        # Create test financial data
        test_member = self.create_test_member()
        test_invoice = self.create_test_sales_invoice(customer=test_member.customer)
        test_batch = self.create_test_direct_debit_batch()
        
        # Link invoice to batch
        batch_invoice = frappe.get_doc({
            "doctype": "Direct Debit Batch Invoice",
            "parent": test_batch.name,
            "parenttype": "Direct Debit Batch",
            "parentfield": "invoices",
            "invoice": test_invoice.name
        })
        batch_invoice.insert()
        
        # Generate financial metrics
        metrics = self.dashboard.get_financial_metrics(days=1)
        
        # Validate metrics structure
        self.assertIn("summary", metrics)
        self.assertIn("status_distribution", metrics)
        self.assertIn("daily_trends", metrics)
        self.assertIn("performance_indicators", metrics)
        
        # Should include our test data
        summary = metrics["summary"]
        self.assertGreaterEqual(summary["total_batches"], 1)
        self.assertGreaterEqual(summary["total_invoices_processed"], 1)
    
    def test_system_alerts(self):
        """Test system alerts generation"""
        # Record some failing operations to trigger alerts
        for _ in range(10):
            self.dashboard.record_sepa_operation(
                operation_type="batch_creation",
                execution_time_ms=15000.0,  # Slow operation
                success=False,
                record_count=0,
                error_message="Test failure"
            )
        
        # Generate alerts
        alerts = self.dashboard.get_system_alerts()
        
        # Should have generated some alerts
        self.assertIsInstance(alerts, list)
        
        # Check for expected alert types
        alert_types = [alert["type"] for alert in alerts]
        self.assertIn("high_failure_rate", alert_types)
    
    def test_comprehensive_report(self):
        """Test comprehensive report generation"""
        # Generate comprehensive report
        report = self.dashboard.get_comprehensive_report(days=1)
        
        # Validate report structure
        expected_sections = [
            "sepa_performance", "batch_analytics", "mandate_health",
            "financial_metrics", "system_alerts", "memory_usage",
            "recommendations"
        ]
        
        for section in expected_sections:
            self.assertIn(section, report)
        
        self.assertIn("report_period_days", report)
        self.assertIn("generated_at", report)


class TestSEPAAlertingSystem(VereningingenTestCase):
    """Test SEPA alerting system functionality"""
    
    def setUp(self):
        super().setUp()
        self.alerting_system = SEPAAlertingSystem()
    
    def test_check_metric_threshold_breach(self):
        """Test metric threshold checking"""
        # Test metric that exceeds threshold
        alerts = self.alerting_system.check_metric(
            "memory_usage_mb", 
            1500.0,  # Exceeds 1024MB threshold
            {"source": "test"}
        )
        
        # Should generate alert
        self.assertTrue(len(alerts) > 0)
        
        alert = alerts[0]
        self.assertEqual(alert.severity, AlertSeverity.WARNING)
        self.assertEqual(alert.details["metric_name"], "memory_usage_mb")
        self.assertEqual(alert.metric_value, 1500.0)
    
    def test_check_metric_no_breach(self):
        """Test metric checking with no threshold breach"""
        # Test metric that doesn't exceed threshold
        alerts = self.alerting_system.check_metric(
            "memory_usage_mb",
            500.0,  # Below 1024MB threshold
            {"source": "test"}
        )
        
        # Should not generate alert
        self.assertEqual(len(alerts), 0)
    
    def test_alert_rate_limiting(self):
        """Test alert rate limiting functionality"""
        # Generate first alert
        alerts1 = self.alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"source": "test1"}
        )
        self.assertTrue(len(alerts1) > 0)
        
        # Generate similar alert immediately after
        alerts2 = self.alerting_system.check_metric(
            "memory_usage_mb", 1600.0, {"source": "test2"}
        )
        
        # Second alert should be rate limited (not generated)
        self.assertEqual(len(alerts2), 0)
    
    def test_acknowledge_alert(self):
        """Test alert acknowledgment"""
        # Generate an alert
        alerts = self.alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"source": "test"}
        )
        self.assertTrue(len(alerts) > 0)
        
        alert = alerts[0]
        
        # Acknowledge the alert
        success = self.alerting_system.acknowledge_alert(
            alert.alert_id, "test@example.com"
        )
        
        self.assertTrue(success)
        self.assertEqual(alert.status, AlertStatus.ACKNOWLEDGED)
        self.assertEqual(alert.acknowledged_by, "test@example.com")
        self.assertIsNotNone(alert.acknowledged_at)
    
    def test_resolve_alert(self):
        """Test alert resolution"""
        # Generate an alert
        alerts = self.alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"source": "test"}
        )
        self.assertTrue(len(alerts) > 0)
        
        alert = alerts[0]
        alert_id = alert.alert_id
        
        # Resolve the alert
        success = self.alerting_system.resolve_alert(
            alert_id, "test@example.com"
        )
        
        self.assertTrue(success)
        self.assertEqual(alert.status, AlertStatus.RESOLVED)
        self.assertIsNotNone(alert.resolved_at)
        
        # Alert should be removed from active alerts
        self.assertNotIn(alert_id, self.alerting_system.active_alerts)
    
    def test_get_active_alerts(self):
        """Test getting active alerts"""
        # Generate multiple alerts of different severities
        self.alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"source": "warning"}
        )
        self.alerting_system.check_metric(
            "memory_usage_mb", 2500.0, {"source": "critical"}
        )
        
        # Get all active alerts
        all_alerts = self.alerting_system.get_active_alerts()
        self.assertGreaterEqual(len(all_alerts), 2)
        
        # Get only critical alerts
        critical_alerts = self.alerting_system.get_active_alerts(
            AlertSeverity.CRITICAL
        )
        self.assertGreaterEqual(len(critical_alerts), 1)
        
        # Verify sorting (critical first)
        if len(all_alerts) >= 2:
            self.assertEqual(all_alerts[0]["severity"], "critical")
    
    def test_alert_statistics(self):
        """Test alert statistics generation"""
        # Generate some test alerts
        alerts1 = self.alerting_system.check_metric(
            "memory_usage_mb", 1500.0, {"source": "test1"}
        )
        alerts2 = self.alerting_system.check_metric(
            "operation_failure_rate_percent", 15.0, {"source": "test2"}
        )
        
        # Get statistics
        stats = self.alerting_system.get_alert_statistics(days=1)
        
        # Validate statistics structure
        self.assertIn("total_alerts", stats)
        self.assertIn("active_alerts", stats)
        self.assertIn("severity_distribution", stats)
        self.assertIn("type_distribution", stats)
        self.assertIn("status_distribution", stats)
        
        # We should have at least 1 alert (may be rate limited)
        total_generated = len(alerts1) + len(alerts2)
        self.assertGreaterEqual(stats["total_alerts"], 1)
        self.assertLessEqual(stats["total_alerts"], total_generated)


class TestSEPAAdminReporting(VereningingenTestCase):
    """Test SEPA admin reporting functionality"""
    
    def setUp(self):
        super().setUp()
        self.report_generator = SEPAAdminReportGenerator()
    
    def test_executive_summary_generation(self):
        """Test executive summary report generation"""
        # Create some test data
        test_member = self.create_test_member()
        test_batch = self.create_test_direct_debit_batch()
        
        # Generate executive summary
        summary = self.report_generator.generate_executive_summary(days=1)
        
        # Validate summary structure
        expected_keys = [
            "report_type", "period_days", "generated_at",
            "kpis", "trends", "risk_indicators", "recommendations"
        ]
        
        for key in expected_keys:
            self.assertIn(key, summary)
        
        self.assertEqual(summary["report_type"], "executive_summary")
        self.assertEqual(summary["period_days"], 1)
        
        # Validate KPIs structure
        kpis = summary["kpis"]
        expected_kpis = [
            "total_batches_processed", "total_amount_processed",
            "average_batch_processing_time", "success_rate_percent",
            "active_mandate_count", "error_rate_percent"
        ]
        
        for kpi in expected_kpis:
            self.assertIn(kpi, kpis)
    
    def test_operational_report_generation(self):
        """Test operational report generation"""
        # Create test data
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        test_batch = self.create_test_direct_debit_batch()
        
        # Generate operational report
        report = self.report_generator.generate_operational_report(days=1)
        
        # Validate report structure
        expected_sections = [
            "report_type", "period_days", "batch_processing",
            "mandate_management", "error_analysis", "performance_metrics",
            "system_health", "action_items"
        ]
        
        for section in expected_sections:
            self.assertIn(section, report)
        
        self.assertEqual(report["report_type"], "operational_report")
        
        # Validate batch processing section
        batch_stats = report["batch_processing"]
        self.assertIn("total_batches", batch_stats)
        self.assertIn("status_distribution", batch_stats)
        
        # Validate mandate management section
        mandate_stats = report["mandate_management"]
        self.assertIn("total_mandates", mandate_stats)
        self.assertIn("active_mandates", mandate_stats)
    
    def test_financial_analysis_generation(self):
        """Test financial analysis report generation"""
        # Create test financial data
        test_member = self.create_test_member()
        test_invoice = self.create_test_sales_invoice(customer=test_member.customer)
        test_batch = self.create_test_direct_debit_batch()
        
        # Link invoice to batch
        batch_invoice = frappe.get_doc({
            "doctype": "Direct Debit Batch Invoice",
            "parent": test_batch.name,
            "parenttype": "Direct Debit Batch",
            "parentfield": "invoices",
            "invoice": test_invoice.name
        })
        batch_invoice.insert()
        
        # Generate financial analysis
        analysis = self.report_generator.generate_financial_analysis(days=1)
        
        # Validate analysis structure
        expected_sections = [
            "summary_metrics", "revenue_analysis", "collection_analysis",
            "risk_assessment", "detailed_batches", "compliance_status"
        ]
        
        for section in expected_sections:
            self.assertIn(section, analysis)
        
        self.assertEqual(analysis["report_type"], "financial_analysis")
        
        # Validate summary metrics
        summary = analysis["summary_metrics"]
        self.assertIn("total_batches", summary)
        self.assertIn("total_gross_amount", summary)
        self.assertIn("collection_rate_percent", summary)
    
    def test_mandate_lifecycle_report(self):
        """Test mandate lifecycle report generation"""
        # Create test mandate with lifecycle data
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        
        # Generate lifecycle report
        report = self.report_generator.generate_mandate_lifecycle_report()
        
        # Validate report structure
        expected_sections = [
            "total_mandates", "lifecycle_analysis", "health_scores",
            "usage_patterns", "compliance_status", "recommendations",
            "detailed_mandates"
        ]
        
        for section in expected_sections:
            self.assertIn(section, report)
        
        self.assertEqual(report["report_type"], "mandate_lifecycle_report")
        self.assertGreaterEqual(report["total_mandates"], 1)
    
    def test_performance_benchmark_report(self):
        """Test performance benchmark report generation"""
        # Generate benchmark report
        report = self.report_generator.generate_performance_benchmark_report(days=1)
        
        # Validate report structure
        expected_sections = [
            "overall_performance_score", "benchmark_results",
            "performance_trends", "improvement_recommendations"
        ]
        
        for section in expected_sections:
            self.assertIn(section, report)
        
        self.assertEqual(report["report_type"], "performance_benchmark_report")
        
        # Validate benchmark results
        benchmark_results = report["benchmark_results"]
        
        # Should have results for key metrics
        expected_metrics = [
            "batch_creation_time_ms", "batch_success_rate_percent",
            "memory_usage_mb", "error_rate_percent"
        ]
        
        for metric in expected_metrics:
            if metric in benchmark_results:
                result = benchmark_results[metric]
                self.assertIn("actual_value", result)
                self.assertIn("target", result)
                self.assertIn("status", result)
    
    def test_csv_export(self):
        """Test CSV export functionality"""
        # Create test data
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        
        # Generate mandate report
        report = self.report_generator.generate_mandate_lifecycle_report()
        
        # Export to CSV
        csv_content = self.report_generator.export_report_to_csv(report)
        
        # Validate CSV content
        self.assertIsInstance(csv_content, str)
        self.assertIn("mandate_id", csv_content)
        self.assertIn("member_name", csv_content)
        self.assertIn(test_mandate.mandate_id, csv_content)


class TestSEPAZabbixIntegration(VereningingenTestCase):
    """Test SEPA Zabbix integration functionality"""
    
    def setUp(self):
        super().setUp()
        self.zabbix_integration = SEPAZabbixIntegration()
    
    def test_get_zabbix_metrics(self):
        """Test Zabbix metrics collection"""
        # Create test data to generate metrics
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        test_batch = self.create_test_direct_debit_batch()
        
        # Get metrics
        metrics = self.zabbix_integration.get_zabbix_metrics()
        
        # Validate metrics structure
        self.assertIn("timestamp", metrics)
        self.assertIn("metrics", metrics)
        self.assertIn("host", metrics)
        self.assertIn("status", metrics)
        
        self.assertEqual(metrics["status"], "success")
        
        # Validate specific metrics
        metric_data = metrics["metrics"]
        
        # Should have key SEPA metrics
        expected_metrics = [
            "sepa.batch.count.total", "sepa.mandate.count.active",
            "sepa.performance.memory_usage", "sepa.health.overall_status"
        ]
        
        for metric_key in expected_metrics:
            if metric_key in metric_data:
                metric = metric_data[metric_key]
                self.assertIn("value", metric)
                self.assertIn("timestamp", metric)
                self.assertIn("type", metric)
                self.assertIn("name", metric)
    
    def test_batch_metrics_collection(self):
        """Test batch-specific metrics collection"""
        # Create test batch
        test_batch = self.create_test_direct_debit_batch()
        
        # Get batch metrics
        batch_metrics = self.zabbix_integration._get_batch_metrics()
        
        # Validate batch metrics
        expected_batch_metrics = [
            "sepa.batch.count.total", "sepa.batch.count.daily",
            "sepa.batch.amount.total", "sepa.batch.success_rate",
            "sepa.batch.stuck_count"
        ]
        
        for metric_key in expected_batch_metrics:
            self.assertIn(metric_key, batch_metrics)
            self.assertIsInstance(batch_metrics[metric_key], (int, float))
    
    def test_mandate_metrics_collection(self):
        """Test mandate-specific metrics collection"""
        # Create test mandate
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        
        # Get mandate metrics
        mandate_metrics = self.zabbix_integration._get_mandate_metrics()
        
        # Validate mandate metrics
        expected_mandate_metrics = [
            "sepa.mandate.count.active", "sepa.mandate.count.total",
            "sepa.mandate.validation_success_rate", "sepa.mandate.expiring_count"
        ]
        
        for metric_key in expected_mandate_metrics:
            self.assertIn(metric_key, mandate_metrics)
            self.assertIsInstance(mandate_metrics[metric_key], (int, float))
        
        # Should have at least one active mandate
        self.assertGreaterEqual(mandate_metrics["sepa.mandate.count.active"], 1)
        self.assertGreaterEqual(mandate_metrics["sepa.mandate.count.total"], 1)
    
    def test_zabbix_discovery_data(self):
        """Test Zabbix discovery data generation"""
        # Create test data for discovery
        test_batch = self.create_test_direct_debit_batch()
        
        # Get discovery data
        discovery_data = self.zabbix_integration.get_zabbix_discovery_data()
        
        # Validate discovery data structure
        self.assertIn("data", discovery_data)
        self.assertIsInstance(discovery_data["data"], list)
        
        # Should have discovery items
        if len(discovery_data["data"]) > 0:
            item = discovery_data["data"][0]
            
            # Should have expected discovery keys
            expected_keys = ["{#BATCH_NAME}", "{#BATCH_STATUS}"]
            for key in expected_keys:
                if key in item:
                    self.assertIsInstance(item[key], str)
    
    def test_zabbix_item_prototypes(self):
        """Test Zabbix item prototype generation"""
        # Test getting item prototype
        item_config = self.zabbix_integration.get_zabbix_item_prototype(
            "sepa.batch.count.total"
        )
        
        # Validate item configuration
        self.assertIsNotNone(item_config)
        self.assertIn("key", item_config)
        self.assertIn("name", item_config)
        self.assertIn("type", item_config)
        self.assertIn("description", item_config)
        
        self.assertEqual(item_config["key"], "sepa.batch.count.total")
        self.assertEqual(item_config["name"], "SEPA Total Batches")
    
    def test_zabbix_trigger_prototypes(self):
        """Test Zabbix trigger prototype generation"""
        # Get trigger prototypes
        triggers = self.zabbix_integration.get_zabbix_trigger_prototypes()
        
        # Validate triggers
        self.assertIsInstance(triggers, list)
        self.assertGreater(len(triggers), 0)
        
        # Validate trigger structure
        for trigger in triggers:
            self.assertIn("name", trigger)
            self.assertIn("expression", trigger)
            self.assertIn("priority", trigger)
            self.assertIn("description", trigger)
    
    def test_zabbix_connectivity_test(self):
        """Test Zabbix connectivity testing"""
        # Run connectivity test
        test_result = self.zabbix_integration.test_zabbix_connectivity()
        
        # Validate test result structure
        self.assertIn("success", test_result)
        self.assertIn("collection_time_ms", test_result)
        self.assertIn("metrics_collected", test_result)
        self.assertIn("timestamp", test_result)
        
        # Should be successful
        self.assertTrue(test_result["success"])
        self.assertGreater(test_result["metrics_collected"], 0)


class TestSEPAMemoryOptimization(VereningingenTestCase):
    """Test SEPA memory optimization functionality"""
    
    def setUp(self):
        super().setUp()
        self.memory_monitor = SEPAMemoryMonitor()
    
    def test_memory_snapshot(self):
        """Test memory snapshot functionality"""
        # Take memory snapshot
        snapshot = self.memory_monitor.take_snapshot("test_snapshot")
        
        # Validate snapshot structure
        self.assertIsNotNone(snapshot)
        self.assertGreater(snapshot.process_memory_mb, 0)
        self.assertGreaterEqual(snapshot.system_memory_percent, 0)
        self.assertLessEqual(snapshot.system_memory_percent, 100)
        self.assertGreater(snapshot.available_memory_mb, 0)
        self.assertGreaterEqual(snapshot.allocated_objects, 0)
    
    def test_memory_trend_analysis(self):
        """Test memory trend analysis"""
        # Take multiple snapshots
        for i in range(5):
            self.memory_monitor.take_snapshot(f"test_trend_{i}")
            time.sleep(0.1)  # Small delay between snapshots
        
        # Analyze trend
        trend = self.memory_monitor.get_memory_trend(minutes=1)
        
        # Validate trend structure
        self.assertIn("trend", trend)
        self.assertIn("snapshots", trend)
        self.assertIn("first_memory_mb", trend)
        self.assertIn("last_memory_mb", trend)
        self.assertIn("peak_memory_mb", trend)
        
        # Should have captured snapshots
        self.assertGreaterEqual(trend["snapshots"], 5)
    
    def test_memory_monitoring_context(self):
        """Test memory monitoring context manager"""
        # Use monitoring context
        with self.memory_monitor.monitor_operation("test_operation") as start_snapshot:
            # Perform some memory-consuming operation
            test_data = [i for i in range(1000)]
            
            # Validate start snapshot
            self.assertIsNotNone(start_snapshot)
            self.assertGreater(start_snapshot.process_memory_mb, 0)
        
        # Context manager should have logged the operation
        # (In a real test, we'd check logs)
    
    def test_memory_cleanup(self):
        """Test memory cleanup functionality"""
        # Take snapshot before cleanup
        before_snapshot = self.memory_monitor.take_snapshot("before_cleanup")
        
        # Force cleanup
        self.memory_monitor.force_cleanup()
        
        # Take snapshot after cleanup
        after_snapshot = self.memory_monitor.take_snapshot("after_cleanup")
        
        # Memory usage should be recorded
        self.assertGreater(before_snapshot.process_memory_mb, 0)
        self.assertGreater(after_snapshot.process_memory_mb, 0)


class TestSEPAWeek4Integration(VereningingenTestCase):
    """Test integration between Week 4 components"""
    
    def test_dashboard_alerting_integration(self):
        """Test integration between dashboard and alerting system"""
        # Get dashboard and alerting instances
        dashboard = get_dashboard_instance()
        alerting = get_alerting_system()
        
        # Record operation that should trigger alert
        dashboard.record_sepa_operation(
            operation_type="batch_creation",
            execution_time_ms=35000.0,  # Should trigger slow operation alert
            success=False,
            record_count=0,
            error_message="Test integration failure"
        )
        
        # Check if alerting system would detect this
        alerts = alerting.check_metric(
            "batch_creation_time_ms",
            35000.0,
            {"source": "integration_test"}
        )
        
        # Should generate alert
        self.assertTrue(len(alerts) > 0)
    
    def test_reporting_dashboard_integration(self):
        """Test integration between reporting and dashboard"""
        # Create test data
        test_member = self.create_test_member()
        test_batch = self.create_test_direct_debit_batch()
        
        # Generate dashboard data
        dashboard = get_dashboard_instance()
        dashboard_data = dashboard.get_comprehensive_report(days=1)
        
        # Generate admin report
        report_generator = SEPAAdminReportGenerator()
        admin_report = report_generator.generate_executive_summary(days=1)
        
        # Both should have consistent data
        self.assertIn("sepa_performance", dashboard_data)
        self.assertIn("kpis", admin_report)
        
        # Both should show the test batch
        self.assertGreaterEqual(admin_report["kpis"]["total_batches_processed"], 1)
    
    def test_zabbix_dashboard_integration(self):
        """Test integration between Zabbix and dashboard"""
        # Create test data
        test_member = self.create_test_member()
        test_mandate = self.create_test_sepa_mandate(member=test_member.name)
        
        # Get dashboard metrics
        dashboard = get_dashboard_instance()
        dashboard_report = dashboard.get_comprehensive_report(days=1)
        
        # Get Zabbix metrics
        zabbix = SEPAZabbixIntegration()
        zabbix_metrics = zabbix.get_zabbix_metrics()
        
        # Both should show consistent mandate counts
        mandate_health = dashboard_report.get("mandate_health", {})
        zabbix_data = zabbix_metrics.get("metrics", {})
        
        if "mandate_distribution" in mandate_health and "sepa.mandate.count.active" in zabbix_data:
            dashboard_active = mandate_health["mandate_distribution"].get("Active", 0)
            zabbix_active = zabbix_data["sepa.mandate.count.active"]["value"]
            
            # Should be consistent (allowing for timing differences)
            self.assertEqual(dashboard_active, zabbix_active)


if __name__ == "__main__":
    # Run the test suite
    unittest.main()