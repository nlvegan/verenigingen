#!/usr/bin/env python3
"""
Test script to validate security framework imports are working correctly
Usage: bench --site dev.veganisme.net execute verenigingen.test_security_framework_imports.test_imports
"""

import frappe


def test_imports():
    """Test that all security framework imports work correctly"""
    try:
        # Test main framework imports
        from verenigingen.utils.security.api_security_framework import (
            OperationType,
            SecurityLevel,
            critical_api,
            get_security_framework,
            high_security_api,
            public_api,
            standard_api,
            utility_api,
        )

        print("✅ All security decorators imported successfully")
        print(
            f"Available decorators: {[critical_api.__name__, high_security_api.__name__, standard_api.__name__, utility_api.__name__, public_api.__name__]}"
        )

        # Test OperationType enum
        print(f"OperationType.FINANCIAL: {OperationType.FINANCIAL}")
        print(f"OperationType.MEMBER_DATA: {OperationType.MEMBER_DATA}")

        # Test SecurityLevel enum
        print(f"SecurityLevel.CRITICAL: {SecurityLevel.CRITICAL}")
        print(f"SecurityLevel.HIGH: {SecurityLevel.HIGH}")

        # Test framework initialization
        framework = get_security_framework()
        print(f"Framework initialized: {framework is not None}")

        return {
            "success": True,
            "message": "All security framework imports working correctly",
            "decorators_available": True,
            "enums_available": True,
            "framework_initialized": True,
        }

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return {"success": False, "error": f"Import error: {e}", "type": "import_error"}
    except Exception as e:
        print(f"❌ Other error: {e}")
        return {"success": False, "error": f"Other error: {e}", "type": "other_error"}


@frappe.whitelist()
def test_api_imports():
    """Test that API files can import security decorators correctly"""
    import importlib
    import os

    api_files_to_test = [
        "verenigingen.api.membership_application_review",
        "verenigingen.api.dd_batch_scheduler",
        "verenigingen.api.periodic_donation_operations",
        "verenigingen.api.sepa_batch_notifications",
        "verenigingen.api.customer_member_link",
    ]

    results = {}

    for module_name in api_files_to_test:
        try:
            module = importlib.import_module(module_name)
            # Check if the module has imported security decorators
            has_decorators = any(
                hasattr(module, attr) for attr in ["critical_api", "high_security_api", "standard_api"]
            )
            results[module_name] = {"imported": True, "has_security_decorators": has_decorators}
            print(f"✅ {module_name}: imported successfully")
        except Exception as e:
            results[module_name] = {"imported": False, "error": str(e)}
            print(f"❌ {module_name}: {e}")

    return {
        "success": True,
        "results": results,
        "total_files": len(api_files_to_test),
        "successful_imports": len([r for r in results.values() if r.get("imported")]),
    }


if __name__ == "__main__":
    test_imports()
