#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Test Runner for Security-Payment System

Executes all tests for:
1. Payment History Race Condition Fix
2. Payment History Validator  
3. API Security Framework Decorators
4. Integrated System Tests

Provides detailed reporting with performance metrics and coverage analysis.
"""

import sys
import time
import traceback
from datetime import datetime

# Add the app path to ensure proper imports
sys.path.insert(0, '/home/frappe/frappe-bench/apps/verenigingen')

import frappe
from frappe.utils import now_datetime


class ComprehensiveTestRunner:
    """Comprehensive test runner with detailed reporting"""
    
    def __init__(self):
        self.test_results = {}
        self.start_time = None
        self.total_start_time = None
        
    def run_all_tests(self):
        """Run all comprehensive tests"""
        self.total_start_time = time.time()
        
        print("=" * 80)
        print("COMPREHENSIVE SECURITY-PAYMENT SYSTEM TEST SUITE")
        print("=" * 80)
        print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Test suites to run
        test_suites = [
            {
                "name": "Payment History Race Condition Tests",
                "module": "verenigingen.tests.test_payment_history_race_condition",
                "class": "TestPaymentHistoryRaceCondition"
            },
            {
                "name": "Payment History Validator Tests", 
                "module": "verenigingen.tests.test_payment_history_validator",
                "class": "TestPaymentHistoryValidator"
            },
            {
                "name": "API Security Decorators Tests",
                "module": "verenigingen.tests.test_api_security_decorators", 
                "class": "TestAPISecurityDecorators"
            },
            {
                "name": "Integrated Security-Payment System Tests",
                "module": "verenigingen.tests.test_integrated_security_payment_system",
                "class": "TestIntegratedSecurityPaymentSystem"
            }
        ]
        
        # Run each test suite
        for suite in test_suites:
            self.run_test_suite(suite)
        
        # Generate final report
        self.generate_final_report()
    
    def run_test_suite(self, suite_config):
        """Run a specific test suite"""
        suite_name = suite_config["name"]
        print(f"\n{'=' * 60}")
        print(f"RUNNING: {suite_name}")
        print(f"{'=' * 60}")
        
        self.start_time = time.time()
        suite_results = {
            "name": suite_name,
            "start_time": datetime.now(),
            "tests": [],
            "total_tests": 0,
            "passed": 0,
            "failed": 0,
            "errors": [],
            "execution_time": 0,
            "performance_metrics": {}
        }
        
        try:
            # Import test module
            module_name = suite_config["module"]
            class_name = suite_config["class"]
            
            # Use Frappe's test runner
            self.run_frappe_tests(module_name, suite_results)
            
        except Exception as e:
            error_msg = f"Failed to run test suite {suite_name}: {str(e)}"
            print(f"ERROR: {error_msg}")
            suite_results["errors"].append({
                "type": "suite_execution_error",
                "message": error_msg,
                "traceback": traceback.format_exc()
            })
        
        suite_results["execution_time"] = time.time() - self.start_time
        self.test_results[suite_name] = suite_results
        
        # Print suite summary
        self.print_suite_summary(suite_results)
    
    def run_frappe_tests(self, module_name, suite_results):
        """Run tests using Frappe's test framework"""
        try:
            # Import the test module
            test_module = frappe.get_module(module_name)
            
            # Get all test classes
            import inspect
            test_classes = []
            for name, obj in inspect.getmembers(test_module):
                if (inspect.isclass(obj) and 
                    name.startswith('Test') and 
                    hasattr(obj, 'setUp')):
                    test_classes.append(obj)
            
            print(f"Found {len(test_classes)} test classes in {module_name}")
            
            # Run tests for each class
            for test_class in test_classes:
                self.run_test_class(test_class, suite_results)
                
        except Exception as e:
            error_msg = f"Error importing or running tests from {module_name}: {str(e)}"
            print(f"ERROR: {error_msg}")
            suite_results["errors"].append({
                "type": "module_import_error",
                "message": error_msg,
                "traceback": traceback.format_exc()
            })
    
    def run_test_class(self, test_class, suite_results):
        """Run all test methods in a test class"""
        import inspect
        
        class_name = test_class.__name__
        print(f"\n  Running test class: {class_name}")
        
        # Get all test methods
        test_methods = []
        for name, method in inspect.getmembers(test_class):
            if name.startswith('test_') and callable(method):
                test_methods.append(name)
        
        print(f"    Found {len(test_methods)} test methods")
        
        # Run each test method
        for method_name in test_methods:
            self.run_test_method(test_class, method_name, suite_results)
    
    def run_test_method(self, test_class, method_name, suite_results):
        """Run a single test method"""
        test_start_time = time.time()
        test_result = {
            "class": test_class.__name__,
            "method": method_name,
            "status": "unknown",
            "execution_time": 0,
            "error_message": None,
            "traceback": None
        }
        
        try:
            # Create test instance
            test_instance = test_class()
            
            # Run setUp
            if hasattr(test_instance, 'setUp'):
                test_instance.setUp()
            
            # Run the test method
            test_method = getattr(test_instance, method_name)
            test_method()
            
            # Run tearDown
            if hasattr(test_instance, 'tearDown'):
                test_instance.tearDown()
            
            test_result["status"] = "passed"
            suite_results["passed"] += 1
            print(f"      ✓ {method_name}")
            
        except Exception as e:
            test_result["status"] = "failed"
            test_result["error_message"] = str(e)
            test_result["traceback"] = traceback.format_exc()
            suite_results["failed"] += 1
            print(f"      ✗ {method_name}: {str(e)}")
            
            # Try to run tearDown even if test failed
            try:
                if hasattr(test_instance, 'tearDown'):
                    test_instance.tearDown()
            except Exception as teardown_error:
                print(f"        Warning: tearDown failed: {str(teardown_error)}")
        
        test_result["execution_time"] = time.time() - test_start_time
        suite_results["tests"].append(test_result)
        suite_results["total_tests"] += 1
    
    def print_suite_summary(self, suite_results):
        """Print summary for a test suite"""
        print(f"\n{'-' * 40}")
        print(f"SUITE SUMMARY: {suite_results['name']}")
        print(f"{'-' * 40}")
        print(f"Total Tests: {suite_results['total_tests']}")
        print(f"Passed: {suite_results['passed']}")
        print(f"Failed: {suite_results['failed']}")
        print(f"Execution Time: {suite_results['execution_time']:.2f} seconds")
        
        if suite_results['failed'] > 0:
            print(f"\nFAILED TESTS:")
            for test in suite_results['tests']:
                if test['status'] == 'failed':
                    print(f"  - {test['class']}.{test['method']}: {test['error_message']}")
        
        if suite_results['errors']:
            print(f"\nSUITE ERRORS:")
            for error in suite_results['errors']:
                print(f"  - {error['type']}: {error['message']}")
    
    def generate_final_report(self):
        """Generate comprehensive final report"""
        total_execution_time = time.time() - self.total_start_time
        
        print(f"\n{'=' * 80}")
        print("FINAL COMPREHENSIVE TEST REPORT")
        print(f"{'=' * 80}")
        print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Execution Time: {total_execution_time:.2f} seconds")
        print()
        
        # Overall statistics
        total_tests = sum(suite["total_tests"] for suite in self.test_results.values())
        total_passed = sum(suite["passed"] for suite in self.test_results.values())
        total_failed = sum(suite["failed"] for suite in self.test_results.values())
        total_errors = sum(len(suite["errors"]) for suite in self.test_results.values())
        
        print("OVERALL STATISTICS:")
        print(f"  Total Test Suites: {len(self.test_results)}")
        print(f"  Total Tests: {total_tests}")
        print(f"  Total Passed: {total_passed}")
        print(f"  Total Failed: {total_failed}")
        print(f"  Total Suite Errors: {total_errors}")
        print(f"  Success Rate: {(total_passed / max(total_tests, 1)) * 100:.1f}%")
        print()
        
        # Suite-by-suite breakdown
        print("SUITE BREAKDOWN:")
        for suite_name, suite_results in self.test_results.items():
            status = "✓ PASSED" if suite_results["failed"] == 0 and len(suite_results["errors"]) == 0 else "✗ FAILED"
            success_rate = (suite_results["passed"] / max(suite_results["total_tests"], 1)) * 100
            print(f"  {status} {suite_name}")
            print(f"    Tests: {suite_results['total_tests']} | Passed: {suite_results['passed']} | Failed: {suite_results['failed']}")
            print(f"    Success Rate: {success_rate:.1f}% | Execution Time: {suite_results['execution_time']:.2f}s")
        
        print()
        
        # Performance analysis
        print("PERFORMANCE ANALYSIS:")
        suite_times = [(name, results["execution_time"]) for name, results in self.test_results.items()]
        suite_times.sort(key=lambda x: x[1], reverse=True)
        
        for suite_name, execution_time in suite_times:
            percentage = (execution_time / total_execution_time) * 100
            print(f"  {suite_name}: {execution_time:.2f}s ({percentage:.1f}%)")
        
        print()
        
        # Detailed failures (if any)
        if total_failed > 0 or total_errors > 0:
            print("DETAILED FAILURE ANALYSIS:")
            for suite_name, suite_results in self.test_results.items():
                if suite_results["failed"] > 0 or suite_results["errors"]:
                    print(f"\n  SUITE: {suite_name}")
                    
                    # Failed tests
                    if suite_results["failed"] > 0:
                        print("    Failed Tests:")
                        for test in suite_results["tests"]:
                            if test["status"] == "failed":
                                print(f"      - {test['class']}.{test['method']}")
                                print(f"        Error: {test['error_message']}")
                                if test["traceback"]:
                                    # Print first few lines of traceback
                                    traceback_lines = test["traceback"].split('\n')[:5]
                                    for line in traceback_lines:
                                        if line.strip():
                                            print(f"        {line}")
                    
                    # Suite errors
                    if suite_results["errors"]:
                        print("    Suite Errors:")
                        for error in suite_results["errors"]:
                            print(f"      - {error['type']}: {error['message']}")
        
        # Recommendations
        print("\nRECOMMENDATIONS:")
        if total_failed == 0 and total_errors == 0:
            print("  ✓ All tests passed! The security-payment system is functioning correctly.")
            print("  ✓ Consider running these tests regularly to maintain system health.")
        else:
            print("  ⚠ Some tests failed. Review the detailed failure analysis above.")
            print("  ⚠ Fix failing tests before deploying to production.")
            if total_errors > 0:
                print("  ⚠ Suite errors indicate potential environment or configuration issues.")
        
        # Coverage analysis
        print("\nCOVERAGE ANALYSIS:")
        components_tested = {
            "Payment History Race Condition": any("race condition" in name.lower() for name in self.test_results.keys()),
            "Payment History Validator": any("validator" in name.lower() for name in self.test_results.keys()), 
            "API Security Decorators": any("security" in name.lower() and "decorator" in name.lower() for name in self.test_results.keys()),
            "Integration Testing": any("integrated" in name.lower() for name in self.test_results.keys())
        }
        
        for component, tested in components_tested.items():
            status = "✓ COVERED" if tested else "✗ NOT COVERED"
            print(f"  {status} {component}")
        
        print(f"\nTest Coverage: {sum(components_tested.values())}/{len(components_tested)} components ({(sum(components_tested.values())/len(components_tested)*100):.0f}%)")
        
        print(f"\n{'=' * 80}")
        
        # Return overall success status
        return total_failed == 0 and total_errors == 0


def main():
    """Main execution function"""
    try:
        # Initialize Frappe
        print("Initializing Frappe environment...")
        
        # Create and run test runner
        runner = ComprehensiveTestRunner()
        success = runner.run_all_tests()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except Exception as e:
        print(f"\nCRITICAL ERROR: Failed to run comprehensive tests: {str(e)}")
        print(f"Traceback: {traceback.format_exc()}")
        sys.exit(2)


if __name__ == "__main__":
    main()