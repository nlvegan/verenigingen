#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive test runner for the enhanced membership dues system
Runs all tests related to the new flexible contribution system, payment plans, and enhanced SEPA processing
"""

import sys
import os
import frappe
from frappe.test_runner import main


def run_membership_dues_tests(suite=None, verbose=False):
    """
    Run membership dues system tests
    
    Args:
        suite: Test suite to run ('core', 'integration', 'all', or None for all)
        verbose: Enable verbose output
    """
    
    # Define test modules for the membership dues system
    test_modules = {
        'core': [
            'verenigingen.tests.backend.components.test_membership_dues_system',
            'verenigingen.tests.backend.components.test_payment_plan_system',
            'verenigingen.tests.backend.components.test_enhanced_sepa_processing',
        ],
        'integration': [
            'verenigingen.tests.workflows.test_enhanced_membership_lifecycle',
        ],
        'api': [
            'verenigingen.tests.unit.api.test_enhanced_membership_api',
            'verenigingen.tests.unit.api.test_payment_plan_api',
        ],
        'validation': [
            'verenigingen.tests.backend.validation.test_membership_dues_validation',
            'verenigingen.tests.backend.validation.test_payment_plan_validation',
        ]
    }
    
    # Determine which tests to run
    if suite == 'core':
        modules_to_run = test_modules['core']
    elif suite == 'integration':
        modules_to_run = test_modules['integration'] 
    elif suite == 'api':
        modules_to_run = test_modules.get('api', [])
    elif suite == 'validation':
        modules_to_run = test_modules.get('validation', [])
    elif suite == 'all' or suite is None:
        modules_to_run = []
        for suite_modules in test_modules.values():
            modules_to_run.extend(suite_modules)
    else:
        print(f"Unknown test suite: {suite}")
        print("Available suites: core, integration, api, validation, all")
        return False
    
    print(f"Running membership dues system tests...")
    print(f"Suite: {suite or 'all'}")
    print(f"Modules: {len(modules_to_run)}")
    print("=" * 60)
    
    # Filter modules that actually exist
    existing_modules = []
    for module in modules_to_run:
        try:
            # Convert module path to file path and check existence
            file_path = module.replace('.', '/') + '.py'
            full_path = os.path.join('/home/frappe/frappe-bench/apps', file_path)
            if os.path.exists(full_path):
                existing_modules.append(module)
            elif verbose:
                print(f"Skipping non-existent module: {module}")
        except:
            if verbose:
                print(f"Error checking module: {module}")
    
    if not existing_modules:
        print("No test modules found!")
        return False
    
    print(f"Running {len(existing_modules)} test modules:")
    for module in existing_modules:
        print(f"  - {module}")
    print()
    
    # Run tests
    success = True
    results = {}
    
    for module in existing_modules:
        print(f"Running {module}...")
        try:
            # Use frappe test runner
            result = main(
                module=module,
                verbose=verbose,
                force=True,
                profile=False
            )
            results[module] = "PASS" if result == 0 else "FAIL"
            if result != 0:
                success = False
                print(f"❌ {module} FAILED")
            else:
                print(f"✅ {module} PASSED")
        except Exception as e:
            results[module] = f"ERROR: {str(e)}"
            success = False
            print(f"💥 {module} ERROR: {e}")
        print()
    
    # Print summary
    print("=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    
    passed = sum(1 for r in results.values() if r == "PASS")
    failed = sum(1 for r in results.values() if r == "FAIL")
    errors = sum(1 for r in results.values() if r.startswith("ERROR"))
    
    for module, result in results.items():
        status_icon = "✅" if result == "PASS" else "❌" if result == "FAIL" else "💥"
        print(f"{status_icon} {module}: {result}")
    
    print(f"\nTotal: {len(results)} modules")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Errors: {errors}")
    
    if success:
        print("\n🎉 All membership dues system tests passed!")
    else:
        print(f"\n⚠️  {failed + errors} test module(s) failed")
    
    return success


def validate_test_environment():
    """Validate that the test environment is properly set up"""
    print("Validating test environment...")
    
    # Check if new DocTypes exist
    required_doctypes = [
        "Membership Dues Schedule",
        "Payment Plan", 
        "Payment Plan Installment",
        "Membership Tier"
    ]
    
    missing_doctypes = []
    for doctype in required_doctypes:
        if not frappe.db.exists("DocType", doctype):
            missing_doctypes.append(doctype)
    
    if missing_doctypes:
        print(f"❌ Missing DocTypes: {', '.join(missing_doctypes)}")
        print("Please run 'bench migrate' to create the required DocTypes")
        return False
    else:
        print("✅ All required DocTypes found")
    
    # Check if test infrastructure is available
    try:
        from verenigingen.tests.utils.base import VereningingenTestCase
        print("✅ Test infrastructure available")
    except ImportError as e:
        print(f"❌ Test infrastructure not available: {e}")
        return False
    
    # Check if API endpoints are available
    try:
        from verenigingen.api.enhanced_membership_application import get_membership_types_for_application
        from verenigingen.api.payment_plan_management import request_payment_plan
        print("✅ API endpoints available")
    except ImportError as e:
        print(f"❌ API endpoints not available: {e}")
        return False
    
    print("✅ Test environment validation passed")
    return True


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Run membership dues system tests")
    parser.add_argument(
        "--suite", 
        choices=["core", "integration", "api", "validation", "all"],
        default="all",
        help="Test suite to run"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true", 
        help="Only validate test environment, don't run tests"
    )
    
    args = parser.parse_args()
    
    # Validate environment first
    if not validate_test_environment():
        sys.exit(1)
    
    if args.validate_only:
        print("Environment validation completed successfully")
        sys.exit(0)
    
    # Run tests
    success = run_membership_dues_tests(
        suite=args.suite,
        verbose=args.verbose
    )
    
    sys.exit(0 if success else 1)