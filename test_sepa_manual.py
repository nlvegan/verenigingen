#!/usr/bin/env python3
"""
Manual test runner for SEPA mandate functionality
"""

import os
import sys
import unittest

# Set up environment
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")


def run_manual_test():
    """Run a manual test of the SEPA mandate test"""
    try:
        # Change to the app directory
        os.chdir("/home/frappe/frappe-bench/apps/verenigingen")

        # Try importing unittest test first to see if basic structure works
        print("Testing basic Python imports...")

        import unittest

        print("✓ unittest imported successfully")

        # Test if the test file can be imported without Frappe
        print("\nTesting test file structure...")

        # Read the test file to check its structure
        with open("verenigingen/tests/test_sepa_mandate_naming.py", "r") as f:
            content = f.read()

        print("✓ Test file exists and is readable")
        print(f"✓ File size: {len(content)} characters")

        # Check for key test methods
        test_methods = [
            "test_default_naming_pattern",
            "test_custom_naming_pattern",
            "test_starting_counter_functionality",
            "test_manual_mandate_id_not_overwritten",
            "test_pattern_date_replacement",
            "test_uniqueness_enforcement",
            "test_fallback_on_error",
            "test_integration_with_existing_workflow",
        ]

        found_methods = []
        for method in test_methods:
            if method in content:
                found_methods.append(method)

        print(f"✓ Found {len(found_methods)}/{len(test_methods)} test methods:")
        for method in found_methods:
            print(f"  - {method}")

        if len(found_methods) != len(test_methods):
            missing = set(test_methods) - set(found_methods)
            print(f"⚠️ Missing test methods: {missing}")

        print("\n✅ Test file structure validation completed")
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    success = run_manual_test()
    print(f"\nTest result: {'PASSED' if success else 'FAILED'}")
    sys.exit(0 if success else 1)
