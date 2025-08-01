"""
Deep Analysis of Decorator Chaining Issues

This test focuses on the specific error:
"decorator() missing 1 required positional argument: 'func'"

This error typically occurs when:
1. A decorator factory is called without parentheses
2. Decorator factories are mixed with direct decorators incorrectly
3. There are issues with decorator application order
"""

import inspect
import traceback
from functools import wraps

import frappe
from frappe import _

from verenigingen.utils.error_handling import handle_api_error
from verenigingen.utils.performance_utils import performance_monitor
from verenigingen.utils.security.api_security_framework import OperationType, standard_api


@frappe.whitelist()
def analyze_decorator_types():
    """Analyze the types and calling patterns of each decorator"""

    analysis = {}

    # Analyze @standard_api
    try:
        # Check if standard_api is a function (decorator factory)
        analysis["standard_api"] = {
            "type": type(standard_api).__name__,
            "callable": callable(standard_api),
            "is_function": inspect.isfunction(standard_api),
            "signature": str(inspect.signature(standard_api)) if callable(standard_api) else None,
            "pattern": "decorator_factory",  # Returns a decorator
        }

        # Test calling standard_api()
        decorator_func = standard_api()
        analysis["standard_api"]["factory_returns"] = {
            "type": type(decorator_func).__name__,
            "callable": callable(decorator_func),
            "pattern": "returns_decorator",
        }

    except Exception as e:
        analysis["standard_api"] = {"error": str(e)}

    # Analyze @handle_api_error
    try:
        analysis["handle_api_error"] = {
            "type": type(handle_api_error).__name__,
            "callable": callable(handle_api_error),
            "is_function": inspect.isfunction(handle_api_error),
            "signature": str(inspect.signature(handle_api_error)) if callable(handle_api_error) else None,
            "pattern": "direct_decorator",  # Takes function directly
        }

    except Exception as e:
        analysis["handle_api_error"] = {"error": str(e)}

    # Analyze @performance_monitor
    try:
        analysis["performance_monitor"] = {
            "type": type(performance_monitor).__name__,
            "callable": callable(performance_monitor),
            "is_function": inspect.isfunction(performance_monitor),
            "signature": str(inspect.signature(performance_monitor))
            if callable(performance_monitor)
            else None,
            "pattern": "decorator_factory",  # Returns a decorator
        }

        # Test calling performance_monitor(threshold_ms=1000)
        decorator_func = performance_monitor(threshold_ms=1000)
        analysis["performance_monitor"]["factory_returns"] = {
            "type": type(decorator_func).__name__,
            "callable": callable(decorator_func),
            "pattern": "returns_decorator",
        }

    except Exception as e:
        analysis["performance_monitor"] = {"error": str(e)}

    return analysis


@frappe.whitelist()
def test_decorator_factory_vs_direct():
    """Test the difference between decorator factories and direct decorators"""

    results = []

    # Test 1: Call @standard_api without parentheses (common mistake)
    try:
        # This simulates: @standard_api (without parentheses)
        def test_func_1():
            return "test"

        # Manually apply decorator without parentheses - this should fail
        decorated_func = standard_api(test_func_1)  # This is wrong - standard_api expects no args
        result = decorated_func()

        results.append(
            {
                "test": "standard_api_without_parentheses",
                "success": True,
                "result": result,
                "note": "Unexpected success - this should have failed",
            }
        )

    except Exception as e:
        results.append(
            {
                "test": "standard_api_without_parentheses",
                "success": False,
                "error": str(e),
                "note": "Expected failure - confirms decorator factory needs ()",
            }
        )

    # Test 2: Correct usage of @standard_api()
    try:

        def test_func_2():
            return "test"

        # Correctly apply decorator factory
        decorator = standard_api()  # Get the decorator
        decorated_func = decorator(test_func_2)  # Apply to function
        result = decorated_func()

        results.append(
            {
                "test": "standard_api_correct_usage",
                "success": True,
                "result": result,
                "note": "Correct decorator factory pattern",
            }
        )

    except Exception as e:
        results.append(
            {
                "test": "standard_api_correct_usage",
                "success": False,
                "error": str(e),
                "note": "Unexpected failure",
            }
        )

    # Test 3: Apply @handle_api_error directly (correct)
    try:

        def test_func_3():
            return "test"

        # Direct decorator application
        decorated_func = handle_api_error(test_func_3)
        result = decorated_func()

        results.append(
            {
                "test": "handle_api_error_direct",
                "success": True,
                "result": result,
                "note": "Direct decorator works correctly",
            }
        )

    except Exception as e:
        results.append(
            {
                "test": "handle_api_error_direct",
                "success": False,
                "error": str(e),
                "note": "Unexpected failure",
            }
        )

    return results


@frappe.whitelist()
def test_problematic_chaining_patterns():
    """Test specific patterns that might cause the 'missing func argument' error"""

    results = []

    # Pattern 1: Mixed decorator types with potential order issues
    try:

        @frappe.whitelist(allow_guest=True)  # Decorator factory
        @standard_api()  # Decorator factory
        @handle_api_error  # Direct decorator
        @performance_monitor(threshold_ms=1000)  # Decorator factory
        def test_mixed_pattern():
            return {"result": "mixed pattern works"}

        result = test_mixed_pattern()
        results.append({"pattern": "mixed_decorator_types", "success": True, "result": result})

    except Exception as e:
        results.append(
            {
                "pattern": "mixed_decorator_types",
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )

    # Pattern 2: Simulate potential import/loading issues
    try:
        # This tests if decorators are properly loaded
        from verenigingen.utils.error_handling import handle_api_error as hae
        from verenigingen.utils.performance_utils import performance_monitor as pm
        from verenigingen.utils.security.api_security_framework import standard_api as sa

        @frappe.whitelist(allow_guest=True)
        @sa()
        @hae
        @pm(threshold_ms=1000)
        def test_reimported_decorators():
            return {"result": "reimported decorators work"}

        result = test_reimported_decorators()
        results.append({"pattern": "reimported_decorators", "success": True, "result": result})

    except Exception as e:
        results.append(
            {
                "pattern": "reimported_decorators",
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )

    # Pattern 3: Test the exact pattern from the failing function
    try:

        @frappe.whitelist(allow_guest=True)
        @standard_api()
        @handle_api_error
        @performance_monitor(threshold_ms=1000)
        def test_exact_failing_pattern(postal_code):
            """Replicate the exact signature and decorator pattern that was failing"""
            if not postal_code:
                return {"success": False, "error": "Postal code is required"}
            return {"success": True, "postal_code": postal_code}

        result = test_exact_failing_pattern("1234AB")
        results.append({"pattern": "exact_failing_pattern", "success": True, "result": result})

    except Exception as e:
        results.append(
            {
                "pattern": "exact_failing_pattern",
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }
        )

    return results


@frappe.whitelist()
def test_decorator_loading_issues():
    """Test if there are issues with decorator loading/imports"""

    results = []

    # Test 1: Check if decorators are properly imported
    try:
        import verenigingen.utils.error_handling
        import verenigingen.utils.performance_utils
        import verenigingen.utils.security.api_security_framework

        # Check if modules loaded correctly
        modules_check = {
            "api_security_framework": hasattr(
                verenigingen.utils.security.api_security_framework, "standard_api"
            ),
            "error_handling": hasattr(verenigingen.utils.error_handling, "handle_api_error"),
            "performance_utils": hasattr(verenigingen.utils.performance_utils, "performance_monitor"),
        }

        results.append(
            {"test": "module_loading", "success": all(modules_check.values()), "details": modules_check}
        )

    except Exception as e:
        results.append({"test": "module_loading", "success": False, "error": str(e)})

    # Test 2: Check decorator attributes/metadata
    try:
        decorator_info = {}

        # Check @standard_api decorator
        sa_decorator = standard_api()
        decorator_info["standard_api"] = {
            "has_wraps": hasattr(sa_decorator, "__wrapped__"),
            "has_name": hasattr(sa_decorator, "__name__"),
            "module": getattr(sa_decorator, "__module__", None),
        }

        # Check @handle_api_error
        decorator_info["handle_api_error"] = {
            "has_wraps": hasattr(handle_api_error, "__wrapped__"),
            "has_name": hasattr(handle_api_error, "__name__"),
            "module": getattr(handle_api_error, "__module__", None),
        }

        # Check @performance_monitor
        pm_decorator = performance_monitor(threshold_ms=1000)
        decorator_info["performance_monitor"] = {
            "has_wraps": hasattr(pm_decorator, "__wrapped__"),
            "has_name": hasattr(pm_decorator, "__name__"),
            "module": getattr(pm_decorator, "__module__", None),
        }

        results.append({"test": "decorator_metadata", "success": True, "details": decorator_info})

    except Exception as e:
        results.append({"test": "decorator_metadata", "success": False, "error": str(e)})

    return results


@frappe.whitelist()
def run_comprehensive_decorator_analysis():
    """Run all decorator analysis tests"""

    results = {
        "decorator_types": analyze_decorator_types(),
        "factory_vs_direct": test_decorator_factory_vs_direct(),
        "chaining_patterns": test_problematic_chaining_patterns(),
        "loading_issues": test_decorator_loading_issues(),
    }

    # Summary analysis
    chaining_failures = [r for r in results["chaining_patterns"] if not r["success"]]
    factory_failures = [r for r in results["factory_vs_direct"] if not r["success"]]

    summary = {
        "total_chaining_tests": len(results["chaining_patterns"]),
        "chaining_failures": len(chaining_failures),
        "factory_test_failures": len(factory_failures),
        "likely_root_cause": None,
        "recommendations": [],
    }

    # Analyze likely root causes
    if chaining_failures:
        for failure in chaining_failures:
            if "missing 1 required positional argument" in failure.get("error", ""):
                summary["likely_root_cause"] = "decorator_factory_confusion"
                summary["recommendations"].append("Use @standard_api() with parentheses, not @standard_api")
            elif "pattern" in failure and failure["pattern"] == "exact_failing_pattern":
                summary["likely_root_cause"] = "specific_decorator_order_issue"
                summary["recommendations"].append("Try different decorator ordering")

    if not chaining_failures:
        summary["likely_root_cause"] = "issue_resolved_or_environment_specific"
        summary["recommendations"].append("The decorator chaining issue may have been resolved")

    results["summary"] = summary
    return results
