#!/usr/bin/env python3
"""
Standalone runner for report regression tests
Validates that the Overdue Member Payments report fix is working correctly
"""

import os
import sys

# Add the verenigingen app to the Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/verenigingen")

import frappe

def run_report_regression_tests():
    """Run the report regression tests standalone"""
    print("🔄 Testing Report Regression Fix")
    print("=" * 50)
    
    try:
        # Execute the test runner wrapper function
        result = frappe.get_attr("verenigingen.tests.utils.test_runner_wrappers.run_report_regression_tests")()
        
        if result.get("success"):
            print(f"✅ SUCCESS: {result.get('message')}")
            print(f"   Tests Run: {result.get('tests_run', 0)}")
            print(f"   Failures: {result.get('failures', 0)}")
            print(f"   Errors: {result.get('errors', 0)}")
            return True
        else:
            print(f"❌ FAILED: {result.get('message')}")
            return False
            
    except Exception as e:
        print(f"💥 ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def run_individual_regression_test():
    """Run the regression test directly"""
    print("\n🧪 Running Individual Test")
    print("-" * 30)
    
    try:
        import unittest
        from verenigingen.tests.backend.components.test_overdue_payments_report_regression import TestOverduePaymentsReportRegression
        
        # Create test suite
        suite = unittest.TestLoader().loadTestsFromTestCase(TestOverduePaymentsReportRegression)
        
        # Run with detailed output
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        
        # Report results
        if result.wasSuccessful():
            print(f"✅ Individual test PASSED: {result.testsRun} tests run")
            return True
        else:
            print(f"❌ Individual test FAILED: {len(result.failures)} failures, {len(result.errors)} errors")
            return False
            
    except Exception as e:
        print(f"💥 Individual test ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Report Regression Test Runner")
    print("Testing fix for UnboundLocalError in Overdue Member Payments report")
    print("=" * 70)
    
    # Test 1: Via test runner wrapper (integration test)
    success1 = run_report_regression_tests()
    
    # Test 2: Direct test execution (unit test)
    success2 = run_individual_regression_test()
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)
    print(f"Test Runner Integration: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"Direct Test Execution:   {'✅ PASS' if success2 else '❌ FAIL'}")
    
    if success1 and success2:
        print("\n🎉 All tests PASSED! Report regression test is properly integrated.")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests FAILED. Check the output above for details.")
        sys.exit(1)