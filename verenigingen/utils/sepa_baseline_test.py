# Copyright (c) 2025, Your Name and contributors
# For license information, please see license.txt

"""
SEPA Performance Baseline Test
=============================

Establishes working performance baseline for simplified SEPA implementation
before adding bulk optimizations.
"""

import time
from typing import Any, Dict, List

import frappe

from verenigingen.verenigingen_payments.utils.sepa_operations_simple import (
    SimpleSEPAManager,
    SimpleSEPAOperation,
    get_simple_sepa_manager,
)


def test_sepa_simple_baseline() -> Dict[str, Any]:
    """
    Test simplified SEPA implementation to establish working baseline

    Returns:
        Dict with baseline performance metrics and validation results
    """

    # Initialize manager
    manager = get_simple_sepa_manager()

    # Test 1: Empty operations handling
    empty_result = manager.process_operations_simple([])

    if not empty_result["success"] or empty_result["processed"] != 0:
        return {"success": False, "error": "Empty operations test failed", "empty_result": empty_result}

    # Test 2: Single operation with mock data
    test_operation = SimpleSEPAOperation(
        member_id="baseline-test-member",
        operation_type="create",
        operation_data={
            "iban": "NL91ABNA0417164300",
            "account_holder": "Baseline Test User",
            "mandate_reference": "BASELINE-001",
        },
    )

    # Test without creating actual member - use mock data to test structure only
    try:
        # Test with fictional member ID to verify structure only
        test_operation.member_id = "MOCK-MEMBER-001"

        # Measure baseline performance
        start_time = time.time()
        single_result = manager.process_operations_simple([test_operation])
        baseline_execution_time = time.time() - start_time

        # Test 3: Multiple operations baseline (5 operations)
        multiple_operations = []
        for i in range(5):
            multiple_operations.append(
                SimpleSEPAOperation(
                    member_id=f"MOCK-MEMBER-{i:03d}",
                    operation_type="create",
                    operation_data={
                        "iban": f"NL91ABNA041716430{i}",
                        "account_holder": f"Test User {i}",
                        "mandate_reference": f"BASELINE-{i:03d}",
                    },
                )
            )

        # Create fresh manager for multiple operations test
        multi_manager = get_simple_sepa_manager()

        multi_start_time = time.time()
        multi_result = multi_manager.process_operations_simple(multiple_operations)
        multi_execution_time = time.time() - multi_start_time

        return {
            "success": True,
            "baseline_metrics": {
                "single_operation_time": baseline_execution_time,
                "multi_operation_time": multi_execution_time,
                "operations_per_second": 5 / multi_execution_time if multi_execution_time > 0 else 0,
                "avg_time_per_operation": multi_execution_time / 5 if multi_execution_time > 0 else 0,
            },
            "validation_results": {
                "empty_operations": empty_result,
                "single_operation": single_result,
                "multiple_operations": multi_result,
            },
            "runtime_errors": None,
            "message": f"✅ SEPA Simple baseline established: {5 / multi_execution_time:.2f} ops/sec",
        }

    except Exception as e:
        return {"success": False, "error": f"Baseline test failed: {str(e)}", "runtime_errors": str(e)}


@frappe.whitelist()
def run_sepa_baseline_test():
    """
    Whitelisted method to run SEPA baseline test

    Returns baseline performance metrics for simplified implementation
    """
    try:
        result = test_sepa_simple_baseline()

        if result["success"]:
            # Log baseline results
            metrics = result["baseline_metrics"]
            frappe.logger().info(
                f"SEPA Simple Baseline Established: "
                f"{metrics['operations_per_second']:.2f} ops/sec, "
                f"{metrics['avg_time_per_operation']:.4f}s per operation"
            )

        return result

    except Exception as e:
        frappe.logger().error(f"SEPA baseline test error: {str(e)}")
        return {"success": False, "error": f"Test execution failed: {str(e)}"}
