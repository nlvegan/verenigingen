#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive test runner for the enhanced membership dues system
Runs all test categories: core functionality, edge cases, real-world scenarios, 
stress testing, and security validation
"""

import sys
import os
import frappe
import time
from collections import defaultdict


def run_comprehensive_membership_dues_tests(test_categories=None, verbose=False):
    """
    Run comprehensive membership dues system tests
    
    Args:
        test_categories: List of test categories to run ('core', 'edge', 'real_world', 'stress', 'security', 'all')
        verbose: Enable verbose output
    """
    
    # Define all test modules by category
    test_suites = {
        'core': {
            'description': 'Core Functionality Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_membership_dues_system',
            ]
        },
        'edge': {
            'description': 'Edge Case Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_membership_dues_edge_cases',
            ]
        },
        'real_world': {
            'description': 'Real-World Scenario Tests', 
            'modules': [
                'verenigingen.tests.backend.components.test_membership_dues_real_world_scenarios',
            ]
        },
        'stress': {
            'description': 'Stress Testing and Performance Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_membership_dues_stress_testing',
            ]
        },
        'security': {
            'description': 'Security Validation Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_membership_dues_security_validation',
            ]
        },
        'payment_plans': {
            'description': 'Payment Plan System Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_payment_plan_system',
            ]
        },
        'sepa': {
            'description': 'Enhanced SEPA Processing Tests',
            'modules': [
                'verenigingen.tests.backend.components.test_enhanced_sepa_processing',
            ]
        },
        'lifecycle': {
            'description': 'Enhanced Membership Lifecycle Tests',
            'modules': [
                'verenigingen.tests.workflows.test_enhanced_membership_lifecycle',
            ]
        }
    }
    
    # Determine which categories to run
    if test_categories is None or 'all' in test_categories:
        categories_to_run = list(test_suites.keys())
    else:
        categories_to_run = [cat for cat in test_categories if cat in test_suites]
        
    if not categories_to_run:
        print("❌ No valid test categories specified")
        print(f"Available categories: {', '.join(test_suites.keys())}")
        return False
        
    print("🚀 Comprehensive Membership Dues System Test Suite")
    print("=" * 60)
    print(f"Categories to run: {', '.join(categories_to_run)}")
    print(f"Verbose output: {'Enabled' if verbose else 'Disabled'}")
    print("=" * 60)
    
    # Track overall results
    overall_results = defaultdict(list)
    total_start_time = time.time()
    
    # Run each category
    for category in categories_to_run:
        suite_info = test_suites[category]
        print(f"\n📂 {suite_info['description']}")
        print("-" * 40)
        
        category_start_time = time.time()
        category_results = []
        
        for module in suite_info['modules']:
            print(f"🧪 Running {module}")
            
            # Check if module exists
            if not module_exists(module):
                print(f"  ⚠️  Module {module} not found - skipping")
                category_results.append(('SKIP', module, 0, "Module not found"))
                continue
                
            module_start_time = time.time()
            
            try:
                # Import and run the test module
                result = run_test_module(module, verbose)
                module_time = time.time() - module_start_time
                
                if result['success']:
                    print(f"  ✅ PASSED ({result['tests_run']} tests in {module_time:.2f}s)")
                    category_results.append(('PASS', module, result['tests_run'], module_time))
                else:
                    print(f"  ❌ FAILED ({result['failures']} failures, {result['errors']} errors)")
                    category_results.append(('FAIL', module, result['tests_run'], module_time))
                    if verbose:
                        print(f"     Details: {result.get('details', 'No details available')}")
                        
            except Exception as e:
                module_time = time.time() - module_start_time
                print(f"  💥 ERROR: {str(e)}")
                category_results.append(('ERROR', module, 0, str(e)))
                if verbose:
                    import traceback
                    print(f"     Traceback: {traceback.format_exc()}")
                    
        category_time = time.time() - category_start_time
        overall_results[category] = category_results
        
        # Category summary
        passed = sum(1 for r in category_results if r[0] == 'PASS')
        failed = sum(1 for r in category_results if r[0] == 'FAIL')
        errors = sum(1 for r in category_results if r[0] == 'ERROR')
        skipped = sum(1 for r in category_results if r[0] == 'SKIP')
        
        print(f"\n📊 {suite_info['description']} Summary:")
        print(f"   ✅ Passed: {passed}")
        print(f"   ❌ Failed: {failed}")
        print(f"   💥 Errors: {errors}")
        print(f"   ⚠️  Skipped: {skipped}")
        print(f"   ⏱️  Time: {category_time:.2f}s")
        
    # Overall summary
    total_time = time.time() - total_start_time
    
    print("\n" + "=" * 60)
    print("🎯 OVERALL TEST RESULTS SUMMARY")
    print("=" * 60)
    
    grand_totals = {'PASS': 0, 'FAIL': 0, 'ERROR': 0, 'SKIP': 0}
    
    for category, results in overall_results.items():
        suite_info = test_suites[category]
        print(f"\n📂 {suite_info['description']}:")
        
        for result_type, module, test_count, timing in results:
            grand_totals[result_type] += 1
            
            icon = {
                'PASS': '✅',
                'FAIL': '❌', 
                'ERROR': '💥',
                'SKIP': '⚠️'
            }.get(result_type, '❓')
            
            if isinstance(timing, (int, float)):
                timing_str = f"{timing:.2f}s" if timing > 0 else "N/A"
            else:
                timing_str = "Error"
                
            module_short = module.split('.')[-1]
            print(f"   {icon} {module_short}: {result_type} ({test_count} tests, {timing_str})")
            
    print(f"\n📈 Grand Totals:")
    print(f"   ✅ Passed: {grand_totals['PASS']} modules")
    print(f"   ❌ Failed: {grand_totals['FAIL']} modules")
    print(f"   💥 Errors: {grand_totals['ERROR']} modules")
    print(f"   ⚠️  Skipped: {grand_totals['SKIP']} modules")
    print(f"   ⏱️  Total Time: {total_time:.2f} seconds")
    
    # Success criteria
    total_modules = sum(grand_totals.values())
    success_rate = (grand_totals['PASS'] / total_modules * 100) if total_modules > 0 else 0
    
    print(f"\n🎯 Success Rate: {success_rate:.1f}%")
    
    if grand_totals['FAIL'] == 0 and grand_totals['ERROR'] == 0:
        print("🎉 ALL TESTS PASSED! Membership dues system is ready for production.")
        return True
    elif success_rate >= 80:
        print("⚠️  MOSTLY SUCCESSFUL but some issues need attention.")
        return False
    else:
        print("❌ SIGNIFICANT ISSUES found. System needs review before deployment.")
        return False


def module_exists(module_path):
    """Check if a Python module exists"""
    try:
        # Convert module path to file path
        file_path = module_path.replace('.', '/') + '.py'
        full_path = os.path.join('/home/frappe/frappe-bench/apps', file_path)
        return os.path.exists(full_path)
    except:
        return False


def run_test_module(module_path, verbose=False):
    """Run a specific test module and return results"""
    try:
        # Import the module
        import importlib
        module = importlib.import_module(module_path)
        
        # Find test classes
        import unittest
        import inspect
        
        test_classes = []
        for name, obj in inspect.getmembers(module):
            if (inspect.isclass(obj) and 
                issubclass(obj, unittest.TestCase) and 
                obj != unittest.TestCase):
                test_classes.append(obj)
                
        if not test_classes:
            return {
                'success': False,
                'tests_run': 0,
                'failures': 0,
                'errors': 1,
                'details': 'No test classes found'
            }
            
        # Create test suite
        suite = unittest.TestSuite()
        for test_class in test_classes:
            tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
            suite.addTests(tests)
            
        # Run tests
        stream = sys.stdout if verbose else open(os.devnull, 'w')
        runner = unittest.TextTestRunner(
            stream=stream,
            verbosity=2 if verbose else 0
        )
        
        result = runner.run(suite)
        
        if not verbose:
            stream.close()
            
        return {
            'success': result.wasSuccessful(),
            'tests_run': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'details': f"{len(result.failures)} failures, {len(result.errors)} errors"
        }
        
    except Exception as e:
        return {
            'success': False,
            'tests_run': 0,
            'failures': 0,
            'errors': 1,
            'details': str(e)
        }


def main():
    """Main entry point for the test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Comprehensive membership dues system test runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Test Categories:
  core        - Core functionality tests (basic operations)
  edge        - Edge case tests (boundary conditions, error handling)
  real_world  - Real-world scenario tests (organization workflows)
  stress      - Stress testing and performance tests
  security    - Security validation tests (permissions, data access)
  payment_plans - Payment plan system tests
  sepa        - Enhanced SEPA processing tests
  lifecycle   - Enhanced membership lifecycle tests
  all         - Run all test categories

Examples:
  python run_comprehensive_membership_dues_tests.py --categories core edge
  python run_comprehensive_membership_dues_tests.py --categories all --verbose
  python run_comprehensive_membership_dues_tests.py --categories stress security
        """
    )
    
    parser.add_argument(
        '--categories',
        nargs='*',
        default=['core'],
        help='Test categories to run (default: core)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    
    parser.add_argument(
        '--list-categories',
        action='store_true',
        help='List available test categories and exit'
    )
    
    args = parser.parse_args()
    
    if args.list_categories:
        print("Available test categories:")
        print("  core        - Core functionality tests")
        print("  edge        - Edge case tests")
        print("  real_world  - Real-world scenario tests")
        print("  stress      - Stress testing and performance tests")
        print("  security    - Security validation tests")
        print("  payment_plans - Payment plan system tests")
        print("  sepa        - Enhanced SEPA processing tests")
        print("  lifecycle   - Enhanced membership lifecycle tests")
        print("  all         - Run all test categories")
        return
        
    success = run_comprehensive_membership_dues_tests(
        test_categories=args.categories,
        verbose=args.verbose
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()