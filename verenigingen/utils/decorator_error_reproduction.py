#!/usr/bin/env python3

import frappe

from verenigingen.utils.security.api_security_framework import standard_api


@frappe.whitelist()
def reproduce_decorator_error():
    """Reproduce the exact decorator error that was happening"""

    results = []
    results.append("=== Reproducing Original Decorator Error ===")

    # Let's look at what standard_api actually is
    results.append(f"standard_api function: {standard_api}")
    results.append(f"standard_api.__code__.co_varnames: {standard_api.__code__.co_varnames}")
    results.append(f"standard_api.__code__.co_argcount: {standard_api.__code__.co_argcount}")

    # Test what happens when we call standard_api with a function (like @standard_api does)
    def dummy_function():
        return "test"

    # This is what happens with @standard_api (without parentheses)
    try:
        result = standard_api(dummy_function)
        results.append(f"standard_api(function) WORKED: {result}")
        results.append(f"Type: {type(result)}")
    except Exception as e:
        results.append(f"standard_api(function) ERROR: {e}")
        results.append(f"Error type: {type(e)}")

    # This is what happens with @standard_api() (with parentheses)
    try:
        decorator = standard_api()
        result = decorator(dummy_function)
        results.append(f"standard_api()(function) WORKED: {result}")
        results.append(f"Type: {type(result)}")
    except Exception as e:
        results.append(f"standard_api()(function) ERROR: {e}")

    # Let's also check the signature of api_security_framework
    from verenigingen.utils.security.api_security_framework import api_security_framework

    results.append(f"\napi_security_framework signature: {api_security_framework.__code__.co_varnames}")
    results.append(f"api_security_framework argcount: {api_security_framework.__code__.co_argcount}")

    return {"results": results}
