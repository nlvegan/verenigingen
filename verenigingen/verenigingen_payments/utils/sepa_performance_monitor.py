"""
SEPA Performance Monitoring and Optimization Utilities

Provides comprehensive performance monitoring, profiling, and optimization
recommendations for SEPA Direct Debit batch processing operations.

Features:
- Real-time performance monitoring of SEPA operations
- Query optimization detection and recommendations
- Memory usage tracking for large batch processing
- XML generation performance analysis
- Bank communication latency monitoring
- Performance regression detection

Author: Verenigingen Development Team
Date: August 2025
"""

import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List

import frappe
import psutil

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


@dataclass
class PerformanceMetric:
    """Single performance measurement"""

    operation: str
    duration_ms: float
    memory_mb: float
    query_count: int
    timestamp: datetime
    batch_size: int = 0
    additional_data: Dict[str, Any] = field(default_factory=dict)


class SEPAPerformanceMonitor:
    """Comprehensive SEPA performance monitoring and optimization"""

    def __init__(self, max_metrics_history: int = 1000):
        self.metrics_history = deque(maxlen=max_metrics_history)
        self.query_counts = {}
        self.memory_baselines = {}
        self.optimization_recommendations = []
        self.current_operations = {}  # Track ongoing operations

    def start_operation(self, operation_name: str, batch_size: int = 0) -> str:
        """Start monitoring a SEPA operation"""
        operation_id = f"{operation_name}_{int(time.time() * 1000)}"

        # Record baseline metrics
        process = psutil.Process()
        memory_baseline = process.memory_info().rss / 1024 / 1024  # MB

        # Begin counting SQL queries for this operation. We wrap frappe.db.sql
        # with a counter (the same technique Frappe's own assertQueryCount uses)
        # rather than relying on a DB-specific counter. Reference-counted so
        # nested operations share a single wrapper and restore it correctly.
        query_baseline = self._begin_query_counting()

        self.current_operations[operation_id] = {
            "operation": operation_name,
            "start_time": time.time(),
            "memory_baseline": memory_baseline,
            "query_baseline": query_baseline,
            "batch_size": batch_size,
        }

        return operation_id

    def _begin_query_counting(self) -> int:
        """Install a SQL-query counter (idempotent / reference-counted).

        Returns the current cumulative query count so the caller can compute a
        per-operation delta in ``end_operation``.
        """
        if not hasattr(self, "_sql_counter_depth"):
            self._sql_counter_depth = 0
            self._sql_query_total = 0

        if self._sql_counter_depth == 0:
            db_cls = frappe.db.__class__
            self._orig_db_sql = db_cls.sql

            orig_sql = self._orig_db_sql
            monitor = self

            def _counting_sql(*args, **kwargs):
                monitor._sql_query_total += 1
                return orig_sql(*args, **kwargs)

            db_cls.sql = _counting_sql

        self._sql_counter_depth += 1
        return self._sql_query_total

    def _end_query_counting(self) -> int:
        """Tear down the SQL-query counter when the outermost op finishes."""
        if not getattr(self, "_sql_counter_depth", 0):
            return getattr(self, "_sql_query_total", 0)

        self._sql_counter_depth -= 1
        total = self._sql_query_total
        if self._sql_counter_depth == 0:
            frappe.db.__class__.sql = self._orig_db_sql
        return total

    def end_operation(self, operation_id: str, additional_data: Dict[str, Any] = None) -> PerformanceMetric:
        """End monitoring and record performance metrics"""
        if operation_id not in self.current_operations:
            frappe.logger().warning(f"Operation {operation_id} not found among current operations")
            return None

        operation_data = self.current_operations.pop(operation_id)

        # Calculate performance metrics
        duration_ms = (time.time() - operation_data["start_time"]) * 1000

        process = psutil.Process()
        current_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_used = current_memory - operation_data["memory_baseline"]

        # Number of SQL queries executed during this operation (delta against the
        # baseline captured at start_operation), then tear down the counter.
        current_queries = self._end_query_counting()
        query_count = current_queries - operation_data["query_baseline"]

        metric = PerformanceMetric(
            operation=operation_data["operation"],
            duration_ms=duration_ms,
            memory_mb=memory_used,
            query_count=query_count,
            timestamp=datetime.now(),
            batch_size=operation_data["batch_size"],
            additional_data=additional_data or {},
        )

        self.metrics_history.append(metric)
        self._analyze_performance(metric)

        frappe.logger().info(
            f"SEPA Performance: {metric.operation} completed in {duration_ms:.1f}ms, "
            f"memory: {memory_used:.1f}MB, queries: {query_count}, batch_size: {metric.batch_size}"
        )

        return metric

    def _analyze_performance(self, metric: PerformanceMetric):
        """Analyze performance metric and generate recommendations"""
        # Query efficiency analysis
        if metric.batch_size > 0:
            queries_per_item = metric.query_count / metric.batch_size
            if queries_per_item > 3:  # Threshold for N+1 query detection
                self.optimization_recommendations.append(
                    {
                        "type": "query_optimization",
                        "severity": "high" if queries_per_item > 5 else "medium",
                        "operation": metric.operation,
                        "issue": f"High query count per item: {queries_per_item:.1f} queries per item",
                        "recommendation": "Use bulk operations to reduce N+1 queries",
                        "timestamp": metric.timestamp,
                    }
                )

        # Memory usage analysis
        if metric.memory_mb > 100:  # Threshold for high memory usage
            self.optimization_recommendations.append(
                {
                    "type": "memory_optimization",
                    "severity": "medium" if metric.memory_mb < 500 else "high",
                    "operation": metric.operation,
                    "issue": f"High memory usage: {metric.memory_mb:.1f}MB",
                    "recommendation": "Consider processing in smaller batches or implementing streaming",
                    "timestamp": metric.timestamp,
                }
            )

        # Duration analysis for batch operations
        if metric.batch_size > 0:
            time_per_item = metric.duration_ms / metric.batch_size
            if time_per_item > 100:  # 100ms per item threshold
                self.optimization_recommendations.append(
                    {
                        "type": "performance_optimization",
                        "severity": "high" if time_per_item > 500 else "medium",
                        "operation": metric.operation,
                        "issue": f"Slow processing: {time_per_item:.1f}ms per item",
                        "recommendation": "Optimize database queries and consider parallel processing",
                        "timestamp": metric.timestamp,
                    }
                )

    def get_performance_summary(self, hours_back: int = 24) -> Dict[str, Any]:
        """Get performance summary for specified time period"""
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        recent_metrics = [m for m in self.metrics_history if m.timestamp >= cutoff_time]

        if not recent_metrics:
            return {"message": "No performance data available for the specified period"}

        # Group by operation
        by_operation = defaultdict(list)
        for metric in recent_metrics:
            by_operation[metric.operation].append(metric)

        summary = {
            "period_hours": hours_back,
            "total_operations": len(recent_metrics),
            "operations_summary": {},
            "overall_stats": {
                "avg_duration_ms": sum(m.duration_ms for m in recent_metrics) / len(recent_metrics),
                "avg_memory_mb": sum(m.memory_mb for m in recent_metrics) / len(recent_metrics),
                "total_queries": sum(m.query_count for m in recent_metrics),
                "total_items_processed": sum(m.batch_size for m in recent_metrics if m.batch_size > 0),
            },
            "recommendations": self.get_recent_recommendations(hours_back),
        }

        # Per-operation statistics
        for operation, metrics in by_operation.items():
            summary["operations_summary"][operation] = {
                "count": len(metrics),
                "avg_duration_ms": sum(m.duration_ms for m in metrics) / len(metrics),
                "max_duration_ms": max(m.duration_ms for m in metrics),
                "avg_memory_mb": sum(m.memory_mb for m in metrics) / len(metrics),
                "total_queries": sum(m.query_count for m in metrics),
                "total_items": sum(m.batch_size for m in metrics if m.batch_size > 0),
            }

        return summary

    def get_recent_recommendations(self, hours_back: int = 24) -> List[Dict[str, Any]]:
        """Get optimization recommendations from recent period"""
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        return [rec for rec in self.optimization_recommendations if rec["timestamp"] >= cutoff_time]

    def monitor_xml_generation(self, batch_size: int, xml_content: str = None) -> Dict[str, Any]:
        """Specialized monitoring for XML generation performance"""
        operation_id = self.start_operation("sepa_xml_generation", batch_size)

        # start_operation installs a process-global query-counting monkey-patch on
        # frappe.db.__class__.sql; end_operation removes it. Wrap the analysis in
        # try/finally so the patch is ALWAYS removed even if XML analysis raises
        # (e.g. _get_xml_depth / _estimate_compression_ratio) — otherwise the patch
        # leaks and inflates query counts in every subsequent operation/test.
        xml_stats = {}
        try:
            if xml_content:
                # Analyze XML characteristics
                try:
                    root = ET.fromstring(xml_content)
                    xml_stats = {
                        "xml_size_bytes": len(xml_content.encode("utf-8")),
                        # ET.Element.iter() returns an iterator (no __len__); materialize it.
                        "xml_elements_count": len(list(root.iter())),
                        "xml_depth": self._get_xml_depth(root),
                        "compression_ratio": self._estimate_compression_ratio(xml_content),
                    }
                except ET.ParseError:
                    xml_stats["xml_parse_error"] = True
        finally:
            metric = self.end_operation(operation_id, xml_stats)

        # XML-specific recommendations
        if xml_stats.get("xml_size_bytes", 0) > 10 * 1024 * 1024:  # 10MB threshold
            self.optimization_recommendations.append(
                {
                    "type": "xml_optimization",
                    "severity": "medium",
                    "operation": "sepa_xml_generation",
                    "issue": f"Large XML file generated: {xml_stats['xml_size_bytes'] / 1024 / 1024:.1f}MB",
                    "recommendation": "Consider splitting large batches or implementing streaming XML generation",
                    "timestamp": metric.timestamp,
                }
            )

        return {
            "performance_metric": metric,
            "xml_statistics": xml_stats,
            "recommendations": self.get_recent_recommendations(1),  # Last hour
        }

    def _get_xml_depth(self, element, depth=0):
        """Calculate maximum depth of XML tree"""
        if not element:
            return depth
        return max([self._get_xml_depth(child, depth + 1) for child in element] + [depth])

    def _estimate_compression_ratio(self, xml_content: str) -> float:
        """Estimate XML compression potential"""
        # Simple estimation based on repetitive patterns
        unique_lines = len(set(xml_content.split("\n")))
        total_lines = len(xml_content.split("\n"))
        return unique_lines / max(total_lines, 1)

    def benchmark_batch_sizes(
        self, operation_func, batch_sizes: List[int], test_data_generator: callable
    ) -> Dict[int, Dict[str, Any]]:
        """Benchmark different batch sizes for an operation"""
        results = {}

        for batch_size in batch_sizes:
            frappe.logger().info(f"Benchmarking batch size: {batch_size}")

            # Generate test data
            test_data = test_data_generator(batch_size)

            # Run benchmark
            operation_id = self.start_operation("batch_benchmark", batch_size)

            try:
                operation_result = operation_func(test_data)
                metric = self.end_operation(operation_id, {"success": True, "result": operation_result})

                results[batch_size] = {
                    "success": True,
                    "duration_ms": metric.duration_ms,
                    "memory_mb": metric.memory_mb,
                    "queries": metric.query_count,
                    "throughput_items_per_second": (
                        batch_size / (metric.duration_ms / 1000) if metric.duration_ms > 0 else 0
                    ),
                }

            except Exception as e:
                self.end_operation(operation_id, {"success": False, "error": str(e)})
                results[batch_size] = {"success": False, "error": str(e)}

        # Analyze results and recommend optimal batch size
        successful_results = {k: v for k, v in results.items() if v["success"]}
        if successful_results:
            optimal_batch_size = max(
                successful_results.keys(), key=lambda k: successful_results[k]["throughput_items_per_second"]
            )
            results["recommendation"] = {
                "optimal_batch_size": optimal_batch_size,
                "peak_throughput": successful_results[optimal_batch_size]["throughput_items_per_second"],
            }

        return results

    def clear_history(self):
        """Clear performance history and recommendations"""
        self.metrics_history.clear()
        self.optimization_recommendations.clear()
        frappe.logger().info("SEPA performance history cleared")


# Singleton instance for global use
_sepa_performance_monitor = None


def get_sepa_performance_monitor() -> SEPAPerformanceMonitor:
    """Get the global SEPA performance monitor instance"""
    global _sepa_performance_monitor
    if _sepa_performance_monitor is None:
        _sepa_performance_monitor = SEPAPerformanceMonitor()
    return _sepa_performance_monitor


# Context manager for easy performance monitoring
class monitor_sepa_operation:
    """Context manager for monitoring SEPA operations"""

    def __init__(self, operation_name: str, batch_size: int = 0, additional_data: Dict[str, Any] = None):
        self.operation_name = operation_name
        self.batch_size = batch_size
        self.additional_data = additional_data or {}
        self.operation_id = None
        self.monitor = get_sepa_performance_monitor()

    def __enter__(self):
        self.operation_id = self.monitor.start_operation(self.operation_name, self.batch_size)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.additional_data["error"] = str(exc_val)
            self.additional_data["success"] = False
        else:
            self.additional_data["success"] = True

        self.monitor.end_operation(self.operation_id, self.additional_data)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_sepa_performance_report(hours_back: int = 24):
    """API endpoint to get SEPA performance report"""
    monitor = get_sepa_performance_monitor()
    return {"success": True, "performance_report": monitor.get_performance_summary(hours_back)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def clear_sepa_performance_data():
    """API endpoint to clear SEPA performance data"""
    monitor = get_sepa_performance_monitor()
    monitor.clear_history()
    return {"success": True, "message": "SEPA performance data cleared"}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def benchmark_sepa_batch_processing(max_batch_size: int = 500):
    """API endpoint to benchmark SEPA batch processing performance"""
    if max_batch_size > 1000:
        frappe.throw("Maximum batch size for benchmarking is 1000 to prevent system overload")

    monitor = get_sepa_performance_monitor()

    # Define test batch sizes
    batch_sizes = (
        [10, 50, 100, 250, max_batch_size] if max_batch_size >= 250 else [10, 25, 50, max_batch_size]
    )

    def mock_operation(test_data):
        # Simulate batch processing with controlled delay
        time.sleep(len(test_data) * 0.001)  # 1ms per item
        return {"processed": len(test_data)}

    def test_data_generator(size):
        return [f"test_invoice_{i}" for i in range(size)]

    results = monitor.benchmark_batch_sizes(mock_operation, batch_sizes, test_data_generator)

    return {
        "success": True,
        "benchmark_results": results,
        "system_info": {
            "cpu_count": psutil.cpu_count(),
            "memory_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "frappe_version": frappe.__version__,
        },
    }
