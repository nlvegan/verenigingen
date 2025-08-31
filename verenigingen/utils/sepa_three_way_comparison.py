# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

"""
SEPA Three-Way Implementation Comparison
========================================

Compares all three SEPA implementations:
1. Simple (working baseline)
2. Optimized (fixed runtime errors)
3. True Bulk (genuine bulk database operations)
"""

import time
from typing import Any, Dict

import frappe

from verenigingen.verenigingen_payments.utils.frappe_native_sepa_operations_optimized import (
    FrappeNativeSEPAManagerOptimized,
    FrappeNativeSEPAOperation,
)
from verenigingen.verenigingen_payments.utils.sepa_operations_bulk_true import (
    BulkSEPAOperation,
    TrueBulkSEPAManager,
)
from verenigingen.verenigingen_payments.utils.sepa_operations_simple import (
    SimpleSEPAManager,
    SimpleSEPAOperation,
)


def run_three_way_comparison(operation_count: int = 5) -> Dict[str, Any]:
    """
    Compare all three SEPA implementations

    Args:
        operation_count: Number of test operations to run

    Returns:
        Comprehensive comparison results
    """

    results = {
        "test_config": {"operation_count": operation_count, "test_type": "mock_operations_performance_only"},
        "implementations": {"simple": {}, "optimized": {}, "true_bulk": {}},
        "comparison_analysis": {},
    }

    # Test 1: Simple Implementation
    try:
        simple_operations = []
        for i in range(operation_count):
            simple_operations.append(
                SimpleSEPAOperation(
                    member_id=f"TEST-MEMBER-{i:03d}",
                    operation_type="create",
                    operation_data={
                        "iban": f"NL91ABNA041716430{i}",
                        "account_holder": f"Test User {i}",
                        "mandate_reference": f"SIMPLE-{i:03d}",
                    },
                )
            )

        simple_manager = SimpleSEPAManager()
        start_time = time.time()
        simple_result = simple_manager.process_operations_simple(simple_operations)
        simple_execution_time = time.time() - start_time

        results["implementations"]["simple"] = {
            "success": simple_result["success"],
            "execution_time": simple_execution_time,
            "processed": simple_result.get("processed", 0),
            "failed": simple_result.get("failed", 0),
            "error_count": len(simple_result.get("errors", [])),
            "implementation_type": "individual_operations",
            "runtime_error": None,
        }

    except Exception as e:
        results["implementations"]["simple"] = {
            "success": False,
            "execution_time": 0,
            "runtime_error": str(e),
            "implementation_type": "individual_operations",
        }

    # Test 2: Optimized Implementation
    try:
        optimized_operations = []
        for i in range(operation_count):
            optimized_operations.append(
                FrappeNativeSEPAOperation(
                    member_id=f"TEST-MEMBER-{i:03d}",
                    operation_type="create",
                    operation_data={
                        "iban": f"NL91ABNA041716430{i}",
                        "account_holder": f"Test User {i}",
                        "mandate_reference": f"OPTIMIZED-{i:03d}",
                    },
                )
            )

        optimized_manager = FrappeNativeSEPAManagerOptimized()
        start_time = time.time()
        optimized_result = optimized_manager.process_bulk_operations_optimized(optimized_operations)
        optimized_execution_time = time.time() - start_time

        results["implementations"]["optimized"] = {
            "success": optimized_result["success"],
            "execution_time": optimized_execution_time,
            "processed": optimized_result.get("processed", 0),
            "failed": optimized_result.get("failed", 0),
            "error_count": len(optimized_result.get("errors", [])),
            "implementation_type": "pseudo_bulk_operations",
            "runtime_error": None,
        }

    except Exception as e:
        results["implementations"]["optimized"] = {
            "success": False,
            "execution_time": 0,
            "runtime_error": str(e),
            "implementation_type": "pseudo_bulk_operations",
        }

    # Test 3: True Bulk Implementation
    try:
        true_bulk_operations = []
        for i in range(operation_count):
            true_bulk_operations.append(
                BulkSEPAOperation(
                    member_id=f"TEST-MEMBER-{i:03d}",
                    operation_type="create",
                    operation_data={
                        "iban": f"NL91ABNA041716430{i}",
                        "account_holder": f"Test User {i}",
                        "mandate_reference": f"TRUEBULK-{i:03d}",
                    },
                )
            )

        true_bulk_manager = TrueBulkSEPAManager()
        start_time = time.time()
        true_bulk_result = true_bulk_manager.process_bulk_operations_true_bulk(true_bulk_operations)
        true_bulk_execution_time = time.time() - start_time

        results["implementations"]["true_bulk"] = {
            "success": true_bulk_result["success"],
            "execution_time": true_bulk_execution_time,
            "processed": true_bulk_result.get("processed", 0),
            "failed": true_bulk_result.get("failed", 0),
            "error_count": len(true_bulk_result.get("errors", [])),
            "implementation_type": "true_bulk_database_operations",
            "optimization_type": true_bulk_result.get("optimization_type", "unknown"),
            "runtime_error": None,
        }

    except Exception as e:
        results["implementations"]["true_bulk"] = {
            "success": False,
            "execution_time": 0,
            "runtime_error": str(e),
            "implementation_type": "true_bulk_database_operations",
        }

    # Comparison Analysis
    implementations = results["implementations"]

    # Check which implementations work
    working_implementations = [
        name
        for name, impl in implementations.items()
        if impl.get("success", False) and impl.get("runtime_error") is None
    ]

    # Performance comparison (for working implementations)
    if len(working_implementations) >= 2:
        execution_times = {
            name: impl["execution_time"]
            for name, impl in implementations.items()
            if name in working_implementations
        }

        fastest = min(execution_times.keys(), key=lambda x: execution_times[x])
        slowest = max(execution_times.keys(), key=lambda x: execution_times[x])

        if execution_times[slowest] > 0:
            performance_improvement = (
                (execution_times[slowest] - execution_times[fastest]) / execution_times[slowest]
            ) * 100
        else:
            performance_improvement = 0
    else:
        fastest = slowest = None
        performance_improvement = 0

    results["comparison_analysis"] = {
        "working_implementations": working_implementations,
        "fastest_implementation": fastest,
        "slowest_implementation": slowest,
        "performance_improvement_percent": round(performance_improvement, 2),
        "runtime_errors_resolved": len(
            [impl for impl in implementations.values() if impl.get("runtime_error") is None]
        )
        > len([impl for impl in implementations.values() if impl.get("runtime_error") is not None]),
        "quality_assessment": {
            "simple_baseline_established": implementations["simple"].get("success", False),
            "optimized_errors_fixed": implementations["optimized"].get("runtime_error") is None,
            "true_bulk_operational": implementations["true_bulk"].get("success", False),
            "ready_for_scaling": all(
                [
                    implementations["simple"].get("success", False),
                    implementations["optimized"].get("runtime_error") is None,
                    implementations["true_bulk"].get("success", False),
                ]
            ),
        },
    }

    return results


@frappe.whitelist()
def run_sepa_three_way_comparison():
    """
    Run comprehensive three-way SEPA implementation comparison
    """
    try:
        result = run_three_way_comparison(operation_count=5)

        # Log results
        analysis = result["comparison_analysis"]
        working = len(analysis["working_implementations"])

        frappe.logger().info(
            f"SEPA Three-Way Comparison: {working}/3 implementations working. "
            f"Quality ready for scaling: {analysis['quality_assessment']['ready_for_scaling']}"
        )

        if analysis["fastest_implementation"]:
            frappe.logger().info(
                f"Performance: {analysis['fastest_implementation']} fastest, "
                f"{analysis['performance_improvement_percent']}% improvement over slowest"
            )

        return result

    except Exception as e:
        frappe.logger().error(f"Three-way SEPA comparison error: {str(e)}")
        return {"success": False, "error": f"Comparison test failed: {str(e)}"}
