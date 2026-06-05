"""
Service Metrics - Performance monitoring and metrics collection for services.

This module provides comprehensive monitoring capabilities for services including
performance metrics, health checks, and alerting mechanisms.

Classes:
    - ServiceMetrics: Individual service metrics collection
    - MetricsCollector: Centralized metrics aggregation
    - HealthMonitor: Service health monitoring
    - PerformanceProfiler: Detailed performance profiling
"""

import logging
import threading
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

import frappe
from frappe import _

from verenigingen.utils.service_error_handler import ServiceError


class ServiceMetrics:
    """Metrics collection for individual services."""

    def __init__(self, service_name: str, max_history: int = 1000, max_operations: int = 100):
        """Initialize service metrics.

        Args:
            service_name: Name of the service
            max_history: Maximum number of historical records to keep
            max_operations: Maximum number of operation types to track (prevents memory leaks)
        """
        self.service_name = service_name
        self.max_history = max_history
        self.max_operations = max_operations

        # Core metrics
        self.call_count = 0
        self.error_count = 0
        self.total_time = 0.0

        # Historical data with size limits
        self.response_times = deque(maxlen=max_history)
        self.error_history = deque(maxlen=max_history)
        self.throughput_history = deque(maxlen=max_history)

        # Detailed operation metrics with memory protection
        self.operation_metrics = {}
        self._operation_access_times = {}  # Track last access for cleanup

        self.lock = threading.Lock()
        self.start_time = time.time()
        self._last_cleanup = time.time()

    def record_operation(self, operation_name: str, duration: float, success: bool = True):
        """Record metrics for a service operation.

        Args:
            operation_name: Name of the operation
            duration: Duration in seconds
            success: Whether the operation succeeded
        """
        with self.lock:
            # Update global metrics
            self.call_count += 1
            self.total_time += duration

            if not success:
                self.error_count += 1

            # Update historical data
            self.response_times.append(duration)
            self.error_history.append(not success)

            # Update operation-specific metrics with memory protection
            current_time = time.time()
            self._operation_access_times[operation_name] = current_time

            # Initialize operation metrics if not exists
            new_operation = operation_name not in self.operation_metrics
            if new_operation:
                self.operation_metrics[operation_name] = {
                    "count": 0,
                    "errors": 0,
                    "total_time": 0.0,
                    "min_time": float("inf"),
                    "max_time": 0.0,
                }

            # Update operation metrics
            op_metrics = self.operation_metrics[operation_name]
            op_metrics["count"] += 1
            op_metrics["total_time"] += duration
            op_metrics["min_time"] = min(op_metrics["min_time"], duration)
            op_metrics["max_time"] = max(op_metrics["max_time"], duration)

            if not success:
                op_metrics["errors"] += 1

            # Enforce the operation-tracking cap after recording, so the tracked
            # set never grows past the configured maximum even when many distinct
            # operation names arrive in quick succession.
            if new_operation and len(self.operation_metrics) > self.max_operations:
                self._cleanup_old_operations()

            # Periodic cleanup to prevent memory leaks
            if current_time - self._last_cleanup > 3600:  # Cleanup every hour
                self._cleanup_old_operations()
                self._last_cleanup = current_time

    def get_summary(self) -> Dict:
        """Get summary metrics.

        Returns:
            Dictionary containing service metrics summary
        """
        with self.lock:
            uptime = time.time() - self.start_time
            avg_response_time = self.total_time / max(self.call_count, 1)
            error_rate = self.error_count / max(self.call_count, 1)
            throughput = self.call_count / max(uptime, 1)

            return {
                "service_name": self.service_name,
                "uptime": uptime,
                "call_count": self.call_count,
                "error_count": self.error_count,
                "error_rate": error_rate,
                "total_time": self.total_time,
                "average_response_time": avg_response_time,
                "throughput": throughput,
                "operations": len(self.operation_metrics),
            }

    def get_detailed_metrics(self) -> Dict:
        """Get detailed metrics including operation breakdown.

        Returns:
            Comprehensive metrics dictionary
        """
        summary = self.get_summary()

        with self.lock:
            # Calculate percentiles from recent response times
            recent_times = list(self.response_times)[-100:]  # Last 100 operations
            if recent_times:
                recent_times.sort()
                n = len(recent_times)
                percentiles = {
                    "p50": recent_times[int(n * 0.5)] if n > 0 else 0,
                    "p95": recent_times[int(n * 0.95)] if n > 0 else 0,
                    "p99": recent_times[int(n * 0.99)] if n > 0 else 0,
                }
            else:
                percentiles = {"p50": 0, "p95": 0, "p99": 0}

            # Operation breakdown
            operations = {}
            for op_name, op_data in self.operation_metrics.items():
                avg_time = op_data["total_time"] / max(op_data["count"], 1)
                op_error_rate = op_data["errors"] / max(op_data["count"], 1)

                operations[op_name] = {
                    "count": op_data["count"],
                    "errors": op_data["errors"],
                    "error_rate": op_error_rate,
                    "total_time": op_data["total_time"],
                    "average_time": avg_time,
                    "min_time": op_data["min_time"] if op_data["min_time"] != float("inf") else 0,
                    "max_time": op_data["max_time"],
                }

            return {**summary, "percentiles": percentiles, "operations": operations}

    def reset_metrics(self):
        """Reset all metrics to initial state."""
        with self.lock:
            self.call_count = 0
            self.error_count = 0
            self.total_time = 0.0
            self.response_times.clear()
            self.error_history.clear()
            self.throughput_history.clear()
            self.operation_metrics.clear()
            self._operation_access_times.clear()
            self.start_time = time.time()
            self._last_cleanup = time.time()

    def _cleanup_old_operations(self):
        """Clean up operation metrics to prevent memory leaks.

        Removes operations that haven't been accessed in the last 24 hours, and
        additionally enforces the ``max_operations`` cap by evicting the
        least-recently-used operations when the tracked set still exceeds the
        cap (e.g. when many distinct operation names are recorded in a short
        window, so the 24h idle rule never matches).
        """
        current_time = time.time()
        cleanup_threshold = 24 * 3600  # 24 hours

        operations_to_remove = [
            op_name
            for op_name, last_access in self._operation_access_times.items()
            if current_time - last_access > cleanup_threshold
        ]

        for op_name in operations_to_remove:
            self.operation_metrics.pop(op_name, None)
            self._operation_access_times.pop(op_name, None)

        # Enforce the cap via LRU eviction. This keeps the tracked operation set
        # bounded regardless of access recency. We evict down to 80% of the cap
        # so the collector stays "memory efficient" with headroom for new
        # operations rather than thrashing right at the limit.
        target = max(1, int(self.max_operations * 0.8))
        if len(self.operation_metrics) > target:
            lru_order = sorted(self._operation_access_times.items(), key=lambda item: item[1])
            excess = len(self.operation_metrics) - target
            for op_name, _ in lru_order[:excess]:
                self.operation_metrics.pop(op_name, None)
                self._operation_access_times.pop(op_name, None)
                operations_to_remove.append(op_name)

        if operations_to_remove:
            import logging

            logger = logging.getLogger("verenigingen.services.metrics")
            logger.info(
                f"Cleaned up {len(operations_to_remove)} old operation metrics for {self.service_name}"
            )

    def get_memory_usage(self) -> Dict:
        """Get current memory usage of metrics collection.

        Returns:
            Dictionary with memory usage statistics
        """
        with self.lock:
            return {
                "service_name": self.service_name,
                "operation_count": len(self.operation_metrics),
                "max_operations": self.max_operations,
                "history_size": len(self.response_times),
                "max_history": self.max_history,
                "memory_efficient": len(self.operation_metrics) < self.max_operations * 0.8,
            }


class MetricsCollector:
    """Centralized metrics collection and aggregation."""

    def __init__(self):
        self.service_metrics = {}
        self.lock = threading.Lock()
        self.logger = logging.getLogger("verenigingen.services.metrics")

    def get_service_metrics(self, service_name: str) -> ServiceMetrics:
        """Get or create metrics for a service.

        Args:
            service_name: Name of the service

        Returns:
            ServiceMetrics instance
        """
        with self.lock:
            if service_name not in self.service_metrics:
                self.service_metrics[service_name] = ServiceMetrics(service_name)
            return self.service_metrics[service_name]

    def record_service_operation(
        self, service_name: str, operation_name: str, duration: float, success: bool = True
    ):
        """Record an operation for a service.

        Args:
            service_name: Name of the service
            operation_name: Name of the operation
            duration: Duration in seconds
            success: Whether the operation succeeded
        """
        metrics = self.get_service_metrics(service_name)
        metrics.record_operation(operation_name, duration, success)

    def get_all_metrics(self) -> Dict[str, Dict]:
        """Get metrics for all services.

        Returns:
            Dictionary mapping service names to their metrics
        """
        with self.lock:
            return {name: metrics.get_summary() for name, metrics in self.service_metrics.items()}

    def get_aggregated_metrics(self) -> Dict:
        """Get aggregated metrics across all services.

        Returns:
            Aggregated metrics summary
        """
        all_metrics = self.get_all_metrics()

        if not all_metrics:
            return {
                "total_services": 0,
                "total_calls": 0,
                "total_errors": 0,
                "overall_error_rate": 0,
                "average_response_time": 0,
            }

        total_calls = sum(m["call_count"] for m in all_metrics.values())
        total_errors = sum(m["error_count"] for m in all_metrics.values())
        total_time = sum(m["total_time"] for m in all_metrics.values())

        return {
            "total_services": len(all_metrics),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "overall_error_rate": total_errors / max(total_calls, 1),
            "average_response_time": total_time / max(total_calls, 1),
            "services": list(all_metrics.keys()),
        }

    def reset_all_metrics(self):
        """Reset metrics for all services."""
        with self.lock:
            for metrics in self.service_metrics.values():
                metrics.reset_metrics()


class HealthMonitor:
    """Service health monitoring with status tracking."""

    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics_collector = metrics_collector
        self.health_thresholds = {
            "max_error_rate": 0.05,  # 5%
            "max_response_time": 5.0,  # 5 seconds
            "min_throughput": 0.1,  # 0.1 requests/second
        }
        self.logger = logging.getLogger("verenigingen.services.health")

    def check_service_health(self, service_name: str) -> Dict:
        """Check health of a specific service.

        Args:
            service_name: Name of the service to check

        Returns:
            Health status dictionary
        """
        try:
            metrics = self.metrics_collector.get_service_metrics(service_name)
            summary = metrics.get_summary()

            health_issues = []

            # Check error rate
            if summary["error_rate"] > self.health_thresholds["max_error_rate"]:
                health_issues.append(f"High error rate: {summary['error_rate']:.2%}")

            # Check response time
            if summary["average_response_time"] > self.health_thresholds["max_response_time"]:
                health_issues.append(f"Slow response time: {summary['average_response_time']:.2f}s")

            # Check throughput
            if summary["throughput"] < self.health_thresholds["min_throughput"]:
                health_issues.append(f"Low throughput: {summary['throughput']:.2f} req/s")

            status = "healthy" if not health_issues else "unhealthy"

            return {
                "success": status == "healthy",
                "service_name": service_name,
                "status": status,
                "data": {"issues": health_issues, "metrics": summary},
                "errors": health_issues if status != "healthy" else [],
                "timestamp": time.time(),
            }

        except Exception as e:
            return {
                "success": False,
                "service_name": service_name,
                "status": "error",
                "data": None,
                "errors": [f"Health check failed: {str(e)}"],
                "timestamp": time.time(),
            }

    def check_all_services_health(self) -> Dict[str, Dict]:
        """Check health of all registered services.

        Returns:
            Dictionary mapping service names to health status
        """
        health_reports = {}

        for service_name in self.metrics_collector.service_metrics:
            health_reports[service_name] = self.check_service_health(service_name)

        return health_reports

    def get_system_health_summary(self) -> Dict:
        """Get overall system health summary.

        Returns:
            System health summary
        """
        health_reports = self.check_all_services_health()

        if not health_reports:
            return {
                "overall_status": "no_services",
                "healthy_services": 0,
                "unhealthy_services": 0,
                "total_services": 0,
            }

        healthy_count = sum(1 for report in health_reports.values() if report["status"] == "healthy")
        unhealthy_count = len(health_reports) - healthy_count

        overall_status = "healthy" if unhealthy_count == 0 else "degraded"
        if healthy_count == 0:
            overall_status = "critical"

        return {
            "success": overall_status == "healthy",
            "status": overall_status,
            "data": {
                "healthy_services": healthy_count,
                "unhealthy_services": unhealthy_count,
                "total_services": len(health_reports),
                "service_reports": health_reports,
            },
            "errors": (
                []
                if overall_status == "healthy"
                else [f"System degraded: {unhealthy_count} unhealthy services"]
            ),
            "timestamp": time.time(),
        }


class PerformanceProfiler:
    """Detailed performance profiling for services."""

    def __init__(self):
        self.profiles = {}
        self.lock = threading.Lock()

    def start_profile(self, service_name: str, operation_name: str) -> str:
        """Start profiling an operation.

        Args:
            service_name: Name of the service
            operation_name: Name of the operation

        Returns:
            Profile ID for tracking
        """
        profile_id = f"{service_name}:{operation_name}:{time.time()}"

        with self.lock:
            self.profiles[profile_id] = {
                "service_name": service_name,
                "operation_name": operation_name,
                "start_time": time.time(),
                "end_time": None,
                "duration": None,
                "success": None,
                "details": {},
            }

        return profile_id

    def end_profile(self, profile_id: str, success: bool = True, details: Dict = None):
        """End profiling an operation.

        Args:
            profile_id: Profile ID from start_profile
            success: Whether the operation succeeded
            details: Additional profiling details
        """
        with self.lock:
            if profile_id in self.profiles:
                profile = self.profiles[profile_id]
                profile["end_time"] = time.time()
                profile["duration"] = profile["end_time"] - profile["start_time"]
                profile["success"] = success
                profile["details"] = details or {}

    def get_profile_results(self, service_name: str = None) -> List[Dict]:
        """Get profiling results.

        Args:
            service_name: Optional service name filter

        Returns:
            List of profile results
        """
        with self.lock:
            results = []
            for profile in self.profiles.values():
                if profile["end_time"] is not None:  # Completed profiles only
                    if service_name is None or profile["service_name"] == service_name:
                        results.append(profile.copy())

            # Sort by duration descending
            results.sort(key=lambda x: x["duration"], reverse=True)
            return results

    def clear_profiles(self, service_name: str = None):
        """Clear profiling data.

        Args:
            service_name: Optional service name filter
        """
        with self.lock:
            if service_name is None:
                self.profiles.clear()
            else:
                self.profiles = {
                    pid: profile
                    for pid, profile in self.profiles.items()
                    if profile["service_name"] != service_name
                }


# Global instances
_global_metrics_collector = None
_global_health_monitor = None
_global_profiler = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector.

    Returns:
        Global MetricsCollector instance
    """
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector


def get_health_monitor() -> HealthMonitor:
    """Get the global health monitor.

    Returns:
        Global HealthMonitor instance
    """
    global _global_health_monitor
    if _global_health_monitor is None:
        _global_health_monitor = HealthMonitor(get_metrics_collector())
    return _global_health_monitor


def get_profiler() -> PerformanceProfiler:
    """Get the global performance profiler.

    Returns:
        Global PerformanceProfiler instance
    """
    global _global_profiler
    if _global_profiler is None:
        _global_profiler = PerformanceProfiler()
    return _global_profiler


def record_operation(service_name: str, operation_name: str, duration: float, success: bool = True):
    """Record a service operation in the global metrics collector.

    Args:
        service_name: Name of the service
        operation_name: Name of the operation
        duration: Duration in seconds
        success: Whether the operation succeeded
    """
    get_metrics_collector().record_service_operation(service_name, operation_name, duration, success)


def get_service_health(service_name: str) -> Dict:
    """Get health status for a service.

    Args:
        service_name: Name of the service

    Returns:
        Health status dictionary
    """
    return get_health_monitor().check_service_health(service_name)


def get_system_health() -> Dict:
    """Get overall system health summary.

    Returns:
        System health summary
    """
    return get_health_monitor().get_system_health_summary()
