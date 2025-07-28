#!/usr/bin/env python3
"""
Test script to verify the improvements made to the JS-Python parameter validator
"""

import sys

sys.path.append("scripts/validation")

import json
from pathlib import Path

from js_python_parameter_validator_enhanced import EnhancedJSPythonParameterValidator, JSCall


def test_validator_improvements():
    """Test the specific improvements made to address the 10 doubtful validation issues"""

    print("Testing Enhanced JS-Python Parameter Validator Improvements")
    print("=" * 60)

    validator = EnhancedJSPythonParameterValidator(".")

    # Test 1: Path Resolution Problems
    print("\n1. Testing Path Resolution Improvements:")
    print("-" * 40)

    # These methods exist but with different paths - test fuzzy matching
    test_methods = [
        "derive_bic_from_iban",  # Should find in utils/validation/iban_validator.py
        "get_billing_amount",  # Should not find (no @frappe.whitelist)
        "get_user_chapters",  # Should find in api/get_user_chapters.py
    ]

    # Build function index first
    validator.scan_python_files()

    for method in test_methods:
        resolved = validator.resolve_method_path(method)
        if resolved:
            print(f"  ✓ {method} -> {resolved.full_method_path}")
            print(f"    File: {resolved.file_path}")
        else:
            print(f"  ✗ {method} -> Not found")

    # Test 2: Framework Method Detection
    print("\n2. Testing Framework Method Detection:")
    print("-" * 40)

    framework_test_methods = [
        "frappe.client.get",
        "frappe.client.get_list",
        "frappe.db.get_value",
        "frappe.call",
        "some.custom.method",  # Should not be framework
    ]

    for method in framework_test_methods:
        is_framework = validator.is_framework_method(method)
        print(f"  {'✓' if is_framework else '✗'} {method} -> {'Framework' if is_framework else 'Custom'}")

    # Test 3: Function Name Indexing
    print("\n3. Testing Function Name Indexing:")
    print("-" * 40)

    print(f"  Total function names indexed: {len(validator.function_name_index)}")

    # Check some specific function names
    sample_functions = ["derive_bic_from_iban", "get_user_chapters", "validate_iban"]
    for func_name in sample_functions:
        if func_name in validator.function_name_index:
            matches = validator.function_name_index[func_name]
            print(f"  ✓ {func_name}: {len(matches)} occurrence(s)")
            for match in matches[:2]:  # Show first 2
                print(f"    - {match.full_method_path}")
        else:
            print(f"  ✗ {func_name}: Not found in index")

    # Test 4: Improved Issue Categorization
    print("\n4. Testing Issue Categorization:")
    print("-" * 40)

    test_calls = [
        JSCall("test.js", 1, "frappe.client.get", {}, "", "frappe.call"),
        JSCall("test.js", 2, "debug_some_function", {}, "", "frappe.call"),
        JSCall("test.js", 3, "verenigingen.api.member_management.get_member", {}, "", "frappe.call"),
        JSCall("test.js", 4, "some_missing_method", {}, "", "frappe.call"),
    ]

    for call in test_calls:
        severity = validator.get_method_severity(call.method_name, call)
        action = validator._get_resolution_action(call.method_name)
        print(f"  {call.method_name}: {severity} severity, {action} action")

    # Test 5: Configuration Support
    print("\n5. Testing Configuration Support:")
    print("-" * 40)

    config = validator.config
    print(f"  Framework methods configured: {len(config.get('framework_methods', []))}")
    print(f"  Exclude patterns: {len(config.get('exclude_patterns', []))}")
    print(
        f"  Fuzzy matching enabled: {config.get('path_resolution', {}).get('enable_fuzzy_matching', False)}"
    )
    print(f"  Severity rules: {list(config.get('severity_rules', {}).keys())}")

    # Test 6: Run Full Validation and Show Statistics
    print("\n6. Full Validation Test Results:")
    print("-" * 40)

    validator_full = EnhancedJSPythonParameterValidator(".")
    results = validator_full.run_validation()

    print(f"  JavaScript files scanned: {results['stats']['js_files_scanned']}")
    print(f"  Python files scanned: {results['stats']['py_files_scanned']}")
    print(f"  Python functions found: {results['stats']['python_functions_found']}")
    print(f"  JavaScript calls found: {results['stats']['js_calls_found']}")
    print(f"  Framework methods detected: {results['framework_methods']}")
    print(f"  Actionable issues: {results['actionable_issues']}")
    print(f"  Total issues (including ignored): {results['total_issues']}")
    print(f"  Fuzzy matches found: {results['stats']['fuzzy_matches_found']}")

    # Test 7: Compare with Known Issues
    print("\n7. Testing Against Known Doubtful Cases:")
    print("-" * 40)

    known_doubtful_cases = [
        ("derive_bic_from_iban", "Should be found via fuzzy matching"),
        ("get_billing_amount", "Should not be found (no @frappe.whitelist)"),
        ("frappe.client.get", "Should be ignored (framework method)"),
        ("frappe.client.get_list", "Should be ignored (framework method)"),
        ("validate_postal_codes", "Should be found or provide good suggestions"),
    ]

    for method, expected in known_doubtful_cases:
        resolved = validator_full.resolve_method_path(method)
        is_framework = validator_full.is_framework_method(method)

        if is_framework:
            status = "✓ Correctly ignored (framework method)"
        elif resolved:
            status = f"✓ Found: {resolved.full_method_path}"
        else:
            # Check fuzzy matches
            fuzzy = validator_full.fuzzy_match_function(method)
            if fuzzy:
                status = f"≈ Fuzzy match: {fuzzy.function_name}"
            else:
                status = "✗ Not found"

        print(f"  {method}: {status}")
        print(f"    Expected: {expected}")

    print(f"\n{'='*60}")
    print("Enhanced Validator Testing Complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    test_validator_improvements()
