"""
Bulk Operations Performance Report
==================================

Comprehensive performance analysis report for bulk account creation operations.
Provides administrators with detailed metrics, trends, and insights for optimizing
large-scale member import processes.
"""

from datetime import datetime, timedelta
from typing import Dict, List

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


def execute(filters=None):
    """Generate bulk operations performance report."""
    columns = get_columns()
    data = get_data(filters)
    summary = get_summary(data)

    return columns, data, None, None, summary


def get_columns():
    """Define report columns."""
    return [
        {
            "fieldname": "name",
            "label": _("Operation ID"),
            "fieldtype": "Link",
            "options": "Bulk Operation Tracker",
            "width": 150,
        },
        {"fieldname": "operation_type", "label": _("Type"), "fieldtype": "Data", "width": 130},
        {"fieldname": "started_at", "label": _("Started"), "fieldtype": "Datetime", "width": 150},
        {"fieldname": "completed_at", "label": _("Completed"), "fieldtype": "Datetime", "width": 150},
        {
            "fieldname": "duration_hours",
            "label": _("Duration (Hours)"),
            "fieldtype": "Float",
            "width": 120,
            "precision": 2,
        },
        {"fieldname": "total_records", "label": _("Total Records"), "fieldtype": "Int", "width": 110},
        {"fieldname": "successful_records", "label": _("Successful"), "fieldtype": "Int", "width": 100},
        {"fieldname": "failed_records", "label": _("Failed"), "fieldtype": "Int", "width": 80},
        {"fieldname": "success_rate", "label": _("Success Rate (%)"), "fieldtype": "Percent", "width": 120},
        {
            "fieldname": "processing_rate_per_minute",
            "label": _("Rate/Min"),
            "fieldtype": "Float",
            "width": 100,
            "precision": 1,
        },
        {"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
        {"fieldname": "retry_queue_count", "label": _("Retry Queue"), "fieldtype": "Int", "width": 100},
    ]


def get_data(filters):
    """Get bulk operations data with performance metrics."""

    # Build date filter
    date_condition = ""
    if filters and filters.get("from_date"):
        date_condition += f" AND started_at >= '{filters['from_date']}'"
    if filters and filters.get("to_date"):
        date_condition += f" AND started_at <= '{filters['to_date']}'"

    # Get bulk operation trackers
    trackers = frappe.db.sql(
        f"""
        SELECT
            name, operation_type, total_records, successful_records, failed_records,
            started_at, completed_at, processing_rate_per_minute, status,
            current_batch, total_batches, retry_queue
        FROM `tabBulk Operation Tracker`
        WHERE operation_type = 'Account Creation'
        {date_condition}
        ORDER BY started_at DESC
        LIMIT 100
        """,
        as_dict=True,
    )

    data = []
    for tracker in trackers:
        # Calculate duration
        duration_hours = 0
        if tracker.started_at and tracker.completed_at:
            duration = tracker.completed_at - tracker.started_at
            duration_hours = duration.total_seconds() / 3600

        # Calculate success rate
        success_rate = 0
        if tracker.total_records > 0:
            success_rate = (tracker.successful_records / tracker.total_records) * 100

        # Count retry queue items
        retry_queue_count = 0
        if tracker.retry_queue:
            try:
                import json

                retry_items = json.loads(tracker.retry_queue)
                retry_queue_count = len(retry_items) if isinstance(retry_items, list) else 0
            except:
                pass

        data.append(
            {
                "name": tracker.name,
                "operation_type": tracker.operation_type,
                "started_at": tracker.started_at,
                "completed_at": tracker.completed_at,
                "duration_hours": flt(duration_hours, 2),
                "total_records": tracker.total_records or 0,
                "successful_records": tracker.successful_records or 0,
                "failed_records": tracker.failed_records or 0,
                "success_rate": flt(success_rate, 2),
                "processing_rate_per_minute": tracker.processing_rate_per_minute or 0,
                "status": tracker.status,
                "retry_queue_count": retry_queue_count,
            }
        )

    return data


def get_summary(data):
    """Generate performance summary statistics."""
    if not data:
        return []

    # Calculate aggregate metrics
    total_operations = len(data)
    completed_operations = len([d for d in data if d["status"] == "Completed"])

    total_records = sum(d["total_records"] for d in data)
    total_successful = sum(d["successful_records"] for d in data)
    total_failed = sum(d["failed_records"] for d in data)

    overall_success_rate = (total_successful / total_records * 100) if total_records > 0 else 0
    operation_success_rate = (completed_operations / total_operations * 100) if total_operations > 0 else 0

    # Calculate averages for completed operations
    completed_data = [d for d in data if d["status"] == "Completed" and d["duration_hours"] > 0]
    avg_duration = (
        sum(d["duration_hours"] for d in completed_data) / len(completed_data) if completed_data else 0
    )
    avg_processing_rate = (
        sum(d["processing_rate_per_minute"] for d in completed_data) / len(completed_data)
        if completed_data
        else 0
    )

    total_retry_queue = sum(d["retry_queue_count"] for d in data)

    return [
        {
            "label": _("Performance Summary"),
            "value": f"{total_operations} operations | {completed_operations} completed ({operation_success_rate:.1f}%)",
            "datatype": "Data",
        },
        {
            "label": _("Record Processing"),
            "value": f"{total_successful:,}/{total_records:,} successful ({overall_success_rate:.1f}%) | {total_failed:,} failed",
            "datatype": "Data",
        },
        {
            "label": _("Average Performance"),
            "value": f"{avg_duration:.1f}h duration | {avg_processing_rate:.1f} records/min",
            "datatype": "Data",
        },
        {
            "label": _("Retry Queue"),
            "value": f"{total_retry_queue} requests pending retry",
            "datatype": "Data",
        },
    ]


def get_chart_data(filters):
    """Generate chart data for performance visualization."""
    data = get_data(filters)

    if not data:
        return None

    # Success rate over time
    dates = []
    success_rates = []

    for row in data:
        if row["started_at"] and row["success_rate"]:
            date_str = row["started_at"].strftime("%Y-%m-%d")
            dates.append(date_str)
            success_rates.append(row["success_rate"])

    return {
        "data": {"labels": dates, "datasets": [{"name": "Success Rate (%)", "values": success_rates}]},
        "type": "line",
        "height": 300,
    }


@frappe.whitelist()
def get_performance_trends():
    """Get performance trends for dashboard widgets."""

    # Get data for last 30 days
    thirty_days_ago = now_datetime() - timedelta(days=30)

    trends = frappe.db.sql(
        """
        SELECT
            DATE(started_at) as date,
            COUNT(*) as operations_count,
            SUM(successful_records) as total_successful,
            SUM(failed_records) as total_failed,
            AVG(processing_rate_per_minute) as avg_rate
        FROM `tabBulk Operation Tracker`
        WHERE started_at >= %s
        AND operation_type = 'Account Creation'
        GROUP BY DATE(started_at)
        ORDER BY date
        """,
        (thirty_days_ago,),
        as_dict=True,
    )

    return trends


@frappe.whitelist()
def get_performance_alerts():
    """Check for performance issues and return alerts."""

    # Import monitoring functions
    from verenigingen.utils.bulk_performance_monitor import check_performance_thresholds

    result = check_performance_thresholds()
    return result.get("alerts", []) if result.get("success") else []
