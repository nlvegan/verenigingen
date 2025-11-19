#!/usr/bin/env python3

import frappe

from verenigingen.utils.security.api_security_framework import standard_api


@frappe.whitelist()
def test_decorator_pattern():
    """Test decorator factory pattern to understand the TypeError"""

    results = []
    results.append("=== Decorator Factory Pattern Analysis ===")

    # Test 1: Analyze standard_api function
    results.append(f"1. standard_api function: {standard_api}")
    results.append(f"   Type: {type(standard_api)}")

    # Test 2: Call standard_api() to get decorator
    decorator = standard_api()
    results.append(f"2. standard_api() result: {decorator}")
    results.append(f"   Type: {type(decorator)}")

    # Test 3: Demonstrate what happens without parentheses
    results.append("\n=== Error Demonstration ===")

    def test_function():
        """Test function for decorator testing"""
        return "test result"

    # This works - using standard_api() with parentheses
    try:
        decorator = standard_api()
        decorated_func = decorator(test_function)
        results.append(f"3. SUCCESS: standard_api()(test_function) = {decorated_func}")
        results.append(f"   Result type: {type(decorated_func)}")
    except Exception as e:
        results.append(f"3. ERROR with standard_api(): {e}")

    # This would fail - using standard_api without parentheses
    try:
        # This is what causes the TypeError:
        # standard_api expects to be called with parameters to return a decorator
        # But without parentheses, Python passes the function directly
        decorated_func = standard_api(test_function)
        results.append(f"4. Using standard_api without parentheses: {decorated_func}")
    except Exception as e:
        results.append(f"4. ERROR with standard_api (no parentheses): {e}")

    results.append("\n=== Explanation ===")
    results.append("standard_api is a decorator FACTORY - it needs to be called to create a decorator")
    results.append("- standard_api() → returns a decorator function")
    results.append("- standard_api (no parentheses) → is the factory function itself")
    results.append("- When used as @standard_api, Python passes the decorated function to the factory")
    results.append("- But the factory expects parameters, not the function to be decorated")

    return {"results": results}
