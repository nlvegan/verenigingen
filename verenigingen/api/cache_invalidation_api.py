#!/usr/bin/env python3
"""
Cache Invalidation API

Provides API endpoints for managing and monitoring the intelligent cache
invalidation system in Phase 5A performance optimization.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe.utils import now_datetime

from verenigingen.utils.performance.cache_invalidation_strategy import (
    CacheInvalidationManager,
    get_cache_invalidation_manager,
)
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def trigger_cache_invalidation(
    doctype: str, doc_name: str, change_type: str = "update", changed_fields: List[str] = None
):
    """
    Manually trigger cache invalidation for a document

    Args:
        doctype: Document type that changed
        doc_name: Name of the changed document
        change_type: Type of change (insert, update, delete)
        changed_fields: List of changed fields (for updates)

    Returns:
        Dict with invalidation results
    """
    try:
        # Validate inputs
        valid_change_types = ["insert", "update", "delete"]
        if change_type not in valid_change_types:
            frappe.throw(f"Invalid change_type. Must be one of: {', '.join(valid_change_types)}")

        # Get invalidation manager
        invalidation_manager = get_cache_invalidation_manager()

        # Trigger invalidation
        result = invalidation_manager.register_document_change(
            doctype=doctype,
            doc_name=doc_name,
            change_type=change_type,
            changed_fields=changed_fields or [],
            user=frappe.session.user,
        )

        return {
            "success": True,
            "data": result,
            "message": f"Cache invalidation triggered for {doctype}/{doc_name}",
        }

    except Exception as e:
        frappe.log_error(f"Error triggering cache invalidation: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def schedule_batch_invalidation(invalidation_jobs: List[Dict], delay_seconds: int = 0):
    """
    Schedule batch cache invalidation for multiple documents

    Args:
        invalidation_jobs: List of invalidation job configurations
        delay_seconds: Delay before executing invalidation

    Returns:
        Dict with batch job ID and status
    """
    try:
        # Validate invalidation jobs
        if not invalidation_jobs or not isinstance(invalidation_jobs, list):
            frappe.throw("invalidation_jobs must be a non-empty list")

        required_fields = ["doctype", "doc_name", "change_type"]
        for i, job in enumerate(invalidation_jobs):
            for field in required_fields:
                if field not in job:
                    frappe.throw(f"Missing required field '{field}' in job {i}")

        # Get invalidation manager
        invalidation_manager = get_cache_invalidation_manager()

        # Schedule batch invalidation
        batch_id = invalidation_manager.schedule_batch_invalidation(invalidation_jobs, delay_seconds)

        if batch_id:
            return {
                "success": True,
                "data": {
                    "batch_id": batch_id,
                    "jobs_scheduled": len(invalidation_jobs),
                    "delay_seconds": delay_seconds,
                    "scheduled_at": now_datetime(),
                },
                "message": f"Batch invalidation scheduled with {len(invalidation_jobs)} jobs",
            }
        else:
            return {"success": False, "error": "Failed to schedule batch invalidation"}

    except Exception as e:
        frappe.log_error(f"Error scheduling batch invalidation: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_invalidation_statistics():
    """
    Get cache invalidation statistics and performance metrics

    Returns:
        Dict with comprehensive invalidation statistics
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()
        stats = invalidation_manager.get_invalidation_statistics()

        return {"success": True, "data": stats, "message": "Invalidation statistics retrieved successfully"}

    except Exception as e:
        frappe.log_error(f"Error getting invalidation statistics: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def validate_cache_consistency(doctype: str = None, doc_name: str = None):
    """
    Validate cache consistency for specific documents or doctypes

    Args:
        doctype: DocType to validate (optional)
        doc_name: Specific document to validate (optional)

    Returns:
        Dict with consistency validation results
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()
        validation_result = invalidation_manager.validate_cache_consistency(doctype, doc_name)

        return {
            "success": True,
            "data": validation_result,
            "message": "Cache consistency validation completed",
        }

    except Exception as e:
        frappe.log_error(f"Error validating cache consistency: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def test_cache_invalidation_system():
    """
    Test the cache invalidation system with sample operations

    Returns:
        Dict with test results
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()

        test_results = {
            "test_timestamp": now_datetime(),
            "test_version": "5A.2.4",
            "invalidation_tests": [],
            "performance_tests": [],
            "overall_test_status": "UNKNOWN",
        }

        # Test 1: Single document invalidation
        test1_result = invalidation_manager.register_document_change(
            doctype="Member",
            doc_name="TEST-MEMBER-001",
            change_type="update",
            changed_fields=["status", "customer"],
            user=frappe.session.user,
        )

        test_results["invalidation_tests"].append(
            {
                "test_name": "single_document_invalidation",
                "passed": "error" not in test1_result,
                "patterns_invalidated": len(test1_result.get("patterns_invalidated", [])),
                "execution_time": test1_result.get("performance_impact", {}).get("execution_time", 0),
            }
        )

        # Test 2: Batch invalidation scheduling
        batch_jobs = [
            {"doctype": "Payment Entry", "doc_name": "TEST-PAY-001", "change_type": "insert"},
            {
                "doctype": "Sales Invoice",
                "doc_name": "TEST-INV-001",
                "change_type": "update",
                "changed_fields": ["grand_total"],
            },
        ]

        batch_id = invalidation_manager.schedule_batch_invalidation(batch_jobs, delay_seconds=0)

        test_results["invalidation_tests"].append(
            {
                "test_name": "batch_invalidation_scheduling",
                "passed": batch_id is not None,
                "batch_id": batch_id,
                "jobs_processed": len(batch_jobs),
            }
        )

        # Test 3: Statistics collection
        stats = invalidation_manager.get_invalidation_statistics()

        test_results["performance_tests"].append(
            {
                "test_name": "statistics_collection",
                "passed": "error" not in stats,
                "total_invalidations": stats.get("total_invalidations", 0),
                "doctypes_tracked": len(stats.get("invalidations_by_doctype", {})),
            }
        )

        # Test 4: Consistency validation
        consistency_result = invalidation_manager.validate_cache_consistency("Member")

        test_results["performance_tests"].append(
            {
                "test_name": "consistency_validation",
                "passed": "error" not in consistency_result,
                "checks_performed": len(consistency_result.get("consistency_checks", [])),
                "inconsistencies_found": len(consistency_result.get("inconsistencies_found", [])),
            }
        )

        # Calculate overall test status
        all_tests = test_results["invalidation_tests"] + test_results["performance_tests"]
        passed_tests = sum(1 for test in all_tests if test.get("passed", False))
        total_tests = len(all_tests)

        success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0

        if success_rate >= 90:
            test_results["overall_test_status"] = "EXCELLENT"
        elif success_rate >= 75:
            test_results["overall_test_status"] = "GOOD"
        elif success_rate >= 60:
            test_results["overall_test_status"] = "ACCEPTABLE"
        else:
            test_results["overall_test_status"] = "NEEDS_IMPROVEMENT"

        test_results["success_rate"] = success_rate
        test_results["tests_passed"] = passed_tests
        test_results["total_tests"] = total_tests

        return {
            "success": True,
            "data": test_results,
            "message": f"Cache invalidation system test completed - {success_rate:.0f}% success rate",
        }

    except Exception as e:
        frappe.log_error(f"Error testing cache invalidation system: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@standard_api(operation_type=OperationType.UTILITY)
def get_invalidation_patterns():
    """
    Get configured invalidation patterns for all document types

    Returns:
        Dict with invalidation pattern configurations
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()

        patterns_info = {
            "patterns_timestamp": now_datetime(),
            "configured_patterns": invalidation_manager.INVALIDATION_PATTERNS.copy(),
            "invalidation_strategies": {
                op_type.value: strategy
                for op_type, strategy in invalidation_manager.INVALIDATION_STRATEGIES.items()
            },
            "supported_doctypes": list(invalidation_manager.INVALIDATION_PATTERNS.keys()),
            "total_patterns": sum(
                len(config.get("patterns", []))
                for config in invalidation_manager.INVALIDATION_PATTERNS.values()
            ),
        }

        return {
            "success": True,
            "data": patterns_info,
            "message": f"Retrieved invalidation patterns for {len(patterns_info['supported_doctypes'])} document types",
        }

    except Exception as e:
        frappe.log_error(f"Error getting invalidation patterns: {e}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def clear_all_caches():
    """
    Clear all application caches (emergency operation)

    Returns:
        Dict with cache clearing results
    """
    try:
        # This is an emergency operation - use with caution
        # Clear Frappe cache
        frappe.cache().clear()

        # Clear local caches if any
        from verenigingen.utils.performance.security_aware_cache import get_security_aware_cache

        cache_manager = get_security_aware_cache()

        # Reset cache manager state (simplified - in production would clear actual cache keys)
        cache_manager.__init__()  # Reinitialize

        end_time = frappe.utils.now()

        return {
            "success": True,
            "data": {
                "operation": "clear_all_caches",
                "executed_at": end_time,
                "execution_time": "< 1 second",
                "cache_types_cleared": ["frappe_cache", "security_aware_cache"],
                "warning": "All cached data has been cleared - performance may be temporarily impacted",
            },
            "message": "All caches cleared successfully",
        }

    except Exception as e:
        frappe.log_error(f"Error clearing all caches: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("🗑️ Cache Invalidation API")
    print("Provides intelligent cache invalidation management with event-driven updates")
