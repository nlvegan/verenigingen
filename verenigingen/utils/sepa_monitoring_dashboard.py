"""
SEPA-Specific Monitoring Dashboard

Week 4 Implementation: Advanced monitoring dashboard specifically designed for
SEPA batch operations, mandate management, and financial transaction monitoring.

This extends the general performance dashboard with SEPA-specific metrics,
business logic monitoring, and operational insights.
"""

import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, now_datetime

from verenigingen.utils.error_handling import log_error
from verenigingen.utils.performance_dashboard import PerformanceMetrics
from verenigingen.utils.sepa_memory_optimizer import SEPAMemoryMonitor


@dataclass
class SEPAOperationMetric:
    """Metric for SEPA operations"""

    operation_type: str
    execution_time_ms: float
    success: bool
    record_count: int
    memory_usage_mb: float
    error_message: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = get_datetime()


class SEPAMonitoringDashboard:
    """
    Enhanced monitoring dashboard specifically for SEPA operations

    Provides detailed insights into batch processing, mandate management,
    financial operations, and business metrics.
    """

    def __init__(self):
        self.memory_monitor = SEPAMemoryMonitor()
        self.performance_metrics = PerformanceMetrics()
        self.sepa_metrics = deque(maxlen=1000)  # Keep last 1000 SEPA operations
        self.batch_analytics = defaultdict(list)
        self.mandate_analytics = defaultdict(int)

    def record_sepa_operation(
        self,
        operation_type: str,
        execution_time_ms: float,
        success: bool,
        record_count: int = 0,
        error_message: str = None,
    ) -> None:
        """
        Record SEPA operation metrics

        Args:
            operation_type: Type of SEPA operation (batch_creation, mandate_validation, etc.)
            execution_time_ms: Execution time in milliseconds
            success: Whether operation succeeded
            record_count: Number of records processed
            error_message: Error message if operation failed
        """
        # Get current memory usage
        memory_snapshot = self.memory_monitor.take_snapshot()

        # Create metric record
        metric = SEPAOperationMetric(
            operation_type=operation_type,
            execution_time_ms=execution_time_ms,
            success=success,
            record_count=record_count,
            memory_usage_mb=memory_snapshot.process_memory_mb,
            error_message=error_message,
        )

        # Store metric
        self.sepa_metrics.append(metric)

        # Update analytics
        self.batch_analytics[operation_type].append(
            {
                "execution_time_ms": execution_time_ms,
                "success": success,
                "record_count": record_count,
                "timestamp": metric.timestamp,
            }
        )

        # Log slow operations
        if execution_time_ms > 5000:  # 5 seconds
            frappe.logger().warning(
                f"Slow SEPA operation: {operation_type} took {execution_time_ms:.2f}ms "
                f"for {record_count} records"
            )

        # Log errors
        if not success and error_message:
            frappe.logger().error(f"SEPA operation failed: {operation_type} - {error_message}")

    def get_sepa_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get SEPA performance summary for specified time period

        Args:
            hours: Time period in hours

        Returns:
            SEPA performance summary
        """
        cutoff_time = get_datetime() - timedelta(hours=hours)
        recent_metrics = [m for m in self.sepa_metrics if m.timestamp >= cutoff_time]

        if not recent_metrics:
            return {"message": "No SEPA operations in the specified time period", "time_period_hours": hours}

        # Group by operation type
        operation_stats = defaultdict(list)
        for metric in recent_metrics:
            operation_stats[metric.operation_type].append(metric)

        summary = {
            "total_operations": len(recent_metrics),
            "time_period_hours": hours,
            "overall_success_rate": sum(1 for m in recent_metrics if m.success) / len(recent_metrics) * 100,
            "total_records_processed": sum(m.record_count for m in recent_metrics),
            "operations": {},
        }

        # Calculate stats per operation type
        for operation_type, metrics in operation_stats.items():
            execution_times = [m.execution_time_ms for m in metrics]
            record_counts = [m.record_count for m in metrics]
            success_count = sum(1 for m in metrics if m.success)

            summary["operations"][operation_type] = {
                "operation_count": len(metrics),
                "success_rate": (success_count / len(metrics)) * 100,
                "total_records": sum(record_counts),
                "avg_records_per_operation": statistics.mean(record_counts) if record_counts else 0,
                "avg_execution_time_ms": statistics.mean(execution_times),
                "min_execution_time_ms": min(execution_times),
                "max_execution_time_ms": max(execution_times),
                "p95_execution_time_ms": self._percentile(execution_times, 95),
                "throughput_records_per_second": self._calculate_throughput(metrics),
                "error_count": len(metrics) - success_count,
                "last_execution": max(m.timestamp for m in metrics).isoformat(),
            }

        return summary

    def get_batch_analytics(self, days: int = 7) -> Dict[str, Any]:
        """
        Get detailed batch processing analytics

        Args:
            days: Time period in days

        Returns:
            Batch analytics
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Get batch creation metrics
        batch_metrics = [
            m
            for m in self.sepa_metrics
            if m.operation_type == "batch_creation" and m.timestamp >= cutoff_time
        ]

        # Get actual batch data from database
        batch_data = frappe.db.sql(
            """
            SELECT
                name,
                creation,
                total_amount,
                status,
                (SELECT COUNT(*) FROM `tabDirect Debit Batch Invoice` WHERE parent = ddb.name) as invoice_count,
                batch_date,
                modified
            FROM `tabDirect Debit Batch` ddb
            WHERE creation >= %(cutoff_time)s
            ORDER BY creation DESC
        """,
            {"cutoff_time": cutoff_time},
            as_dict=True,
        )

        # Calculate analytics
        analytics = {
            "time_period_days": days,
            "total_batches_created": len(batch_data),
            "total_amount_processed": sum(flt(b.total_amount) for b in batch_data),
            "total_invoices_processed": sum(cint(b.invoice_count) for b in batch_data),
            "batch_status_distribution": defaultdict(int),
            "daily_statistics": defaultdict(
                lambda: {"batch_count": 0, "total_amount": 0.0, "invoice_count": 0}
            ),
            "performance_metrics": {},
            "error_analysis": [],
        }

        # Process batch data
        for batch in batch_data:
            # Status distribution
            analytics["batch_status_distribution"][batch.status] += 1

            # Daily statistics
            day_key = batch.creation.strftime("%Y-%m-%d")
            analytics["daily_statistics"][day_key]["batch_count"] += 1
            analytics["daily_statistics"][day_key]["total_amount"] += flt(batch.total_amount)
            analytics["daily_statistics"][day_key]["invoice_count"] += cint(batch.invoice_count)

        # Performance metrics from recorded operations
        if batch_metrics:
            execution_times = [m.execution_time_ms for m in batch_metrics]
            analytics["performance_metrics"] = {
                "avg_creation_time_ms": statistics.mean(execution_times),
                "min_creation_time_ms": min(execution_times),
                "max_creation_time_ms": max(execution_times),
                "p95_creation_time_ms": self._percentile(execution_times, 95),
                "success_rate": sum(1 for m in batch_metrics if m.success) / len(batch_metrics) * 100,
            }

            # Error analysis
            failed_operations = [m for m in batch_metrics if not m.success]
            for failed_op in failed_operations:
                analytics["error_analysis"].append(
                    {
                        "timestamp": failed_op.timestamp.isoformat(),
                        "error_message": failed_op.error_message,
                        "records_attempted": failed_op.record_count,
                    }
                )

        return analytics

    def get_mandate_health_report(self) -> Dict[str, Any]:
        """
        Get comprehensive mandate health report

        Returns:
            Mandate health analysis
        """
        # Get mandate statistics from database
        mandate_stats = frappe.db.sql(
            """
            SELECT
                status,
                COUNT(*) as count,
                AVG(DATEDIFF(NOW(), sign_date)) as avg_age_days,
                MIN(sign_date) as oldest_mandate,
                MAX(sign_date) as newest_mandate
            FROM `tabSEPA Mandate`
            WHERE docstatus = 1
            GROUP BY status
        """,
            as_dict=True,
        )

        # Get recent mandate operations
        recent_mandate_metrics = [
            m
            for m in self.sepa_metrics
            if m.operation_type in ["mandate_validation", "mandate_creation", "mandate_update"]
            and m.timestamp >= get_datetime() - timedelta(hours=24)
        ]

        # Check for problematic patterns
        problems = []

        # Analyze mandate age distribution
        active_mandates = next((s for s in mandate_stats if s.status == "Active"), None)
        if active_mandates and active_mandates.avg_age_days > 365:
            problems.append(
                {
                    "type": "old_mandates",
                    "severity": "warning",
                    "message": f"Active mandates are averaging {active_mandates.avg_age_days:.0f} days old",
                }
            )

        # Check for high failure rates in recent operations
        if recent_mandate_metrics:
            failure_rate = (
                1 - sum(1 for m in recent_mandate_metrics if m.success) / len(recent_mandate_metrics)
            ) * 100
            if failure_rate > 10:  # More than 10% failure rate
                problems.append(
                    {
                        "type": "high_failure_rate",
                        "severity": "critical",
                        "message": f"Mandate operations have {failure_rate:.1f}% failure rate in last 24 hours",
                    }
                )

        # Get inactive mandates with recent usage attempts
        inactive_with_attempts = (
            frappe.db.sql(
                """
            SELECT COUNT(DISTINCT sm.name) as count
            FROM `tabSEPA Mandate` sm
            JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.invoice IN (
                SELECT si.name FROM `tabSales Invoice` si
                JOIN `tabMember` m ON m.customer = si.customer
                WHERE m.name = sm.member
            )
            JOIN `tabDirect Debit Batch` ddb ON ddb.name = ddbi.parent
            WHERE sm.status != 'Active'
            AND ddb.creation >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """
            )[0][0]
            or 0
        )

        if inactive_with_attempts > 0:
            problems.append(
                {
                    "type": "inactive_mandate_usage",
                    "severity": "warning",
                    "message": f"{inactive_with_attempts} inactive mandates were used in recent batches",
                }
            )

        return {
            "mandate_distribution": {stat.status: stat.count for stat in mandate_stats},
            "mandate_ages": {
                stat.status: {
                    "avg_age_days": stat.avg_age_days,
                    "oldest_mandate": stat.oldest_mandate.isoformat() if stat.oldest_mandate else None,
                    "newest_mandate": stat.newest_mandate.isoformat() if stat.newest_mandate else None,
                }
                for stat in mandate_stats
            },
            "recent_operations": {
                "total_operations": len(recent_mandate_metrics),
                "success_rate": sum(1 for m in recent_mandate_metrics if m.success)
                / len(recent_mandate_metrics)
                * 100
                if recent_mandate_metrics
                else 100,
                "avg_execution_time_ms": statistics.mean(
                    [m.execution_time_ms for m in recent_mandate_metrics]
                )
                if recent_mandate_metrics
                else 0,
            },
            "health_problems": problems,
            "overall_health": "healthy"
            if not problems
            else "degraded"
            if all(p["severity"] == "warning" for p in problems)
            else "critical",
        }

    def get_financial_metrics(self, days: int = 30) -> Dict[str, Any]:
        """
        Get financial transaction metrics for SEPA operations

        Args:
            days: Time period in days

        Returns:
            Financial metrics summary
        """
        cutoff_time = get_datetime() - timedelta(days=days)

        # Get SEPA batch financial data
        financial_data = frappe.db.sql(
            """
            SELECT
                ddb.name as batch_name,
                ddb.creation,
                ddb.total_amount,
                ddb.status,
                COUNT(ddbi.invoice) as invoice_count,
                SUM(si.outstanding_amount) as total_outstanding,
                SUM(CASE WHEN si.status = 'Paid' THEN si.grand_total ELSE 0 END) as paid_amount,
                AVG(si.outstanding_amount) as avg_invoice_amount
            FROM `tabDirect Debit Batch` ddb
            LEFT JOIN `tabDirect Debit Batch Invoice` ddbi ON ddbi.parent = ddb.name
            LEFT JOIN `tabSales Invoice` si ON si.name = ddbi.invoice
            WHERE ddb.creation >= %(cutoff_time)s
            GROUP BY ddb.name
            ORDER BY ddb.creation DESC
        """,
            {"cutoff_time": cutoff_time},
            as_dict=True,
        )

        if not financial_data:
            return {
                "message": "No financial data available for the specified period",
                "time_period_days": days,
            }

        # Calculate metrics
        total_batches = len(financial_data)
        total_amount_processed = sum(flt(b.total_amount) for b in financial_data)
        total_invoices = sum(cint(b.invoice_count) for b in financial_data)
        total_outstanding = sum(flt(b.total_outstanding) for b in financial_data)
        total_paid = sum(flt(b.paid_amount) for b in financial_data)

        # Status distribution
        status_distribution = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for batch in financial_data:
            status_distribution[batch.status]["count"] += 1
            status_distribution[batch.status]["amount"] += flt(batch.total_amount)

        # Daily trends
        daily_trends = defaultdict(lambda: {"batches": 0, "amount": 0.0, "invoices": 0})
        for batch in financial_data:
            day_key = batch.creation.strftime("%Y-%m-%d")
            daily_trends[day_key]["batches"] += 1
            daily_trends[day_key]["amount"] += flt(batch.total_amount)
            daily_trends[day_key]["invoices"] += cint(batch.invoice_count)

        # Collection efficiency (paid vs processed)
        collection_rate = (total_paid / total_amount_processed * 100) if total_amount_processed > 0 else 0

        return {
            "time_period_days": days,
            "summary": {
                "total_batches": total_batches,
                "total_amount_processed": total_amount_processed,
                "total_invoices_processed": total_invoices,
                "total_outstanding": total_outstanding,
                "total_collected": total_paid,
                "collection_rate_percent": collection_rate,
                "avg_batch_amount": total_amount_processed / total_batches if total_batches > 0 else 0,
                "avg_invoice_amount": total_amount_processed / total_invoices if total_invoices > 0 else 0,
            },
            "status_distribution": dict(status_distribution),
            "daily_trends": dict(daily_trends),
            "performance_indicators": {
                "large_batch_threshold": 10000.0,  # €10,000
                "large_batches": sum(1 for b in financial_data if flt(b.total_amount) > 10000),
                "small_batch_threshold": 100.0,  # €100
                "micro_batches": sum(1 for b in financial_data if flt(b.total_amount) < 100),
                "avg_processing_days": self._calculate_avg_processing_days(financial_data),
            },
        }

    def get_system_alerts(self) -> List[Dict[str, Any]]:
        """
        Get current system alerts based on monitored metrics

        Returns:
            List of active alerts
        """
        alerts = []

        # Check recent SEPA operation failures
        recent_failures = [
            m
            for m in self.sepa_metrics
            if not m.success and m.timestamp >= get_datetime() - timedelta(hours=1)
        ]

        if len(recent_failures) > 5:
            alerts.append(
                {
                    "type": "high_failure_rate",
                    "severity": "critical",
                    "message": f"{len(recent_failures)} SEPA operations failed in the last hour",
                    "timestamp": get_datetime().isoformat(),
                    "details": {"failure_count": len(recent_failures)},
                }
            )

        # Check for slow operations
        slow_operations = [
            m
            for m in self.sepa_metrics
            if m.execution_time_ms > 10000 and m.timestamp >= get_datetime() - timedelta(hours=2)
        ]

        if slow_operations:
            alerts.append(
                {
                    "type": "slow_operations",
                    "severity": "warning",
                    "message": f"{len(slow_operations)} slow SEPA operations detected (>10s)",
                    "timestamp": get_datetime().isoformat(),
                    "details": {
                        "slow_operations": [
                            {
                                "operation": op.operation_type,
                                "time_ms": op.execution_time_ms,
                                "records": op.record_count,
                            }
                            for op in slow_operations
                        ]
                    },
                }
            )

        # Check memory usage
        current_memory = self.memory_monitor.take_snapshot()
        if current_memory.process_memory_mb > 1024:  # More than 1GB
            alerts.append(
                {
                    "type": "high_memory_usage",
                    "severity": "warning",
                    "message": f"High memory usage: {current_memory.process_memory_mb:.1f}MB",
                    "timestamp": get_datetime().isoformat(),
                    "details": {
                        "memory_mb": current_memory.process_memory_mb,
                        "system_memory_percent": current_memory.system_memory_percent,
                    },
                }
            )

        # Check for stuck batches
        stuck_batches = (
            frappe.db.sql(
                """
            SELECT COUNT(*) as count
            FROM `tabDirect Debit Batch`
            WHERE status = 'Draft'
            AND creation < DATE_SUB(NOW(), INTERVAL 2 HOUR)
        """
            )[0][0]
            or 0
        )

        if stuck_batches > 0:
            alerts.append(
                {
                    "type": "stuck_batches",
                    "severity": "warning",
                    "message": f"{stuck_batches} batches stuck in Draft status for >2 hours",
                    "timestamp": get_datetime().isoformat(),
                    "details": {"stuck_batch_count": stuck_batches},
                }
            )

        return alerts

    def get_comprehensive_report(self, days: int = 7) -> Dict[str, Any]:
        """
        Generate comprehensive SEPA monitoring report

        Args:
            days: Time period in days

        Returns:
            Comprehensive monitoring report
        """
        return {
            "report_period_days": days,
            "generated_at": get_datetime().isoformat(),
            "sepa_performance": self.get_sepa_performance_summary(hours=days * 24),
            "batch_analytics": self.get_batch_analytics(days=days),
            "mandate_health": self.get_mandate_health_report(),
            "financial_metrics": self.get_financial_metrics(days=days),
            "system_alerts": self.get_system_alerts(),
            "memory_usage": {
                "current_usage_mb": self.memory_monitor.take_snapshot().process_memory_mb,
                "usage_trend": self.memory_monitor.get_memory_trend(minutes=60),
            },
            "recommendations": self._generate_sepa_recommendations(),
        }

    def _generate_sepa_recommendations(self) -> List[str]:
        """Generate SEPA-specific recommendations based on metrics"""
        recommendations = []

        # Analyze recent performance
        recent_metrics = [m for m in self.sepa_metrics if m.timestamp >= get_datetime() - timedelta(hours=24)]

        if not recent_metrics:
            recommendations.append("No recent SEPA activity detected. Verify system is processing normally.")
            return recommendations

        # Check for slow batch operations
        slow_batches = [
            m for m in recent_metrics if m.operation_type == "batch_creation" and m.execution_time_ms > 5000
        ]
        if slow_batches:
            avg_slow_time = statistics.mean([m.execution_time_ms for m in slow_batches])
            recommendations.append(
                f"Batch creation is slow (avg {avg_slow_time:.0f}ms). Consider optimizing database queries or increasing page sizes."
            )

        # Check error patterns
        failed_operations = [m for m in recent_metrics if not m.success]
        if len(failed_operations) > len(recent_metrics) * 0.05:  # More than 5% failure rate
            error_types = defaultdict(int)
            for op in failed_operations:
                if op.error_message:
                    # Categorize errors
                    if "timeout" in op.error_message.lower():
                        error_types["timeout"] += 1
                    elif "validation" in op.error_message.lower():
                        error_types["validation"] += 1
                    elif "database" in op.error_message.lower():
                        error_types["database"] += 1
                    else:
                        error_types["other"] += 1

            for error_type, count in error_types.items():
                recommendations.append(
                    f"High {error_type} error rate: {count} occurrences. Investigate and implement specific fixes."
                )

        # Memory optimization recommendations
        current_memory = self.memory_monitor.take_snapshot()
        if current_memory.process_memory_mb > 512:
            recommendations.append(
                f"Memory usage is elevated ({current_memory.process_memory_mb:.1f}MB). "
                "Consider enabling adaptive pagination and more frequent cleanup."
            )

        # Mandate health recommendations
        inactive_mandates = frappe.db.count("SEPA Mandate", {"status": ["!=", "Active"]})
        total_mandates = frappe.db.count("SEPA Mandate")
        if total_mandates > 0 and inactive_mandates / total_mandates > 0.2:  # More than 20% inactive
            recommendations.append(
                f"{inactive_mandates} of {total_mandates} mandates are inactive. "
                "Consider implementing mandate renewal workflows."
            )

        return recommendations or ["SEPA system performance is optimal. Continue regular monitoring."]

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of a dataset"""
        if not data:
            return 0.0

        sorted_data = sorted(data)
        index = (percentile / 100) * (len(sorted_data) - 1)

        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index % 1)

    def _calculate_throughput(self, metrics: List[SEPAOperationMetric]) -> float:
        """Calculate throughput in records per second"""
        if not metrics:
            return 0.0

        total_records = sum(m.record_count for m in metrics)
        total_time_seconds = sum(m.execution_time_ms for m in metrics) / 1000

        return total_records / total_time_seconds if total_time_seconds > 0 else 0.0

    def _calculate_avg_processing_days(self, financial_data: List[Dict[str, Any]]) -> float:
        """Calculate average processing days for batches"""
        if not financial_data:
            return 0.0

        processing_days = []
        for batch in financial_data:
            # Calculate days from creation to current date (simplified)
            creation_date = batch.creation.date() if hasattr(batch.creation, "date") else batch.creation
            current_date = get_datetime().date()
            days_diff = (current_date - creation_date).days
            processing_days.append(days_diff)

        return statistics.mean(processing_days) if processing_days else 0.0


# Global instance
_sepa_dashboard = SEPAMonitoringDashboard()


# API Functions


@frappe.whitelist()
def get_sepa_dashboard_data(days: int = 7) -> Dict[str, Any]:
    """
    Get SEPA dashboard data

    Args:
        days: Time period in days

    Returns:
        Dashboard data
    """
    return _sepa_dashboard.get_comprehensive_report(days=int(days))


@frappe.whitelist()
def get_sepa_performance_metrics(hours: int = 24) -> Dict[str, Any]:
    """
    Get SEPA performance metrics

    Args:
        hours: Time period in hours

    Returns:
        Performance metrics
    """
    return _sepa_dashboard.get_sepa_performance_summary(hours=int(hours))


@frappe.whitelist()
def get_batch_analytics(days: int = 7) -> Dict[str, Any]:
    """
    Get batch processing analytics

    Args:
        days: Time period in days

    Returns:
        Batch analytics
    """
    return _sepa_dashboard.get_batch_analytics(days=int(days))


@frappe.whitelist()
def get_mandate_health_report() -> Dict[str, Any]:
    """
    Get mandate health report

    Returns:
        Mandate health analysis
    """
    return _sepa_dashboard.get_mandate_health_report()


@frappe.whitelist()
def get_financial_metrics(days: int = 30) -> Dict[str, Any]:
    """
    Get financial metrics

    Args:
        days: Time period in days

    Returns:
        Financial metrics
    """
    return _sepa_dashboard.get_financial_metrics(days=int(days))


@frappe.whitelist()
def get_system_alerts() -> List[Dict[str, Any]]:
    """
    Get current system alerts

    Returns:
        List of active alerts
    """
    return _sepa_dashboard.get_system_alerts()


@frappe.whitelist()
def record_sepa_operation(
    operation_type: str,
    execution_time_ms: float,
    success: bool = True,
    record_count: int = 0,
    error_message: str = None,
) -> Dict[str, Any]:
    """
    Record SEPA operation for monitoring

    Args:
        operation_type: Type of operation
        execution_time_ms: Execution time in milliseconds
        success: Whether operation succeeded
        record_count: Number of records processed
        error_message: Error message if failed

    Returns:
        Success confirmation
    """
    try:
        _sepa_dashboard.record_sepa_operation(
            operation_type=operation_type,
            execution_time_ms=float(execution_time_ms),
            success=bool(success),
            record_count=int(record_count),
            error_message=error_message,
        )

        return {"success": True, "message": "Operation recorded successfully"}

    except Exception as e:
        log_error(
            e,
            context={"operation_type": operation_type, "execution_time_ms": execution_time_ms},
            module="sepa_monitoring_dashboard",
        )

        return {"success": False, "error": str(e)}


# Helper function for integration with existing SEPA operations
def get_dashboard_instance() -> SEPAMonitoringDashboard:
    """Get the global dashboard instance for direct integration"""
    return _sepa_dashboard
