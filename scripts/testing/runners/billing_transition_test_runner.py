#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2025, Foppe de Haan  
# License: GNU Affero General Public License v3 (AGPLv3)

"""
Billing Transition Test Runner
Runs comprehensive tests to ensure no duplicate billing during frequency changes

This runner now uses Frappe's proper test infrastructure instead of 
executing test code from temporary files.
"""

import sys
import os
import argparse
import subprocess
from pathlib import Path

def run_billing_transition_tests(test_type="all", verbose=False):
    """
    Run billing transition tests using Frappe's test infrastructure
    
    Args:
        test_type: Type of tests to run (all, personas, transitions, validation)
        verbose: Enable verbose output
    """
    
    print("🧪 Starting Billing Transition Test Suite")
    print("=" * 60)
    
    results = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": []
    }
    
    # Map test categories to actual test modules
    test_modules = {
        "all": [
            "verenigingen.tests.test_billing_transitions",
            "verenigingen.tests.test_billing_transitions_proper",
            "verenigingen.tests.test_billing_transitions_simplified"
        ],
        "personas": [
            "verenigingen.tests.fixtures.billing_transition_personas"
        ],
        "transitions": [
            "verenigingen.tests.test_billing_transitions"
        ],
        "validation": [
            "verenigingen.tests.test_billing_transitions_proper"
        ]
    }
    
    modules_to_run = test_modules.get(test_type, test_modules["all"])
    
    for module in modules_to_run:
        results["total"] += 1
        
        print(f"\n📋 Running: {module}")
        print("-" * 40)
        
        # Run tests using bench run-tests
        success = run_module_tests(module, verbose)
        
        if success:
            results["passed"] += 1
            print(f"✅ {module} PASSED")
        else:
            results["failed"] += 1
            results["errors"].append(module)
            print(f"❌ {module} FAILED")
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 BILLING TRANSITION TEST SUMMARY")
    print("=" * 60)
    print(f"Total Test Modules: {results['total']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    
    if results["failed"] > 0:
        print(f"\n❌ Failed Modules: {', '.join(results['errors'])}")
        return False
    else:
        print("\n✅ All billing transition tests passed!")
        return True

def run_module_tests(module_path, verbose=False):
    """
    Run tests for a specific module using bench run-tests
    
    Args:
        module_path: Full module path (e.g., verenigingen.tests.test_billing_transitions)
        verbose: Enable verbose output
    
    Returns:
        bool: True if tests passed, False otherwise
    """
    try:
        cmd = [
            "bench", "--site", "dev.veganisme.net", 
            "run-tests",
            "--app", "verenigingen",
            "--module", module_path
        ]
        
        if verbose:
            cmd.append("--verbose")
            print(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            cwd="/home/frappe/frappe-bench",
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout
        )
        
        if verbose:
            print("Output:", result.stdout)
            if result.stderr:
                print("Errors:", result.stderr)
        
        # Check for test failures in output
        return result.returncode == 0 and "FAILED" not in result.stdout
        
    except subprocess.TimeoutExpired:
        print("❌ Test timed out after 5 minutes")
        return False
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False

def validate_test_files():
    """Validate that required test files exist"""
    print("🔍 Validating test files...")
    
    required_files = [
        "verenigingen/tests/test_billing_transitions.py",
        "verenigingen/tests/test_billing_transitions_proper.py",
        "verenigingen/tests/test_billing_transitions_simplified.py",
        "verenigingen/tests/fixtures/billing_transition_personas.py"
    ]
    
    app_path = "/home/frappe/frappe-bench/apps/verenigingen"
    all_exist = True
    
    for file_path in required_files:
        full_path = os.path.join(app_path, file_path)
        exists = os.path.exists(full_path)
        
        if exists:
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path} - NOT FOUND")
            all_exist = False
    
    return all_exist

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Run billing transition tests"
    )
    parser.add_argument(
        "--type",
        choices=["all", "personas", "transitions", "validation"],
        default="all",
        help="Type of tests to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate test files exist"
    )
    
    args = parser.parse_args()
    
    # Validate test files
    if not validate_test_files():
        print("\n❌ Required test files are missing!")
        sys.exit(1)
    
    if args.validate_only:
        print("\n✅ All test files present")
        sys.exit(0)
    
    # Run tests
    success = run_billing_transition_tests(
        test_type=args.type,
        verbose=args.verbose
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()