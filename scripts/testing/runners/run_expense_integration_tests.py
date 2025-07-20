#!/usr/bin/env python3
"""
Comprehensive test runner for ERPNext expense integration
Runs all tests related to the ERPNext expense system migration

Updated: December 2024 - Post-legacy system phase-out
"""

import argparse
import os
import sys
import unittest
from datetime import datetime

# Add the app path to Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")

# Set up Frappe environment
os.chdir("/home/frappe/frappe-bench")
os.environ["DEV_SERVER"] = "1"

import frappe


def setup_test_environment():
    """Set up the test environment"""
    try:
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
        print("✅ Connected to site: dev.veganisme.net")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to site: {str(e)}")
        return False


def run_test_suite(suite_name, test_classes):
    """Run a specific test suite"""
    print(f"\n{'='*60}")
    print(f"🧪 Running {suite_name}")
    print(f"{'='*60}")

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    for test_class in test_classes:
        try:
            tests = loader.loadTestsFromTestCase(test_class)
            suite.addTests(tests)
        except Exception as e:
            print(f"⚠️ Could not load tests from {test_class.__name__}: {str(e)}")

    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(suite)

    return result.wasSuccessful(), len(result.failures), len(result.errors)


def main():
    parser = argparse.ArgumentParser(description="Run ERPNext expense integration tests")
    parser.add_argument(
        "--suite",
        choices=["core", "report", "legacy", "integration", "all"],
        default="all",
        help="Test suite to run",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    print("🔧 ERPNext Expense Integration Test Runner")
    print("=" * 50)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test Suite: {args.suite}")
    print(f"Site: dev.veganisme.net")

    if not setup_test_environment():
        sys.exit(1)

    # Import test classes
    try:
        from verenigingen.tests.test_chapter_expense_report import (
            TestChapterExpenseReport,
            TestChapterExpenseReportIntegration,
        )
        from verenigingen.tests.test_erpnext_expense_integration import (
            TestERPNextExpenseEdgeCases,
            TestERPNextExpenseIntegration,
        )
        from verenigingen.tests.test_legacy_system_removal import (
            TestERPNextMigrationCompliance,
            TestLegacySystemRemoval,
        )

        print("✅ Successfully imported all test classes")
    except ImportError as e:
        print(f"❌ Failed to import test classes: {str(e)}")
        sys.exit(1)

    # Define test suites
    test_suites = {
        "core": {"name": "Core ERPNext Integration Tests", "classes": [TestERPNextExpenseIntegration]},
        "report": {
            "name": "Chapter Expense Report Tests",
            "classes": [TestChapterExpenseReport, TestChapterExpenseReportIntegration]},
        "legacy": {
            "name": "Legacy System Removal Verification",
            "classes": [TestLegacySystemRemoval, TestERPNextMigrationCompliance]},
        "integration": {"name": "Edge Cases and Integration Tests", "classes": [TestERPNextExpenseEdgeCases]},
        "all": {
            "name": "Complete Test Suite",
            "classes": [
                TestERPNextExpenseIntegration,
                TestERPNextExpenseEdgeCases,
                TestChapterExpenseReport,
                TestChapterExpenseReportIntegration,
                TestLegacySystemRemoval,
                TestERPNextMigrationCompliance,
            ]}}

    if args.suite not in test_suites:
        print(f"❌ Unknown test suite: {args.suite}")
        sys.exit(1)

    # Run the selected test suite
    suite_config = test_suites[args.suite]
    success, failures, errors = run_test_suite(suite_config["name"], suite_config["classes"])

    # Print summary
    print(f"\n{'='*60}")
    print(f"📊 TEST SUMMARY")
    print(f"{'='*60}")
    print(f"Suite: {suite_config['name']}")
    print(f"Result: {'✅ PASSED' if success else '❌ FAILED'}")
    print(f"Failures: {failures}")
    print(f"Errors: {errors}")

    if not success:
        print(f"\n⚠️  Some tests failed. Review the output above for details.")
        sys.exit(1)
    else:
        print(f"\n🎉 All tests passed successfully!")

        # Additional verification for complete test suite
        if args.suite == "all":
            print(f"\n✅ ERPNext expense integration verification complete:")
            print(f"   - Core expense submission functionality working")
            print(f"   - Chapter Expense Report updated for ERPNext")
            print(f"   - Legacy system components properly removed")
            print(f"   - Employee creation integration functional")
            print(f"   - Workspace shortcuts configured")
            print(f"   - Error handling robust")


if __name__ == "__main__":
    main()
