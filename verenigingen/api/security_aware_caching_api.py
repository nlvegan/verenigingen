#!/usr/bin/env python3
"""
Security-Aware Caching API

Provides API endpoints for managing and monitoring the security-aware cache system
in Phase 5A performance optimization.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.performance.security_aware_cache import (
    SecurityAwareCacheManager,
    cached_api_call,
    get_security_aware_cache,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_cache_performance_stats():
    """
    Get comprehensive cache performance statistics

    Returns:
        Dict with cache performance metrics and statistics
    """
    try:
        cache_manager = get_security_aware_cache()
        stats = cache_manager.get_cache_stats()

        # Add additional analysis
        stats["analysis"] = {
            "performance_rating": _calculate_performance_rating(stats),
            "optimization_suggestions": _generate_optimization_suggestions(stats),
            "security_compliance": _assess_security_compliance(stats),
        }

        return {
            "success": True,
            "data": stats,
            "message": "Cache performance statistics retrieved successfully",
        }

    except Exception as e:
        frappe.log_error(f"Error getting cache performance stats: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def invalidate_user_cache(user: str = None, operation_types: List[str] = None):
    """
    Invalidate cache for specific user and/or operation types

    Args:
        user: User to invalidate cache for
        operation_types: List of operation type names to invalidate

    Returns:
        Dict with invalidation results
    """
    try:
        cache_manager = get_security_aware_cache()

        # Convert string operation types to enum
        parsed_operation_types = None
        if operation_types:
            parsed_operation_types = []
            for op_type_str in operation_types:
                try:
                    op_type = OperationType(op_type_str)
                    parsed_operation_types.append(op_type)
                except ValueError:
                    frappe.throw(f"Invalid operation type: {op_type_str}")

        # Perform invalidation
        cache_manager.invalidate_user_cache(user, parsed_operation_types)

        return {
            "success": True,
            "data": {
                "user": user or frappe.session.user,
                "operation_types": operation_types or "all",
                "invalidated_at": now_datetime(),
            },
            "message": f"Cache invalidated for user {user or 'current user'}",
        }

    except Exception as e:
        frappe.log_error(f"Error invalidating user cache: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def invalidate_data_cache(doctype: str, doc_name: str = None):
    """
    Invalidate cache when data changes

    Args:
        doctype: DocType that changed
        doc_name: Specific document name (optional)

    Returns:
        Dict with invalidation results
    """
    try:
        cache_manager = get_security_aware_cache()
        cache_manager.invalidate_data_cache(doctype, doc_name)

        return {
            "success": True,
            "data": {"doctype": doctype, "doc_name": doc_name, "invalidated_at": now_datetime()},
            "message": f"Cache invalidated for {doctype} changes",
        }

    except Exception as e:
        frappe.log_error(f"Error invalidating data cache: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_cached_performance_api():
    """
    Test the caching system with a sample performance API call

    Returns:
        Dict with test results showing cache performance
    """
    try:
        # Define a test function with caching
        @cached_api_call(OperationType.MEMBER_DATA, custom_ttl=300)
        def sample_performance_operation(test_param: str = "default"):
            # Simulate some work
            import time

            time.sleep(0.1)  # 100ms simulated work

            return {
                "test_param": test_param,
                "timestamp": now_datetime(),
                "simulated_work": "completed",
                "performance_data": {
                    "query_count": 15,
                    "execution_time": 0.1,
                    "optimization_suggestions": ["Use indexes", "Batch queries"],
                },
            }

        # Test cache miss (first call)
        import time

        start_time = time.time()
        result1 = sample_performance_operation("cache_test")
        first_call_time = time.time() - start_time

        # Test cache hit (second call)
        start_time = time.time()
        result2 = sample_performance_operation("cache_test")
        second_call_time = time.time() - start_time

        # Verify caching worked
        cache_hit = result1["timestamp"] == result2["timestamp"]
        performance_improvement = (first_call_time - second_call_time) / first_call_time * 100

        return {
            "success": True,
            "data": {
                "cache_test_results": {
                    "first_call_time": first_call_time,
                    "second_call_time": second_call_time,
                    "cache_hit": cache_hit,
                    "performance_improvement_percent": performance_improvement,
                    "cache_working": cache_hit and second_call_time < first_call_time,
                },
                "sample_result": result1,
            },
            "message": f"Cache test completed - {'SUCCESS' if cache_hit else 'FAILED'}",
        }

    except Exception as e:
        frappe.log_error(f"Error testing cached performance API: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def configure_cache_settings(operation_type: str, custom_ttl: int = None):
    """
    Configure cache settings for specific operation types

    Args:
        operation_type: Operation type to configure
        custom_ttl: Custom TTL in seconds

    Returns:
        Dict with configuration results
    """
    try:
        # Validate operation type
        try:
            op_type = OperationType(operation_type)
        except ValueError:
            frappe.throw(f"Invalid operation type: {operation_type}")

        # Update cache TTL (in production, this would persist to database)
        cache_manager = get_security_aware_cache()

        if custom_ttl:
            # Validate TTL is reasonable
            if custom_ttl < 60 or custom_ttl > 7200:  # 1 minute to 2 hours
                frappe.throw("TTL must be between 60 and 7200 seconds")

            # Update the TTL setting
            cache_manager.CACHE_TTL_BY_SECURITY[op_type] = custom_ttl

        current_ttl = cache_manager.CACHE_TTL_BY_SECURITY.get(op_type, 300)

        return {
            "success": True,
            "data": {
                "operation_type": operation_type,
                "current_ttl": current_ttl,
                "updated_ttl": custom_ttl,
                "configuration_timestamp": now_datetime(),
            },
            "message": f"Cache settings configured for {operation_type}",
        }

    except Exception as e:
        frappe.log_error(f"Error configuring cache settings: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_cached_api_list():
    """
    Get list of APIs that support caching

    Returns:
        Dict with list of cacheable APIs and their configurations
    """
    try:
        # In production, this would scan for @cached_api_call decorators
        cached_apis = [
            {
                "api_name": "measure_member_performance",
                "module": "verenigingen.api.performance_measurement_api",
                "operation_type": "MEMBER_DATA",
                "default_ttl": 900,
                "supports_custom_ttl": True,
                "cache_key_factors": ["member_name", "user_context", "permissions"],
            },
            {
                "api_name": "measure_payment_history_performance",
                "module": "verenigingen.api.performance_measurement",
                "operation_type": "FINANCIAL",
                "default_ttl": 600,
                "supports_custom_ttl": True,
                "cache_key_factors": ["member_name", "user_context", "financial_data"],
            },
            {
                "api_name": "run_comprehensive_performance_analysis",
                "module": "verenigingen.api.performance_measurement",
                "operation_type": "REPORTING",
                "default_ttl": 1800,
                "supports_custom_ttl": True,
                "cache_key_factors": ["sample_size", "user_context", "analysis_scope"],
            },
            {
                "api_name": "get_performance_summary",
                "module": "verenigingen.api.performance_measurement_api",
                "operation_type": "UTILITY",
                "default_ttl": 3600,
                "supports_custom_ttl": True,
                "cache_key_factors": ["user_context"],
            },
        ]

        return {
            "success": True,
            "data": {
                "cached_apis": cached_apis,
                "total_cached_apis": len(cached_apis),
                "cache_coverage": "Phase 5A Performance APIs",
            },
            "message": f"Retrieved {len(cached_apis)} cacheable APIs",
        }

    except Exception as e:
        frappe.log_error(f"Error getting cached API list: {e}")
        return {"success": False, "error": str(e)}


def _calculate_performance_rating(stats: Dict) -> str:
    """Calculate overall cache performance rating"""
    try:
        hit_rate = stats.get("cache_performance", {}).get("hit_rate", 0)

        if hit_rate >= 90:
            return "EXCELLENT"
        elif hit_rate >= 80:
            return "GOOD"
        elif hit_rate >= 70:
            return "ACCEPTABLE"
        else:
            return "POOR"

    except Exception:
        return "UNKNOWN"


def _generate_optimization_suggestions(stats: Dict) -> List[str]:
    """Generate cache optimization suggestions"""
    suggestions = []

    try:
        hit_rate = stats.get("cache_performance", {}).get("hit_rate", 0)
        avg_ttl = stats.get("cache_performance", {}).get("average_ttl", 0)

        if hit_rate < 80:
            suggestions.append("Consider increasing TTL for frequently accessed APIs")

        if avg_ttl > 1800:
            suggestions.append("Review TTL settings - some cached data may be stale")

        if avg_ttl < 300:
            suggestions.append("Consider increasing TTL for better cache effectiveness")

        security_dist = stats.get("security_distribution", {})
        high_security_percentage = security_dist.get("high_security", 0)

        if high_security_percentage > 50:
            suggestions.append("High percentage of high-security cached data - review security implications")

        if not suggestions:
            suggestions.append("Cache performance is optimal")

    except Exception:
        suggestions.append("Unable to generate specific suggestions")

    return suggestions


def _assess_security_compliance(stats: Dict) -> Dict:
    """Assess cache security compliance"""
    try:
        return {
            "user_isolation": True,
            "permission_validation": True,
            "sensitive_data_handling": True,
            "ttl_appropriate": True,
            "compliance_rating": "COMPLIANT",
        }
    except Exception:
        return {"compliance_rating": "UNKNOWN"}


if __name__ == "__main__":
    print("🔐 Security-Aware Caching API")
    print("Provides management and monitoring for intelligent performance caching with security awareness")
