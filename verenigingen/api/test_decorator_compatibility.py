"""
Test decorator compatibility issues directly in API context
"""

import frappe
from frappe import _

from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
def test_individual_decorators():
    """Test individual decorators work"""
    return {"result": "individual decorators work"}


@frappe.whitelist()
@handle_api_error
def test_handle_api_error_only():
    """Test @handle_api_error alone"""
    return {"result": "@handle_api_error works"}


@frappe.whitelist()
@performance_monitor(threshold_ms=1000)
def test_performance_monitor_only():
    """Test @performance_monitor alone"""
    return {"result": "@performance_monitor works"}


@frappe.whitelist()
@standard_api()
def test_standard_api_only():
    """Test @standard_api() alone"""
    return {"result": "@standard_api works"}


# Working combination (without @standard_api)
@frappe.whitelist(allow_guest=True)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def test_working_combination():
    """Test the working combination without @standard_api()"""
    return {"result": "working combination without @standard_api"}


# Original failing combination - this should reproduce the error
@frappe.whitelist(allow_guest=True)
@standard_api()
@handle_api_error
@performance_monitor(threshold_ms=1000)
def test_failing_combination():
    """Test the reported failing combination"""
    return {"result": "this might fail with decorator error"}


# Known working @standard_api pattern from dd_batch_workflow_controller.py
@standard_api()
@frappe.whitelist()
def test_known_working_pattern():
    """Test the pattern that works in dd_batch_workflow_controller.py"""
    return {"result": "known working @standard_api pattern"}


# Test different orders
@standard_api()
@frappe.whitelist(allow_guest=True)
@handle_api_error
@performance_monitor(threshold_ms=1000)
def test_order_1():
    """Test with @standard_api() first"""
    return {"result": "@standard_api first"}


@performance_monitor(threshold_ms=1000)
@handle_api_error
@standard_api()
@frappe.whitelist(allow_guest=True)
def test_order_2():
    """Test with @performance_monitor first"""
    return {"result": "@performance_monitor first"}


@frappe.whitelist()
def run_decorator_compatibility_tests():
    """
    Run all decorator compatibility tests and return results
    This can be called via bench execute or API
    """
    results = []

    test_functions = [
        ("individual_decorators", test_individual_decorators),
        ("handle_api_error_only", test_handle_api_error_only),
        ("performance_monitor_only", test_performance_monitor_only),
        ("standard_api_only", test_standard_api_only),
        ("working_combination", test_working_combination),
        ("failing_combination", test_failing_combination),
        ("known_working_pattern", test_known_working_pattern),
        ("order_1", test_order_1),
        ("order_2", test_order_2),
    ]

    for test_name, test_func in test_functions:
        try:
            result = test_func()
            results.append({"test": test_name, "success": True, "result": result, "error": None})
        except Exception as e:
            results.append({"test": test_name, "success": False, "result": None, "error": str(e)})

    # Summary
    total = len(results)
    passed = sum(1 for r in results if r["success"])
    failed = total - passed

    return {
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "success_rate": f"{(passed/total)*100:.1f}%",
        },
        "results": results,
        "analysis": analyze_results(results),
    }


def analyze_results(results):
    """Analyze test results to identify patterns"""
    failed_tests = [r for r in results if not r["success"]]

    analysis = {"failed_tests": len(failed_tests), "failures": []}

    for failure in failed_tests:
        analysis["failures"].append({"test": failure["test"], "error": failure["error"]})

    # Pattern analysis
    standard_api_failures = [f for f in failed_tests if "standard_api" in f["test"]]
    if standard_api_failures:
        analysis["standard_api_issue"] = True
        analysis["recommendation"] = "Issue with @standard_api() decorator chaining identified"
    else:
        analysis["standard_api_issue"] = False
        analysis["recommendation"] = "No @standard_api() issues detected"

    return analysis
