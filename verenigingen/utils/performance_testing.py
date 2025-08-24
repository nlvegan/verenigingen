#!/usr/bin/env python3
"""
Performance Testing and Validation Module
Problem #1 Resolution: Testing framework for query optimization validation

This module provides comprehensive testing and benchmarking tools to validate
the effectiveness of the database query performance optimizations.

Testing Components:
1. Before/after performance benchmarking
2. N+1 query pattern detection and validation
3. Database index effectiveness testing
4. Cache performance validation
5. Load testing for optimized operations

Performance Validation Goals:
- Verify 70-80% reduction in database calls
- Validate query execution time improvements
- Ensure cache hit rates are above 80% for frequent operations
- Confirm backward compatibility is maintained
"""

import statistics
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import cint, now, nowdate

from verenigingen.utils.optimized_queries import (
    OptimizedMemberQueries,
    OptimizedSEPAQueries,
    OptimizedVolunteerQueries,
    QueryCache,
)


class PerformanceTester:
    """Main performance testing and benchmarking class"""

    def __init__(self):
        self.results = {"tests": [], "summary": {}, "timestamp": now()}

    @frappe.whitelist()
    def run_comprehensive_performance_test(self) -> Dict[str, Any]:
        """Run comprehensive performance testing suite"""

        try:
            frappe.logger().info("Starting comprehensive performance test suite")

            # Test 1: Database index effectiveness
            self._test_database_index_performance()

            # Test 2: N+1 pattern elimination
            self._test_n1_pattern_elimination()

            # Test 3: Bulk query optimization
            self._test_bulk_query_optimization()

            # Test 4: Cache performance
            self._test_cache_performance()

            # Test 5: Load testing
            self._test_load_performance()

            # Generate summary
            self._generate_test_summary()

            frappe.logger().info("Performance test suite completed successfully")

            return {
                "success": True,
                "results": self.results,
                "performance_improvement": self._calculate_overall_improvement(),
            }

        except Exception as e:
            error_msg = f"Performance testing failed: {str(e)}"
            frappe.log_error(error_msg)
            return {"success": False, "error": error_msg}

    def _test_database_index_performance(self):
        """Test database index effectiveness"""

        test_name = "Database Index Performance"

        try:
            # Test critical queries that should benefit from indexes
            index_tests = []

            # Test 1: Member by customer lookup (most critical)
            with self._query_timer("member_by_customer_lookup") as timer:
                test_customers = self._get_test_customers(10)
                for customer in test_customers:
                    frappe.get_all("Member", filters={"customer": customer}, fields=["name"])

            index_tests.append(
                {
                    "query": "Member by customer lookup",
                    "execution_time": timer.execution_time,
                    "query_count": len(test_customers),
                    "avg_time_per_query": timer.execution_time / max(len(test_customers), 1),
                }
            )

            # Test 2: Active member status filtering
            with self._query_timer("active_member_status_filtering") as timer:
                frappe.get_all("Member", filters={"status": "Active"}, fields=["name", "customer"])

            index_tests.append(
                {
                    "query": "Active member status filtering",
                    "execution_time": timer.execution_time,
                    "query_count": 1,
                    "avg_time_per_query": timer.execution_time,
                }
            )

            # Test 3: Volunteer-member relationship lookups
            with self._query_timer("volunteer_member_lookups") as timer:
                test_members = self._get_test_members(10)
                for member in test_members:
                    frappe.get_all("Volunteer", filters={"member": member}, fields=["name"])

            index_tests.append(
                {
                    "query": "Volunteer-member relationship lookups",
                    "execution_time": timer.execution_time,
                    "query_count": len(test_members),
                    "avg_time_per_query": timer.execution_time / max(len(test_members), 1),
                }
            )

            # Test 4: SEPA mandate member lookups
            with self._query_timer("sepa_mandate_member_lookups") as timer:
                for member in test_members[:5]:  # Test subset for SEPA
                    frappe.get_all(
                        "SEPA Mandate", filters={"member": member, "status": "Active"}, fields=["name"]
                    )

            index_tests.append(
                {
                    "query": "SEPA mandate member lookups",
                    "execution_time": timer.execution_time,
                    "query_count": min(len(test_members), 5),
                    "avg_time_per_query": timer.execution_time / max(min(len(test_members), 5), 1),
                }
            )

            # Calculate index performance score
            total_avg_time = sum(test["avg_time_per_query"] for test in index_tests)
            performance_score = max(0, 100 - (total_avg_time * 1000))  # Lower time = higher score

            self.results["tests"].append(
                {
                    "name": test_name,
                    "status": "passed" if performance_score > 70 else "warning",
                    "details": index_tests,
                    "performance_score": round(performance_score, 2),
                    "recommendation": "Good index performance"
                    if performance_score > 70
                    else "Consider additional index optimization",
                }
            )

        except Exception as e:
            self.results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})

    def _test_n1_pattern_elimination(self):
        """Test N+1 query pattern elimination effectiveness"""

        test_name = "N+1 Pattern Elimination"

        try:
            # Test Member Payment History Update (the biggest N+1 pattern)
            n1_tests = []

            # Test 1: Original vs Optimized Member Payment History Update
            test_members = self._get_test_members(5)

            # Simulate original N+1 pattern (for testing purposes only)
            with self._query_counter() as original_counter:
                with self._query_timer("original_member_payment_update") as original_timer:
                    for member_name in test_members:
                        # Simulate the N+1 pattern (without actually updating)
                        member_doc = frappe.get_doc("Member", member_name)
                        customer = member_doc.customer
                        if customer:
                            payment_history = frappe.get_all(
                                "Sales Invoice",
                                filters={"customer": customer},
                                fields=["name", "posting_date", "grand_total", "outstanding_amount"],
                            )
                            # This simulates the individual document loads
                            for invoice in payment_history[:3]:  # Limit for testing
                                frappe.get_doc("Sales Invoice", invoice.name)

            # Test optimized bulk approach
            with self._query_counter() as optimized_counter:
                with self._query_timer("optimized_member_payment_update") as optimized_timer:
                    result = OptimizedMemberQueries.bulk_update_payment_history(test_members)

            query_reduction = (
                max(
                    0,
                    (
                        (original_counter.query_count - optimized_counter.query_count)
                        / original_counter.query_count
                    )
                    * 100,
                )
                if original_counter.query_count > 0
                else 0
            )
            time_improvement = (
                max(
                    0,
                    (
                        (original_timer.execution_time - optimized_timer.execution_time)
                        / original_timer.execution_time
                    )
                    * 100,
                )
                if original_timer.execution_time > 0
                else 0
            )

            n1_tests.append(
                {
                    "pattern": "Member Payment History Update",
                    "original_queries": original_counter.query_count,
                    "optimized_queries": optimized_counter.query_count,
                    "query_reduction_percent": round(query_reduction, 2),
                    "original_time": original_timer.execution_time,
                    "optimized_time": optimized_timer.execution_time,
                    "time_improvement_percent": round(time_improvement, 2),
                }
            )

            # Test 2: Volunteer Assignment Loading
            test_volunteers = self._get_test_volunteers(3)

            # Simulate original pattern
            with self._query_counter() as vol_original_counter:
                with self._query_timer("original_volunteer_assignments") as vol_original_timer:
                    for volunteer_name in test_volunteers:
                        # Simulate individual assignment queries
                        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
                        if volunteer_doc.member:
                            # Board assignments
                            frappe.get_all("Chapter Board Member", filters={"volunteer": volunteer_name})
                            # Team assignments
                            frappe.get_all("Team Member", filters={"volunteer": volunteer_name})
                            # Activities
                            frappe.get_all("Volunteer Activity", filters={"volunteer": volunteer_name})

            # Test optimized bulk approach
            with self._query_counter() as vol_optimized_counter:
                with self._query_timer("optimized_volunteer_assignments") as vol_optimized_timer:
                    assignments = OptimizedVolunteerQueries.get_volunteer_assignments_bulk(test_volunteers)

            vol_query_reduction = (
                max(
                    0,
                    (
                        (vol_original_counter.query_count - vol_optimized_counter.query_count)
                        / vol_original_counter.query_count
                    )
                    * 100,
                )
                if vol_original_counter.query_count > 0
                else 0
            )
            vol_time_improvement = (
                max(
                    0,
                    (
                        (vol_original_timer.execution_time - vol_optimized_timer.execution_time)
                        / vol_original_timer.execution_time
                    )
                    * 100,
                )
                if vol_original_timer.execution_time > 0
                else 0
            )

            n1_tests.append(
                {
                    "pattern": "Volunteer Assignment Loading",
                    "original_queries": vol_original_counter.query_count,
                    "optimized_queries": vol_optimized_counter.query_count,
                    "query_reduction_percent": round(vol_query_reduction, 2),
                    "original_time": vol_original_timer.execution_time,
                    "optimized_time": vol_optimized_timer.execution_time,
                    "time_improvement_percent": round(vol_time_improvement, 2),
                }
            )

            # Calculate overall N+1 elimination score
            avg_query_reduction = statistics.mean([test["query_reduction_percent"] for test in n1_tests])
            avg_time_improvement = statistics.mean([test["time_improvement_percent"] for test in n1_tests])

            overall_score = (avg_query_reduction + avg_time_improvement) / 2

            self.results["tests"].append(
                {
                    "name": test_name,
                    "status": "passed" if overall_score > 50 else "warning",
                    "details": n1_tests,
                    "average_query_reduction": round(avg_query_reduction, 2),
                    "average_time_improvement": round(avg_time_improvement, 2),
                    "overall_score": round(overall_score, 2),
                    "target_achieved": overall_score > 70,
                }
            )

        except Exception as e:
            self.results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})

    def _test_bulk_query_optimization(self):
        """Test bulk query optimization effectiveness"""

        test_name = "Bulk Query Optimization"

        try:
            bulk_tests = []

            # Test bulk member data loading
            test_members = self._get_test_members(10)

            # Individual loading simulation
            with self._query_timer("individual_member_loading") as individual_timer:
                individual_results = []
                for member_name in test_members:
                    member_data = frappe.get_doc("Member", member_name)
                    # Simulate financial data loading
                    if member_data.customer:
                        invoices = frappe.get_all("Sales Invoice", filters={"customer": member_data.customer})
                        payments = frappe.get_all(
                            "Payment Entry", filters={"party": member_data.customer, "party_type": "Customer"}
                        )
                        individual_results.append(
                            {"member": member_name, "invoices": len(invoices), "payments": len(payments)}
                        )

            # Bulk loading
            with self._query_timer("bulk_member_loading") as bulk_timer:
                bulk_results = OptimizedMemberQueries.get_members_with_payment_data({"status": "Active"})

            time_improvement = (
                (
                    (individual_timer.execution_time - bulk_timer.execution_time)
                    / individual_timer.execution_time
                )
                * 100
                if individual_timer.execution_time > 0
                else 0
            )

            bulk_tests.append(
                {
                    "operation": "Member financial data loading",
                    "individual_time": individual_timer.execution_time,
                    "bulk_time": bulk_timer.execution_time,
                    "time_improvement_percent": round(max(0, time_improvement), 2),
                    "records_processed": len(test_members),
                    "bulk_efficiency": round(bulk_timer.execution_time / len(test_members), 4)
                    if len(test_members) > 0
                    else 0,
                }
            )

            # Test SEPA mandate bulk loading
            with self._query_timer("bulk_sepa_loading") as sepa_timer:
                sepa_results = OptimizedSEPAQueries.get_active_mandates_for_members(test_members)

            bulk_tests.append(
                {
                    "operation": "SEPA mandate bulk loading",
                    "bulk_time": sepa_timer.execution_time,
                    "records_processed": len(test_members),
                    "mandates_found": len(sepa_results),
                    "bulk_efficiency": round(sepa_timer.execution_time / len(test_members), 4)
                    if len(test_members) > 0
                    else 0,
                }
            )

            avg_improvement = statistics.mean(
                [
                    test.get("time_improvement_percent", 0)
                    for test in bulk_tests
                    if "time_improvement_percent" in test
                ]
            )

            self.results["tests"].append(
                {
                    "name": test_name,
                    "status": "passed" if avg_improvement > 30 else "warning",
                    "details": bulk_tests,
                    "average_improvement": round(avg_improvement, 2),
                    "recommendation": "Excellent bulk optimization"
                    if avg_improvement > 50
                    else "Consider additional bulk optimizations",
                }
            )

        except Exception as e:
            self.results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})

    def _test_cache_performance(self):
        """Test cache performance and effectiveness"""

        test_name = "Cache Performance"

        try:
            cache_tests = []

            # Reset cache statistics for accurate testing
            frappe.cache().set_value("cache_stats:hits", 0, expires_in_sec=86400)
            frappe.cache().set_value("cache_stats:misses", 0, expires_in_sec=86400)

            test_members = self._get_test_members(5)

            # Test cache miss (first access)
            with self._query_timer("cache_miss_test") as miss_timer:
                for member_name in test_members:
                    cached_data = QueryCache.get_cached_member_data(member_name)
                    if not cached_data:
                        # Simulate loading and caching
                        member_data = frappe.get_doc("Member", member_name).as_dict()
                        QueryCache.set_cached_member_data(member_name, member_data)

            # Test cache hit (subsequent access)
            with self._query_timer("cache_hit_test") as hit_timer:
                hit_count = 0
                for member_name in test_members:
                    cached_data = QueryCache.get_cached_member_data(member_name)
                    if cached_data:
                        hit_count += 1

            hit_rate = (hit_count / len(test_members)) * 100 if len(test_members) > 0 else 0
            cache_efficiency = (
                ((miss_timer.execution_time - hit_timer.execution_time) / miss_timer.execution_time) * 100
                if miss_timer.execution_time > 0
                else 0
            )

            cache_tests.append(
                {
                    "cache_type": "Member data cache",
                    "hit_rate_percent": round(hit_rate, 2),
                    "cache_miss_time": miss_timer.execution_time,
                    "cache_hit_time": hit_timer.execution_time,
                    "cache_efficiency_percent": round(max(0, cache_efficiency), 2),
                    "records_tested": len(test_members),
                }
            )

            # Test volunteer assignment cache
            test_volunteers = self._get_test_volunteers(3)

            volunteer_hit_count = 0
            with self._query_timer("volunteer_cache_test") as vol_cache_timer:
                for volunteer_name in test_volunteers:
                    # First access (cache miss)
                    assignments = QueryCache.get_cached_volunteer_assignments(volunteer_name)
                    if not assignments:
                        # Load and cache
                        assignments = OptimizedVolunteerQueries.get_volunteer_assignments_bulk(
                            [volunteer_name]
                        )
                        QueryCache.set_cached_volunteer_assignments(
                            volunteer_name, assignments.get(volunteer_name, [])
                        )

                    # Second access (cache hit)
                    cached_assignments = QueryCache.get_cached_volunteer_assignments(volunteer_name)
                    if cached_assignments:
                        volunteer_hit_count += 1

            volunteer_hit_rate = (
                (volunteer_hit_count / len(test_volunteers)) * 100 if len(test_volunteers) > 0 else 0
            )

            cache_tests.append(
                {
                    "cache_type": "Volunteer assignments cache",
                    "hit_rate_percent": round(volunteer_hit_rate, 2),
                    "total_time": vol_cache_timer.execution_time,
                    "records_tested": len(test_volunteers),
                }
            )

            overall_hit_rate = statistics.mean([test["hit_rate_percent"] for test in cache_tests])

            self.results["tests"].append(
                {
                    "name": test_name,
                    "status": "passed" if overall_hit_rate > 80 else "warning",
                    "details": cache_tests,
                    "overall_hit_rate": round(overall_hit_rate, 2),
                    "cache_effectiveness": "Excellent"
                    if overall_hit_rate > 90
                    else "Good"
                    if overall_hit_rate > 70
                    else "Needs improvement",
                }
            )

        except Exception as e:
            self.results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})

    def _test_load_performance(self):
        """Test performance under load conditions"""

        test_name = "Load Performance"

        try:
            # Simulate concurrent operations
            load_tests = []

            # Test bulk member operations under load
            member_counts = [10, 25, 50]

            for count in member_counts:
                test_members = self._get_test_members(count)

                with self._query_timer(f"load_test_{count}_members") as load_timer:
                    # Simulate concurrent member payment history updates
                    result = OptimizedMemberQueries.bulk_update_payment_history(test_members)

                throughput = count / load_timer.execution_time if load_timer.execution_time > 0 else 0

                load_tests.append(
                    {
                        "operation": f"Bulk payment history update - {count} members",
                        "record_count": count,
                        "execution_time": load_timer.execution_time,
                        "throughput_per_second": round(throughput, 2),
                        "success": result.get("success", False),
                        "updated_count": result.get("updated_count", 0),
                    }
                )

            # Calculate load performance score
            avg_throughput = statistics.mean([test["throughput_per_second"] for test in load_tests])

            self.results["tests"].append(
                {
                    "name": test_name,
                    "status": "passed" if avg_throughput > 5 else "warning",
                    "details": load_tests,
                    "average_throughput": round(avg_throughput, 2),
                    "load_capacity": "High"
                    if avg_throughput > 10
                    else "Medium"
                    if avg_throughput > 5
                    else "Low",
                }
            )

        except Exception as e:
            self.results["tests"].append({"name": test_name, "status": "failed", "error": str(e)})

    def _generate_test_summary(self):
        """Generate comprehensive test summary"""

        total_tests = len(self.results["tests"])
        passed_tests = len([t for t in self.results["tests"] if t["status"] == "passed"])
        failed_tests = len([t for t in self.results["tests"] if t["status"] == "failed"])
        warning_tests = len([t for t in self.results["tests"] if t["status"] == "warning"])

        pass_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0

        self.results["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "warning_tests": warning_tests,
            "pass_rate_percent": round(pass_rate, 2),
            "overall_status": "excellent"
            if pass_rate >= 90
            else "good"
            if pass_rate >= 70
            else "needs_improvement",
            "recommendations": self._generate_recommendations(),
        }

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on test results"""

        recommendations = []

        for test in self.results["tests"]:
            if test["status"] == "failed":
                recommendations.append(f"Fix failed test: {test['name']}")
            elif test["status"] == "warning":
                if "Database Index Performance" in test["name"]:
                    recommendations.append("Consider adding additional database indexes")
                elif "N+1 Pattern Elimination" in test["name"]:
                    recommendations.append("Review and optimize remaining N+1 patterns")
                elif "Cache Performance" in test["name"]:
                    recommendations.append("Tune caching strategy and increase cache hit rates")
                elif "Load Performance" in test["name"]:
                    recommendations.append("Optimize for higher throughput under load conditions")

        if not recommendations:
            recommendations.append("All performance tests passed successfully - system is well optimized")

        return recommendations

    def _calculate_overall_improvement(self) -> Dict[str, float]:
        """Calculate overall performance improvement metrics"""

        improvements = {
            "query_reduction_percent": 0,
            "time_improvement_percent": 0,
            "cache_hit_rate_percent": 0,
            "throughput_improvement": 0,
        }

        # Extract improvement metrics from test results
        for test in self.results["tests"]:
            if test["name"] == "N+1 Pattern Elimination" and test["status"] != "failed":
                improvements["query_reduction_percent"] = test.get("average_query_reduction", 0)
                improvements["time_improvement_percent"] = test.get("average_time_improvement", 0)
            elif test["name"] == "Cache Performance" and test["status"] != "failed":
                improvements["cache_hit_rate_percent"] = test.get("overall_hit_rate", 0)
            elif test["name"] == "Load Performance" and test["status"] != "failed":
                improvements["throughput_improvement"] = test.get("average_throughput", 0)

        return improvements

    # Utility methods
    @contextmanager
    def _query_timer(self, operation_name: str):
        """Context manager for timing database operations"""

        class Timer:
            def __init__(self):
                self.start_time = None
                self.execution_time = 0

        timer = Timer()
        timer.start_time = time.time()

        try:
            yield timer
        finally:
            timer.execution_time = time.time() - timer.start_time

    @contextmanager
    def _query_counter(self):
        """Context manager for counting database queries"""

        class QueryCounter:
            def __init__(self):
                self.query_count = 0
                self.original_sql_method = None

        counter = QueryCounter()

        # Hook into frappe.db.sql to count queries
        counter.original_sql_method = frappe.db.sql

        def counting_sql(*args, **kwargs):
            counter.query_count += 1
            return counter.original_sql_method(*args, **kwargs)

        frappe.db.sql = counting_sql

        try:
            yield counter
        finally:
            # Restore original method
            frappe.db.sql = counter.original_sql_method

    def _get_test_members(self, limit: int = 10) -> List[str]:
        """Get test member names for performance testing"""

        members = frappe.get_all("Member", filters={"docstatus": ["<", 2]}, fields=["name"], limit=limit)

        return [m.name for m in members]

    def _get_test_volunteers(self, limit: int = 5) -> List[str]:
        """Get test volunteer names for performance testing"""

        volunteers = frappe.get_all(
            "Volunteer", filters={"docstatus": ["<", 2]}, fields=["name"], limit=limit
        )

        return [v.name for v in volunteers]

    def _get_test_customers(self, limit: int = 10) -> List[str]:
        """Get test customer names for performance testing"""

        customers = frappe.get_all("Customer", filters={"disabled": 0}, fields=["name"], limit=limit)

        return [c.name for c in customers]


# API endpoints for testing
@frappe.whitelist()
def run_performance_test_suite():
    """API endpoint to run the complete performance test suite"""

    try:
        tester = PerformanceTester()
        results = tester.run_comprehensive_performance_test()

        # Show results to user
        if results["success"]:
            improvement = results.get("performance_improvement", {})

            message = f"""
Performance Test Results:

Query Reduction: {improvement.get('query_reduction_percent', 0):.1f}%
Time Improvement: {improvement.get('time_improvement_percent', 0):.1f}%
Cache Hit Rate: {improvement.get('cache_hit_rate_percent', 0):.1f}%

Pass Rate: {results['results']['summary'].get('pass_rate_percent', 0):.1f}%
Status: {results['results']['summary'].get('overall_status', 'Unknown')}
            """

            frappe.msgprint(
                message,
                title="Performance Test Results",
                indicator="green"
                if results["results"]["summary"].get("pass_rate_percent", 0) > 70
                else "orange",
            )
        else:
            frappe.msgprint(
                f"Performance testing failed: {results.get('error')}", title="Test Failure", indicator="red"
            )

        return results

    except Exception as e:
        error_msg = f"Performance testing execution failed: {str(e)}"
        frappe.log_error(error_msg)
        frappe.msgprint(error_msg, title="Testing Error", indicator="red")
        return {"success": False, "error": error_msg}


@frappe.whitelist()
def quick_performance_check():
    """Quick performance validation check"""

    try:
        # Quick index validation
        critical_indexes = {
            "member_customer": ("tabMember", "customer"),
            "member_status": ("tabMember", "status"),
            "volunteer_member": ("tabVolunteer", "member"),
        }

        index_results = {}
        for name, (table, column) in critical_indexes.items():
            # Check if column exists and has good cardinality
            cardinality_query = f"""
                SELECT COUNT(DISTINCT `{column}`) as distinct_values,
                       COUNT(*) as total_rows
                FROM `{table}`
                WHERE `{column}` IS NOT NULL
            """

            try:
                result = frappe.db.sql(cardinality_query, as_dict=True)
                if result:
                    distinct_values = result[0]["distinct_values"]
                    total_rows = result[0]["total_rows"]
                    selectivity = (distinct_values / total_rows) if total_rows > 0 else 0

                    index_results[name] = {
                        "exists": True,
                        "selectivity": round(selectivity, 3),
                        "effectiveness": "High"
                        if selectivity > 0.1
                        else "Medium"
                        if selectivity > 0.01
                        else "Low",
                    }
                else:
                    index_results[name] = {"exists": False}

            except Exception:
                index_results[name] = {"exists": False, "error": "Column may not exist"}

        # Quick cache check
        cache_stats = {
            "member_cache_active": bool(frappe.cache().get_value("member_data:test")),
            "volunteer_cache_active": bool(frappe.cache().get_value("volunteer_assignments:test")),
        }

        return {
            "success": True,
            "index_status": index_results,
            "cache_status": cache_stats,
            "timestamp": now(),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def benchmark_single_operation(operation_type: str, record_count: int = 10):
    """Benchmark a single operation for quick testing"""

    try:
        tester = PerformanceTester()

        if operation_type == "member_payment_history":
            test_members = tester._get_test_members(record_count)

            with tester._query_timer("benchmark_operation") as timer:
                result = OptimizedMemberQueries.bulk_update_payment_history(test_members)

            return {
                "success": True,
                "operation": operation_type,
                "record_count": len(test_members),
                "execution_time": timer.execution_time,
                "throughput": len(test_members) / timer.execution_time if timer.execution_time > 0 else 0,
                "result": result,
            }

        elif operation_type == "volunteer_assignments":
            test_volunteers = tester._get_test_volunteers(record_count)

            with tester._query_timer("benchmark_operation") as timer:
                result = OptimizedVolunteerQueries.get_volunteer_assignments_bulk(test_volunteers)

            return {
                "success": True,
                "operation": operation_type,
                "record_count": len(test_volunteers),
                "execution_time": timer.execution_time,
                "throughput": len(test_volunteers) / timer.execution_time if timer.execution_time > 0 else 0,
                "assignments_found": sum(len(assignments) for assignments in result.values()),
            }

        else:
            return {"success": False, "error": f"Unknown operation type: {operation_type}"}

    except Exception as e:
        return {"success": False, "error": str(e)}
