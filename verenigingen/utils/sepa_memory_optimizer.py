"""
SEPA Memory Optimization Manager

Week 4 Implementation: Memory optimization for large datasets with pagination,
streaming processing, and memory usage monitoring.

This module provides comprehensive memory management for SEPA batch operations,
ensuring the system can handle large datasets efficiently without memory exhaustion.
"""

import gc
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

import frappe
import psutil
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now

from verenigingen.utils.error_handling import SEPAError, log_error
from verenigingen.utils.performance_utils import performance_monitor


@dataclass
class MemoryUsageSnapshot:
    """Memory usage snapshot for monitoring"""

    timestamp: datetime
    process_memory_mb: float
    system_memory_percent: float
    available_memory_mb: float
    allocated_objects: int
    query_cache_size: int
    frappe_cache_size: int


@dataclass
class PaginationConfig:
    """Configuration for pagination operations"""

    page_size: int = 1000
    max_pages: Optional[int] = None
    memory_threshold_mb: float = 512.0
    enable_adaptive_sizing: bool = True
    min_page_size: int = 100
    max_page_size: int = 5000


class SEPAMemoryMonitor:
    """
    Memory usage monitoring for SEPA operations

    Tracks memory consumption and provides alerts when thresholds are exceeded.
    """

    def __init__(self, alert_threshold_mb: float = 1024.0):
        self.alert_threshold_mb = alert_threshold_mb
        self.snapshots: List[MemoryUsageSnapshot] = []
        self.max_snapshots = 100  # Keep last 100 snapshots
        self.process = psutil.Process()

    def take_snapshot(self, label: str = None) -> MemoryUsageSnapshot:
        """
        Take a memory usage snapshot

        Args:
            label: Optional label for the snapshot

        Returns:
            MemoryUsageSnapshot object
        """
        try:
            # Get process memory info
            memory_info = self.process.memory_info()
            process_memory_mb = memory_info.rss / 1024 / 1024

            # Get system memory info
            system_memory = psutil.virtual_memory()
            system_memory_percent = system_memory.percent
            available_memory_mb = system_memory.available / 1024 / 1024

            # Get Python object counts
            allocated_objects = len(gc.get_objects())

            # Get cache sizes (approximate)
            query_cache_size = len(getattr(frappe.db, "_query_cache", {}))
            frappe_cache_size = len(getattr(frappe.cache(), "cache_data", {}))

            snapshot = MemoryUsageSnapshot(
                timestamp=get_datetime(now()),
                process_memory_mb=process_memory_mb,
                system_memory_percent=system_memory_percent,
                available_memory_mb=available_memory_mb,
                allocated_objects=allocated_objects,
                query_cache_size=query_cache_size,
                frappe_cache_size=frappe_cache_size,
            )

            # Store snapshot
            self.snapshots.append(snapshot)

            # Trim old snapshots
            if len(self.snapshots) > self.max_snapshots:
                self.snapshots = self.snapshots[-self.max_snapshots :]

            # Log snapshot with label
            if label:
                frappe.logger().info(
                    f"Memory snapshot [{label}]: "
                    f"Process={process_memory_mb:.1f}MB, "
                    f"System={system_memory_percent:.1f}%, "
                    f"Available={available_memory_mb:.1f}MB, "
                    f"Objects={allocated_objects}"
                )

            # Check for alerts
            if process_memory_mb > self.alert_threshold_mb:
                self._trigger_memory_alert(snapshot)

            return snapshot

        except Exception as e:
            frappe.logger().error(f"Error taking memory snapshot: {str(e)}")
            # Return empty snapshot on error
            return MemoryUsageSnapshot(
                timestamp=get_datetime(now()),
                process_memory_mb=0.0,
                system_memory_percent=0.0,
                available_memory_mb=0.0,
                allocated_objects=0,
                query_cache_size=0,
                frappe_cache_size=0,
            )

    def _trigger_memory_alert(self, snapshot: MemoryUsageSnapshot):
        """Trigger memory usage alert"""
        alert_data = {
            "alert_type": "high_memory_usage",
            "process_memory_mb": snapshot.process_memory_mb,
            "threshold_mb": self.alert_threshold_mb,
            "system_memory_percent": snapshot.system_memory_percent,
            "available_memory_mb": snapshot.available_memory_mb,
            "timestamp": snapshot.timestamp,
        }

        frappe.log_error(
            f"High memory usage detected: {snapshot.process_memory_mb:.1f}MB "
            f"(threshold: {self.alert_threshold_mb:.1f}MB)",
            "SEPA Memory Alert",
            alert_data,
        )

        # Also log to performance monitoring
        frappe.log_info(alert_data, "SEPA Memory Monitoring")

    def get_memory_trend(self, minutes: int = 10) -> Dict[str, Any]:
        """
        Get memory usage trend over specified time period

        Args:
            minutes: Time period in minutes

        Returns:
            Memory trend analysis
        """
        cutoff_time = get_datetime(now()) - timedelta(minutes=minutes)
        recent_snapshots = [s for s in self.snapshots if s.timestamp >= cutoff_time]

        if not recent_snapshots:
            return {"trend": "no_data", "snapshots": 0}

        # Calculate trend
        first_memory = recent_snapshots[0].process_memory_mb
        last_memory = recent_snapshots[-1].process_memory_mb
        peak_memory = max(s.process_memory_mb for s in recent_snapshots)
        avg_memory = sum(s.process_memory_mb for s in recent_snapshots) / len(recent_snapshots)

        trend = "stable"
        if last_memory > first_memory * 1.2:
            trend = "increasing"
        elif last_memory < first_memory * 0.8:
            trend = "decreasing"

        return {
            "trend": trend,
            "snapshots": len(recent_snapshots),
            "first_memory_mb": first_memory,
            "last_memory_mb": last_memory,
            "peak_memory_mb": peak_memory,
            "average_memory_mb": avg_memory,
            "change_percent": ((last_memory - first_memory) / first_memory * 100) if first_memory > 0 else 0,
        }

    @contextmanager
    def monitor_operation(self, operation_name: str):
        """
        Context manager to monitor memory during an operation

        Args:
            operation_name: Name of the operation being monitored
        """
        start_snapshot = self.take_snapshot(f"{operation_name}_start")
        start_time = time.time()

        try:
            yield start_snapshot

        finally:
            end_snapshot = self.take_snapshot(f"{operation_name}_end")
            duration = time.time() - start_time

            # Calculate memory change
            memory_change = end_snapshot.process_memory_mb - start_snapshot.process_memory_mb

            # Log operation summary
            frappe.logger().info(
                f"Memory monitoring [{operation_name}]: "
                f"Duration={duration:.2f}s, "
                f"Memory change={memory_change:+.1f}MB, "
                f"Peak objects={end_snapshot.allocated_objects - start_snapshot.allocated_objects:+d}"
            )

    def force_cleanup(self):
        """Force memory cleanup operations"""
        try:
            # Clear query cache
            if hasattr(frappe.db, "_query_cache"):
                frappe.db._query_cache.clear()

            # Clear Frappe cache
            frappe.cache().clear()

            # Force garbage collection
            collected = gc.collect()

            frappe.logger().info(f"Forced memory cleanup: {collected} objects collected")

            # Take snapshot after cleanup
            self.take_snapshot("after_cleanup")

        except Exception as e:
            frappe.logger().error(f"Error during memory cleanup: {str(e)}")


class SEPABatchPaginator:
    """
    Efficient pagination system for SEPA batch operations

    Handles large datasets by breaking them into manageable chunks
    with adaptive sizing based on memory usage.
    """

    def __init__(self, config: PaginationConfig = None):
        self.config = config or PaginationConfig()
        self.memory_monitor = SEPAMemoryMonitor()
        self.current_page_size = self.config.page_size

    def paginate_invoice_query(
        self, base_filters: Dict[str, Any], fields: List[str] = None
    ) -> Iterator[List[Dict[str, Any]]]:
        """
        Paginate invoice query results

        Args:
            base_filters: Base filters for invoice query
            fields: Fields to retrieve

        Yields:
            Pages of invoice records
        """
        fields = fields or [
            "name",
            "outstanding_amount",
            "due_date",
            "status",
            "customer",
            "membership",
            "posting_date",
        ]

        # Get total count first
        total_count = frappe.db.count("Sales Invoice", filters=base_filters)

        if total_count == 0:
            return

        frappe.logger().info(f"Paginating {total_count} invoices with page size {self.current_page_size}")

        offset = 0
        page_num = 0

        with self.memory_monitor.monitor_operation("invoice_pagination"):
            while offset < total_count:
                # Check memory before processing page
                if self.config.enable_adaptive_sizing:
                    self._adjust_page_size()

                # Check max pages limit
                if self.config.max_pages and page_num >= self.config.max_pages:
                    frappe.logger().warning(f"Reached max pages limit: {self.config.max_pages}")
                    break

                # Fetch page
                try:
                    page_data = frappe.get_all(
                        "Sales Invoice",
                        filters=base_filters,
                        fields=fields,
                        order_by="posting_date desc, name",
                        limit_start=offset,
                        limit_page_length=self.current_page_size,
                    )

                    if not page_data:
                        break

                    frappe.logger().debug(
                        f"Yielding page {page_num + 1}: {len(page_data)} records "
                        f"(offset {offset}, page_size {self.current_page_size})"
                    )

                    yield page_data

                    offset += len(page_data)
                    page_num += 1

                    # Small delay to prevent overwhelming the system
                    if page_num % 10 == 0:
                        time.sleep(0.1)

                except Exception as e:
                    log_error(
                        e,
                        context={
                            "operation": "invoice_pagination",
                            "offset": offset,
                            "page_size": self.current_page_size,
                            "page_num": page_num,
                        },
                        module="sepa_memory_optimizer",
                    )
                    break

    def paginate_member_data(self, member_filters: Dict[str, Any] = None) -> Iterator[List[Dict[str, Any]]]:
        """
        Paginate member data with related information

        Args:
            member_filters: Filters for member query

        Yields:
            Pages of member records with SEPA mandate info
        """
        member_filters = member_filters or {}

        # Use optimized query to get members with mandate info
        with self.memory_monitor.monitor_operation("member_pagination"):
            offset = 0
            page_num = 0

            while True:
                if self.config.enable_adaptive_sizing:
                    self._adjust_page_size()

                if self.config.max_pages and page_num >= self.config.max_pages:
                    break

                try:
                    # Optimized query with JOIN
                    page_data = frappe.db.sql(
                        """
                        SELECT
                            m.name as member,
                            m.full_name,
                            m.email,
                            m.status as member_status,
                            sm.name as mandate_name,
                            sm.iban,
                            sm.bic,
                            sm.mandate_id,
                            sm.status as mandate_status,
                            sm.sign_date
                        FROM `tabMember` m
                        LEFT JOIN `tabSEPA Mandate` sm ON sm.member = m.name AND sm.status = 'Active'
                        WHERE m.docstatus = 1
                        {filters}
                        ORDER BY m.creation DESC
                        LIMIT %(limit)s OFFSET %(offset)s
                    """.format(
                            filters=self._build_filter_clause(member_filters, "m")
                        ),
                        {"limit": self.current_page_size, "offset": offset},
                        as_dict=True,
                    )

                    if not page_data:
                        break

                    frappe.logger().debug(f"Member page {page_num + 1}: {len(page_data)} records")

                    yield page_data

                    offset += len(page_data)
                    page_num += 1

                    if page_num % 10 == 0:
                        time.sleep(0.1)

                except Exception as e:
                    log_error(
                        e,
                        context={
                            "operation": "member_pagination",
                            "offset": offset,
                            "page_size": self.current_page_size,
                        },
                        module="sepa_memory_optimizer",
                    )
                    break

    def _adjust_page_size(self):
        """Adjust page size based on current memory usage"""
        if not self.config.enable_adaptive_sizing:
            return

        snapshot = self.memory_monitor.take_snapshot()

        # Adjust based on memory usage
        if snapshot.process_memory_mb > self.config.memory_threshold_mb:
            # Reduce page size if memory is high
            new_size = max(int(self.current_page_size * 0.7), self.config.min_page_size)
            if new_size != self.current_page_size:
                frappe.logger().info(
                    f"Reducing page size from {self.current_page_size} to {new_size} "
                    f"due to high memory usage ({snapshot.process_memory_mb:.1f}MB)"
                )
                self.current_page_size = new_size

        elif snapshot.process_memory_mb < self.config.memory_threshold_mb * 0.5:
            # Increase page size if memory is low
            new_size = min(int(self.current_page_size * 1.3), self.config.max_page_size)
            if new_size != self.current_page_size:
                frappe.logger().debug(
                    f"Increasing page size from {self.current_page_size} to {new_size} "
                    f"due to low memory usage ({snapshot.process_memory_mb:.1f}MB)"
                )
                self.current_page_size = new_size

    def _build_filter_clause(self, filters: Dict[str, Any], table_alias: str) -> str:
        """Build SQL filter clause from filter dictionary"""
        if not filters:
            return ""

        clauses = []
        for field, value in filters.items():
            if isinstance(value, (list, tuple)):
                if len(value) == 2 and value[0] in ["in", "not in", ">", "<", ">=", "<=", "!="]:
                    operator, val = value
                    if operator in ["in", "not in"]:
                        val_str = ", ".join([f"'{v}'" for v in val if isinstance(val, (list, tuple))])
                        clauses.append(f"AND {table_alias}.{field} {operator} ({val_str})")
                    else:
                        clauses.append(f"AND {table_alias}.{field} {operator} '{val}'")
                else:
                    # Assume 'in' for list values
                    val_str = ", ".join([f"'{v}'" for v in value])
                    clauses.append(f"AND {table_alias}.{field} IN ({val_str})")
            else:
                clauses.append(f"AND {table_alias}.{field} = '{value}'")

        return " ".join(clauses)


class SEPAStreamProcessor:
    """
    Stream processing for large SEPA batch operations

    Processes data in streams to minimize memory usage while maintaining performance.
    """

    def __init__(self, batch_size: int = 500):
        self.batch_size = batch_size
        self.memory_monitor = SEPAMemoryMonitor()
        self.processed_count = 0
        self.error_count = 0

    @performance_monitor(threshold_ms=5000)
    def stream_process_invoices(self, filters: Dict[str, Any], processor_func, **kwargs) -> Dict[str, Any]:
        """
        Stream process invoices with memory monitoring

        Args:
            filters: Filters for invoice selection
            processor_func: Function to process each batch
            **kwargs: Additional arguments for processor function

        Returns:
            Processing summary
        """
        paginator = SEPABatchPaginator(
            PaginationConfig(
                page_size=self.batch_size,
                memory_threshold_mb=256.0,  # Lower threshold for streaming
                enable_adaptive_sizing=True,
            )
        )

        results = {
            "success": True,
            "processed_count": 0,
            "error_count": 0,
            "batches_processed": 0,
            "memory_peak_mb": 0.0,
            "processing_time_seconds": 0.0,
            "errors": [],
        }

        start_time = time.time()

        with self.memory_monitor.monitor_operation("stream_processing"):
            try:
                for batch_num, invoice_batch in enumerate(paginator.paginate_invoice_query(filters), 1):
                    # Monitor memory before processing batch
                    pre_batch_snapshot = self.memory_monitor.take_snapshot(f"batch_{batch_num}_start")

                    try:
                        # Process batch
                        processor_func(invoice_batch, **kwargs)

                        # Update counters
                        results["processed_count"] += len(invoice_batch)
                        results["batches_processed"] += 1

                        # Track peak memory
                        results["memory_peak_mb"] = max(
                            results["memory_peak_mb"], pre_batch_snapshot.process_memory_mb
                        )

                        # Log progress periodically
                        if batch_num % 10 == 0:
                            frappe.logger().info(
                                f"Stream processing progress: {results['processed_count']} invoices "
                                f"in {batch_num} batches, memory: {pre_batch_snapshot.process_memory_mb:.1f}MB"
                            )

                        # Force cleanup periodically
                        if batch_num % 50 == 0:
                            self.memory_monitor.force_cleanup()

                    except Exception as e:
                        results["error_count"] += 1
                        results["errors"].append(
                            {"batch_num": batch_num, "error": str(e), "invoice_count": len(invoice_batch)}
                        )

                        frappe.logger().error(f"Error processing batch {batch_num}: {str(e)}")

                        # Continue with next batch unless too many errors
                        if results["error_count"] > 10:
                            frappe.logger().error("Too many errors, stopping stream processing")
                            results["success"] = False
                            break

            except Exception as e:
                results["success"] = False
                results["errors"].append({"type": "stream_processing_error", "error": str(e)})

                log_error(
                    e,
                    context={"operation": "stream_process_invoices", "filters": filters},
                    module="sepa_memory_optimizer",
                )

        results["processing_time_seconds"] = time.time() - start_time

        # Final memory snapshot
        final_snapshot = self.memory_monitor.take_snapshot("stream_processing_complete")
        results["final_memory_mb"] = final_snapshot.process_memory_mb

        return results

    def create_memory_efficient_batch(
        self, invoice_stream: Iterator[List[Dict[str, Any]]], max_batch_amount: float = 50000.0
    ) -> Iterator[Dict[str, Any]]:
        """
        Create memory-efficient batches from invoice stream

        Args:
            invoice_stream: Stream of invoice batches
            max_batch_amount: Maximum amount per batch

        Yields:
            Batch dictionaries ready for processing
        """
        current_batch = {"invoices": [], "total_amount": 0.0, "invoice_count": 0}

        with self.memory_monitor.monitor_operation("batch_creation"):
            for invoice_page in invoice_stream:
                for invoice in invoice_page:
                    # Add invoice to current batch
                    invoice_amount = flt(invoice.get("outstanding_amount", 0))

                    current_batch["invoices"].append(invoice)
                    current_batch["total_amount"] += invoice_amount
                    current_batch["invoice_count"] += 1

                    # Check if batch is full
                    if (
                        current_batch["total_amount"] >= max_batch_amount
                        or current_batch["invoice_count"] >= self.batch_size
                    ):
                        # Yield current batch
                        yield dict(current_batch)  # Copy to avoid mutation

                        # Reset for next batch
                        current_batch = {"invoices": [], "total_amount": 0.0, "invoice_count": 0}

                        # Memory cleanup after each batch
                        if self.processed_count % 10 == 0:
                            gc.collect()

                        self.processed_count += 1

            # Yield final batch if it has content
            if current_batch["invoice_count"] > 0:
                yield current_batch


# API Functions


@frappe.whitelist()
def get_memory_usage_stats() -> Dict[str, Any]:
    """
    Get current memory usage statistics

    Returns:
        Memory usage statistics
    """
    monitor = SEPAMemoryMonitor()
    snapshot = monitor.take_snapshot("api_request")

    return {
        "current_memory_mb": snapshot.process_memory_mb,
        "system_memory_percent": snapshot.system_memory_percent,
        "available_memory_mb": snapshot.available_memory_mb,
        "allocated_objects": snapshot.allocated_objects,
        "query_cache_size": snapshot.query_cache_size,
        "frappe_cache_size": snapshot.frappe_cache_size,
        "timestamp": snapshot.timestamp,
        "trend": monitor.get_memory_trend(minutes=5),
    }


@frappe.whitelist()
def optimize_sepa_batch_processing(filters: Dict[str, Any] = None, page_size: int = 1000) -> Dict[str, Any]:
    """
    Optimize SEPA batch processing with memory management

    Args:
        filters: Filters for invoice selection
        page_size: Page size for pagination

    Returns:
        Optimization result
    """
    filters = filters or {"status": ["in", ["Unpaid", "Overdue"]], "docstatus": 1}

    paginator = SEPABatchPaginator(
        PaginationConfig(page_size=page_size, memory_threshold_mb=512.0, enable_adaptive_sizing=True)
    )

    results = {
        "total_invoices": 0,
        "batches_created": 0,
        "memory_peak_mb": 0.0,
        "processing_time_seconds": 0.0,
        "optimization_applied": [],
    }

    start_time = time.time()
    monitor = SEPAMemoryMonitor()

    with monitor.monitor_operation("batch_optimization"):
        for batch_num, invoice_batch in enumerate(paginator.paginate_invoice_query(filters), 1):
            # Track memory usage
            snapshot = monitor.take_snapshot(f"optimization_batch_{batch_num}")
            results["memory_peak_mb"] = max(results["memory_peak_mb"], snapshot.process_memory_mb)

            results["total_invoices"] += len(invoice_batch)
            results["batches_created"] += 1

            # Apply optimizations periodically
            if batch_num % 20 == 0:
                monitor.force_cleanup()
                results["optimization_applied"].append(f"Memory cleanup after batch {batch_num}")

    results["processing_time_seconds"] = time.time() - start_time

    return results


@frappe.whitelist()
def force_memory_cleanup() -> Dict[str, Any]:
    """
    Force memory cleanup operations

    Returns:
        Cleanup result
    """
    if not frappe.has_permission("System Manager"):
        frappe.throw(_("Only system managers can force memory cleanup"))

    monitor = SEPAMemoryMonitor()

    # Take snapshot before cleanup
    before_snapshot = monitor.take_snapshot("before_cleanup")

    # Force cleanup
    monitor.force_cleanup()

    # Take snapshot after cleanup
    after_snapshot = monitor.take_snapshot("after_cleanup")

    # Calculate improvement
    memory_freed = before_snapshot.process_memory_mb - after_snapshot.process_memory_mb

    return {
        "success": True,
        "memory_before_mb": before_snapshot.process_memory_mb,
        "memory_after_mb": after_snapshot.process_memory_mb,
        "memory_freed_mb": memory_freed,
        "objects_before": before_snapshot.allocated_objects,
        "objects_after": after_snapshot.allocated_objects,
        "objects_freed": before_snapshot.allocated_objects - after_snapshot.allocated_objects,
    }
