#!/usr/bin/env python3
"""
Test script to validate the intelligent item creation integration in E-Boekhouden import
"""

import frappe


def test_intelligent_item_creation():
    """Test the intelligent item creation function"""

    # Import the function
    from verenigingen.utils.eboekhouden.eboekhouden_improved_item_naming import get_or_create_item_improved

    # Test parameters
    test_cases = [
        {
            "account_code": "8000",
            "company": "Test Company",
            "transaction_type": "Sales",
            "description": "Test Income Transaction",
        },
        {
            "account_code": "6000",
            "company": "Test Company",
            "transaction_type": "Purchase",
            "description": "Test Expense Transaction",
        },
        {
            "account_code": "MISC",
            "company": "Test Company",
            "transaction_type": "Both",
            "description": "Test General Transaction",
        },
    ]

    results = []

    for test_case in test_cases:
        try:
            item_code = get_or_create_item_improved(
                account_code=test_case["account_code"],
                company=test_case["company"],
                transaction_type=test_case["transaction_type"],
                description=test_case["description"],
            )

            # Check if item exists
            item_exists = frappe.db.exists("Item", item_code)

            results.append(
                {"test_case": test_case, "item_code": item_code, "item_exists": item_exists, "success": True}
            )

        except Exception as e:
            results.append({"test_case": test_case, "error": str(e), "success": False})

    return results


def test_enhanced_import_ready():
    """Test that the enhanced import is ready to use"""

    # Check if the function exists
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_rest_full_migration import start_full_rest_import

        function_exists = True
    except ImportError as e:
        function_exists = False
        import_error = str(e)

    # Check if intelligent item creation is available
    try:
        from verenigingen.utils.eboekhouden.eboekhouden_improved_item_naming import (
            get_or_create_item_improved,
        )

        item_function_exists = True
    except ImportError as e:
        item_function_exists = False
        item_import_error = str(e)

    return {
        "start_full_rest_import_available": function_exists,
        "get_or_create_item_improved_available": item_function_exists,
        "import_error": import_error if not function_exists else None,
        "item_import_error": item_import_error if not item_function_exists else None,
        "ready_for_testing": function_exists and item_function_exists,
    }


if __name__ == "__main__":
    print("Testing intelligent item creation integration...")

    # Test 1: Check if functions are available
    print("\n1. Testing function availability:")
    readiness = test_enhanced_import_ready()
    print(f"   - start_full_rest_import available: {readiness['start_full_rest_import_available']}")
    print(f"   - get_or_create_item_improved available: {readiness['get_or_create_item_improved_available']}")
    print(f"   - Ready for testing: {readiness['ready_for_testing']}")

    if readiness["ready_for_testing"]:
        print("\n✅ All functions are available - enhanced import is ready!")

        # Test 2: Test intelligent item creation
        print("\n2. Testing intelligent item creation:")
        item_results = test_intelligent_item_creation()

        for i, result in enumerate(item_results, 1):
            if result["success"]:
                print(f"   Test {i}: ✅ Created item '{result['item_code']}'")
            else:
                print(f"   Test {i}: ❌ Failed - {result['error']}")
    else:
        print("\n❌ Functions not available - check import paths")
        if readiness.get("import_error"):
            print(f"   Import error: {readiness['import_error']}")
        if readiness.get("item_import_error"):
            print(f"   Item import error: {readiness['item_import_error']}")
