#!/usr/bin/env python3
"""
Performance testing for Phase 1 monitoring implementation
"""

import json
import time

import frappe
from frappe.utils import now


@frappe.whitelist()
def test_audit_log_creation_performance():
    """Test performance impact of audit log creation"""
    try:
        from verenigingen.doctype.sepa_audit_log.sepa_audit_log import SEPAAuditLog

        # Test batch creation performance
        batch_size = 10
        start_time = time.time()

        created_logs = []
        for i in range(batch_size):
            log = SEPAAuditLog.log_sepa_event(
                process_type="Performance Test",
                reference_doc=None,
                action=f"performance_test_{i}",
                details={"batch_index": i, "test_type": "performance"},
            )
            if log:
                created_logs.append(log.name)

        end_time = time.time()
        duration = end_time - start_time

        return {
            "status": "success",
            "message": f"Created {len(created_logs)} audit logs in {duration:.3f} seconds",
            "batch_size": batch_size,
            "duration_seconds": round(duration, 3),
            "logs_per_second": round(batch_size / duration, 2) if duration > 0 else "instant",
            "avg_time_per_log": round(duration / batch_size, 4) if batch_size > 0 else 0,
            "created_logs": created_logs[:3],  # Show first 3 for verification
        }

    except Exception as e:
        return {"status": "error", "message": f"Performance test failed: {str(e)}"}


@frappe.whitelist()
def test_alert_manager_performance():
    """Test performance of alert manager checks"""
    try:
        from verenigingen.utils.alert_manager import AlertManager

        alert_manager = AlertManager()
        results = {}

        # Test error rate check performance
        start_time = time.time()
        alert_manager.check_error_rate_alert()
        error_check_time = time.time() - start_time
        results["error_rate_check_time"] = round(error_check_time, 4)

        # Test SEPA compliance check performance
        start_time = time.time()
        alert_manager.check_sepa_compliance_alert()
        sepa_check_time = time.time() - start_time
        results["sepa_compliance_check_time"] = round(sepa_check_time, 4)

        # Test daily report generation performance (without sending email)
        start_time = time.time()
        try:
            # Generate stats without sending email
            daily_stats = {
                "errors_24h": frappe.db.count(
                    "Error Log", {"creation": (">=", frappe.utils.add_to_date(now(), days=-1))}
                ),
                "members_created": frappe.db.count(
                    "Member", {"creation": (">=", frappe.utils.add_to_date(now(), days=-1))}
                ),
                "invoices_generated": frappe.db.count(
                    "Sales Invoice",
                    {"creation": (">=", frappe.utils.add_to_date(now(), days=-1)), "docstatus": 1},
                ),
            }
            daily_report_time = time.time() - start_time
            results["daily_report_generation_time"] = round(daily_report_time, 4)
            results["daily_stats"] = daily_stats
        except Exception as e:
            results["daily_report_error"] = str(e)

        total_time = (
            results.get("error_rate_check_time", 0)
            + results.get("sepa_compliance_check_time", 0)
            + results.get("daily_report_generation_time", 0)
        )
        results["total_monitoring_time"] = round(total_time, 4)

        return {
            "status": "success",
            "message": f"Alert manager performance test completed in {total_time:.4f} seconds",
            "results": results,
        }

    except Exception as e:
        return {"status": "error", "message": f"Alert manager performance test failed: {str(e)}"}


@frappe.whitelist()
def test_database_query_performance():
    """Test database query performance impact"""
    try:
        results = {}

        # Test 1: Count queries performance
        start_time = time.time()

        queries = [
            ("Error Log count", lambda: frappe.db.count("Error Log")),
            ("SEPA Audit Log count", lambda: frappe.db.count("SEPA Audit Log")),
            ("Member count", lambda: frappe.db.count("Member")),
            ("Sales Invoice count", lambda: frappe.db.count("Sales Invoice")),
        ]

        for query_name, query_func in queries:
            query_start = time.time()
            count = query_func()
            query_time = time.time() - query_start
            results[f"{query_name.lower().replace(' ', '_')}"] = {
                "count": count,
                "time_seconds": round(query_time, 4),
            }

        total_query_time = time.time() - start_time
        results["total_query_time"] = round(total_query_time, 4)

        # Test 2: Complex query performance (monitoring typical queries)
        start_time = time.time()

        # Typical monitoring query: recent errors
        recent_errors = frappe.db.sql(
            """
            SELECT COUNT(*) as count
            FROM `tabError Log`
            WHERE creation >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
        """,
            as_dict=True,
        )

        complex_query_time = time.time() - start_time
        results["complex_query_time"] = round(complex_query_time, 4)
        results["recent_errors_found"] = recent_errors[0]["count"] if recent_errors else 0

        return {
            "status": "success",
            "message": f"Database query performance test completed",
            "results": results,
        }

    except Exception as e:
        return {"status": "error", "message": f"Database performance test failed: {str(e)}"}


@frappe.whitelist()
def test_monitoring_overhead():
    """Test overall monitoring system overhead"""
    try:
        from verenigingen.utils.alert_manager import run_daily_checks, run_hourly_checks

        results = {}

        # Test hourly check overhead
        start_time = time.time()
        run_hourly_checks()
        hourly_time = time.time() - start_time
        results["hourly_check_time"] = round(hourly_time, 4)

        # Test daily check overhead
        start_time = time.time()
        run_daily_checks()
        daily_time = time.time() - start_time
        results["daily_check_time"] = round(daily_time, 4)

        # Estimate daily overhead (24 hourly + 1 daily)
        estimated_daily_overhead = (hourly_time * 24) + daily_time
        results["estimated_daily_overhead"] = round(estimated_daily_overhead, 4)

        # Performance assessment
        if hourly_time < 1.0:
            results["hourly_performance"] = "EXCELLENT"
        elif hourly_time < 5.0:
            results["hourly_performance"] = "GOOD"
        else:
            results["hourly_performance"] = "NEEDS_OPTIMIZATION"

        if daily_time < 5.0:
            results["daily_performance"] = "EXCELLENT"
        elif daily_time < 15.0:
            results["daily_performance"] = "GOOD"
        else:
            results["daily_performance"] = "NEEDS_OPTIMIZATION"

        return {"status": "success", "message": f"Monitoring overhead test completed", "results": results}

    except Exception as e:
        return {"status": "error", "message": f"Monitoring overhead test failed: {str(e)}"}


@frappe.whitelist()
def run_all_performance_tests():
    """Run all performance tests for monitoring implementation"""
    results = {}

    # Test 1: Audit log creation performance
    results["audit_log_performance"] = test_audit_log_creation_performance()

    # Test 2: Alert manager performance
    results["alert_manager_performance"] = test_alert_manager_performance()

    # Test 3: Database query performance
    results["database_performance"] = test_database_query_performance()

    # Test 4: Overall monitoring overhead
    results["monitoring_overhead"] = test_monitoring_overhead()

    # Summary
    success_count = sum(1 for result in results.values() if result["status"] == "success")
    total_count = len(results)

    # Performance summary
    performance_summary = {
        "audit_logs_per_second": results.get("audit_log_performance", {}).get("logs_per_second", "N/A"),
        "total_monitoring_time": results.get("alert_manager_performance", {})
        .get("results", {})
        .get("total_monitoring_time", "N/A"),
        "estimated_daily_overhead": results.get("monitoring_overhead", {})
        .get("results", {})
        .get("estimated_daily_overhead", "N/A"),
    }

    return {
        "status": "completed",
        "message": f"All performance tests completed: {success_count}/{total_count} successful",
        "success_rate": f"{(success_count/total_count)*100:.1f}%",
        "performance_summary": performance_summary,
        "results": results,
    }
