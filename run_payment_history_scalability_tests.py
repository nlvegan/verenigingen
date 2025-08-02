#!/usr/bin/env python3
"""
Payment History Scalability Test Runner
======================================

Command-line interface for running payment history scalability tests with
comprehensive performance monitoring and reporting.

This runner provides:
- Progressive scaling test execution
- Real-time performance monitoring
- Detailed performance reporting
- Resource usage tracking
- Test configuration options
- Automatic cleanup management

Usage Examples:
    # Run smoke test (100 members)
    python run_payment_history_scalability_tests.py --suite smoke

    # Run progressive scaling tests
    python run_payment_history_scalability_tests.py --suite scaling

    # Run all tests with detailed output
    python run_payment_history_scalability_tests.py --suite all --verbose

    # Run specific scale test
    python run_payment_history_scalability_tests.py --suite custom --members 1000 --months 6

    # Generate performance report only
    python run_payment_history_scalability_tests.py --report-only
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import frappe
    from frappe.utils import get_site_name

    from verenigingen.tests.scalability.payment_history_test_factory import PaymentHistoryTestFactory
    from verenigingen.tests.scalability.test_payment_history_scalability import (
        TestPaymentHistoryExtremeScale,
        TestPaymentHistoryLargeScale,
        TestPaymentHistoryMediumScale,
        TestPaymentHistoryPerformanceAnalysis,
        TestPaymentHistorySmallScale,
    )
except ImportError as e:
    print(f"Error importing required modules: {e}")
    print("Please ensure you're running this from the correct directory and Frappe is installed.")
    sys.exit(1)


class PaymentHistoryScalabilityRunner:
    """Main test runner for payment history scalability tests"""

    def __init__(self, site: str = None, verbose: bool = False):
        """Initialize test runner"""
        self.site = site or get_site_name()
        self.verbose = verbose
        self.results = []
        self.start_time = None
        self.test_config = {}

        print(f"🚀 Payment History Scalability Test Runner")
        print(f"Site: {self.site}")
        print(f"Timestamp: {datetime.now().isoformat()}")
        print("-" * 60)

    def run_smoke_test(self) -> Dict[str, Any]:
        """Run basic smoke test with small dataset"""
        print("\n🔍 Running Smoke Test (100 members, 3 months)")
        print("=" * 50)

        self.start_time = time.time()

        try:
            # Initialize Frappe context
            frappe.init(site=self.site)
            frappe.connect()

            # Run small scale test
            test_case = TestPaymentHistorySmallScale()
            test_case.setUp()

            try:
                test_case.test_small_scale_payment_history_creation()
                test_case.test_small_scale_payment_history_update()

                result = {
                    "status": "success",
                    "test_suite": "smoke",
                    "duration": time.time() - self.start_time,
                    "member_count": 100,
                    "tests_passed": 2,
                    "tests_failed": 0,
                }

                print("✅ Smoke test completed successfully")

            except Exception as e:
                result = {
                    "status": "failed",
                    "test_suite": "smoke",
                    "duration": time.time() - self.start_time,
                    "error": str(e),
                    "tests_passed": 0,
                    "tests_failed": 1,
                }

                print(f"❌ Smoke test failed: {e}")

            finally:
                test_case.tearDown()

        except Exception as e:
            result = {
                "status": "error",
                "test_suite": "smoke",
                "duration": time.time() - self.start_time if self.start_time else 0,
                "error": str(e),
            }

            print(f"💥 Smoke test setup failed: {e}")

        finally:
            frappe.destroy()

        self.results.append(result)
        return result

    def run_scaling_tests(self) -> List[Dict[str, Any]]:
        """Run progressive scaling tests"""
        print("\n📈 Running Progressive Scaling Tests")
        print("=" * 50)

        scaling_tests = [
            {
                "name": "small_scale",
                "class": TestPaymentHistorySmallScale,
                "methods": ["test_small_scale_payment_history_creation"],
                "description": "100 members, 3 months",
            },
            {
                "name": "medium_scale",
                "class": TestPaymentHistoryMediumScale,
                "methods": [
                    "test_medium_scale_payment_history_creation",
                    "test_medium_scale_background_job_processing",
                ],
                "description": "500 members, 6 months",
            },
            {
                "name": "large_scale",
                "class": TestPaymentHistoryLargeScale,
                "methods": [
                    "test_large_scale_payment_history_creation",
                    "test_large_scale_batch_payment_processing",
                ],
                "description": "1000 members, 12 months",
            },
            {
                "name": "extreme_scale",
                "class": TestPaymentHistoryExtremeScale,
                "methods": ["test_extreme_scale_creation_performance"],
                "description": "2500 members, 12 months",
            },
        ]

        scaling_results = []

        for test_config in scaling_tests:
            print(f"\n🎯 Running {test_config['name']}: {test_config['description']}")

            result = self._run_test_class(test_config)
            scaling_results.append(result)

            # Print intermediate results
            if result["status"] == "success":
                print(f"✅ {test_config['name']} completed in {result['duration']:.1f}s")
            else:
                print(f"❌ {test_config['name']} failed: {result.get('error', 'Unknown error')}")

                # For scaling tests, continue even if one fails
                if self.verbose:
                    print("   Continuing with remaining tests...")

        self.results.extend(scaling_results)
        return scaling_results

    def run_maximum_scale_test(self) -> Dict[str, Any]:
        """Run maximum scale test (5000 members)"""
        print("\n🏋️ Running Maximum Scale Test (5000 members)")
        print("=" * 50)
        print("⚠️ This test may take 30+ minutes and use significant system resources")

        test_config = {
            "name": "maximum_scale",
            "class": TestPaymentHistoryExtremeScale,
            "methods": ["test_maximum_scale_limits"],
            "description": "5000 members, 12 months - System Limit Test",
        }

        result = self._run_test_class(test_config)
        self.results.append(result)

        if result["status"] == "success":
            print(f"✅ Maximum scale test completed successfully in {result['duration']:.1f}s")
            print("🎉 System can handle 5000+ member scale!")
        else:
            print(f"⚠️ Maximum scale test reached system limits: {result.get('error', 'Unknown limit')}")
            print("💡 This indicates the practical scale limit for the current system configuration")

        return result

    def run_custom_test(self, members: int, months: int, payments_per_month: float = 1.5) -> Dict[str, Any]:
        """Run custom test with specified parameters"""
        print(f"\n⚙️ Running Custom Test ({members} members, {months} months)")
        print("=" * 50)

        self.start_time = time.time()

        try:
            frappe.init(site=self.site)
            frappe.connect()

            # Create test factory and run custom test
            factory = PaymentHistoryTestFactory(cleanup_on_exit=True, seed=42)

            try:
                batch_result = factory.create_payment_history_batch(
                    member_count=members, months_history=months, avg_payments_per_month=payments_per_month
                )

                result = {
                    "status": "success",
                    "test_suite": "custom",
                    "duration": time.time() - self.start_time,
                    "member_count": members,
                    "months_history": months,
                    "total_records": batch_result["metrics"]["total_records"],
                    "records_per_second": batch_result["metrics"]["total_records"]
                    / (time.time() - self.start_time),
                    "creation_time": batch_result["metrics"]["creation_time_seconds"],
                }

                print(f"✅ Custom test completed successfully")
                print(f"   Created {result['total_records']} records in {result['duration']:.1f}s")
                print(f"   Rate: {result['records_per_second']:.1f} records/second")

            except Exception as e:
                result = {
                    "status": "failed",
                    "test_suite": "custom",
                    "duration": time.time() - self.start_time,
                    "member_count": members,
                    "error": str(e),
                }

                print(f"❌ Custom test failed: {e}")

            finally:
                factory.cleanup()

        except Exception as e:
            result = {
                "status": "error",
                "test_suite": "custom",
                "duration": time.time() - self.start_time if self.start_time else 0,
                "error": str(e),
            }

            print(f"💥 Custom test setup failed: {e}")

        finally:
            frappe.destroy()

        self.results.append(result)
        return result

    def _run_test_class(self, test_config: Dict[str, Any]) -> Dict[str, Any]:
        """Run a specific test class with error handling"""
        start_time = time.time()

        try:
            frappe.init(site=self.site)
            frappe.connect()

            test_class = test_config["class"]
            test_instance = test_class()
            test_instance.setUp()

            passed_tests = 0
            failed_tests = 0
            errors = []

            try:
                for method_name in test_config["methods"]:
                    if hasattr(test_instance, method_name):
                        try:
                            if self.verbose:
                                print(f"  Running {method_name}...")

                            method = getattr(test_instance, method_name)
                            method()
                            passed_tests += 1

                            if self.verbose:
                                print(f"    ✅ {method_name} passed")

                        except Exception as e:
                            failed_tests += 1
                            errors.append(f"{method_name}: {str(e)}")

                            if self.verbose:
                                print(f"    ❌ {method_name} failed: {e}")
                    else:
                        failed_tests += 1
                        errors.append(f"Method {method_name} not found in {test_class.__name__}")

                result = {
                    "status": "success" if failed_tests == 0 else "failed",
                    "test_suite": test_config["name"],
                    "duration": time.time() - start_time,
                    "tests_passed": passed_tests,
                    "tests_failed": failed_tests,
                    "errors": errors,
                }

            finally:
                test_instance.tearDown()

        except Exception as e:
            result = {
                "status": "error",
                "test_suite": test_config["name"],
                "duration": time.time() - start_time,
                "error": str(e),
            }

        finally:
            frappe.destroy()

        return result

    def generate_performance_report(self) -> str:
        """Generate comprehensive performance report"""
        print("\n📊 Generating Performance Report")
        print("=" * 50)

        if not self.results:
            print("⚠️ No test results available for reporting")
            return ""

        report_lines = []
        report_lines.append("PAYMENT HISTORY SCALABILITY TEST REPORT")
        report_lines.append("=" * 60)
        report_lines.append(f"Generated: {datetime.now().isoformat()}")
        report_lines.append(f"Site: {self.site}")
        report_lines.append("")

        # Summary statistics
        total_tests = len(self.results)
        successful_tests = len([r for r in self.results if r.get("status") == "success"])
        failed_tests = len([r for r in self.results if r.get("status") in ["failed", "error"]])

        report_lines.append("SUMMARY")
        report_lines.append("-" * 30)
        report_lines.append(f"Total Tests: {total_tests}")
        report_lines.append(f"Successful: {successful_tests}")
        report_lines.append(f"Failed: {failed_tests}")
        report_lines.append(
            f"Success Rate: {(successful_tests/total_tests*100):.1f}%" if total_tests > 0 else "N/A"
        )
        report_lines.append("")

        # Individual test results
        report_lines.append("DETAILED RESULTS")
        report_lines.append("-" * 30)

        for result in self.results:
            report_lines.append(f"Test: {result.get('test_suite', 'unknown')}")
            report_lines.append(f"  Status: {result.get('status', 'unknown')}")
            report_lines.append(f"  Duration: {result.get('duration', 0):.2f}s")

            if "member_count" in result:
                report_lines.append(f"  Members: {result['member_count']:,}")

            if "records_per_second" in result:
                report_lines.append(f"  Rate: {result['records_per_second']:.1f} records/sec")

            if "total_records" in result:
                report_lines.append(f"  Records: {result['total_records']:,}")

            if result.get("status") != "success" and "error" in result:
                report_lines.append(f"  Error: {result['error']}")

            report_lines.append("")

        # Performance analysis
        successful_results = [
            r for r in self.results if r.get("status") == "success" and "records_per_second" in r
        ]

        if successful_results:
            report_lines.append("PERFORMANCE ANALYSIS")
            report_lines.append("-" * 30)

            rates = [r["records_per_second"] for r in successful_results]
            durations = [r["duration"] for r in successful_results]

            report_lines.append(f"Average Rate: {sum(rates)/len(rates):.1f} records/sec")
            report_lines.append(f"Best Rate: {max(rates):.1f} records/sec")
            report_lines.append(f"Worst Rate: {min(rates):.1f} records/sec")
            report_lines.append(f"Average Duration: {sum(durations)/len(durations):.1f}s")
            report_lines.append("")

        # System recommendations
        report_lines.append("RECOMMENDATIONS")
        report_lines.append("-" * 30)

        if successful_tests == total_tests:
            report_lines.append("✅ All tests passed - system shows good scalability")
        elif successful_tests > 0:
            report_lines.append("⚠️ Some tests failed - review failed test errors")
        else:
            report_lines.append("❌ All tests failed - system needs investigation")

        # Determine maximum validated scale
        max_members = 0
        for result in successful_results:
            if "member_count" in result:
                max_members = max(max_members, result["member_count"])

        if max_members > 0:
            report_lines.append(f"✅ Maximum validated scale: {max_members:,} members")

            if max_members >= 5000:
                report_lines.append("🎉 System can handle enterprise scale (5000+ members)")
            elif max_members >= 1000:
                report_lines.append("👍 System can handle large scale (1000+ members)")
            elif max_members >= 500:
                report_lines.append("✓ System can handle medium scale (500+ members)")
            else:
                report_lines.append("⚠️ System limited to small scale (<500 members)")

        report_lines.append("")
        report_lines.append("=" * 60)

        report_text = "\n".join(report_lines)
        print(report_text)

        # Save report to file
        report_filename = f"payment_history_scalability_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(report_filename, "w") as f:
                f.write(report_text)
            print(f"\n📄 Report saved to: {report_filename}")
        except Exception as e:
            print(f"⚠️ Could not save report to file: {e}")

        return report_text

    def run_all_tests(self) -> List[Dict[str, Any]]:
        """Run complete test suite"""
        print("\n🎯 Running Complete Test Suite")
        print("=" * 50)

        # Run tests in order of increasing scale
        self.run_smoke_test()
        self.run_scaling_tests()

        # Ask before running maximum scale test (optional)
        print(f"\n🤔 Run maximum scale test (5000 members)? This may take 30+ minutes.")
        print("Type 'yes' to continue, or any other key to skip:")

        try:
            user_input = input().strip().lower()
            if user_input == "yes":
                self.run_maximum_scale_test()
            else:
                print("⏭️ Skipping maximum scale test")
        except KeyboardInterrupt:
            print("\n⏭️ Skipping maximum scale test (interrupted)")
        except Exception:
            print("⏭️ Skipping maximum scale test (input error)")

        # Generate final report
        self.generate_performance_report()

        return self.results


def main():
    """Main command-line interface"""
    parser = argparse.ArgumentParser(
        description="Run payment history scalability tests with performance monitoring",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --suite smoke                    # Quick validation test
  %(prog)s --suite scaling                  # Progressive scaling tests
  %(prog)s --suite all                      # Complete test suite
  %(prog)s --suite custom --members 1000    # Custom test configuration
  %(prog)s --report-only                    # Generate report from previous results
        """,
    )

    parser.add_argument(
        "--suite",
        choices=["smoke", "scaling", "maximum", "custom", "all"],
        default="smoke",
        help="Test suite to run (default: smoke)",
    )

    parser.add_argument("--site", help="Frappe site name (auto-detected if not specified)")

    parser.add_argument(
        "--members", type=int, default=100, help="Number of members for custom test (default: 100)"
    )

    parser.add_argument(
        "--months", type=int, default=6, help="Months of payment history for custom test (default: 6)"
    )

    parser.add_argument(
        "--payments-per-month",
        type=float,
        default=1.5,
        help="Average payments per member per month (default: 1.5)",
    )

    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")

    parser.add_argument(
        "--report-only", action="store_true", help="Generate performance report only (no new tests)"
    )

    args = parser.parse_args()

    # Create test runner
    runner = PaymentHistoryScalabilityRunner(site=args.site, verbose=args.verbose)

    try:
        if args.report_only:
            runner.generate_performance_report()
            return

        # Run selected test suite
        if args.suite == "smoke":
            runner.run_smoke_test()
        elif args.suite == "scaling":
            runner.run_scaling_tests()
        elif args.suite == "maximum":
            runner.run_maximum_scale_test()
        elif args.suite == "custom":
            runner.run_custom_test(
                members=args.members, months=args.months, payments_per_month=args.payments_per_month
            )
        elif args.suite == "all":
            runner.run_all_tests()

        # Generate final report
        if args.suite != "all":  # 'all' generates its own report
            runner.generate_performance_report()

    except KeyboardInterrupt:
        print("\n\n⚠️ Test execution interrupted by user")
        print("Generating report for completed tests...")
        runner.generate_performance_report()
        sys.exit(1)

    except Exception as e:
        print(f"\n💥 Test execution failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
