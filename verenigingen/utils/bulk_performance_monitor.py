"""
Bulk Operations Performance Monitoring
======================================

This module provides performance monitoring and alerting for bulk account creation
operations, tracking key metrics like processing times, failure rates, and resource usage.

Author: Verenigingen Development Team
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


def collect_performance_metrics() -> Dict:
    """
    Collect performance metrics for bulk operations.

    Returns:
        dict: Performance metrics and analysis
    """
    try:
        # Get recent bulk operations (last 7 days)
        seven_days_ago = now_datetime() - timedelta(days=7)

        trackers = frappe.get_all(
            "Bulk Operation Tracker",
            filters={"creation": [">=", seven_days_ago], "operation_type": "Account Creation"},
            fields=[
                "name",
                "total_records",
                "successful_records",
                "failed_records",
                "started_at",
                "completed_at",
                "processing_rate_per_minute",
                "status",
                "current_batch",
                "total_batches",
            ],
            order_by="creation desc",
        )

        if not trackers:
            return {"success": True, "message": "No recent bulk operations found", "metrics": {}}

        # Calculate aggregate metrics
        metrics = {
            "total_operations": len(trackers),
            "total_records_processed": sum(t.get("total_records", 0) for t in trackers),
            "total_successful": sum(t.get("successful_records", 0) for t in trackers),
            "total_failed": sum(t.get("failed_records", 0) for t in trackers),
            "completed_operations": len([t for t in trackers if t.get("status") == "Completed"]),
            "failed_operations": len([t for t in trackers if t.get("status") == "Failed"]),
            "in_progress_operations": len([t for t in trackers if t.get("status") == "Processing"]),
            "average_processing_rate": 0,
            "average_completion_time_hours": 0,
            "success_rate_percentage": 0,
            "operation_success_rate": 0,
        }

        # Calculate success rates
        if metrics["total_records_processed"] > 0:
            metrics["success_rate_percentage"] = flt(
                (metrics["total_successful"] / metrics["total_records_processed"]) * 100, 2
            )

        if metrics["total_operations"] > 0:
            metrics["operation_success_rate"] = flt(
                (metrics["completed_operations"] / metrics["total_operations"]) * 100, 2
            )

        # Calculate processing rates and completion times for completed operations
        completed_trackers = [
            t
            for t in trackers
            if t.get("status") == "Completed" and t.get("started_at") and t.get("completed_at")
        ]

        if completed_trackers:
            # Average processing rate
            rates = [
                t.get("processing_rate_per_minute", 0)
                for t in completed_trackers
                if t.get("processing_rate_per_minute", 0) > 0
            ]
            if rates:
                metrics["average_processing_rate"] = flt(sum(rates) / len(rates), 2)

            # Average completion time
            completion_times = []
            for t in completed_trackers:
                try:
                    start = frappe.utils.get_datetime(t["started_at"])
                    end = frappe.utils.get_datetime(t["completed_at"])
                    duration_hours = (end - start).total_seconds() / 3600
                    completion_times.append(duration_hours)
                except:
                    continue

            if completion_times:
                metrics["average_completion_time_hours"] = flt(
                    sum(completion_times) / len(completion_times), 2
                )

        # Add recent operation details
        metrics["recent_operations"] = []
        for tracker in trackers[:5]:  # Last 5 operations
            operation_detail = {
                "name": tracker.get("name"),
                "records": tracker.get("total_records", 0),
                "successful": tracker.get("successful_records", 0),
                "failed": tracker.get("failed_records", 0),
                "status": tracker.get("status"),
                "progress_percentage": 0,
            }

            if tracker.get("total_records", 0) > 0:
                processed = tracker.get("successful_records", 0) + tracker.get("failed_records", 0)
                operation_detail["progress_percentage"] = flt((processed / tracker["total_records"]) * 100, 1)

            metrics["recent_operations"].append(operation_detail)

        return {"success": True, "metrics": metrics}

    except Exception as e:
        frappe.logger().error(f"Failed to collect performance metrics: {str(e)}")
        return {"success": False, "error": str(e)}


def check_performance_thresholds() -> Dict:
    """
    Check if performance metrics exceed configured thresholds and create alerts.

    Returns:
        dict: Alert information
    """
    try:
        metrics_result = collect_performance_metrics()
        if not metrics_result.get("success"):
            return metrics_result

        metrics = metrics_result.get("metrics", {})
        alerts = []

        # Define performance thresholds
        thresholds = {
            "min_success_rate": 95.0,  # 95% success rate
            "max_completion_time_hours": 6.0,  # 6 hours max
            "min_processing_rate": 15.0,  # 15 records per minute
            "max_failure_rate": 5.0,  # 5% failure rate
        }

        # Check success rate
        success_rate = metrics.get("success_rate_percentage", 0)
        if success_rate > 0 and success_rate < thresholds["min_success_rate"]:
            alerts.append(
                {
                    "type": "low_success_rate",
                    "message": f"Bulk operation success rate ({success_rate}%) below threshold ({thresholds['min_success_rate']}%)",
                    "severity": "warning",
                    "metric": "success_rate_percentage",
                    "value": success_rate,
                    "threshold": thresholds["min_success_rate"],
                }
            )

        # Check completion time
        completion_time = metrics.get("average_completion_time_hours", 0)
        if completion_time > thresholds["max_completion_time_hours"]:
            alerts.append(
                {
                    "type": "slow_completion",
                    "message": f"Average completion time ({completion_time:.1f}h) exceeds threshold ({thresholds['max_completion_time_hours']}h)",
                    "severity": "warning",
                    "metric": "average_completion_time_hours",
                    "value": completion_time,
                    "threshold": thresholds["max_completion_time_hours"],
                }
            )

        # Check processing rate
        processing_rate = metrics.get("average_processing_rate", 0)
        if processing_rate > 0 and processing_rate < thresholds["min_processing_rate"]:
            alerts.append(
                {
                    "type": "slow_processing",
                    "message": f"Processing rate ({processing_rate:.1f}/min) below threshold ({thresholds['min_processing_rate']}/min)",
                    "severity": "info",
                    "metric": "average_processing_rate",
                    "value": processing_rate,
                    "threshold": thresholds["min_processing_rate"],
                }
            )

        # Check for stuck operations
        stuck_operations = [
            op
            for op in metrics.get("recent_operations", [])
            if op.get("status") == "Processing" and op.get("progress_percentage", 0) == 0
        ]

        if stuck_operations:
            alerts.append(
                {
                    "type": "stuck_operations",
                    "message": f"{len(stuck_operations)} operations appear stuck with no progress",
                    "severity": "error",
                    "stuck_operations": stuck_operations,
                }
            )

        # Log alerts
        for alert in alerts:
            if alert["severity"] == "error":
                frappe.log_error(alert["message"], "Bulk Operations Performance Alert")
            elif alert["severity"] == "warning":
                frappe.logger().warning(f"Performance Alert: {alert['message']}")
            else:
                frappe.logger().info(f"Performance Notice: {alert['message']}")

        return {
            "success": True,
            "alerts": alerts,
            "metrics_summary": {
                "total_operations": metrics.get("total_operations", 0),
                "success_rate": success_rate,
                "completion_time": completion_time,
                "processing_rate": processing_rate,
            },
        }

    except Exception as e:
        frappe.logger().error(f"Performance threshold check failed: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def get_performance_dashboard_data():
    """Get performance data for admin dashboard display."""
    if not frappe.has_permission("Bulk Operation Tracker", "read"):
        frappe.throw(_("Insufficient permissions"))

    try:
        # Get metrics
        metrics_result = collect_performance_metrics()

        # Get current alerts
        alerts_result = check_performance_thresholds()

        # Get queue status from bulk_queue_config
        from verenigingen.utils.bulk_queue_config import get_queue_status

        queue_status = get_queue_status()

        return {
            "success": True,
            "performance_metrics": metrics_result.get("metrics", {}),
            "alerts": alerts_result.get("alerts", []),
            "queue_status": queue_status.get("bulk", {}),
            "last_updated": now_datetime().isoformat(),
        }

    except Exception as e:
        frappe.logger().error(f"Failed to get dashboard data: {str(e)}")
        return {"success": False, "error": str(e)}


def run_performance_monitoring():
    """
    Scheduled function to run performance monitoring checks.

    This function is called periodically to check performance thresholds
    and generate alerts for administrators.
    """
    try:
        frappe.logger().info("Starting bulk operations performance monitoring")

        result = check_performance_thresholds()

        if result.get("success"):
            alert_count = len(result.get("alerts", []))
            if alert_count > 0:
                frappe.logger().warning(f"Performance monitoring found {alert_count} alerts")
            else:
                frappe.logger().info("Performance monitoring: All metrics within thresholds")
        else:
            frappe.logger().error(f"Performance monitoring failed: {result.get('error')}")

        return result

    except Exception as e:
        frappe.log_error(f"Performance monitoring error: {str(e)}", "Performance Monitoring Error")
        return {"success": False, "error": str(e)}
