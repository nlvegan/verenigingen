#!/usr/bin/env python3
"""Quick test to verify edge case methods are available"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


@frappe.whitelist()
def test_edge_case_methods_availability():
    """Test that edge case methods are available"""

    try:
        # Check if methods exist
        methods_to_check = [
            "clear_member_auto_schedules",
            "create_controlled_dues_schedule",
            "setup_edge_case_testing",
        ]

        results = {}

        for method_name in methods_to_check:
            if hasattr(VereningingenTestCase, method_name):
                method = getattr(VereningingenTestCase, method_name)
                results[method_name] = {
                    "available": True,
                    "callable": callable(method),
                    "has_docstring": bool(method.__doc__),
                    "docstring_length": len(method.__doc__) if method.__doc__ else 0,
                }
            else:
                results[method_name] = {"available": False}

        return {
            "success": True,
            "methods": results,
            "summary": f'Found {len([r for r in results.values() if r.get("available")])} of {len(methods_to_check)} methods',
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Direct execution test
    result = test_edge_case_methods_availability()
    print(f"Test result: {result}")
