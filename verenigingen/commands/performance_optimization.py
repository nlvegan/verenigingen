#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Performance Optimization Management Commands
===========================================

Command-line utilities for managing and monitoring database performance
optimizations in the Verenigingen application.

Commands:
- bench --site [site] execute verenigingen.commands.performance_optimization.apply_optimizations
- bench --site [site] execute verenigingen.commands.performance_optimization.check_optimization_status
- bench --site [site] execute verenigingen.commands.performance_optimization.analyze_query_performance

Usage Examples:
- Apply all performance optimizations:
  bench --site dev.veganisme.net execute verenigingen.commands.performance_optimization.apply_optimizations

- Check current optimization status:
  bench --site dev.veganisme.net execute verenigingen.commands.performance_optimization.check_optimization_status

- Run performance analysis:
  bench --site dev.veganisme.net execute verenigingen.commands.performance_optimization.analyze_query_performance
"""

import time
from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.utils.constants import Roles
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
)


@frappe.whitelist(allow_guest=False)
@critical_api(operation_type=OperationType.ADMIN)
def apply_optimizations():
    """Apply all performance optimizations to the database"""

    if Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can apply performance optimizations"))

    print("🚀 APPLYING PERFORMANCE OPTIMIZATIONS")
    print("=" * 50)

    start_time = time.time()

    try:
        from verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup import (
            run_performance_optimization,
        )

        result = run_performance_optimization()

        execution_time = time.time() - start_time

        if result.get("success"):
            print(f"✅ Performance optimizations completed successfully in {execution_time:.2f}s")
            print(f"   {result.get('message', 'All optimizations applied')}")
        else:
            print(f"❌ Performance optimization failed after {execution_time:.2f}s")
            print(f"   Error: {result.get('error', 'Unknown error')}")

        return result

    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"Performance optimization failed after {execution_time:.2f}s: {str(e)}"
        print(f"❌ {error_msg}")
        frappe.logger().error(error_msg)
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.ADMIN)
def check_optimization_status():
    """Check the current status of performance optimizations"""

    print("📊 PERFORMANCE OPTIMIZATION STATUS")
    print("=" * 50)

    try:
        # Check optimization setup status
        from verenigingen.verenigingen.doctype.performance_optimization_setup.performance_optimization_setup import (
            get_optimization_status,
        )

        status = get_optimization_status()

        if status.get("applied"):
            print(f"✅ Performance optimizations: {status.get('status', 'Applied')}")
            if status.get("completion_date"):
                print(f"   Completion Date: {status.get('completion_date')}")
        else:
            print("❌ Performance optimizations: Not Applied")
            if status.get("error"):
                print(f"   Error: {status.get('error')}")

        # Check caching status
        from verenigingen.utils.performance_cache import PerformanceCache

        cache = PerformanceCache()
        cache_stats = cache.get_cache_stats()

        print("\n📋 CACHING STATUS")
        print(f"   Enabled: {'✅' if cache_stats.get('enabled') else '❌'}")
        if cache_stats.get("enabled"):
            print(f"   Backend: {cache_stats.get('backend', 'Unknown')}")
            if cache_stats.get("categories"):
                print("   Cached Categories:")
                for category, count in cache_stats.get("categories", {}).items():
                    print(f"     - {category}: {count} keys")

        # Check database indexes
        critical_indexes = _check_critical_indexes()

        print("\n🔍 CRITICAL DATABASE INDEXES")
        for table, index_info in critical_indexes.items():
            status_icon = "✅" if index_info["has_optimized_indexes"] else "⚠️"
            print(f"   {status_icon} {table}: {index_info['index_count']} indexes")
            if not index_info["has_optimized_indexes"]:
                print(f"      Missing recommended indexes: {', '.join(index_info['missing_indexes'])}")

        return {"optimization_status": status, "cache_stats": cache_stats, "index_status": critical_indexes}

    except Exception as e:
        error_msg = f"Status check failed: {str(e)}"
        print(f"❌ {error_msg}")
        frappe.logger().error(error_msg)
        return {"success": False, "error": str(e)}


@frappe.whitelist(allow_guest=False)
@high_security_api(operation_type=OperationType.ADMIN)
def analyze_query_performance():
    """Analyze current query performance and identify bottlenecks"""

    if Roles.SYSTEM_MANAGER not in frappe.get_roles():
        frappe.throw(_("Only System Managers can run performance analysis"))

    print("🔬 QUERY PERFORMANCE ANALYSIS")
    print("=" * 50)

    try:
        # Sample key queries from our optimizations and measure performance
        performance_tests = [
            {
                "name": "Chapter Member Lookup",
                "description": "Test batch chapter member queries",
                "test_function": _test_chapter_member_performance,
            },
            {
                "name": "Payment History Query",
                "description": "Test payment entry queries",
                "test_function": _test_payment_query_performance,
            },
            {
                "name": "Membership Status Query",
                "description": "Test membership queries",
                "test_function": _test_membership_query_performance,
            },
        ]

        results = []

        for test in performance_tests:
            print(f"\n🧪 Running: {test['name']}")
            print(f"   {test['description']}")

            start_time = time.time()
            try:
                test_result = test["test_function"]()
                execution_time = time.time() - start_time

                print(f"   ✅ Completed in {execution_time:.3f}s")
                if test_result.get("record_count"):
                    print(f"   📊 Processed {test_result.get('record_count')} records")

                results.append(
                    {
                        "test": test["name"],
                        "success": True,
                        "execution_time": execution_time,
                        "details": test_result,
                    }
                )

            except Exception as e:
                execution_time = time.time() - start_time
                print(f"   ❌ Failed after {execution_time:.3f}s: {str(e)}")

                results.append(
                    {
                        "test": test["name"],
                        "success": False,
                        "execution_time": execution_time,
                        "error": str(e),
                    }
                )

        # Summary
        successful_tests = [r for r in results if r["success"]]
        total_time = sum(r["execution_time"] for r in results)

        print("\n📈 PERFORMANCE ANALYSIS SUMMARY")
        print(f"   Total Tests: {len(results)}")
        print(f"   Successful: {len(successful_tests)}")
        print(f"   Total Execution Time: {total_time:.3f}s")
        print(f"   Average Test Time: {total_time / len(results):.3f}s")

        return {
            "success": True,
            "test_results": results,
            "summary": {
                "total_tests": len(results),
                "successful_tests": len(successful_tests),
                "total_time": total_time,
                "average_time": total_time / len(results),
            },
        }

    except Exception as e:
        error_msg = f"Performance analysis failed: {str(e)}"
        print(f"❌ {error_msg}")
        frappe.logger().error(error_msg)
        return {"success": False, "error": str(e)}


def _check_critical_indexes() -> Dict[str, Dict]:
    """Check if critical performance indexes exist"""

    critical_tables = {
        "tabChapter Member": {
            "recommended_indexes": ["idx_member_status_creation", "idx_parent_status_enabled"]
        },
        "tabPayment Entry": {
            "recommended_indexes": ["idx_party_type_party_docstatus", "idx_party_posting_date_desc"]
        },
        "tabMember": {"recommended_indexes": ["idx_customer_docstatus", "idx_status_member_since"]},
        "tabMembership": {
            "recommended_indexes": ["idx_member_status_start_date", "idx_member_creation_desc"]
        },
    }

    results = {}

    for table, config in critical_tables.items():
        try:
            # Get existing indexes
            indexes = frappe.db.sql(f"SHOW INDEX FROM `{table}`", as_dict=True)
            existing_index_names = {idx["Key_name"] for idx in indexes}

            # Check which recommended indexes exist
            missing_indexes = [
                idx for idx in config["recommended_indexes"] if idx not in existing_index_names
            ]

            results[table] = {
                "index_count": len(existing_index_names),
                "has_optimized_indexes": len(missing_indexes) == 0,
                "missing_indexes": missing_indexes,
                "existing_indexes": list(existing_index_names),
            }

        except Exception as e:
            results[table] = {
                "error": str(e),
                "has_optimized_indexes": False,
                "missing_indexes": config["recommended_indexes"],
            }

    return results


def _test_chapter_member_performance() -> Dict:
    """Test chapter member query performance"""

    # Get a sample of members to test with
    sample_members = frappe.get_all("Member", fields=["name"], limit=50)

    if not sample_members:
        return {"record_count": 0, "note": "No members found for testing"}

    member_names = [m.name for m in sample_members]

    # Test the optimized batch query
    chapter_memberships = frappe.db.sql(
        """
        SELECT cm.member, cm.parent as chapter_name
        FROM `tabChapter Member` cm
        WHERE cm.member IN %(member_names)s
        AND cm.status = 'Active'
        ORDER BY cm.member, cm.creation DESC
    """,
        {"member_names": member_names},
        as_dict=True,
    )

    return {
        "record_count": len(sample_members),
        "chapter_memberships_found": len(chapter_memberships),
        "query_type": "Optimized batch query",
    }


def _test_payment_query_performance() -> Dict:
    """Test payment entry query performance"""

    # Get a sample of customers to test with
    sample_customers = frappe.get_all("Customer", fields=["name"], limit=20)

    if not sample_customers:
        return {"record_count": 0, "note": "No customers found for testing"}

    customer_names = [c.name for c in sample_customers]

    # Test the optimized payment date query
    last_payments = frappe.db.sql(
        """
        SELECT
            pe.party as customer,
            MAX(pe.posting_date) as last_payment_date
        FROM `tabPayment Entry` pe
        WHERE pe.party_type = 'Customer'
            AND pe.party IN %(customer_names)s
            AND pe.docstatus = 1
        GROUP BY pe.party
    """,
        {"customer_names": customer_names},
        as_dict=True,
    )

    return {
        "record_count": len(sample_customers),
        "payments_found": len(last_payments),
        "query_type": "Optimized batch payment query",
    }


def _test_membership_query_performance() -> Dict:
    """Test membership query performance"""

    # Get a sample of members to test with
    sample_members = frappe.get_all("Member", fields=["name"], limit=30)

    if not sample_members:
        return {"record_count": 0, "note": "No members found for testing"}

    member_names = [m.name for m in sample_members]

    # Test the optimized membership query
    memberships = frappe.get_all(
        "Membership",
        filters={"member": ["in", member_names], "status": "Active"},
        fields=["member", "membership_type", "grace_period_status"],
    )

    return {
        "record_count": len(sample_members),
        "memberships_found": len(memberships),
        "query_type": "Optimized batch membership query",
    }
