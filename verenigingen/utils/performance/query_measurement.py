"""
Database Query Measurement Tools
Phase 1 Implementation - Evidence-Based Performance Improvement Plan

This module provides comprehensive query counting, timing, and analysis tools
for measuring database performance in the Verenigingen system.
"""

import functools
import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import get_datetime, now


class QueryProfiler:
    """Context manager and decorator for profiling database queries"""

    def __init__(self, operation_name: str = "Unknown Operation"):
        self.operation_name = operation_name
        self.start_time = None
        self.end_time = None
        self.query_count_start = 0
        self.query_count_end = 0
        self.queries = []
        self.original_execute = None

    def __enter__(self):
        """Start profiling queries"""
        self.start_time = time.time()
        self.query_count_start = self._get_query_count()

        # Hook into frappe.db.sql to capture queries
        self.original_execute = frappe.db.sql
        frappe.db.sql = self._traced_sql

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop profiling and collect results"""
        self.end_time = time.time()
        self.query_count_end = self._get_query_count()

        # Restore original sql method
        if self.original_execute:
            frappe.db.sql = self.original_execute

    def _traced_sql(self, query, values=None, *args, **kwargs):
        """Wrapper for frappe.db.sql to capture query details"""
        query_start = time.time()

        # Execute the original query
        result = self.original_execute(query, values, *args, **kwargs)

        query_end = time.time()
        execution_time = query_end - query_start

        # Capture query details
        self.queries.append(
            {
                "query": str(query)[:500],  # Truncate long queries
                "values": str(values)[:200] if values else None,
                "execution_time": execution_time,
                "timestamp": time.time(),
            }
        )

        return result

    def _get_query_count(self) -> int:
        """Get current query count from frappe"""
        try:
            # Try to get from frappe's internal counter if available
            if hasattr(frappe.db, "_query_count"):
                return frappe.db._query_count
            # Fallback: estimate from queries list length
            return len(getattr(self, "queries", []))
        except Exception:
            return 0

    def get_results(self) -> Dict[str, Any]:
        """Get profiling results"""
        execution_time = (self.end_time - self.start_time) if self.end_time and self.start_time else 0
        query_count = len(self.queries)

        # Calculate query statistics
        query_times = [q["execution_time"] for q in self.queries]
        total_query_time = sum(query_times)
        avg_query_time = total_query_time / len(query_times) if query_times else 0
        max_query_time = max(query_times) if query_times else 0

        # Identify slow queries (>100ms)
        slow_queries = [q for q in self.queries if q["execution_time"] > 0.1]

        # Pattern analysis
        query_patterns = self._analyze_query_patterns()

        return {
            "operation_name": self.operation_name,
            "execution_time": execution_time,
            "query_count": query_count,
            "total_query_time": total_query_time,
            "avg_query_time": avg_query_time,
            "max_query_time": max_query_time,
            "slow_query_count": len(slow_queries),
            "slow_queries": slow_queries[:5],  # Top 5 slowest queries
            "query_patterns": query_patterns,
            "queries_per_second": query_count / execution_time if execution_time > 0 else 0,
            "timestamp": now(),
        }

    def _analyze_query_patterns(self) -> Dict[str, Any]:
        """Analyze query patterns to identify N+1 queries and common patterns"""
        patterns = defaultdict(int)
        table_access = defaultdict(int)

        for query in self.queries:
            query_text = query["query"].upper()

            # Count by query type
            if query_text.startswith("SELECT"):
                patterns["SELECT"] += 1
            elif query_text.startswith("INSERT"):
                patterns["INSERT"] += 1
            elif query_text.startswith("UPDATE"):
                patterns["UPDATE"] += 1
            elif query_text.startswith("DELETE"):
                patterns["DELETE"] += 1

            # Extract table names
            tables = self._extract_table_names(query_text)
            for table in tables:
                table_access[table] += 1

        # Identify potential N+1 patterns
        n_plus_one_candidates = []
        for table, count in table_access.items():
            if count > 10:  # More than 10 queries on same table might indicate N+1
                n_plus_one_candidates.append({"table": table, "query_count": count})

        return {
            "query_types": dict(patterns),
            "table_access": dict(table_access),
            "n_plus_one_candidates": n_plus_one_candidates,
        }

    def _extract_table_names(self, query: str) -> List[str]:
        """Extract table names from SQL query"""
        import re

        # Simple regex to find table names after FROM and JOIN
        tables = []

        # Find FROM clauses
        from_matches = re.findall(r"FROM\s+`?(\w+)`?", query, re.IGNORECASE)
        tables.extend(from_matches)

        # Find JOIN clauses
        join_matches = re.findall(r"JOIN\s+`?(\w+)`?", query, re.IGNORECASE)
        tables.extend(join_matches)

        return list(set(tables))


def profile_queries(operation_name: str = "Unknown Operation"):
    """Decorator for profiling queries in a function"""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with QueryProfiler(operation_name) as profiler:
                result = func(*args, **kwargs)

            # Store results for later analysis
            profile_results = profiler.get_results()
            QueryMeasurementStore.store_result(profile_results)

            return result

        return wrapper

    return decorator


class QueryMeasurementStore:
    """Storage and retrieval for query measurement results"""

    @staticmethod
    def store_result(result: Dict[str, Any]) -> None:
        """Store measurement result"""
        try:
            # Store in cache for immediate access
            cache_key = f"query_profile_{result['operation_name']}_{int(time.time())}"
            frappe.cache().set(cache_key, result, expires_in_sec=3600)

            # Also store in a list for aggregation
            all_results_key = "query_profile_all_results"
            all_results = frappe.cache().get(all_results_key) or []
            all_results.append(result)

            # Keep only last 100 results to prevent memory issues
            if len(all_results) > 100:
                all_results = all_results[-100:]

            frappe.cache().set(all_results_key, all_results, expires_in_sec=7200)

        except Exception as e:
            frappe.log_error(f"Failed to store query measurement result: {e}")

    @staticmethod
    def get_results(operation_name: str = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get stored measurement results"""
        try:
            all_results = frappe.cache().get("query_profile_all_results") or []

            if operation_name:
                # Filter by operation name
                filtered_results = [r for r in all_results if r["operation_name"] == operation_name]
                return filtered_results[-limit:]
            else:
                return all_results[-limit:]

        except Exception as e:
            frappe.log_error(f"Failed to get query measurement results: {e}")
            return []

    @staticmethod
    def get_aggregated_stats() -> Dict[str, Any]:
        """Get aggregated statistics across all measurements"""
        try:
            all_results = frappe.cache().get("query_profile_all_results") or []

            if not all_results:
                return {}

            # Aggregate by operation name
            stats_by_operation = defaultdict(list)
            for result in all_results:
                stats_by_operation[result["operation_name"]].append(result)

            aggregated = {}
            for operation_name, results in stats_by_operation.items():
                query_counts = [r["query_count"] for r in results]
                execution_times = [r["execution_time"] for r in results]

                aggregated[operation_name] = {
                    "measurement_count": len(results),
                    "avg_query_count": sum(query_counts) / len(query_counts),
                    "max_query_count": max(query_counts),
                    "min_query_count": min(query_counts),
                    "avg_execution_time": sum(execution_times) / len(execution_times),
                    "max_execution_time": max(execution_times),
                    "min_execution_time": min(execution_times),
                    "last_measured": max(r["timestamp"] for r in results),
                }

            return aggregated

        except Exception as e:
            frappe.log_error(f"Failed to get aggregated query stats: {e}")
            return {}


class PaymentHistoryProfiler:
    """Specialized profiler for payment history operations"""

    @staticmethod
    def profile_member_payment_loading(member_name: str) -> Dict[str, Any]:
        """Profile payment history loading for a specific member"""
        with QueryProfiler(f"PaymentHistory_Load_{member_name}") as profiler:
            # Get member document
            member = frappe.get_doc("Member", member_name)

            # Profile the payment history loading
            if hasattr(member, "_load_payment_history_without_save"):
                member._load_payment_history_without_save()
            else:
                # Fallback to public method
                member.load_payment_history()

        results = profiler.get_results()

        # Add payment-specific metrics
        payment_count = len(getattr(member, "payment_history", []))
        results["payment_entries_loaded"] = payment_count
        results["queries_per_payment"] = results["query_count"] / payment_count if payment_count > 0 else 0

        return results

    @staticmethod
    def profile_sepa_mandate_checking(member_name: str) -> Dict[str, Any]:
        """Profile SEPA mandate checking operations"""
        with QueryProfiler(f"SEPA_Mandate_Check_{member_name}") as profiler:
            member = frappe.get_doc("Member", member_name)

            # Profile various SEPA operations
            if hasattr(member, "get_active_sepa_mandates"):
                active_mandates = member.get_active_sepa_mandates()

            if hasattr(member, "get_default_sepa_mandate"):
                default_mandate = member.get_default_sepa_mandate()

            if hasattr(member, "has_active_sepa_mandate"):
                has_mandate = member.has_active_sepa_mandate()

        results = profiler.get_results()
        results["mandates_found"] = len(active_mandates) if "active_mandates" in locals() else 0

        return results

    @staticmethod
    def profile_invoice_processing(customer_name: str, limit: int = 20) -> Dict[str, Any]:
        """Profile invoice processing operations"""
        with QueryProfiler(f"Invoice_Processing_{customer_name}") as profiler:
            # Get invoices
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={"customer": customer_name, "docstatus": ["in", [0, 1]]},
                fields=[
                    "name",
                    "posting_date",
                    "due_date",
                    "grand_total",
                    "outstanding_amount",
                    "status",
                    "docstatus",
                    "membership",
                ],
                order_by="posting_date desc",
                limit=limit,
            )

            # Get payment entries for these invoices
            if invoices:
                invoice_names = [inv.name for inv in invoices]
                payment_refs = frappe.get_all(
                    "Payment Entry Reference",
                    filters={"reference_doctype": "Sales Invoice", "reference_name": ["in", invoice_names]},
                    fields=["parent", "reference_name", "allocated_amount"],
                )

        results = profiler.get_results()
        results["invoices_processed"] = len(invoices) if invoices else 0
        results["payment_refs_found"] = len(payment_refs) if "payment_refs" in locals() else 0

        return results


class PerformanceBaselineCollector:
    """Collects performance baselines for current system state"""

    @staticmethod
    def collect_member_payment_baselines(sample_size: int = 10) -> List[Dict[str, Any]]:
        """Collect baseline measurements for member payment operations"""
        # Get sample of members with customers
        members = frappe.get_all(
            "Member",
            filters={"customer": ("!=", "")},
            fields=["name", "full_name", "customer"],
            limit=sample_size,
        )

        baselines = []
        for member in members:
            try:
                baseline = PaymentHistoryProfiler.profile_member_payment_loading(member.name)
                baseline["member_name"] = member.full_name
                baseline["customer"] = member.customer
                baselines.append(baseline)

                # Add small delay to prevent overload
                time.sleep(0.1)

            except Exception as e:
                frappe.log_error(f"Failed to collect baseline for member {member.name}: {e}")
                continue

        return baselines

    @staticmethod
    def collect_sepa_mandate_baselines(sample_size: int = 10) -> List[Dict[str, Any]]:
        """Collect baseline measurements for SEPA mandate operations"""
        # Get sample of members with SEPA mandates
        members_with_mandates = frappe.get_all(
            "SEPA Mandate", filters={"status": "Active"}, fields=["member"], limit=sample_size
        )

        baselines = []
        for mandate_info in members_with_mandates:
            try:
                if mandate_info.member:
                    baseline = PaymentHistoryProfiler.profile_sepa_mandate_checking(mandate_info.member)
                    baselines.append(baseline)

                    # Add small delay
                    time.sleep(0.1)

            except Exception as e:
                frappe.log_error(f"Failed to collect SEPA baseline for member {mandate_info.member}: {e}")
                continue

        return baselines

    @staticmethod
    def generate_baseline_report() -> Dict[str, Any]:
        """Generate comprehensive baseline report"""
        report = {
            "timestamp": now(),
            "system_info": {"frappe_version": frappe.__version__, "site": frappe.local.site},
        }

        # Collect payment history baselines
        frappe.logger().info("Collecting payment history baselines...")
        payment_baselines = PerformanceBaselineCollector.collect_member_payment_baselines(15)

        # Collect SEPA mandate baselines
        frappe.logger().info("Collecting SEPA mandate baselines...")
        sepa_baselines = PerformanceBaselineCollector.collect_sepa_mandate_baselines(10)

        # Calculate averages
        if payment_baselines:
            payment_query_counts = [b["query_count"] for b in payment_baselines]
            payment_exec_times = [b["execution_time"] for b in payment_baselines]

            report["payment_history_baseline"] = {
                "sample_size": len(payment_baselines),
                "avg_query_count": sum(payment_query_counts) / len(payment_query_counts),
                "max_query_count": max(payment_query_counts),
                "min_query_count": min(payment_query_counts),
                "avg_execution_time": sum(payment_exec_times) / len(payment_exec_times),
                "max_execution_time": max(payment_exec_times),
                "individual_results": payment_baselines,
            }

        if sepa_baselines:
            sepa_query_counts = [b["query_count"] for b in sepa_baselines]
            sepa_exec_times = [b["execution_time"] for b in sepa_baselines]

            report["sepa_mandate_baseline"] = {
                "sample_size": len(sepa_baselines),
                "avg_query_count": sum(sepa_query_counts) / len(sepa_query_counts),
                "max_query_count": max(sepa_query_counts),
                "min_query_count": min(sepa_query_counts),
                "avg_execution_time": sum(sepa_exec_times) / len(sepa_exec_times),
                "max_execution_time": max(sepa_exec_times),
                "individual_results": sepa_baselines,
            }

        return report


# Context manager for easy profiling
@contextmanager
def measure_queries(operation_name: str = "Operation"):
    """Context manager for measuring queries"""
    with QueryProfiler(operation_name) as profiler:
        yield profiler

    # Store results
    results = profiler.get_results()
    QueryMeasurementStore.store_result(results)

    return results


# Utility functions for common measurements
def measure_member_payment_history(member_name: str) -> Dict[str, Any]:
    """Quick measurement of member payment history loading"""
    return PaymentHistoryProfiler.profile_member_payment_loading(member_name)


def measure_sepa_mandate_operations(member_name: str) -> Dict[str, Any]:
    """Quick measurement of SEPA mandate operations"""
    return PaymentHistoryProfiler.profile_sepa_mandate_checking(member_name)


def get_performance_summary() -> Dict[str, Any]:
    """Get summary of recent performance measurements"""
    return {
        "recent_measurements": QueryMeasurementStore.get_results(limit=20),
        "aggregated_stats": QueryMeasurementStore.get_aggregated_stats(),
    }
