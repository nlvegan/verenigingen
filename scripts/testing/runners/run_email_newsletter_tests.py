#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Email/Newsletter System Test Runner
===================================

Dedicated test runner for the comprehensive email/newsletter system test suite.
Provides focused test execution with detailed reporting and validation.

Usage:
    python scripts/testing/runners/run_email_newsletter_tests.py [options]
    
    --suite [security|integration|business|performance|errors|all]
    --verbose          Show detailed test output
    --stop-on-fail     Stop execution on first failure
    --generate-report  Generate detailed HTML test report
"""

import argparse
import os
import sys
import time
from datetime import datetime

# Add the apps directory to Python path
sys.path.insert(0, '/home/frappe/frappe-bench/apps')

# Set up Frappe environment
os.environ['FRAPPE_SITE'] = 'dev.veganisme.net'

try:
    import frappe
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
except Exception as e:
    print(f"❌ Failed to initialize Frappe environment: {e}")
    sys.exit(1)

import unittest
from io import StringIO
from unittest import TextTestRunner, TestLoader

# Import test classes
try:
    from verenigingen.tests.test_email_newsletter_system import (
        TestEmailNewsletterSystemSecurity,
        TestEmailNewsletterSystemIntegration,
        TestEmailNewsletterSystemBusinessLogic,
        TestEmailNewsletterSystemPerformance,
        TestEmailNewsletterSystemErrorHandling,
    )
except ImportError as e:
    print(f"❌ Failed to import email newsletter tests: {e}")
    sys.exit(1)


class EmailNewsletterTestRunner:
    """
    Specialized test runner for email/newsletter system tests.
    """

    def __init__(self):
        self.test_suites = {
            'security': {
                'name': 'Security Validation Tests',
                'description': 'Validate all security fixes (SQL injection, permissions, input sanitization)',
                'test_class': TestEmailNewsletterSystemSecurity,
                'priority': 'CRITICAL'
            },
            'integration': {
                'name': 'DocType Integration Tests',
                'description': 'Test real DocType interactions and relationships',
                'test_class': TestEmailNewsletterSystemIntegration,
                'priority': 'HIGH'
            },
            'business': {
                'name': 'Business Logic Tests',
                'description': 'Test core functionality (templates, campaigns, segmentation)',
                'test_class': TestEmailNewsletterSystemBusinessLogic,
                'priority': 'HIGH'
            },
            'performance': {
                'name': 'Performance & Scalability Tests',
                'description': 'Test system behavior with large datasets',
                'test_class': TestEmailNewsletterSystemPerformance,
                'priority': 'MEDIUM'
            },
            'errors': {
                'name': 'Error Handling & Resilience Tests',
                'description': 'Test system behavior under error conditions',
                'test_class': TestEmailNewsletterSystemErrorHandling,
                'priority': 'MEDIUM'
            }
        }
        
        self.results = {}
        self.start_time = None
        self.end_time = None

    def run_suite(self, suite_name, verbose=False, stop_on_fail=False):
        """
        Run a specific test suite.
        """
        if suite_name not in self.test_suites:
            raise ValueError(f"Unknown test suite: {suite_name}")
        
        suite_info = self.test_suites[suite_name]
        print(f"\n{'='*80}")
        print(f"🧪 RUNNING: {suite_info['name']}")
        print(f"📋 DESCRIPTION: {suite_info['description']}")
        print(f"⚡ PRIORITY: {suite_info['priority']}")
        print(f"{'='*80}")
        
        # Load test suite
        loader = TestLoader()
        suite = loader.loadTestsFromTestCase(suite_info['test_class'])
        
        # Configure test runner
        stream = StringIO() if not verbose else sys.stdout
        runner = TextTestRunner(
            stream=stream,
            verbosity=2 if verbose else 1,
            failfast=stop_on_fail
        )
        
        # Run tests
        start_time = time.time()
        result = runner.run(suite)
        end_time = time.time()
        
        # Store results
        self.results[suite_name] = {
            'suite_info': suite_info,
            'result': result,
            'duration': end_time - start_time,
            'start_time': start_time,
            'end_time': end_time
        }
        
        # Print results if not verbose
        if not verbose:
            self._print_suite_results(suite_name)
        
        return result

    def run_all_suites(self, verbose=False, stop_on_fail=False):
        """
        Run all test suites in priority order.
        """
        self.start_time = time.time()
        
        print(f"\n🚀 STARTING COMPREHENSIVE EMAIL/NEWSLETTER SYSTEM TESTS")
        print(f"📅 Test Run Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🎯 Test Suites: {len(self.test_suites)}")
        
        # Order suites by priority
        priority_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
        ordered_suites = []
        
        for priority in priority_order:
            for suite_name, suite_info in self.test_suites.items():
                if suite_info['priority'] == priority:
                    ordered_suites.append(suite_name)
        
        # Run suites in order
        total_failures = 0
        for suite_name in ordered_suites:
            try:
                result = self.run_suite(suite_name, verbose, stop_on_fail)
                if result.failures or result.errors:
                    total_failures += len(result.failures) + len(result.errors)
                    if stop_on_fail:
                        print(f"\n❌ STOPPING: Failure detected in {suite_name} suite")
                        break
            except Exception as e:
                print(f"\n❌ CRITICAL ERROR in {suite_name} suite: {e}")
                if stop_on_fail:
                    break
                total_failures += 1
        
        self.end_time = time.time()
        
        # Print overall results
        self._print_overall_results()
        
        return total_failures == 0

    def _print_suite_results(self, suite_name):
        """
        Print results for a single suite.
        """
        suite_result = self.results[suite_name]
        result = suite_result['result']
        duration = suite_result['duration']
        
        tests_run = result.testsRun
        failures = len(result.failures)
        errors = len(result.errors)
        success = tests_run - failures - errors
        
        print(f"\n📊 RESULTS: {suite_result['suite_info']['name']}")
        print(f"⏱️  Duration: {duration:.2f}s")
        print(f"✅ Passed: {success}/{tests_run}")
        
        if failures > 0:
            print(f"❌ Failures: {failures}")
            for test, traceback in result.failures:
                print(f"   • {test}: {traceback.split('AssertionError:')[-1].strip()}")
        
        if errors > 0:
            print(f"💥 Errors: {errors}")
            for test, traceback in result.errors:
                print(f"   • {test}: {traceback.split('Exception:')[-1].strip()}")
        
        # Overall suite status
        if failures == 0 and errors == 0:
            print(f"🎉 SUITE STATUS: PASSED")
        else:
            print(f"🚨 SUITE STATUS: FAILED")

    def _print_overall_results(self):
        """
        Print overall test run results.
        """
        if not self.results:
            print("\n❌ No test results available")
            return
        
        total_duration = self.end_time - self.start_time
        total_tests = sum(r['result'].testsRun for r in self.results.values())
        total_failures = sum(len(r['result'].failures) for r in self.results.values())
        total_errors = sum(len(r['result'].errors) for r in self.results.values())
        total_success = total_tests - total_failures - total_errors
        
        print(f"\n{'='*80}")
        print(f"📋 COMPREHENSIVE EMAIL/NEWSLETTER SYSTEM TEST RESULTS")
        print(f"{'='*80}")
        print(f"⏱️  Total Duration: {total_duration:.2f}s")
        print(f"📊 Test Suites Run: {len(self.results)}")
        print(f"🧪 Total Tests: {total_tests}")
        print(f"✅ Passed: {total_success}")
        print(f"❌ Failed: {total_failures}")
        print(f"💥 Errors: {total_errors}")
        
        # Suite-by-suite breakdown
        print(f"\n📋 SUITE BREAKDOWN:")
        for suite_name, suite_result in self.results.items():
            result = suite_result['result']
            tests_run = result.testsRun
            failures = len(result.failures)
            errors = len(result.errors)
            success = tests_run - failures - errors
            
            status = "✅ PASSED" if failures == 0 and errors == 0 else "❌ FAILED"
            priority = suite_result['suite_info']['priority']
            
            print(f"   {status} [{priority}] {suite_result['suite_info']['name']}: {success}/{tests_run} passed")
        
        # Overall status
        if total_failures == 0 and total_errors == 0:
            print(f"\n🎉 OVERALL STATUS: ALL TESTS PASSED")
            print(f"✨ The email/newsletter system is ready for production!")
        else:
            print(f"\n🚨 OVERALL STATUS: TESTS FAILED")
            print(f"⚠️  Please review failures before deploying to production.")
        
        print(f"{'='*80}")

    def generate_html_report(self, output_file="email_newsletter_test_report.html"):
        """
        Generate detailed HTML test report.
        """
        if not self.results:
            print("❌ No test results to generate report")
            return
        
        html_content = self._generate_html_report_content()
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"📄 HTML report generated: {output_file}")
        except Exception as e:
            print(f"❌ Failed to generate HTML report: {e}")

    def _generate_html_report_content(self):
        """
        Generate HTML content for test report.
        """
        total_tests = sum(r['result'].testsRun for r in self.results.values())
        total_failures = sum(len(r['result'].failures) for r in self.results.values())
        total_errors = sum(len(r['result'].errors) for r in self.results.values())
        total_success = total_tests - total_failures - total_errors
        success_rate = (total_success / total_tests * 100) if total_tests > 0 else 0
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Email/Newsletter System Test Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 8px 8px 0 0; }}
        .header h1 {{ margin: 0; font-size: 2.5em; }}
        .header p {{ margin: 10px 0 0 0; opacity: 0.9; }}
        .summary {{ padding: 30px; border-bottom: 1px solid #eee; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .stat {{ text-align: center; padding: 20px; border-radius: 8px; }}
        .stat.success {{ background: #d4edda; color: #155724; }}
        .stat.warning {{ background: #fff3cd; color: #856404; }}
        .stat.danger {{ background: #f8d7da; color: #721c24; }}
        .stat h3 {{ margin: 0; font-size: 2em; }}
        .stat p {{ margin: 5px 0 0 0; }}
        .suite {{ margin: 20px; padding: 20px; border-radius: 8px; border-left: 4px solid #ddd; }}
        .suite.passed {{ border-left-color: #28a745; background: #f8fff9; }}
        .suite.failed {{ border-left-color: #dc3545; background: #fff5f5; }}
        .suite h3 {{ margin: 0 0 10px 0; color: #333; }}
        .suite .meta {{ color: #666; font-size: 0.9em; margin-bottom: 15px; }}
        .test-results {{ margin-top: 15px; }}
        .test {{ padding: 10px; margin: 5px 0; border-radius: 4px; font-family: monospace; font-size: 0.9em; }}
        .test.passed {{ background: #e7f5e7; color: #2d5d2d; }}
        .test.failed {{ background: #fde7e7; color: #5d2d2d; }}
        .test.error {{ background: #fff3e0; color: #5d4d2d; }}
        .footer {{ padding: 20px; text-align: center; color: #666; border-top: 1px solid #eee; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📧 Email/Newsletter System Test Report</h1>
            <p>Production-Ready System Validation | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="summary">
            <div class="stats">
                <div class="stat success">
                    <h3>{total_tests}</h3>
                    <p>Total Tests</p>
                </div>
                <div class="stat success">
                    <h3>{total_success}</h3>
                    <p>Passed</p>
                </div>
                <div class="stat {'success' if total_failures == 0 else 'danger'}">
                    <h3>{total_failures}</h3>
                    <p>Failed</p>
                </div>
                <div class="stat {'success' if total_errors == 0 else 'warning'}">
                    <h3>{total_errors}</h3>
                    <p>Errors</p>
                </div>
                <div class="stat success">
                    <h3>{success_rate:.1f}%</h3>
                    <p>Success Rate</p>
                </div>
            </div>
        </div>
"""
        
        # Add suite details
        for suite_name, suite_result in self.results.items():
            result = suite_result['result']
            suite_info = suite_result['suite_info']
            
            tests_run = result.testsRun
            failures = len(result.failures)
            errors = len(result.errors)
            success = tests_run - failures - errors
            
            suite_status = "passed" if failures == 0 and errors == 0 else "failed"
            
            html += f"""
        <div class="suite {suite_status}">
            <h3>{suite_info['name']}</h3>
            <div class="meta">
                <strong>Priority:</strong> {suite_info['priority']} | 
                <strong>Duration:</strong> {suite_result['duration']:.2f}s | 
                <strong>Tests:</strong> {tests_run} | 
                <strong>Success Rate:</strong> {(success/tests_run*100):.1f}%
            </div>
            <p>{suite_info['description']}</p>
            
            <div class="test-results">
"""
            
            # Add individual test results (simplified)
            for test, traceback in result.failures:
                html += f'<div class="test failed">❌ FAILED: {test}</div>'
            
            for test, traceback in result.errors:
                html += f'<div class="test error">💥 ERROR: {test}</div>'
            
            # Show success count
            if success > 0:
                html += f'<div class="test passed">✅ {success} tests passed successfully</div>'
            
            html += "            </div>\n        </div>\n"
        
        html += f"""
        <div class="footer">
            <p>Generated by Email/Newsletter System Test Runner | Verenigingen Association Management System</p>
            <p>This report validates the production-ready email/newsletter system with comprehensive security, integration, and performance testing.</p>
        </div>
    </div>
</body>
</html>
"""
        
        return html


def main():
    """
    Main entry point for the test runner.
    """
    parser = argparse.ArgumentParser(
        description="Run comprehensive tests for the email/newsletter system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_email_newsletter_tests.py --suite security
  python run_email_newsletter_tests.py --suite all --verbose
  python run_email_newsletter_tests.py --suite integration --generate-report
  python run_email_newsletter_tests.py --suite all --stop-on-fail

Test Suites:
  security     - Validate SQL injection fixes, permission enforcement, input sanitization
  integration  - Test real DocType interactions and relationships  
  business     - Test core functionality (templates, campaigns, segmentation)
  performance  - Test system behavior with large datasets
  errors       - Test error handling and resilience
  all          - Run all test suites
"""
    )
    
    parser.add_argument(
        '--suite', 
        choices=['security', 'integration', 'business', 'performance', 'errors', 'all'],
        default='all',
        help='Test suite to run (default: all)'
    )
    
    parser.add_argument(
        '--verbose', 
        action='store_true',
        help='Show detailed test output'
    )
    
    parser.add_argument(
        '--stop-on-fail', 
        action='store_true',
        help='Stop execution on first failure'
    )
    
    parser.add_argument(
        '--generate-report', 
        action='store_true',
        help='Generate detailed HTML test report'
    )
    
    args = parser.parse_args()
    
    # Initialize test runner
    runner = EmailNewsletterTestRunner()
    
    try:
        # Run tests
        if args.suite == 'all':
            success = runner.run_all_suites(args.verbose, args.stop_on_fail)
        else:
            result = runner.run_suite(args.suite, args.verbose, args.stop_on_fail)
            success = len(result.failures) == 0 and len(result.errors) == 0
        
        # Generate report if requested
        if args.generate_report:
            runner.generate_html_report()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Test run interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Critical error in test runner: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Clean up Frappe environment
        try:
            frappe.destroy()
        except:
            pass


if __name__ == '__main__':
    main()
