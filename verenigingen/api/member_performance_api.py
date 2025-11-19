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
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import cint, flt

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    development_only_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def create_member_optimized(member_data: str) -> Dict[str, Any]:
    """
    Create member using performance optimizations

    Args:
        member_data: JSON string containing member information

    Returns:
        Dictionary with member creation result
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

        return {
            "success": True,
            "member_name": member_name,
            "full_name": member.full_name,
            "message": _("Member created successfully with performance optimizations"),
        }

    except Exception as e:
        frappe.log_error(f"Optimized member creation failed: {str(e)}")
        return {"success": False, "error": str(e), "message": _("Member creation failed")}


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def search_members_fast(filters: str = None, limit: int = 20) -> Dict[str, Any]:
    """
    Fast member search with comprehensive related data

    Args:
        filters: JSON string with search filters
        limit: Maximum number of results to return

    Returns:
        Dictionary with search results and metadata
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

        return {
            "success": True,
            "results": results,
            "count": len(results),
            "message": _("Search completed successfully"),
        }

    except Exception as e:
        frappe.log_error(f"Fast member search failed: {str(e)}")
        return {"success": False, "error": str(e), "results": [], "count": 0, "message": _("Search failed")}


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_dashboard_fast(member_name: str) -> Dict[str, Any]:
    """
    Get member dashboard data with caching

    Args:
        member_name: Name of the member

    Returns:
        Dictionary with comprehensive member dashboard data
    """
    try:
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        # Get cached dashboard data
        dashboard_data = member_optimizer.get_member_dashboard_cached(member_name)

        if not dashboard_data:
            return {"success": False, "message": _("Member not found"), "data": {}}

        return {"success": True, "data": dashboard_data, "message": _("Dashboard data loaded successfully")}

    except Exception as e:
        frappe.log_error(f"Fast dashboard load failed for {member_name}: {str(e)}")
        return {"success": False, "error": str(e), "data": {}, "message": _("Dashboard load failed")}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def clear_member_cache(member_name: str = None) -> Dict[str, Any]:
    """
    Clear member-related caches

    Args:
        member_name: Specific member to clear cache for, or None for all

    Returns:
        Dictionary with operation result
    """
    try:
        from verenigingen.utils.member_performance_optimizer import member_optimizer

        if member_name:
            member_optimizer.clear_member_cache(member_name)
            message = _("Cache cleared for member {0}").format(member_name)
        else:
            member_optimizer.clear_all_member_caches()
            message = _("All member caches cleared")

        return {"success": True, "message": message}

    except Exception as e:
        frappe.log_error(f"Cache clearing failed: {str(e)}")
        return {"success": False, "error": str(e), "message": _("Cache clearing failed")}


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_performance_stats() -> Dict[str, Any]:
    """
    Get current performance statistics and cache status

    Returns:
        Dictionary with performance metrics
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

        return {
            "success": True,
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
            "message": _("Performance statistics retrieved"),
        }

    except Exception as e:
        frappe.log_error(f"Performance stats retrieval failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "stats": {},
            "message": _("Performance stats retrieval failed"),
        }


@frappe.whitelist()
@high_security_api(operation_type=OperationType.MEMBER_DATA)
def bulk_create_members(members_data: str) -> Dict[str, Any]:
    """
    Create multiple members using optimizations

    Args:
        members_data: JSON string containing array of member data

    Returns:
        Dictionary with bulk creation results
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

        return {
            "success": True,
            "results": results,
            "success_rate": round(success_rate, 1),
            "message": _("Bulk creation completed: {0}/{1} successful").format(
                len(results["created"]), results["total"]
            ),
        }

    except Exception as e:
        frappe.log_error(f"Bulk member creation failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "results": {"created": [], "failed": [], "total": 0},
            "message": _("Bulk creation failed"),
        }


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_performance_optimization() -> Dict[str, Any]:
    """
    Run performance optimization validation tests

    Returns:
        Dictionary with test results and performance metrics
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

        return {
            "success": True,
            "test_results": test_results,
            "success_rate": round(success_rate, 1),
            "message": _("Performance tests completed: {0}/{1} passed").format(
                test_results["tests_passed"], test_results["tests_run"]
            ),
        }

    except Exception as e:
        frappe.log_error(f"Performance optimization test failed: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "test_results": {},
            "message": _("Performance tests failed"),
        }
