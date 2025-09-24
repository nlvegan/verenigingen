#!/usr/bin/env python3
"""
Failed Payment System Test Runner
=================================

Comprehensive test runner for the Mollie failed payment handling system.
Runs all unit tests, integration tests, and performance tests with detailed
reporting and coverage analysis.

Usage:
    python run_failed_payment_tests.py [options]

Options:
    --unit           Run only unit tests
    --integration    Run only integration tests
    --performance    Run only performance tests
    --coverage       Generate coverage report
    --verbose        Verbose output
    --fast           Skip slow performance tests

Example:
    python run_failed_payment_tests.py --unit --coverage
    python run_failed_payment_tests.py --integration --verbose
    python run_failed_payment_tests.py --all
"""

import sys
import os
import argparse
import time
import subprocess
from pathlib import Path

# Add the apps directory to Python path for imports
sys.path.insert(0, '/home/frappe/frappe-bench/apps')

def run_command(command, description):
    """Run a command and return success status"""
    print(f"\n{'='*60}")
    print(f"🔄 {description}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=False)
        end_time = time.time()
        print(f"✅ {description} completed in {end_time - start_time:.2f}s")
        return True
    except subprocess.CalledProcessError as e:
        end_time = time.time()
        print(f"❌ {description} failed after {end_time - start_time:.2f}s")
        print(f"Error: {e}")
        return False

def run_unit_tests():
    """Run unit tests for failed payment processing"""
    print("\n🧪 Running Unit Tests")
    print("=" * 50)

    test_files = [
        "verenigingen.integrations.mollie.tests.test_failed_payment_processing",
        "verenigingen.tests.test_payment_failure_email_templates"
    ]

    success_count = 0
    total_count = len(test_files)

    for test_file in test_files:
        command = f"cd /home/frappe/frappe-bench && bench --site dev.veganisme.net run-tests --module {test_file}"
        if run_command(command, f"Unit Tests: {test_file.split('.')[-1]}"):
            success_count += 1

    print(f"\n📊 Unit Test Results: {success_count}/{total_count} test suites passed")
    return success_count == total_count

def run_integration_tests():
    """Run integration tests for webhook processing"""
    print("\n🔗 Running Integration Tests")
    print("=" * 50)

    test_files = [
        "verenigingen.integrations.mollie.tests.test_webhook_integration_comprehensive"
    ]

    success_count = 0
    total_count = len(test_files)

    for test_file in test_files:
        command = f"cd /home/frappe/frappe-bench && bench --site dev.veganisme.net run-tests --module {test_file}"
        if run_command(command, f"Integration Tests: {test_file.split('.')[-1]}"):
            success_count += 1

    print(f"\n📊 Integration Test Results: {success_count}/{total_count} test suites passed")
    return success_count == total_count

def run_performance_tests(fast=False):
    """Run performance tests"""
    print("\n⚡ Running Performance Tests")
    print("=" * 50)

    if fast:
        print("🚀 Running fast performance tests only")

    # Performance tests are included in the comprehensive integration tests
    # but can be run separately if needed
    test_files = [
        "verenigingen.integrations.mollie.tests.test_webhook_integration_comprehensive.TestWebhookPerformanceIntegration"
    ]

    success_count = 0
    total_count = len(test_files)

    for test_file in test_files:
        if fast and "bulk" in test_file.lower():
            print(f"⏭️ Skipping slow test: {test_file}")
            continue

        command = f"cd /home/frappe/frappe-bench && bench --site dev.veganisme.net run-tests --module {test_file}"
        if run_command(command, f"Performance Tests: {test_file.split('.')[-1]}"):
            success_count += 1

    print(f"\n📊 Performance Test Results: {success_count}/{total_count} test suites passed")
    return success_count == total_count

def generate_coverage_report():
    """Generate test coverage report"""
    print("\n📈 Generating Coverage Report")
    print("=" * 50)

    # Install coverage if not available
    install_cmd = "cd /home/frappe/frappe-bench && pip install coverage"
    run_command(install_cmd, "Installing coverage tool")

    # Run tests with coverage
    coverage_cmd = """
    cd /home/frappe/frappe-bench &&
    coverage run --source=apps/verenigingen/verenigingen/integrations/mollie/api --omit="*/tests/*" -m pytest apps/verenigingen/verenigingen/integrations/mollie/tests/test_failed_payment_processing.py -v
    """

    if run_command(coverage_cmd, "Running tests with coverage"):
        # Generate coverage report
        report_cmd = "cd /home/frappe/frappe-bench && coverage report -m"
        run_command(report_cmd, "Generating coverage report")

        # Generate HTML report
        html_cmd = "cd /home/frappe/frappe-bench && coverage html -d htmlcov_failed_payments"
        if run_command(html_cmd, "Generating HTML coverage report"):
            print("📄 HTML coverage report generated at: /home/frappe/frappe-bench/htmlcov_failed_payments/index.html")

        return True

    return False

def validate_test_setup():
    """Validate that test environment is properly set up"""
    print("\n🔧 Validating Test Setup")
    print("=" * 50)

    checks = []

    # Check if test files exist
    test_files = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/integrations/mollie/tests/test_failed_payment_processing.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/integrations/mollie/tests/test_webhook_integration_comprehensive.py",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/tests/test_payment_failure_email_templates.py"
    ]

    for test_file in test_files:
        if os.path.exists(test_file):
            print(f"✅ Test file exists: {os.path.basename(test_file)}")
            checks.append(True)
        else:
            print(f"❌ Test file missing: {test_file}")
            checks.append(False)

    # Check Python syntax
    for test_file in test_files:
        if os.path.exists(test_file):
            cmd = f"python -m py_compile {test_file}"
            if run_command(cmd, f"Syntax check: {os.path.basename(test_file)}"):
                checks.append(True)
            else:
                checks.append(False)

    # Check if enhanced test factory is available
    try:
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
        print("✅ Enhanced Test Factory available")
        checks.append(True)
    except ImportError:
        print("❌ Enhanced Test Factory not available")
        checks.append(False)

    success_rate = sum(checks) / len(checks) * 100
    print(f"\n📊 Setup Validation: {success_rate:.1f}% ({sum(checks)}/{len(checks)} checks passed)")

    return success_rate > 80

def main():
    """Main test runner function"""
    parser = argparse.ArgumentParser(description="Run failed payment system tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    parser.add_argument("--performance", action="store_true", help="Run performance tests only")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--fast", action="store_true", help="Skip slow performance tests")
    parser.add_argument("--validate", action="store_true", help="Validate test setup only")

    args = parser.parse_args()

    print("🧪 Mollie Failed Payment System Test Runner")
    print("=" * 60)

    start_time = time.time()

    # Validate setup first
    if not validate_test_setup():
        print("❌ Test setup validation failed. Please fix issues before running tests.")
        return 1

    if args.validate:
        print("✅ Test setup validation completed successfully.")
        return 0

    results = []

    # Determine what tests to run
    run_all = not (args.unit or args.integration or args.performance)

    if args.unit or run_all:
        results.append(("Unit Tests", run_unit_tests()))

    if args.integration or run_all:
        results.append(("Integration Tests", run_integration_tests()))

    if args.performance or run_all:
        results.append(("Performance Tests", run_performance_tests(fast=args.fast)))

    if args.coverage:
        results.append(("Coverage Report", generate_coverage_report()))

    # Summary
    end_time = time.time()
    total_time = end_time - start_time

    print("\n" + "=" * 60)
    print("📋 TEST SUMMARY")
    print("=" * 60)

    passed_tests = 0
    total_tests = len(results)

    for test_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{test_name:.<40} {status}")
        if success:
            passed_tests += 1

    print("-" * 60)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {total_tests - passed_tests}")
    print(f"Success Rate: {passed_tests/total_tests*100:.1f}%")
    print(f"Total Time: {total_time:.2f}s")

    if passed_tests == total_tests:
        print("\n🎉 All tests passed! The failed payment system is ready for deployment.")
        return 0
    else:
        print("\n💥 Some tests failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())