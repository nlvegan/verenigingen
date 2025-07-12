#!/usr/bin/env python3
"""
Critical Business Logic Test Runner
Runs all critical tests to ensure business logic methods exist and core functionality works
"""

import os
import subprocess
import sys

# Test modules to run
CRITICAL_TEST_MODULES = [
    # Core critical business logic tests
    "verenigingen.tests.backend.business_logic.test_critical_business_logic",
    # High-risk doctype tests
    "verenigingen.verenigingen.doctype.membership_termination_request.test_membership_termination_request_critical",
    "verenigingen.verenigingen.doctype.e_boekhouden_migration.test_e_boekhouden_migration_critical",
    # Comprehensive doctype tests
    "verenigingen.verenigingen.doctype.membership_termination_request.test_membership_termination_request",
    "verenigingen.verenigingen.doctype.e_boekhouden_migration.test_e_boekhouden_migration",
    # Core doctype tests that should always pass
    "verenigingen.verenigingen.doctype.membership.test_membership",
    "verenigingen.verenigingen.doctype.member.test_member",
    "verenigingen.verenigingen.doctype.chapter.test_chapter",
    "verenigingen.verenigingen.doctype.volunteer.test_volunteer",
    "verenigingen.verenigingen.doctype.volunteer_expense.test_volunteer_expense",
]


def run_test_module(module_name):
    """Run a single test module"""
    print(f"\n{'='*60}")
    print(f"Running tests: {module_name}")
    print(f"{'='*60}")

    cmd = [
        "bench",
        "--site",
        "dev.veganisme.net",
        "run-tests",
        "--app",
        "verenigingen",
        "--module",
        module_name,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/frappe/frappe-bench")

        print(f"Return code: {result.returncode}")
        if result.stdout:
            print("STDOUT:")
            print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        return result.returncode == 0

    except Exception as e:
        print(f"Error running test module {module_name}: {e}")
        return False


def main():
    """Run all critical business logic tests"""
    print("🚀 Starting Critical Business Logic Test Suite")
    print(f"Running {len(CRITICAL_TEST_MODULES)} test modules...")

    results = {}
    total_passed = 0
    total_failed = 0

    for module in CRITICAL_TEST_MODULES:
        success = run_test_module(module)
        results[module] = success

        if success:
            total_passed += 1
            print(f"✅ {module} - PASSED")
        else:
            total_failed += 1
            print(f"❌ {module} - FAILED")

    print(f"\n{'='*60}")
    print("📊 TEST RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total modules tested: {len(CRITICAL_TEST_MODULES)}")
    print(f"Passed: {total_passed}")
    print(f"Failed: {total_failed}")
    print(f"Success rate: {(total_passed / len(CRITICAL_TEST_MODULES)) * 100:.1f}%")

    if total_failed > 0:
        print(f"\n❌ FAILED MODULES:")
        for module, success in results.items():
            if not success:
                print(f"  - {module}")

    print(f"\n{'='*60}")
    if total_failed == 0:
        print("🎉 ALL CRITICAL TESTS PASSED!")
        print("✅ Business logic integrity verified")
        print("✅ No missing methods detected")
        print("✅ Core functionality working")
    else:
        print("⚠️  SOME TESTS FAILED")
        print("🔍 Review failed modules above")
        print("🛠️  Fix issues before deployment")

    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
