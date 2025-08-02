#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-Boekhouden Migration Integration Test Runner

This script provides a comprehensive test runner for the E-Boekhouden migration
integration tests. It includes test discovery, execution, reporting, and
environment validation.

Usage:
    python run_e_boekhouden_integration_tests.py [options]
    
    Options:
        --suite [security|payment|pipeline|integrity|performance|all]
        --verbose
        --report-file [filename]
        --setup-test-data
        --cleanup-after
"""

import argparse
import json
import os
import sys
import time
import unittest
from datetime import datetime
from typing import Dict, List, Optional

# Add the project root to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

try:
    import frappe
    from frappe.utils import now_datetime
    from verenigingen.tests.test_e_boekhouden_migration_integration import (
        TestEBoekhoudenSecurityIntegration,
        TestPaymentProcessingIntegration,
        TestMigrationPipelineIntegration,
        TestDataIntegrityAndEdgeCases,
        TestPerformanceAndScalability,
    )
except ImportError as e:
    print(f"ERROR: Failed to import required modules: {e}")
    print("Make sure you're running this from the Frappe environment:")
    print("bench --site [site] execute scripts.testing.run_e_boekhouden_integration_tests")
    sys.exit(1)


class EBoekhoudenIntegrationTestRunner:
    """
    Comprehensive test runner for E-Boekhouden integration tests
    """
    
    def __init__(self):
        self.test_suites = {
            "security": TestEBoekhoudenSecurityIntegration,
            "payment": TestPaymentProcessingIntegration,
            "pipeline": TestMigrationPipelineIntegration,
            "integrity": TestDataIntegrityAndEdgeCases,
            "performance": TestPerformanceAndScalability,
        }
        
        self.results = {}
        self.start_time = None
        self.end_time = None
        
    def validate_environment(self) -> bool:
        """
        Validate that the environment is properly set up for testing
        
        Returns:
            True if environment is valid, False otherwise
        """
        try:
            # Check if we're in Frappe context
            if not hasattr(frappe, 'db'):
                print("ERROR: Not running in Frappe context")
                return False
                
            # Check database connection
            frappe.db.sql("SELECT 1")
            
            # Check for required modules
            required_modules = [
                "verenigingen.e_boekhouden.utils.security_helper",
                "verenigingen.e_boekhouden.utils.payment_processing.payment_entry_handler",
                "verenigingen.tests.fixtures.enhanced_test_factory"
            ]
            
            for module in required_modules:
                try:
                    __import__(module)
                except ImportError as e:
                    print(f"ERROR: Required module not found: {module} - {e}")
                    return False
                    
            # Check for required DocTypes
            required_doctypes = [
                "E-Boekhouden Migration",
                "E-Boekhouden Ledger Mapping", 
                "Company",
                "Account",
                "Customer",
                "Supplier",
                "Payment Entry"
            ]
            
            for doctype in required_doctypes:
                if not frappe.db.exists("DocType", doctype):
                    print(f"ERROR: Required DocType not found: {doctype}")
                    return False
                    
            print("✅ Environment validation passed")
            return True
            
        except Exception as e:
            print(f"ERROR: Environment validation failed: {e}")
            return False
            
    def setup_test_environment(self):
        """
        Setup test environment prerequisites
        """
        print("🔧 Setting up test environment...")
        
        try:
            # Ensure test site is active
            if not frappe.db:
                frappe.init()
                
            # Create minimal test data if needed
            self._ensure_test_prerequisites()
            
            print("✅ Test environment setup completed")
            
        except Exception as e:
            print(f"ERROR: Failed to setup test environment: {e}")
            raise
            
    def _ensure_test_prerequisites(self):
        """
        Ensure basic prerequisites exist for testing
        """
        # Ensure E-Boekhouden Settings exist (minimal config)
        if not frappe.db.exists("E-Boekhouden Settings"):
            settings = frappe.new_doc("E-Boekhouden Settings")
            settings.api_token = "TEST_INTEGRATION_TOKEN"
            settings.api_base_url = "https://api-test.e-boekhouden.nl"
            settings.insert(ignore_permissions=True)
            frappe.db.commit()
            
    def run_test_suite(self, suite_name: str, verbose: bool = False) -> Dict:
        """
        Run a specific test suite
        
        Args:
            suite_name: Name of the test suite to run
            verbose: Whether to run in verbose mode
            
        Returns:
            Dictionary with test results
        """
        if suite_name not in self.test_suites:
            raise ValueError(f"Unknown test suite: {suite_name}")
            
        test_class = self.test_suites[suite_name]
        
        print(f"🚀 Running {suite_name} test suite...")
        print(f"   Test class: {test_class.__name__}")
        
        # Load tests from the class
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)
        
        # Run tests with custom result collector
        result_collector = DetailedTestResult()
        
        # Set verbosity
        verbosity = 2 if verbose else 1
        runner = unittest.TextTestRunner(
            stream=sys.stdout,
            verbosity=verbosity,
            resultclass=lambda: result_collector
        )
        
        start_time = time.time()
        result = runner.run(suite)
        end_time = time.time()
        
        # Collect results
        suite_results = {
            "suite_name": suite_name,
            "test_class": test_class.__name__,
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped) if hasattr(result, 'skipped') else 0,
            "success_rate": ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
            "duration": end_time - start_time,
            "successful": len(result.failures) == 0 and len(result.errors) == 0,
            "failure_details": [f"{test}: {error}" for test, error in result.failures],
            "error_details": [f"{test}: {error}" for test, error in result.errors]
        }
        
        return suite_results
        
    def run_all_suites(self, verbose: bool = False) -> Dict:
        """
        Run all test suites
        
        Args:
            verbose: Whether to run in verbose mode
            
        Returns:
            Dictionary with all test results
        """
        self.start_time = now_datetime()
        all_results = {}
        
        print("🎯 Running all E-Boekhouden integration test suites...")
        print(f"   Total suites: {len(self.test_suites)}")
        print("=" * 60)
        
        for suite_name in self.test_suites.keys():
            try:
                suite_results = self.run_test_suite(suite_name, verbose)
                all_results[suite_name] = suite_results
                
                # Print summary
                if suite_results["successful"]:
                    print(f"✅ {suite_name}: {suite_results['tests_run']} tests passed ({suite_results['duration']:.2f}s)")
                else:
                    print(f"❌ {suite_name}: {suite_results['failures']} failures, {suite_results['errors']} errors ({suite_results['duration']:.2f}s)")
                    
            except Exception as e:
                print(f"💥 {suite_name}: CRASHED - {e}")
                all_results[suite_name] = {
                    "suite_name": suite_name,
                    "successful": False,
                    "crashed": True,
                    "error": str(e)
                }
                
            print("-" * 40)
            
        self.end_time = now_datetime()
        
        # Calculate overall statistics
        total_tests = sum(r.get("tests_run", 0) for r in all_results.values())
        total_failures = sum(r.get("failures", 0) for r in all_results.values())
        total_errors = sum(r.get("errors", 0) for r in all_results.values())
        successful_suites = sum(1 for r in all_results.values() if r.get("successful", False))
        
        all_results["_summary"] = {
            "total_suites": len(self.test_suites),
            "successful_suites": successful_suites,
            "total_tests": total_tests,
            "total_failures": total_failures,
            "total_errors": total_errors,
            "overall_success_rate": ((total_tests - total_failures - total_errors) / total_tests * 100) if total_tests > 0 else 0,
            "total_duration": (self.end_time - self.start_time).total_seconds(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat()
        }
        
        return all_results
        
    def print_detailed_report(self, results: Dict):
        """
        Print detailed test results report
        
        Args:
            results: Results dictionary from run_all_suites or run_test_suite
        """
        print("\n" + "=" * 80)
        print("📊 E-BOEKHOUDEN INTEGRATION TEST REPORT")
        print("=" * 80)
        
        if "_summary" in results:
            # Multiple suites
            summary = results["_summary"]
            
            print(f"🕐 Test Run Duration: {summary['total_duration']:.2f} seconds")
            print(f"📅 Start Time: {summary['start_time']}")
            print(f"📅 End Time: {summary['end_time']}")
            print()
            
            print(f"📈 OVERALL RESULTS:")
            print(f"   Test Suites: {summary['successful_suites']}/{summary['total_suites']} successful")
            print(f"   Total Tests: {summary['total_tests']}")
            print(f"   Failures: {summary['total_failures']}")
            print(f"   Errors: {summary['total_errors']}")
            print(f"   Success Rate: {summary['overall_success_rate']:.1f}%")
            print()
            
            # Individual suite details
            for suite_name, suite_results in results.items():
                if suite_name == "_summary":
                    continue
                    
                status = "✅ PASSED" if suite_results.get("successful", False) else "❌ FAILED"
                print(f"{status} {suite_name.upper()} SUITE:")
                
                if suite_results.get("crashed", False):
                    print(f"   💥 CRASHED: {suite_results.get('error', 'Unknown error')}")
                else:
                    print(f"   Tests: {suite_results.get('tests_run', 0)}")
                    print(f"   Failures: {suite_results.get('failures', 0)}")
                    print(f"   Errors: {suite_results.get('errors', 0)}")
                    print(f"   Duration: {suite_results.get('duration', 0):.2f}s")
                    
                    # Show failure details
                    if suite_results.get('failure_details'):
                        print("   Failure Details:")
                        for detail in suite_results['failure_details'][:3]:  # Limit to first 3
                            print(f"     - {detail[:100]}...")
                            
                    if suite_results.get('error_details'):
                        print("   Error Details:")
                        for detail in suite_results['error_details'][:3]:  # Limit to first 3
                            print(f"     - {detail[:100]}...")
                            
                print()
                
        else:
            # Single suite
            suite_name = results.get("suite_name", "Unknown")
            status = "✅ PASSED" if results.get("successful", False) else "❌ FAILED"
            
            print(f"{status} {suite_name.upper()} SUITE RESULTS:")
            print(f"   Tests Run: {results.get('tests_run', 0)}")
            print(f"   Failures: {results.get('failures', 0)}")
            print(f"   Errors: {results.get('errors', 0)}")
            print(f"   Success Rate: {results.get('success_rate', 0):.1f}%")
            print(f"   Duration: {results.get('duration', 0):.2f} seconds")
            
        print("=" * 80)
        
    def save_report(self, results: Dict, filename: str):
        """
        Save test results to file
        
        Args:
            results: Results dictionary
            filename: Output filename
        """
        try:
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"📁 Report saved to: {filename}")
        except Exception as e:
            print(f"ERROR: Failed to save report: {e}")
            
    def cleanup_test_data(self):
        """
        Cleanup test data created during testing
        """
        print("🧹 Cleaning up test data...")
        
        try:
            # Clean up test companies
            test_companies = frappe.get_all(
                "Company", 
                filters={"company_name": ["like", "TEST-%"]},
                fields=["name"]
            )
            
            for company in test_companies:
                try:
                    frappe.delete_doc("Company", company.name, ignore_permissions=True, force=True)
                except Exception as e:
                    print(f"   Warning: Could not delete company {company.name}: {e}")
                    
            # Clean up test accounts
            test_accounts = frappe.get_all(
                "Account",
                filters={"account_name": ["like", "TEST%"]},
                fields=["name"]
            )
            
            for account in test_accounts:
                try:
                    frappe.delete_doc("Account", account.name, ignore_permissions=True, force=True)
                except Exception as e:
                    print(f"   Warning: Could not delete account {account.name}: {e}")
                    
            frappe.db.commit()
            print("✅ Cleanup completed")
            
        except Exception as e:
            print(f"WARNING: Cleanup failed: {e}")


class DetailedTestResult(unittest.TestResult):
    """
    Custom test result class that captures detailed information
    """
    
    def __init__(self):
        super().__init__()
        self.test_details = []
        
    def startTest(self, test):
        super().startTest(test)
        self.test_start_time = time.time()
        
    def stopTest(self, test):
        super().stopTest(test)
        duration = time.time() - self.test_start_time
        self.test_details.append({
            "test": str(test),
            "duration": duration
        })


def main():
    """
    Main entry point for the test runner
    """
    parser = argparse.ArgumentParser(description="E-Boekhouden Integration Test Runner")
    parser.add_argument(
        "--suite",
        choices=["security", "payment", "pipeline", "integrity", "performance", "all"],
        default="all",
        help="Test suite to run"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--report-file", help="Save report to file")
    parser.add_argument("--setup-test-data", action="store_true", help="Setup test data")
    parser.add_argument("--cleanup-after", action="store_true", help="Cleanup after tests")
    
    args = parser.parse_args()
    
    # Initialize test runner
    runner = EBoekhoudenIntegrationTestRunner()
    
    try:
        # Validate environment
        if not runner.validate_environment():
            print("❌ Environment validation failed. Cannot run tests.")
            sys.exit(1)
            
        # Setup test environment
        if args.setup_test_data:
            runner.setup_test_environment()
            
        # Run tests
        if args.suite == "all":
            results = runner.run_all_suites(verbose=args.verbose)
        else:
            results = runner.run_test_suite(args.suite, verbose=args.verbose)
            
        # Print report
        runner.print_detailed_report(results)
        
        # Save report if requested
        if args.report_file:
            runner.save_report(results, args.report_file)
            
        # Cleanup if requested
        if args.cleanup_after:
            runner.cleanup_test_data()
            
        # Exit with appropriate code
        if isinstance(results, dict) and "_summary" in results:
            # Multiple suites
            success = results["_summary"]["total_failures"] == 0 and results["_summary"]["total_errors"] == 0
        else:
            # Single suite
            success = results.get("successful", False)
            
        if success:
            print("🎉 All tests passed!")
            sys.exit(0)
        else:
            print("💥 Some tests failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n⚠️  Test run interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"💥 Test runner crashed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()