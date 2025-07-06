#!/usr/bin/env python3
"""
Test runner for Volunteer Portal comprehensive test suite

This script runs all volunteer portal tests including:
- Core functionality tests
- Security tests
- Edge case tests
- Integration tests

Usage:
    python run_volunteer_portal_tests.py [options]

Options:
    --verbose, -v     : Verbose output
    --suite SUITE     : Run specific test suite (core, security, edge, integration)
    --coverage        : Run with coverage reporting
    --html-report     : Generate HTML test report
    --benchmark       : Include performance benchmarks
"""

import argparse
import os
import sys
import unittest

# Add the apps directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Import frappe
import frappe


class VolunteerPortalTestRunner:
    """Custom test runner for volunteer portal tests"""

    def __init__(self):
        self.test_modules = {
            "core": "verenigingen.tests.test_volunteer_expense_portal",
            "security": "verenigingen.tests.test_volunteer_portal_security",
            "edge": "verenigingen.tests.test_volunteer_portal_edge_cases",
            "integration": "verenigingen.tests.test_volunteer_portal_integration",
        }

        self.results = {}

    def setup_test_environment(self):
        """Set up test environment"""
        print("Setting up test environment...")

        # Initialize Frappe if not already done
        if not hasattr(frappe, "db") or not frappe.db:
            frappe.init(site="dev.veganisme.net")
            frappe.connect()

        # Set test user
        frappe.set_user("Administrator")
        
        # Enable test mode and email mocking
        frappe.flags.in_test = True
        from verenigingen.tests.test_config import setup_global_test_config, enable_test_email_mocking
        setup_global_test_config()
        enable_test_email_mocking()

        print("Test environment ready with email mocking enabled.")

    def run_test_suite(self, suite_name, verbose=False):
        """Run a specific test suite"""
        if suite_name not in self.test_modules:
            print(f"Error: Unknown test suite '{suite_name}'")
            print(f"Available suites: {', '.join(self.test_modules.keys())}")
            return False

        print(f"\n{'='*60}")
        print(f"Running {suite_name.upper()} test suite")
        print(f"Module: {self.test_modules[suite_name]}")
        print(f"{'='*60}")

        try:
            # Import the test module
            module = __import__(self.test_modules[suite_name], fromlist=[""])

            # Create test loader
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromModule(module)

            # Run tests
            runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, stream=sys.stdout, buffer=True)

            result = runner.run(suite)

            # Store results
            self.results[suite_name] = {
                "tests_run": result.testsRun,
                "failures": len(result.failures),
                "errors": len(result.errors),
                "skipped": len(result.skipped) if hasattr(result, "skipped") else 0,
                "success": result.wasSuccessful(),
            }

            return result.wasSuccessful()

        except Exception as e:
            print(f"Error running {suite_name} tests: {str(e)}")
            import traceback

            traceback.print_exc()
            return False

    def run_all_suites(self, verbose=False):
        """Run all test suites"""
        print("Running all volunteer portal test suites...")

        all_passed = True

        for suite_name in self.test_modules.keys():
            success = self.run_test_suite(suite_name, verbose)
            if not success:
                all_passed = False

        return all_passed

    def generate_summary_report(self):
        """Generate summary report of test results"""
        if not self.results:
            print("No test results to report.")
            return

        print(f"\n{'='*60}")
        print("VOLUNTEER PORTAL TEST SUMMARY")
        print(f"{'='*60}")

        total_tests = 0
        total_failures = 0
        total_errors = 0
        total_skipped = 0

        for suite_name, results in self.results.items():
            print(f"\n{suite_name.upper()} Suite:")
            print(f"  Tests Run:  {results['tests_run']}")
            print(f"  Failures:   {results['failures']}")
            print(f"  Errors:     {results['errors']}")
            print(f"  Skipped:    {results['skipped']}")
            print(f"  Status:     {'PASS' if results['success'] else 'FAIL'}")

            total_tests += results["tests_run"]
            total_failures += results["failures"]
            total_errors += results["errors"]
            total_skipped += results["skipped"]

        print(f"\n{'='*60}")
        print("OVERALL SUMMARY:")
        print(f"  Total Tests:    {total_tests}")
        print(f"  Total Failures: {total_failures}")
        print(f"  Total Errors:   {total_errors}")
        print(f"  Total Skipped:  {total_skipped}")
        print(
            f"  Success Rate:   {((total_tests - total_failures - total_errors) / total_tests * 100):.1f}%"
            if total_tests > 0
            else "N/A"
        )

        overall_success = total_failures == 0 and total_errors == 0
        print(f"  Overall Status: {'PASS' if overall_success else 'FAIL'}")
        print(f"{'='*60}")

        return overall_success

    def run_coverage_analysis(self, suite_names=None):
        """Run tests with coverage analysis"""
        try:
            import coverage
        except ImportError:
            print("Coverage.py not installed. Install with: pip install coverage")
            return False

        print("Running tests with coverage analysis...")

        # Start coverage
        cov = coverage.Coverage(source=["verenigingen"])
        cov.start()

        try:
            # Run tests
            if suite_names:
                for suite_name in suite_names:
                    self.run_test_suite(suite_name)
            else:
                self.run_all_suites()
        finally:
            # Stop coverage and generate report
            cov.stop()
            cov.save()

            print("\n" + "=" * 60)
            print("COVERAGE REPORT")
            print("=" * 60)
            cov.report()

            # Generate HTML report if requested
            try:
                cov.html_report(directory="htmlcov")
                print(f"\nHTML coverage report generated in 'htmlcov' directory")
            except Exception as e:
                print(f"Could not generate HTML report: {e}")

        return True

    def cleanup(self):
        """Clean up test environment"""
        print("Cleaning up test environment...")

        try:
            # Clean up test data if needed
            frappe.db.rollback()
        except Exception as e:
            print(f"Cleanup warning: {e}")

        print("Cleanup complete.")


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Volunteer Portal Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_volunteer_portal_tests.py                    # Run all tests
  python run_volunteer_portal_tests.py --suite core      # Run core tests only
  python run_volunteer_portal_tests.py --verbose         # Verbose output
  python run_volunteer_portal_tests.py --coverage        # With coverage
        """,
    )

    parser.add_argument(
        "--suite",
        choices=["core", "security", "edge", "integration", "all"],
        default="all",
        help="Test suite to run (default: all)",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose test output")

    parser.add_argument("--coverage", action="store_true", help="Run with coverage analysis")

    parser.add_argument("--benchmark", action="store_true", help="Include performance benchmarks")

    args = parser.parse_args()

    # Create test runner
    runner = VolunteerPortalTestRunner()

    try:
        # Setup test environment
        runner.setup_test_environment()

        # Run tests
        if args.coverage:
            suite_names = [args.suite] if args.suite != "all" else None
            success = runner.run_coverage_analysis(suite_names)
        else:
            if args.suite == "all":
                success = runner.run_all_suites(args.verbose)
            else:
                success = runner.run_test_suite(args.suite, args.verbose)

        # Generate summary
        overall_success = runner.generate_summary_report()

        # Exit with appropriate code
        sys.exit(0 if overall_success else 1)

    except KeyboardInterrupt:
        print("\nTest run interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error running tests: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        runner.cleanup()


if __name__ == "__main__":
    main()
