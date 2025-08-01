"""
Performance monitoring dashboard for Verenigingen app

This utility provides performance metrics, monitoring, and optimization insights
for the association management system.
"""

import statistics
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import get_datetime, now_datetime

from verenigingen.utils.config_manager import ConfigManager
from verenigingen.utils.error_handling import get_logger


class PerformanceMetrics:
    """Collect and manage performance metrics"""

    def __init__(self):
        self.logger = get_logger("verenigingen.performance")
        self.metrics = defaultdict(list)
        self.api_calls = deque(maxlen=1000)  # Keep last 1000 API calls
        self.slow_queries = deque(maxlen=100)  # Keep last 100 slow queries
        self.error_counts = defaultdict(int)

    def record_api_call(
        self, endpoint: str, execution_time_ms: float, success: bool, user: str = None
    ) -> None:
        """Record API call metrics"""

        call_data = {
            "endpoint": endpoint,
            "execution_time_ms": execution_time_ms,
            "success": success,
            "user": user or frappe.session.user,
            "timestamp": now_datetime(),
        }

        self.api_calls.append(call_data)
        self.metrics["api_{endpoint}_time"].append(execution_time_ms)

        # Log slow operations
        threshold = ConfigManager.get("slow_query_threshold_ms", 1000)
        if execution_time_ms > threshold:
            self.slow_queries.append(call_data)
            self.logger.warning(f"Slow API call: {endpoint} took {execution_time_ms:.2f}ms", extra=call_data)

        # Track error rates
        if not success:
            self.error_counts[endpoint] += 1

    def record_database_query(self, query_type: str, execution_time_ms: float, row_count: int = 0) -> None:
        """Record database query metrics"""

        query_data = {
            "query_type": query_type,
            "execution_time_ms": execution_time_ms,
            "row_count": row_count,
            "timestamp": now_datetime(),
        }

        self.metrics["db_{query_type}_time"].append(execution_time_ms)
        self.metrics["db_{query_type}_rows"].append(row_count)

        # Log slow queries
        threshold = ConfigManager.get("slow_query_threshold_ms", 1000)
        if execution_time_ms > threshold:
            self.slow_queries.append(query_data)

    def get_api_performance_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get API performance summary for the last N hours"""

        cutoff_time = now_datetime() - timedelta(hours=hours)
        recent_calls = [call for call in self.api_calls if call["timestamp"] > cutoff_time]

        if not recent_calls:
            return {"message": "No API calls in the specified time period"}

        # Group by endpoint
        endpoint_stats = defaultdict(list)
        for call in recent_calls:
            endpoint_stats[call["endpoint"]].append(call)

        summary = {"total_calls": len(recent_calls), "time_period_hours": hours, "endpoints": {}}

        for endpoint, calls in endpoint_stats.items():
            execution_times = [call["execution_time_ms"] for call in calls]
            success_count = sum(1 for call in calls if call["success"])

            summary["endpoints"][endpoint] = {
                "call_count": len(calls),
                "success_rate": (success_count / len(calls)) * 100,
                "avg_time_ms": statistics.mean(execution_times),
                "min_time_ms": min(execution_times),
                "max_time_ms": max(execution_times),
                "median_time_ms": statistics.median(execution_times),
                "p95_time_ms": self._percentile(execution_times, 95),
                "error_count": len(calls) - success_count,
            }

        return summary

    def get_slow_operations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the slowest operations"""

        sorted_operations = sorted(
            self.slow_queries, key=lambda x: x.get("execution_time_ms", 0), reverse=True
        )

        return list(sorted_operations)[:limit]

    def get_error_analysis(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze error patterns"""

        cutoff_time = now_datetime() - timedelta(hours=hours)
        recent_calls = [
            call for call in self.api_calls if call["timestamp"] > cutoff_time and not call["success"]
        ]

        error_analysis = {
            "total_errors": len(recent_calls),
            "error_rate": 0,
            "top_error_endpoints": {},
            "error_timeline": [],
        }

        if recent_calls:
            total_calls = len([call for call in self.api_calls if call["timestamp"] > cutoff_time])

            error_analysis["error_rate"] = (len(recent_calls) / total_calls) * 100

            # Group errors by endpoint
            endpoint_errors = defaultdict(int)
            for call in recent_calls:
                endpoint_errors[call["endpoint"]] += 1

            error_analysis["top_error_endpoints"] = dict(
                sorted(endpoint_errors.items(), key=lambda x: x[1], reverse=True)[:10]
            )

        return error_analysis

    def _percentile(self, data: List[float], percentile: int) -> float:
        """Calculate percentile of a dataset"""
        if not data:
            return 0

        sorted_data = sorted(data)
        index = (percentile / 100) * (len(sorted_data) - 1)

        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index % 1)


class PerformanceDashboard:
    """Performance monitoring dashboard"""

    def __init__(self):
        self.metrics = PerformanceMetrics()
        self.logger = get_logger("verenigingen.dashboard")

    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health metrics"""

        health = {"status": "healthy", "timestamp": now_datetime().isoformat(), "checks": {}}

        # Database connectivity
        try:
            start_time = time.time()
            frappe.db.sql("SELECT 1")
            db_response_time = (time.time() - start_time) * 1000
            health["checks"]["database"] = {"status": "ok", "response_time_ms": db_response_time}
        except Exception as e:
            health["checks"]["database"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Dues schedule processing health (replaces subscription processing)
        try:
            dues_schedule_health = self._check_dues_schedule_health()
            health["checks"]["dues_schedule_processing"] = dues_schedule_health
            if dues_schedule_health["status"] != "ok":
                health["status"] = "degraded" if health["status"] == "healthy" else "critical"
        except Exception as e:
            health["checks"]["dues_schedule_processing"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Invoice generation health
        try:
            invoice_health = self._check_invoice_generation_health()
            health["checks"]["invoice_generation"] = invoice_health
            if invoice_health["status"] != "ok":
                health["status"] = "degraded" if health["status"] == "healthy" else health["status"]
        except Exception as e:
            health["checks"]["invoice_generation"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Scheduler health
        try:
            scheduler_health = self._check_scheduler_health()
            health["checks"]["scheduler"] = scheduler_health
            if scheduler_health["status"] != "ok":
                health["status"] = "critical" if scheduler_health["status"] == "critical" else "degraded"
        except Exception as e:
            health["checks"]["scheduler"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # Cache performance
        try:
            from verenigingen.utils.performance_utils import CacheManager

            # Simple cache test
            test_key = "health_check_test"
            test_value = "test_value"

            start_time = time.time()
            CacheManager.set(test_key, test_value, ttl=5)
            cached_value = CacheManager.get(test_key)
            cache_time = (time.time() - start_time) * 1000

            if cached_value == test_value:
                health["checks"]["cache"] = {"status": "ok", "response_time_ms": cache_time}
            else:
                health["checks"]["cache"] = {"status": "error", "error": "Cache verification failed"}
                health["status"] = "degraded"

            CacheManager.delete(test_key)

        except Exception as e:
            health["checks"]["cache"] = {"status": "error", "error": str(e)}
            health["status"] = "degraded"

        # API responsiveness
        api_summary = self.metrics.get_api_performance_summary(hours=1)
        if api_summary.get("endpoints"):
            avg_response_times = [endpoint["avg_time_ms"] for endpoint in api_summary["endpoints"].values()]
            overall_avg = statistics.mean(avg_response_times) if avg_response_times else 0

            health["checks"]["api_performance"] = {
                "status": "ok" if overall_avg < 1000 else "slow",
                "avg_response_time_ms": overall_avg,
                "active_endpoints": len(api_summary["endpoints"]),
            }

            if overall_avg > 2000:
                health["status"] = "degraded"
        else:
            health["checks"]["api_performance"] = {"status": "unknown", "message": "No recent API activity"}

        return health

    def get_performance_report(self, hours: int = 24) -> Dict[str, Any]:
        """Generate comprehensive performance report"""

        report = {
            "report_period_hours": hours,
            "generated_at": now_datetime().isoformat(),
            "system_health": self.get_system_health(),
            "api_performance": self.metrics.get_api_performance_summary(hours),
            "slow_operations": self.metrics.get_slow_operations(limit=10),
            "error_analysis": self.metrics.get_error_analysis(hours),
            "recommendations": [],
        }

        # Generate recommendations based on metrics
        recommendations = self._generate_recommendations(report)
        report["recommendations"] = recommendations

        return report

    def _generate_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate performance optimization recommendations"""

        recommendations = []

        # Check API performance
        api_perf = report.get("api_performance", {})
        if api_perf.get("endpoints"):
            slow_endpoints = [
                endpoint for endpoint, stats in api_perf["endpoints"].items() if stats["avg_time_ms"] > 1000
            ]

            if slow_endpoints:
                recommendations.append(
                    "Optimize slow endpoints: {', '.join(slow_endpoints)}. "
                    "Consider adding caching or optimizing database queries."
                )

        # Check error rates
        error_analysis = report.get("error_analysis", {})
        if error_analysis.get("error_rate", 0) > 5:  # More than 5% error rate
            recommendations.append(
                f"High error rate detected ({error_analysis['error_rate']:.1f}%). "
                "Review error logs and implement better error handling."
            )

        # Check slow operations
        slow_ops = report.get("slow_operations", [])
        if slow_ops:
            recommendations.append(
                "Found {len(slow_ops)} slow operations. "
                "Consider optimizing queries or adding performance monitoring."
            )

        # System health checks
        health = report.get("system_health", {})
        if health.get("status") != "healthy":
            failed_checks = [
                check for check, status in health.get("checks", {}).items() if status.get("status") != "ok"
            ]

            if failed_checks:
                recommendations.append(
                    "System health issues detected in: {', '.join(failed_checks)}. "
                    "Review system resources and dependencies."
                )

        # General recommendations
        if not recommendations:
            recommendations.extend(
                [
                    "System performance is good. Consider implementing proactive monitoring.",
                    "Add more comprehensive logging for better debugging.",
                    "Consider setting up automated performance alerts.",
                ]
            )

        return recommendations

    def get_optimization_suggestions(self) -> Dict[str, Any]:
        """Get specific optimization suggestions"""

        suggestions = {
            "caching_opportunities": [],
            "query_optimizations": [],
            "api_improvements": [],
            "monitoring_enhancements": [],
        }

        # Analyze recent API calls for caching opportunities
        recent_calls = list(self.metrics.api_calls)
        endpoint_frequency = defaultdict(int)

        for call in recent_calls:
            endpoint_frequency[call["endpoint"]] += 1

        # Suggest caching for frequently called endpoints
        frequent_endpoints = [
            endpoint
            for endpoint, count in endpoint_frequency.items()
            if count > 10  # Called more than 10 times recently
        ]

        for endpoint in frequent_endpoints:
            if "get_" in endpoint or "list_" in endpoint:
                suggestions["caching_opportunities"].append(
                    f"Add caching to {endpoint} (called {endpoint_frequency[endpoint]} times)"
                )

        # Query optimization suggestions
        slow_queries = [op for op in self.metrics.slow_queries if "db_" in op.get("query_type", "")]
        if slow_queries:
            suggestions["query_optimizations"].extend(
                [
                    "Optimize {op['query_type']} query (took {op['execution_time_ms']:.2f}ms)"
                    for op in slow_queries[:5]
                ]
            )

        # API improvement suggestions
        api_summary = self.metrics.get_api_performance_summary(hours=24)
        if api_summary.get("endpoints"):
            for endpoint, stats in api_summary["endpoints"].items():
                if stats["success_rate"] < 95:
                    suggestions["api_improvements"].append(
                        "Improve reliability of {endpoint} (success rate: {stats['success_rate']:.1f}%)"
                    )

                if stats["p95_time_ms"] > 2000:
                    suggestions["api_improvements"].append(
                        "Optimize {endpoint} performance (95th percentile: {stats['p95_time_ms']:.2f}ms)"
                    )

        # Monitoring enhancement suggestions
        suggestions["monitoring_enhancements"].extend(
            [
                "Implement automated performance alerts for slow operations",
                "Add business metrics tracking (member registrations, payments, etc.)",
                "Set up performance regression detection",
                "Implement capacity planning based on usage trends",
            ]
        )

        return suggestions

    def _check_dues_schedule_health(self) -> Dict[str, Any]:
        """Check dues schedule processing health (replaces subscription processing)"""
        try:
            # Check if dues schedule processing is working
            if not frappe.db.exists("DocType", "Membership Dues Schedule"):
                return {"status": "unknown", "message": "Membership Dues Schedule doctype not found"}

            # Get last dues schedule processing time from scheduled job logs
            last_process = frappe.db.get_value(
                "Scheduled Job Log",
                filters={"scheduled_job_type": ["like", "%dues_schedule%"]},
                fieldname="creation",
                order_by="creation desc",
            )

            if not last_process:
                return {"status": "warning", "message": "No dues schedule processing history found"}

            hours_ago = (now_datetime() - get_datetime(last_process)).total_seconds() / 3600

            # Get active dues schedules count
            active_dues_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active"})

            # Get today's membership invoices (linked to dues schedules)
            today_start = get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)
            dues_invoices_today = (
                frappe.db.sql(
                    """
                SELECT COUNT(DISTINCT si.name)
                FROM `tabSales Invoice` si
                INNER JOIN `tabMembership Dues Schedule` mds ON mds.member = si.member
                WHERE si.creation >= %s
                AND si.docstatus = 1
                AND mds.status = 'Active'
                AND si.member IS NOT NULL
            """,
                    (today_start,),
                )[0][0]
                or 0
            )

            if hours_ago > 25:  # More than 25 hours since last processing
                return {
                    "status": "critical",
                    "message": f"Dues schedule processing stopped {hours_ago:.1f} hours ago",
                    "last_processed": last_process,
                    "active_dues_schedules": active_dues_schedules,
                    "invoices_today": dues_invoices_today,
                }
            elif hours_ago > 4:  # More than 4 hours (should process daily)
                return {
                    "status": "warning",
                    "message": f"Dues schedule processing delayed {hours_ago:.1f} hours",
                    "last_processed": last_process,
                    "active_dues_schedules": active_dues_schedules,
                    "invoices_today": dues_invoices_today,
                }
            else:
                return {
                    "status": "ok",
                    "message": f"Last processed {hours_ago:.1f} hours ago",
                    "last_processed": last_process,
                    "active_dues_schedules": active_dues_schedules,
                    "invoices_today": dues_invoices_today,
                }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_invoice_generation_health(self) -> Dict[str, Any]:
        """Check invoice generation health"""
        try:
            today_start = get_datetime().replace(hour=0, minute=0, second=0, microsecond=0)

            # Count different types of invoices today
            sales_invoices_today = frappe.db.count("Sales Invoice", {"creation": [">=", today_start]})
            dues_invoices_today = (
                frappe.db.sql(
                    """
                SELECT COUNT(DISTINCT si.name)
                FROM `tabSales Invoice` si
                INNER JOIN `tabMembership Dues Schedule` mds ON mds.member = si.member
                WHERE si.creation >= %s
                AND si.docstatus = 1
                AND mds.status = 'Active'
                AND si.member IS NOT NULL
            """,
                    (today_start,),
                )[0][0]
                or 0
            )

            total_invoices_today = sales_invoices_today + frappe.db.count(
                "Purchase Invoice", {"creation": [">=", today_start]}
            )

            # Check for active dues schedules that should generate invoices
            active_dues_schedules = frappe.db.count("Membership Dues Schedule", {"status": "Active"})

            # Simple health logic
            if active_dues_schedules > 0 and dues_invoices_today == 0:
                # Check if it's early in the day (before 6 AM) - might not have processed yet
                current_hour = now_datetime().hour
                if current_hour < 6:
                    status = "ok"
                    message = f"Too early for invoicing (current hour: {current_hour})"
                else:
                    status = "warning"
                    message = f"No dues schedule invoices generated today (active schedules: {active_dues_schedules})"
            else:
                status = "ok"
                message = "Invoice generation healthy"

            return {
                "status": status,
                "message": message,
                "sales_invoices_today": sales_invoices_today,
                "dues_invoices_today": dues_invoices_today,
                "total_invoices_today": total_invoices_today,
                "active_dues_schedules": active_dues_schedules,
            }

        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_scheduler_health(self) -> Dict[str, Any]:
        """Check scheduler health for stuck jobs"""
        try:
            if not frappe.db.exists("DocType", "Scheduled Job Type"):
                return {"status": "unknown", "message": "Scheduled Job Type doctype not found"}

            # Check for stuck daily jobs
            stuck_jobs = frappe.db.sql(
                """
                SELECT COUNT(*)
                FROM `tabScheduled Job Type`
                WHERE stopped = 0
                AND frequency IN ('Daily', 'Daily Long')
                AND (last_execution IS NULL OR last_execution < DATE_SUB(NOW(), INTERVAL 25 HOUR))
            """
            )[0][0]

            # Check recent job activity
            recent_jobs = frappe.db.count(
                "Scheduled Job Log", {"modified": [">=", get_datetime() - timedelta(minutes=30)]}
            )

            if stuck_jobs > 0:
                return {
                    "status": "critical",
                    "message": f"{stuck_jobs} daily jobs haven't run in 25+ hours",
                    "stuck_jobs": stuck_jobs,
                    "recent_activity": recent_jobs,
                }
            elif recent_jobs == 0:
                return {
                    "status": "warning",
                    "message": "No scheduler activity in last 30 minutes",
                    "stuck_jobs": stuck_jobs,
                    "recent_activity": recent_jobs,
                }
            else:
                return {
                    "status": "ok",
                    "message": f"Scheduler healthy ({recent_jobs} recent jobs)",
                    "stuck_jobs": stuck_jobs,
                    "recent_activity": recent_jobs,
                }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# Global performance metrics instance
_performance_metrics = PerformanceMetrics()
_performance_dashboard = PerformanceDashboard()


# API endpoints for performance monitoring


@frappe.whitelist()
def get_performance_dashboard():
    """Get performance dashboard data"""
    return _performance_dashboard.get_performance_report(hours=24)


@frappe.whitelist()
def get_system_health():
    """Get system health check"""
    return _performance_dashboard.get_system_health()


@frappe.whitelist()
def get_optimization_suggestions():
    """Get performance optimization suggestions"""
    return _performance_dashboard.get_optimization_suggestions()


@frappe.whitelist()
def get_api_performance_summary(hours=24):
    """Get API performance summary"""
    return _performance_metrics.get_api_performance_summary(int(hours))


# Helper functions for integration with performance monitoring


def record_api_performance(endpoint: str, execution_time_ms: float, success: bool = True):
    """Record API call performance (called by decorators)"""
    _performance_metrics.record_api_call(endpoint, execution_time_ms, success)


def record_query_performance(query_type: str, execution_time_ms: float, row_count: int = 0):
    """Record database query performance"""
    _performance_metrics.record_database_query(query_type, execution_time_ms, row_count)
