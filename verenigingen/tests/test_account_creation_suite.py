#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Account Creation Test Suite
========================================

This test suite runner provides comprehensive validation of the AccountCreationManager
system across all critical areas: security, functionality, background processing, 
and Dutch association business logic.

Test Coverage Areas:
- Security: Permission validation, injection prevention, audit integrity
- Functionality: Complete pipeline execution, error handling, retry mechanisms
- Background Processing: Redis queue integration, concurrent processing, fault tolerance
- Dutch Business Logic: Age validation, role assignments, regulatory compliance

Usage:
    python -m unittest verenigingen.tests.test_account_creation_suite
    
Or run specific test categories:
    python -m unittest verenigingen.tests.test_account_creation_suite.SecurityTestSuite
    python -m unittest verenigingen.tests.test_account_creation_suite.FunctionalityTestSuite
    python -m unittest verenigingen.tests.test_account_creation_suite.BackgroundProcessingTestSuite
    python -m unittest verenigingen.tests.test_account_creation_suite.BusinessLogicTestSuite

Author: Verenigingen Test Team
"""

import unittest
import sys
import time
import frappe
from frappe.utils import now

# Import all our test modules
from .test_account_creation_manager_comprehensive import (
    TestAccountCreationManagerSecurity,
    TestAccountCreationManagerFunctionality,
    TestAccountCreationManagerErrorHandling,
    TestAccountCreationManagerBackgroundProcessing,
    TestAccountCreationManagerIntegration,
    TestAccountCreationManagerDutchBusinessLogic,
    TestAccountCreationManagerEnhancedFactory
)

from .test_account_creation_security_deep import (
    TestAccountCreationDeepSecurity,
    TestAccountCreationAuditCompliance
)

from .test_account_creation_background_processing import (
    TestAccountCreationBackgroundProcessing,
    TestAccountCreationQueueResilience
)

from .test_account_creation_dutch_business_logic import (
    TestDutchAssociationBusinessLogic,
    TestAccountCreationBusinessRuleEdgeCases
)


class TestSuiteReporter:
    """Test suite execution reporter"""
    
    def __init__(self):
        self.start_time = None
        self.results = {}
        
    def start_suite(self, suite_name):
        """Start timing a test suite"""
        self.start_time = time.time()
        print(f"\n{'='*60}")
        print(f"STARTING TEST SUITE: {suite_name}")
        print(f"{'='*60}")
        
    def end_suite(self, suite_name, result):
        """End timing and report results"""
        execution_time = time.time() - self.start_time
        
        self.results[suite_name] = {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "execution_time": execution_time,
            "success": result.wasSuccessful()
        }
        
        print(f"\n{'='*60}")
        print(f"COMPLETED TEST SUITE: {suite_name}")
        print(f"Tests Run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        print(f"Skipped: {len(result.skipped)}")
        print(f"Execution Time: {execution_time:.2f} seconds")
        print(f"Success: {'✓' if result.wasSuccessful() else '✗'}")
        print(f"{'='*60}")
        
        if result.failures:
            print("\nFAILURES:")
            for test, traceback in result.failures:
                print(f"- {test}: {traceback.splitlines()[-1]}")
                
        if result.errors:
            print("\nERRORS:")
            for test, traceback in result.errors:
                print(f"- {test}: {traceback.splitlines()[-1]}")
                
    def print_summary(self):
        """Print overall test execution summary"""
        print(f"\n{'='*80}")
        print("ACCOUNT CREATION TEST SUITE SUMMARY")
        print(f"{'='*80}")
        
        total_tests = sum(r["tests_run"] for r in self.results.values())
        total_failures = sum(r["failures"] for r in self.results.values())
        total_errors = sum(r["errors"] for r in self.results.values())
        total_skipped = sum(r["skipped"] for r in self.results.values())
        total_time = sum(r["execution_time"] for r in self.results.values())
        
        print(f"Total Test Suites: {len(self.results)}")
        print(f"Total Tests Run: {total_tests}")
        print(f"Total Failures: {total_failures}")
        print(f"Total Errors: {total_errors}")
        print(f"Total Skipped: {total_skipped}")
        print(f"Total Execution Time: {total_time:.2f} seconds")
        print(f"Overall Success Rate: {((total_tests - total_failures - total_errors) / max(total_tests, 1)) * 100:.1f}%")
        
        print(f"\nSUITE BREAKDOWN:")
        for suite_name, results in self.results.items():
            status = "✓ PASS" if results["success"] else "✗ FAIL"
            print(f"  {suite_name}: {results['tests_run']} tests, {results['execution_time']:.1f}s - {status}")
            
        print(f"\n{'='*80}")
        
        # Return overall success
        return total_failures == 0 and total_errors == 0


# Define test suites by category
class SecurityTestSuite:
    """Security-focused test suite"""
    
    @staticmethod
    def get_suite():
        suite = unittest.TestSuite()
        
        # Core security tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerSecurity))
        
        # Deep security validation
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationDeepSecurity))
        
        # Audit compliance
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationAuditCompliance))
        
        return suite


class FunctionalityTestSuite:
    """Functionality and integration test suite"""
    
    @staticmethod
    def get_suite():
        suite = unittest.TestSuite()
        
        # Core functionality
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerFunctionality))
        
        # Error handling
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerErrorHandling))
        
        # Integration tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerIntegration))
        
        # Enhanced factory integration
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerEnhancedFactory))
        
        return suite


class BackgroundProcessingTestSuite:
    """Background processing and queue management test suite"""
    
    @staticmethod
    def get_suite():
        suite = unittest.TestSuite()
        
        # Manager background processing tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerBackgroundProcessing))
        
        # Dedicated background processing tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationBackgroundProcessing))
        
        # Queue resilience tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationQueueResilience))
        
        return suite


class BusinessLogicTestSuite:
    """Dutch association business logic test suite"""
    
    @staticmethod
    def get_suite():
        suite = unittest.TestSuite()
        
        # Manager Dutch business logic tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationManagerDutchBusinessLogic))
        
        # Dedicated Dutch business logic tests
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestDutchAssociationBusinessLogic))
        
        # Business rule edge cases
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(TestAccountCreationBusinessRuleEdgeCases))
        
        return suite


class ComprehensiveTestSuite:
    """Complete comprehensive test suite"""
    
    @staticmethod
    def get_suite():
        suite = unittest.TestSuite()
        
        # Add all test suites
        suite.addTests(SecurityTestSuite.get_suite())
        suite.addTests(FunctionalityTestSuite.get_suite())
        suite.addTests(BackgroundProcessingTestSuite.get_suite())
        suite.addTests(BusinessLogicTestSuite.get_suite())
        
        return suite


def run_test_suite(suite_class, suite_name):
    """Run a specific test suite with reporting"""
    reporter = TestSuiteReporter()
    reporter.start_suite(suite_name)
    
    # Run the test suite
    suite = suite_class.get_suite()
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)
    
    reporter.end_suite(suite_name, result)
    return result


def run_all_suites():
    """Run all test suites with comprehensive reporting"""
    reporter = TestSuiteReporter()
    
    suites = [
        (SecurityTestSuite, "Security Tests"),
        (FunctionalityTestSuite, "Functionality Tests"),
        (BackgroundProcessingTestSuite, "Background Processing Tests"),
        (BusinessLogicTestSuite, "Business Logic Tests")
    ]
    
    print(f"\n{'='*80}")
    print("ACCOUNT CREATION MANAGER COMPREHENSIVE TEST SUITE")
    print(f"Started at: {now()}")
    print(f"{'='*80}")
    
    all_results = []
    
    for suite_class, suite_name in suites:
        try:
            reporter.start_suite(suite_name)
            
            suite = suite_class.get_suite()
            runner = unittest.TextTestRunner(verbosity=1, stream=sys.stdout, buffer=True)
            result = runner.run(suite)
            
            reporter.end_suite(suite_name, result)
            all_results.append(result)
            
        except Exception as e:
            print(f"ERROR running suite {suite_name}: {e}")
            import traceback
            traceback.print_exc()
    
    # Print comprehensive summary
    success = reporter.print_summary()
    
    return success


def validate_test_environment():
    """Validate test environment is properly set up"""
    print("Validating test environment...")
    
    try:
        # Check Frappe connection
        frappe.connect()
        print("✓ Frappe connection established")
        
        # Check required DocTypes exist
        required_doctypes = [
            "Account Creation Request",
            "Member", 
            "Volunteer",
            "User",
            "Employee"
        ]
        
        for doctype in required_doctypes:
            if frappe.db.exists("DocType", doctype):
                print(f"✓ DocType '{doctype}' exists")
            else:
                print(f"✗ DocType '{doctype}' missing")
                return False
                
        # Check permissions
        if frappe.has_permission("User", "create"):
            print("✓ User creation permissions available")
        else:
            print("⚠ Limited user creation permissions")
            
        print("✓ Test environment validation completed")
        return True
        
    except Exception as e:
        print(f"✗ Test environment validation failed: {e}")
        return False


if __name__ == "__main__":
    # Validate environment first
    if not validate_test_environment():
        print("Test environment validation failed. Exiting.")
        sys.exit(1)
    
    # Check command line arguments for specific suite
    if len(sys.argv) > 1:
        suite_name = sys.argv[1].lower()
        
        suite_map = {
            "security": (SecurityTestSuite, "Security Tests"),
            "functionality": (FunctionalityTestSuite, "Functionality Tests"),
            "background": (BackgroundProcessingTestSuite, "Background Processing Tests"),
            "business": (BusinessLogicTestSuite, "Business Logic Tests"),
            "all": None  # Special case for all suites
        }
        
        if suite_name in suite_map:
            if suite_name == "all":
                success = run_all_suites()
            else:
                suite_class, display_name = suite_map[suite_name]
                result = run_test_suite(suite_class, display_name)
                success = result.wasSuccessful()
        else:
            print(f"Unknown test suite: {suite_name}")
            print(f"Available suites: {', '.join(suite_map.keys())}")
            sys.exit(1)
    else:
        # Run all suites by default
        success = run_all_suites()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)