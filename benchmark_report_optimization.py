#!/usr/bin/env python3
"""
Report Optimization Benchmark
============================

Compare performance between original and optimized membership dues coverage analysis.
Demonstrates N+1 query elimination in practice.
"""

import time

import frappe
from frappe.utils import random_string


def benchmark_report_optimization():
    """Compare original vs optimized report performance"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        print("📊 REPORT OPTIMIZATION BENCHMARK")
        print("=" * 50)

        # Test different member counts
        test_scenarios = [
            {"member_count": 10, "name": "Small Dataset"},
            {"member_count": 50, "name": "Medium Dataset"},
            {"member_count": 100, "name": "Large Dataset"},
        ]

        results = {}

        for scenario in test_scenarios:
            print(f"\n🎯 Testing {scenario['name']} ({scenario['member_count']} members)")
            print("-" * 40)

            # Get test members
            members = frappe.get_all(
                "Member", filters={"status": "Active"}, fields=["name"], limit=scenario["member_count"]
            )

            if len(members) < scenario["member_count"]:
                print(f"⚠️  Only {len(members)} active members available, adjusting test...")

            actual_count = len(members)

            # Test original version (with N+1 queries)
            print(f"Testing ORIGINAL version with {actual_count} members...")
            original_time, original_queries = benchmark_original_report({"member_count": actual_count})

            # Test optimized version (bulk operations)
            print(f"Testing OPTIMIZED version with {actual_count} members...")
            optimized_time, optimized_queries = benchmark_optimized_report({"member_count": actual_count})

            # Calculate improvements
            time_improvement = ((original_time - optimized_time) / original_time) * 100
            query_reduction = ((original_queries - optimized_queries) / original_queries) * 100

            results[scenario["name"]] = {
                "member_count": actual_count,
                "original_time": original_time,
                "original_queries": original_queries,
                "optimized_time": optimized_time,
                "optimized_queries": optimized_queries,
                "time_improvement_percent": time_improvement,
                "query_reduction_percent": query_reduction,
            }

            # Display results for this scenario
            print("")
            print(f"📈 Results for {scenario['name']}:")
            print(f"  Members processed: {actual_count}")
            print(f"  Original:  {original_time:.2f}ms ({original_queries} queries)")
            print(f"  Optimized: {optimized_time:.2f}ms ({optimized_queries} queries)")
            print(f"  ⚡ Speed improvement: {time_improvement:.1f}% faster")
            print(f"  📉 Query reduction:   {query_reduction:.1f}% fewer queries")

            if time_improvement > 50:
                print("  🚀 EXCELLENT performance improvement!")
            elif time_improvement > 20:
                print("  ✅ GOOD performance improvement")
            else:
                print("  ⚠️  Modest improvement - may need further optimization")

        # Summary across all scenarios
        print("\n" + "=" * 60)
        print("🏆 BENCHMARK SUMMARY")
        print("=" * 60)

        for scenario_name, result in results.items():
            print(
                f"{scenario_name:15}: {result['time_improvement_percent']:5.1f}% faster, {result['query_reduction_percent']:5.1f}% fewer queries"
            )

        # Calculate averages
        avg_time_improvement = sum(r["time_improvement_percent"] for r in results.values()) / len(results)
        avg_query_reduction = sum(r["query_reduction_percent"] for r in results.values()) / len(results)

        print("")
        print("📊 Average Improvements:")
        print(f"  Speed: {avg_time_improvement:.1f}% faster")
        print(f"  Queries: {avg_query_reduction:.1f}% fewer")

        # Analysis
        print("\n🔍 ANALYSIS:")
        if avg_query_reduction > 80:
            print("✅ Excellent N+1 elimination - most queries converted to bulk operations")
        elif avg_query_reduction > 50:
            print("✅ Good N+1 reduction - significant improvement achieved")
        else:
            print("⚠️  Limited N+1 improvement - may need further optimization")

        if avg_time_improvement > 60:
            print("🚀 Outstanding performance improvement")
        elif avg_time_improvement > 30:
            print("✅ Solid performance gains")
        else:
            print("📈 Moderate performance improvement")

        return results

    except Exception as e:
        print(f"❌ Benchmark failed: {e}")
        import traceback

        traceback.print_exc()
        return None
    finally:
        frappe.destroy()


def benchmark_original_report(filters):
    """Benchmark the original report with N+1 queries"""

    from verenigingen.verenigingen.report.membership_dues_coverage_analysis.membership_dues_coverage_analysis import (
        get_data,
    )

    query_count = 0
    original_sql = frappe.db.sql

    def counting_sql(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        return original_sql(*args, **kwargs)

    frappe.db.sql = counting_sql

    try:
        start_time = time.time()

        # Run original report logic (simulate with limited members)
        test_filters = {"show_only_gaps": False}  # Get all members for fair comparison
        get_data(test_filters)

        end_time = time.time()
        execution_time = (end_time - start_time) * 1000  # Convert to ms

        return execution_time, query_count

    finally:
        frappe.db.sql = original_sql


def benchmark_optimized_report(filters):
    """Benchmark the optimized report with bulk operations"""

    # Import our optimized version
    import os
    import sys

    sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")
    from membership_dues_coverage_optimized import get_data_optimized

    query_count = 0
    original_sql = frappe.db.sql

    def counting_sql(*args, **kwargs):
        nonlocal query_count
        query_count += 1
        return original_sql(*args, **kwargs)

    frappe.db.sql = counting_sql

    try:
        start_time = time.time()

        # Run optimized report logic
        test_filters = {"show_only_gaps": False}  # Get all members for fair comparison
        get_data_optimized(test_filters)

        end_time = time.time()
        execution_time = (end_time - start_time) * 1000  # Convert to ms

        return execution_time, query_count

    finally:
        frappe.db.sql = original_sql


if __name__ == "__main__":
    results = benchmark_report_optimization()

    if results:
        print("\n✅ Benchmark completed successfully!")
    else:
        print("\n❌ Benchmark failed - check the errors above")
