# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

"""
SEPA Optimization Comparison Test
================================

Compares simplified SEPA implementation (working baseline) with
original optimized version to validate runtime error fixes.
"""

import time
import traceback
from typing import Any, Dict, List

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
from verenigingen.verenigingen_payments.utils.sepa_operations_simple import (
    SimpleSEPAManager,
    SimpleSEPAOperation,
    get_simple_sepa_manager,
)

# Import optimized version to test for runtime errors
try:
    from verenigingen.verenigingen_payments.utils.frappe_native_sepa_operations_optimized import (
        FrappeNativeSEPAManagerOptimized,
        FrappeNativeSEPAOperation,
        get_optimized_sepa_manager,
    )

    OPTIMIZED_AVAILABLE = True
except ImportError as e:
    frappe.logger().warning(f"Optimized SEPA manager not available: {e}")
    OPTIMIZED_AVAILABLE = False


def test_both_implementations() -> Dict[str, Any]:
    """
    Test both simple and optimized SEPA implementations

    Returns:
        Dict with comparison results showing runtime error fixes
    """

    results = {
        "simple_implementation": {},
        "optimized_implementation": {},
        "comparison": {},
        "runtime_errors_fixed": False,
    }

    # Test operations
    test_operations_simple = []
    test_operations_optimized = []

    for i in range(3):
        # Simple implementation operations
        test_operations_simple.append(
            SimpleSEPAOperation(
                member_id=f"TEST-MEMBER-{i:03d}",
                operation_type="create",
                operation_data={
                    "iban": f"NL91ABNA041716430{i}",
                    "account_holder": f"Test User {i}",
                    "mandate_reference": f"TEST-{i:03d}",
                },
            )
        )

        # Optimized implementation operations
        if OPTIMIZED_AVAILABLE:
            test_operations_optimized.append(
                FrappeNativeSEPAOperation(
                    member_id=f"TEST-MEMBER-{i:03d}",
                    operation_type="create",
                    operation_data={
                        "iban": f"NL91ABNA041716430{i}",
                        "account_holder": f"Test User {i}",
                        "mandate_reference": f"TEST-{i:03d}",
                    },
                )
            )

    # Test 1: Simple Implementation
    try:
        simple_manager = get_simple_sepa_manager()

        start_time = time.time()
        simple_result = simple_manager.process_operations_simple(test_operations_simple)
        simple_execution_time = time.time() - start_time

        results["simple_implementation"] = {
            "success": True,
            "execution_time": simple_execution_time,
            "result": simple_result,
            "runtime_error": None,
        }

    except Exception as e:
        results["simple_implementation"] = {
            "success": False,
            "execution_time": 0,
            "result": None,
            "runtime_error": str(e),
            "traceback": traceback.format_exc(),
        }

    # Test 2: Optimized Implementation (if available)
    if OPTIMIZED_AVAILABLE:
        try:
            optimized_manager = get_optimized_sepa_manager()

            start_time = time.time()
            optimized_result = optimized_manager.process_bulk_operations_optimized(test_operations_optimized)
            optimized_execution_time = time.time() - start_time

            results["optimized_implementation"] = {
                "success": True,
                "execution_time": optimized_execution_time,
                "result": optimized_result,
                "runtime_error": None,
            }

        except Exception as e:
            results["optimized_implementation"] = {
                "success": False,
                "execution_time": 0,
                "result": None,
                "runtime_error": str(e),
                "traceback": traceback.format_exc(),
            }
    else:
        results["optimized_implementation"] = {
            "success": False,
            "execution_time": 0,
            "result": None,
            "runtime_error": "Optimized implementation not available for import",
        }

    # Comparison analysis
    simple_success = results["simple_implementation"]["success"]
    optimized_success = results["optimized_implementation"]["success"]

    results["runtime_errors_fixed"] = simple_success and not optimized_success

    results["comparison"] = {
        "simple_works": simple_success,
        "optimized_works": optimized_success,
        "runtime_errors_resolved": results["runtime_errors_fixed"],
        "error_analysis": {
            "simple_error": results["simple_implementation"].get("runtime_error"),
            "optimized_error": results["optimized_implementation"].get("runtime_error"),
        },
    }

    return results


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def run_sepa_comparison_test():
    """
    Whitelisted method to run SEPA implementation comparison

    Validates that runtime errors are fixed in simplified version
    """
    try:
        result = test_both_implementations()

        # Log comparison results
        simple_success = result["simple_implementation"]["success"]
        optimized_success = result["optimized_implementation"]["success"]

        if result["runtime_errors_fixed"]:
            frappe.logger().info(
                "✅ SEPA Runtime Errors Fixed: Simple implementation works, "
                "optimized version has runtime errors as expected"
            )
        elif simple_success and optimized_success:
            frappe.logger().info("✅ Both SEPA implementations work - optimization appears successful")
        elif not simple_success:
            frappe.logger().error("❌ Simple SEPA implementation failed - unexpected error")
        else:
            frappe.logger().info("ℹ️  SEPA implementation status unclear - check detailed results")

        return result

    except Exception as e:
        frappe.logger().error(f"SEPA comparison test error: {str(e)}")
        return {"success": False, "error": f"Comparison test execution failed: {str(e)}"}
