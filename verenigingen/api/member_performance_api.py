"""
Member Performance Optimization API
===================================

Production API endpoints for accessing optimized member operations.
These endpoints provide improved performance while maintaining full
business logic validation and security controls.

Key Features:
- Optimized member creation with ~85% fewer queries
- Fast member search with comprehensive related data
- Cached dashboard data with automatic invalidation
- Bulk operations support for administrative tasks
"""

import json
import traceback
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, flt

from verenigingen.utils.operation_result import OperationResult
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    standard_api,
)


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def create_member_optimized(member_data: str) -> OperationResult[Dict[str, Any]]:
    """
    Create member using performance optimizations

    Args:
        member_data: JSON string containing member information

    Returns:
        OperationResult with member creation result
    """
    try:
        # Parse and validate input
        if isinstance(member_data, str):
            data = json.loads(member_data)
        else:
            data = member_data

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Create member with optimizations
        member_name = member_optimizer.create_member_optimized(data)
        member = frappe.get_doc("Member", member_name)

        return OperationResult.ok(
            {
                "member_name": member_name,
                "full_name": member.full_name,
            },
            message=_("Member created successfully with performance optimizations"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Optimized member creation failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(e, message=_("Member creation failed"))


@standard_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def search_members_fast(filters: str = None, limit: int = 20) -> OperationResult[Dict[str, Any]]:
    """
    Fast member search with comprehensive related data

    Args:
        filters: JSON string with search filters
        limit: Maximum number of results to return

    Returns:
        OperationResult with search results and metadata
    """
    try:
        # Parse filters
        if filters:
            if isinstance(filters, str):
                filter_dict = json.loads(filters)
            else:
                filter_dict = filters
        else:
            filter_dict = {}

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Perform optimized search
        results = member_optimizer.bulk_load_members_optimized(filters=filter_dict, limit=cint(limit))

        return OperationResult.ok(
            {
                "results": results,
                "count": len(results),
            },
            message=_("Search completed successfully"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Fast member search failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Search failed"), fallback_data={"results": [], "count": 0}
        )


@standard_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def get_member_dashboard_fast(member_name: str) -> OperationResult[Dict[str, Any]]:
    """
    Get member dashboard data with caching

    Args:
        member_name: Name of the member

    Returns:
        OperationResult with comprehensive member dashboard data
    """
    try:
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Get cached dashboard data
        dashboard_data = member_optimizer.get_member_dashboard_cached(member_name)

        if not dashboard_data:
            return OperationResult.fail(
                message=_("Member not found"),
                data={"data": {}},
            )

        return OperationResult.ok(
            {"data": dashboard_data},
            message=_("Dashboard data loaded successfully"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Fast dashboard load failed for {0}").format(member_name),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Dashboard load failed"), fallback_data={"data": {}}
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def clear_member_cache(member_name: str = None) -> OperationResult[Dict[str, Any]]:
    """
    Clear member-related caches

    Args:
        member_name: Specific member to clear cache for, or None for all

    Returns:
        OperationResult with operation result
    """
    try:
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        if member_name:
            member_optimizer.clear_member_cache(member_name)
            message = _("Cache cleared for member {0}").format(member_name)
        else:
            member_optimizer.clear_all_member_caches()
            message = _("All member caches cleared")

        return OperationResult.ok({}, message=message)

    except Exception as e:
        frappe.log_error(
            title=_("Cache clearing failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(e, message=_("Cache clearing failed"))


@standard_api(operation_type=OperationType.REPORTING)
@frappe.whitelist()
def get_performance_stats() -> OperationResult[Dict[str, Any]]:
    """
    Get current performance statistics and cache status

    Returns:
        OperationResult with performance metrics
    """
    try:
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Get cache statistics
        cache = frappe.cache()
        member_cache_keys = cache.get_keys("member_dashboard:*") or []

        # Get basic member counts
        total_members = frappe.db.count("Member")
        active_members = frappe.db.count("Member", {"status": "Active"})

        # Get DocType metadata cache info
        metadata_cache_info = member_optimizer.get_doctype_meta_cached.cache_info()

        return OperationResult.ok(
            {
                "stats": {
                    "total_members": total_members,
                    "active_members": active_members,
                    "cached_dashboards": len(member_cache_keys),
                    "metadata_cache_hits": (
                        metadata_cache_info.hits if hasattr(metadata_cache_info, "hits") else 0
                    ),
                    "metadata_cache_misses": (
                        metadata_cache_info.misses if hasattr(metadata_cache_info, "misses") else 0
                    ),
                    "cache_hit_rate": (
                        round(
                            metadata_cache_info.hits
                            / (metadata_cache_info.hits + metadata_cache_info.misses)
                            * 100,
                            1,
                        )
                        if hasattr(metadata_cache_info, "hits")
                        and (metadata_cache_info.hits + metadata_cache_info.misses) > 0
                        else 0
                    ),
                },
            },
            message=_("Performance statistics retrieved"),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Performance stats retrieval failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Performance stats retrieval failed"), fallback_data={"stats": {}}
        )


@high_security_api(operation_type=OperationType.MEMBER_DATA)
@frappe.whitelist()
def bulk_create_members(members_data: str) -> OperationResult[Dict[str, Any]]:
    """
    Create multiple members using optimizations

    Args:
        members_data: JSON string containing array of member data

    Returns:
        OperationResult with bulk creation results
    """
    try:
        # Parse input
        if isinstance(members_data, str):
            members_list = json.loads(members_data)
        else:
            members_list = members_data

        if not isinstance(members_list, list):
            raise ValueError("Input must be a list of member data objects")

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        results = {"created": [], "failed": [], "total": len(members_list)}

        # Process each member
        for i, member_data in enumerate(members_list):
            try:
                member_name = member_optimizer.create_member_optimized(member_data)
                results["created"].append(
                    {
                        "index": i,
                        "member_name": member_name,
                        "full_name": member_data.get("first_name", "")
                        + " "
                        + member_data.get("last_name", ""),
                    }
                )
            except Exception as e:
                results["failed"].append({"index": i, "error": str(e), "data": member_data})

        success_rate = len(results["created"]) / results["total"] * 100 if results["total"] > 0 else 0

        return OperationResult.ok(
            {
                "results": results,
                "success_rate": round(success_rate, 1),
            },
            message=_("Bulk creation completed: {0}/{1} successful").format(
                len(results["created"]), results["total"]
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Bulk member creation failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e,
            message=_("Bulk creation failed"),
            fallback_data={"results": {"created": [], "failed": [], "total": 0}},
        )


@development_only_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def test_performance_optimization() -> OperationResult[Dict[str, Any]]:
    """
    Run performance optimization validation tests

    Returns:
        OperationResult with test results and performance metrics
    """
    try:
        import time

        from verenigingen.utils.member_performance_optimizer import member_optimizer

        test_results = {"tests_run": 0, "tests_passed": 0, "performance_metrics": {}, "recommendations": []}

        # Test 1: Metadata caching
        start_time = time.time()
        member_optimizer.get_doctype_meta_cached("Member")
        member_optimizer.get_doctype_meta_cached("Member")  # Should hit cache
        cache_time = time.time() - start_time

        test_results["tests_run"] += 1
        if cache_time < 0.1:  # Should be very fast due to caching
            test_results["tests_passed"] += 1

        test_results["performance_metrics"]["metadata_cache_time"] = round(cache_time * 1000, 2)

        # Test 2: Search performance
        start_time = time.time()
        search_results = member_optimizer.bulk_load_members_optimized(limit=10)
        search_time = time.time() - start_time

        test_results["tests_run"] += 1
        if search_time < 1.0:  # Should be fast
            test_results["tests_passed"] += 1

        test_results["performance_metrics"]["search_time"] = round(search_time * 1000, 2)
        test_results["performance_metrics"]["search_results_count"] = len(search_results)

        # Generate recommendations
        if cache_time > 0.05:
            test_results["recommendations"].append("Consider implementing more aggressive metadata caching")

        if search_time > 0.5:
            test_results["recommendations"].append("Database indexes may need optimization for member search")

        success_rate = (
            test_results["tests_passed"] / test_results["tests_run"] * 100
            if test_results["tests_run"] > 0
            else 0
        )

        return OperationResult.ok(
            {
                "test_results": test_results,
                "success_rate": round(success_rate, 1),
            },
            message=_("Performance tests completed: {0}/{1} passed").format(
                test_results["tests_passed"], test_results["tests_run"]
            ),
        )

    except Exception as e:
        frappe.log_error(
            title=_("Performance optimization test failed"),
            message=f"Error: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.from_exception(
            e, message=_("Performance tests failed"), fallback_data={"test_results": {}}
        )
