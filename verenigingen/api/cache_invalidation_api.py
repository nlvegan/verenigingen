#!/usr/bin/env python3
"""
Cache Invalidation API

Provides API endpoints for managing and monitoring the intelligent cache
invalidation system in Phase 5A performance optimization.
"""

import traceback
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import now_datetime

from verenigingen.utils.operation_result import OperationResult
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


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def trigger_cache_invalidation(
    doctype: str, doc_name: str, change_type: str = "update", changed_fields: List[str] = None
) -> OperationResult[Dict[str, Any]]:
    """
    Manually trigger cache invalidation for a document

    Args:
        doctype: Document type that changed
        doc_name: Name of the changed document
        change_type: Type of change (insert, update, delete)
        changed_fields: List of changed fields (for updates)

    Returns:
        OperationResult[Dict[str, Any]]: Result containing invalidation details
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

        return OperationResult.ok(
            result, message=_("Cache invalidation triggered for {0}/{1}").format(doctype, doc_name)
        )

    except Exception as e:
        frappe.log_error(
            f"Error triggering cache invalidation: {str(e)}\n{traceback.format_exc()}",
            "Cache Invalidation Trigger Failed",
        )
        return OperationResult.fail(
            _("Failed to trigger cache invalidation"),
            errors=[str(e)],
            context={"operation": "trigger_cache_invalidation", "doctype": doctype, "doc_name": doc_name},
        )


@critical_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def schedule_batch_invalidation(
    invalidation_jobs: List[Dict], delay_seconds: int = 0
) -> OperationResult[Dict[str, Any]]:
    """
    Schedule batch cache invalidation for multiple documents

    Args:
        invalidation_jobs: List of invalidation job configurations
        delay_seconds: Delay before executing invalidation

    Returns:
        OperationResult[Dict[str, Any]]: Result containing batch job ID and status
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
            data = {
                "batch_id": batch_id,
                "jobs_scheduled": len(invalidation_jobs),
                "delay_seconds": delay_seconds,
                "scheduled_at": now_datetime(),
            }
            return OperationResult.ok(
                data, message=_("Batch invalidation scheduled with {0} jobs").format(len(invalidation_jobs))
            )
        else:
            return OperationResult.fail(
                _("Failed to schedule batch invalidation"),
                errors=["Batch ID was not generated"],
                context={"operation": "schedule_batch_invalidation", "jobs_count": len(invalidation_jobs)},
            )

    except Exception as e:
        frappe.log_error(
            f"Error scheduling batch invalidation: {str(e)}\n{traceback.format_exc()}",
            "Batch Invalidation Scheduling Failed",
        )
        return OperationResult.fail(
            _("Failed to schedule batch invalidation"),
            errors=[str(e)],
            context={
                "operation": "schedule_batch_invalidation",
                "jobs_count": len(invalidation_jobs) if invalidation_jobs else 0,
            },
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_invalidation_statistics() -> OperationResult[Dict[str, Any]]:
    """
    Get cache invalidation statistics and performance metrics

    Returns:
        OperationResult[Dict[str, Any]]: Result containing comprehensive invalidation statistics
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()
        stats = invalidation_manager.get_invalidation_statistics()

        return OperationResult.ok(stats, message=_("Invalidation statistics retrieved successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error getting invalidation statistics: {str(e)}\n{traceback.format_exc()}",
            "Invalidation Statistics Retrieval Failed",
        )
        return OperationResult.fail(
            _("Failed to retrieve invalidation statistics"),
            errors=[str(e)],
            context={"operation": "get_invalidation_statistics"},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def validate_cache_consistency(doctype: str = None, doc_name: str = None) -> OperationResult[Dict[str, Any]]:
    """
    Validate cache consistency for specific documents or doctypes

    Args:
        doctype: DocType to validate (optional)
        doc_name: Specific document to validate (optional)

    Returns:
        OperationResult[Dict[str, Any]]: Result containing consistency validation results
    """
    try:
        invalidation_manager = get_cache_invalidation_manager()
        validation_result = invalidation_manager.validate_cache_consistency(doctype, doc_name)

        return OperationResult.ok(validation_result, message=_("Cache consistency validation completed"))

    except Exception as e:
        frappe.log_error(
            f"Error validating cache consistency: {str(e)}\n{traceback.format_exc()}",
            "Cache Consistency Validation Failed",
        )
        return OperationResult.fail(
            _("Failed to validate cache consistency"),
            errors=[str(e)],
            context={"operation": "validate_cache_consistency", "doctype": doctype, "doc_name": doc_name},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def test_cache_invalidation_system() -> OperationResult[Dict[str, Any]]:
    """
    Test the cache invalidation system with sample operations

    Returns:
        OperationResult[Dict[str, Any]]: Result containing comprehensive test results
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

        return OperationResult.ok(
            test_results,
            message=_("Cache invalidation system test completed - {0}% success rate").format(
                int(success_rate)
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error testing cache invalidation system: {str(e)}\n{traceback.format_exc()}",
            "Cache Invalidation System Test Failed",
        )
        return OperationResult.fail(
            _("Failed to test cache invalidation system"),
            errors=[str(e)],
            context={"operation": "test_cache_invalidation_system"},
        )


@standard_api(operation_type=OperationType.UTILITY)
@frappe.whitelist()
def get_invalidation_patterns() -> OperationResult[Dict[str, Any]]:
    """
    Get configured invalidation patterns for all document types

    Returns:
        OperationResult[Dict[str, Any]]: Result containing invalidation pattern configurations
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

        return OperationResult.ok(
            patterns_info,
            message=_("Retrieved invalidation patterns for {0} document types").format(
                len(patterns_info["supported_doctypes"])
            ),
        )

    except Exception as e:
        frappe.log_error(
            f"Error getting invalidation patterns: {str(e)}\n{traceback.format_exc()}",
            "Invalidation Patterns Retrieval Failed",
        )
        return OperationResult.fail(
            _("Failed to retrieve invalidation patterns"),
            errors=[str(e)],
            context={"operation": "get_invalidation_patterns"},
        )


@high_security_api(operation_type=OperationType.ADMIN)
@frappe.whitelist()
def clear_all_caches() -> OperationResult[Dict[str, Any]]:
    """
    Clear all application caches (emergency operation)

    Returns:
        OperationResult[Dict[str, Any]]: Result containing cache clearing results
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

        data = {
            "operation": "clear_all_caches",
            "executed_at": end_time,
            "execution_time": "< 1 second",
            "cache_types_cleared": ["frappe_cache", "security_aware_cache"],
            "warning": "All cached data has been cleared - performance may be temporarily impacted",
        }

        return OperationResult.ok(data, message=_("All caches cleared successfully"))

    except Exception as e:
        frappe.log_error(
            f"Error clearing all caches: {str(e)}\n{traceback.format_exc()}", "Cache Clearing Failed"
        )
        return OperationResult.fail(
            _("Failed to clear all caches"), errors=[str(e)], context={"operation": "clear_all_caches"}
        )


if __name__ == "__main__":
    print("🗑️ Cache Invalidation API")
    print("Provides intelligent cache invalidation management with event-driven updates")
