#!/usr/bin/env python3
"""
SEPA Service Unit Test Runner

Comprehensive test runner for all SEPA Mandate service unit tests. This script
provides various execution modes for running the service tests individually
or as a complete suite.

Usage Examples:
    # Run all SEPA service tests
    python run_sepa_service_tests.py --all

    # Run specific service tests
    python run_sepa_service_tests.py --identity
    python run_sepa_service_tests.py --validation
    python run_sepa_service_tests.py --lifecycle
    python run_sepa_service_tests.py --integration

    # Run with verbose output
    python run_sepa_service_tests.py --all --verbose

    # Run with coverage report
    python run_sepa_service_tests.py --all --coverage

Features:
- Individual service test execution
- Complete test suite execution
- Coverage reporting
- Verbose output control
- Performance timing
- Error reporting and logging
"""

import sys
import os
import unittest
import time
import argparse
from io import StringIO
from pathlib import Path

# Add the app path to ensure imports work correctly
app_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(app_path))

# Import test modules
try:
    from verenigingen.tests.test_sepa_mandate_identity_service import TestSEPAMandateIdentityService
    from verenigingen.tests.test_sepa_mandate_validation_service import TestSEPAMandateValidationService
    from verenigingen.tests.test_sepa_mandate_lifecycle_service import TestSEPAMandateLifecycleService
    from verenigingen.tests.test_sepa_mandate_member_integration_service import TestSEPAMandateMemberIntegrationService

    # Track which test modules were successfully imported
    AVAILABLE_TEST_MODULES = {
        'identity': TestSEPAMandateIdentityService,
        'validation': TestSEPAMandateValidationService,
        'lifecycle': TestSEPAMandateLifecycleService,
        'integration': TestSEPAMandateMemberIntegrationService
    }

except ImportError as e:
    print(f"Warning: Could not import all test modules: {e}")
    print("This is expected when running outside of Frappe context.")
    print("Use 'bench --site <site> execute verenigingen.tests.run_sepa_service_tests.main' instead.")
    AVAILABLE_TEST_MODULES = {}


class SEPAServiceTestRunner:
    """Custom test runner for SEPA service tests"""

    def __init__(self, verbose=False, coverage=False):
        self.verbose = verbose
        self.coverage = coverage
        self.results = {}

    def run_test_module(self, module_name, test_class):
        """Run tests for a specific service module"""
        print(f"\n{'='*60}")
        print(f"Running tests for SEPA {module_name.title()} Service")
        print(f"{'='*60}")

        # Create test suite
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)

        # Configure test runner
        stream = StringIO() if not self.verbose else sys.stdout
        runner = unittest.TextTestRunner(
            stream=stream,
            verbosity=2 if self.verbose else 1,
            buffer=True
        )

        # Run tests with timing
        start_time = time.time()
        result = runner.run(suite)
        end_time = time.time()

        # Store results
        self.results[module_name] = {
            'tests_run': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
            'success': result.wasSuccessful(),
            'duration': end_time - start_time
        }

        # Print summary
        if not self.verbose:
            output = stream.getvalue()
            if output:
                print(output)

        self._print_module_summary(module_name, self.results[module_name])

        return result.wasSuccessful()

    def run_all_tests(self):
        """Run all available SEPA service tests"""
        print(f"SEPA Service Unit Test Suite")
        print(f"Running tests for {len(AVAILABLE_TEST_MODULES)} service modules")
        print(f"Verbose: {self.verbose}, Coverage: {self.coverage}")

        overall_success = True
        total_start_time = time.time()

        # Run each test module
        for module_name, test_class in AVAILABLE_TEST_MODULES.items():
            success = self.run_test_module(module_name, test_class)
            overall_success = overall_success and success

        total_end_time = time.time()

        # Print overall summary
        self._print_overall_summary(total_end_time - total_start_time, overall_success)

        return overall_success

    def _print_module_summary(self, module_name, result):
        """Print summary for a single test module"""
        status = "✓ PASSED" if result['success'] else "✗ FAILED"
        print(f"\n{module_name.upper()} SERVICE TESTS {status}")
        print(f"  Tests run: {result['tests_run']}")
        print(f"  Failures: {result['failures']}")
        print(f"  Errors: {result['errors']}")
        print(f"  Skipped: {result['skipped']}")
        print(f"  Duration: {result['duration']:.2f}s")

    def _print_overall_summary(self, total_duration, overall_success):
        """Print overall test suite summary"""
        print(f"\n{'='*60}")
        print(f"OVERALL TEST SUITE RESULTS")
        print(f"{'='*60}")

        total_tests = sum(r['tests_run'] for r in self.results.values())
        total_failures = sum(r['failures'] for r in self.results.values())
        total_errors = sum(r['errors'] for r in self.results.values())
        total_skipped = sum(r['skipped'] for r in self.results.values())

        print(f"Total modules tested: {len(self.results)}")
        print(f"Total tests run: {total_tests}")
        print(f"Total failures: {total_failures}")
        print(f"Total errors: {total_errors}")
        print(f"Total skipped: {total_skipped}")
        print(f"Total duration: {total_duration:.2f}s")

        status = "✓ ALL TESTS PASSED" if overall_success else "✗ SOME TESTS FAILED"
        print(f"\nFINAL RESULT: {status}")

        # Print module breakdown
        print(f"\nMODULE BREAKDOWN:")
        for module_name, result in self.results.items():
            status_icon = "✓" if result['success'] else "✗"
            print(f"  {status_icon} {module_name.title()} Service: {result['tests_run']} tests in {result['duration']:.2f}s")


def run_coverage_analysis():
    """Run coverage analysis for SEPA service tests"""
    try:
        import coverage
        print("Running coverage analysis...")
        # Coverage implementation would go here
        # This is a placeholder for future enhancement
        print("Coverage analysis not yet implemented.")
        return True
    except ImportError:
        print("Coverage module not available. Install with: pip install coverage")
        return False


def main():
    """Main entry point for the test runner"""
    parser = argparse.ArgumentParser(
        description="Run SEPA Mandate Service Unit Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_sepa_service_tests.py --all                    # Run all tests
  python run_sepa_service_tests.py --identity --verbose     # Run identity service tests with verbose output
  python run_sepa_service_tests.py --validation             # Run validation service tests only
  python run_sepa_service_tests.py --all --coverage         # Run all tests with coverage
        """
    )

    # Test selection arguments
    parser.add_argument('--all', action='store_true', help='Run all SEPA service tests')
    parser.add_argument('--identity', action='store_true', help='Run SEPA Identity Service tests')
    parser.add_argument('--validation', action='store_true', help='Run SEPA Validation Service tests')
    parser.add_argument('--lifecycle', action='store_true', help='Run SEPA Lifecycle Service tests')
    parser.add_argument('--integration', action='store_true', help='Run SEPA Member Integration Service tests')

    # Output control arguments
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--coverage', action='store_true', help='Run with coverage analysis')

    args = parser.parse_args()

    # Check if we have any test modules available
    if not AVAILABLE_TEST_MODULES:
        print("ERROR: No test modules could be imported.")
        print("Make sure you're running this from within a Frappe environment:")
        print("  bench --site <site> execute verenigingen.tests.run_sepa_service_tests.main")
        return False

    # Create test runner
    runner = SEPAServiceTestRunner(verbose=args.verbose, coverage=args.coverage)

    # Determine which tests to run
    if args.all:
        success = runner.run_all_tests()
    else:
        # Run individual test modules
        success = True
        tests_run = False

        if args.identity and 'identity' in AVAILABLE_TEST_MODULES:
            success = success and runner.run_test_module('identity', AVAILABLE_TEST_MODULES['identity'])
            tests_run = True

        if args.validation and 'validation' in AVAILABLE_TEST_MODULES:
            success = success and runner.run_test_module('validation', AVAILABLE_TEST_MODULES['validation'])
            tests_run = True

        if args.lifecycle and 'lifecycle' in AVAILABLE_TEST_MODULES:
            success = success and runner.run_test_module('lifecycle', AVAILABLE_TEST_MODULES['lifecycle'])
            tests_run = True

        if args.integration and 'integration' in AVAILABLE_TEST_MODULES:
            success = success and runner.run_test_module('integration', AVAILABLE_TEST_MODULES['integration'])
            tests_run = True

        if not tests_run:
            print("No tests specified. Use --all or specify individual test modules.")
            print("Use --help for more information.")
            return False

    # Run coverage analysis if requested
    if args.coverage:
        run_coverage_analysis()

    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)