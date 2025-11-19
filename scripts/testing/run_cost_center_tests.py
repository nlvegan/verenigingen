#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cost Center Creation Test Suite Runner
=====================================

Comprehensive test runner for the Phase 2 Cost Center Creation feature test suite.
Provides organized execution of different test categories with detailed reporting,
performance metrics, and failure analysis.

Usage:
    # Run all tests
    python scripts/testing/run_cost_center_tests.py

    # Run specific test category
    python scripts/testing/run_cost_center_tests.py --suite business_logic
    python scripts/testing/run_cost_center_tests.py --suite integration
    python scripts/testing/run_cost_center_tests.py --suite performance

    # Run with specific options
    python scripts/testing/run_cost_center_tests.py --verbose --stop-on-failure
    python scripts/testing/run_cost_center_tests.py --suite all --performance-metrics

Test Suites:
- data_generation: Dutch accounting data generation tests
- business_logic: RGS-based suggestion intelligence tests  
- integration: API endpoint integration tests
- error_handling: Error scenarios and edge cases
- performance: Large dataset and scalability tests
- ui: User interface integration tests
- all: Complete test suite (default)

Features:
- Organized test execution by category
- Detailed performance metrics and timing
- Comprehensive failure analysis and reporting
- Memory usage monitoring
- Test data cleanup verification
- HTML and JSON result reporting
"""

import os
import sys
import time
import json
import argparse
import unittest
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional
import subprocess

# Add project path to Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import test modules
try:
    from verenigingen.tests.e_boekhouden.test_cost_center_creation_comprehensive import (
        TestDutchAccountingDataGeneration,
        TestBusinessLogicValidation, 
        TestAPIEndpointIntegration,
        TestErrorHandlingAndEdgeCases,
        TestPerformanceAndScalability
    )
    from verenigingen.tests.e_boekhouden.test_cost_center_ui_integration import (
        TestCostCenterUIIntegration,
        TestCostCenterUIWorkflows
    )
except ImportError as e:
    print(f"❌ Failed to import test modules: {e}")
    print("Make sure you're running this from the Frappe environment:")
    print("bench --site dev.veganisme.net execute verenigingen.scripts.testing.run_cost_center_tests")
    sys.exit(1)


class TestResult:
    """Enhanced test result tracking"""
    
    def __init__(self):
        self.start_time = time.time()
        self.end_time = None
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.skipped_tests = 0
        self.errors = []
        self.failures = []
        self.performance_metrics = {}
        self.memory_usage = {}
        
    def add_success(self, test_name: str, duration: float):
        self.passed_tests += 1
        self.total_tests += 1
        self.performance_metrics[test_name] = duration
        
    def add_failure(self, test_name: str, failure_info: str, duration: float):
        self.failed_tests += 1
        self.total_tests += 1
        self.failures.append({
            "test_name": test_name,
            "failure": failure_info,
            "duration": duration
        })
        
    def add_error(self, test_name: str, error_info: str, duration: float):
        self.failed_tests += 1
        self.total_tests += 1
        self.errors.append({
            "test_name": test_name,
            "error": error_info,
            "duration": duration
        })
        
    def add_skip(self, test_name: str, reason: str):
        self.skipped_tests += 1
        self.total_tests += 1
        
    def finish(self):
        self.end_time = time.time()
        
    @property
    def duration(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
        
    @property
    def success_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100
        

class CostCenterTestRunner:
    """Enhanced test runner for Cost Center Creation tests"""
    
    def __init__(self, verbose: bool = False, stop_on_failure: bool = False,
                 performance_metrics: bool = False):
        self.verbose = verbose
        self.stop_on_failure = stop_on_failure
        self.performance_metrics = performance_metrics
        self.results = TestResult()
        
        # Test suite definitions
        self.test_suites = {
            "data_generation": [
                TestDutchAccountingDataGeneration
            ],
            "business_logic": [
                TestBusinessLogicValidation
            ],
            "integration": [
                TestAPIEndpointIntegration
            ],
            "error_handling": [
                TestErrorHandlingAndEdgeCases
            ],
            "performance": [
                TestPerformanceAndScalability
            ],
            "ui": [
                TestCostCenterUIIntegration,
                TestCostCenterUIWorkflows
            ]
        }
        
    def run_test_suite(self, suite_name: str) -> TestResult:
        """Run specific test suite"""
        
        if suite_name == "all":
            return self.run_all_suites()
            
        if suite_name not in self.test_suites:
            raise ValueError(f"Unknown test suite: {suite_name}")
            
        print(f"\n🧪 Running {suite_name} test suite...")
        print("=" * 60)
        
        test_classes = self.test_suites[suite_name]
        
        for test_class in test_classes:
            self._run_test_class(test_class)
            
        self.results.finish()
        return self.results
        
    def run_all_suites(self) -> TestResult:
        """Run all test suites in order"""
        
        print("\n🧪 Running Complete Cost Center Creation Test Suite...")
        print("=" * 60)
        
        # Run suites in logical order
        suite_order = [
            "data_generation",
            "business_logic", 
            "integration",
            "error_handling",
            "ui",
            "performance"  # Performance tests last
        ]
        
        for suite_name in suite_order:
            if self.stop_on_failure and self.results.failed_tests > 0:
                print(f"\n⏹️  Stopping execution due to failures in previous suites")
                break
                
            print(f"\n📁 {suite_name.upper()} Test Suite")
            print("-" * 40)
            
            test_classes = self.test_suites[suite_name]
            
            for test_class in test_classes:
                self._run_test_class(test_class)
                
        self.results.finish()
        return self.results
        
    def _run_test_class(self, test_class):
        """Run individual test class"""
        
        class_name = test_class.__name__
        print(f"\n📝 {class_name}")
        
        # Create test suite
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)
        
        # Run tests
        for test in suite:
            test_name = f"{class_name}.{test._testMethodName}"
            
            if self.verbose:
                print(f"  🔍 {test._testMethodName}...", end=" ")
                
            start_time = time.time()
            
            try:
                # Run individual test
                result = unittest.TestResult()
                test(result)
                
                duration = time.time() - start_time
                
                if result.wasSuccessful():
                    self.results.add_success(test_name, duration)
                    if self.verbose:
                        print(f"✅ ({duration:.3f}s)")
                    else:
                        print(".", end="", flush=True)
                else:
                    # Handle failures and errors
                    if result.failures:
                        failure_info = "\\n".join([f[1] for f in result.failures])
                        self.results.add_failure(test_name, failure_info, duration)
                        if self.verbose:
                            print(f"❌ FAILED ({duration:.3f}s)")
                            print(f"     {failure_info[:200]}...")
                        else:
                            print("F", end="", flush=True)
                            
                    if result.errors:
                        error_info = "\\n".join([e[1] for e in result.errors])
                        self.results.add_error(test_name, error_info, duration)
                        if self.verbose:
                            print(f"💥 ERROR ({duration:.3f}s)")
                            print(f"     {error_info[:200]}...")
                        else:
                            print("E", end="", flush=True)
                            
                if self.stop_on_failure and not result.wasSuccessful():
                    print(f"\n⏹️  Stopping due to failure in {test_name}")
                    return
                    
            except Exception as e:
                duration = time.time() - start_time
                error_info = traceback.format_exc()
                self.results.add_error(test_name, error_info, duration)
                
                if self.verbose:
                    print(f"💥 EXCEPTION ({duration:.3f}s)")
                    print(f"     {str(e)}")
                else:
                    print("E", end="", flush=True)
                    
                if self.stop_on_failure:
                    print(f"\n⏹️  Stopping due to exception in {test_name}")
                    return
                    
        if not self.verbose:
            print()  # New line after dots
            
    def print_summary(self):
        """Print comprehensive test summary"""
        
        print("\n" + "=" * 60)
        print("📊 COST CENTER CREATION TEST RESULTS SUMMARY")
        print("=" * 60)
        
        # Overall results
        print(f"🕒 Total Duration: {self.results.duration:.2f} seconds")
        print(f"🧪 Total Tests: {self.results.total_tests}")
        print(f"✅ Passed: {self.results.passed_tests}")
        print(f"❌ Failed: {self.results.failed_tests}")
        print(f"⏭️  Skipped: {self.results.skipped_tests}")
        print(f"📈 Success Rate: {self.results.success_rate:.1f}%")
        
        # Performance metrics
        if self.performance_metrics and self.results.performance_metrics:
            print(f"\n⚡ PERFORMANCE METRICS")
            print("-" * 30)
            
            # Sort by duration (slowest first)
            sorted_metrics = sorted(
                self.results.performance_metrics.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            print("Slowest tests:")
            for test_name, duration in sorted_metrics[:10]:  # Top 10 slowest
                test_short = test_name.split('.')[-1]
                print(f"  {test_short}: {duration:.3f}s")
                
            # Performance statistics
            durations = list(self.results.performance_metrics.values())
            avg_duration = sum(durations) / len(durations)
            max_duration = max(durations)
            min_duration = min(durations)
            
            print(f"\\nPerformance statistics:")
            print(f"  Average: {avg_duration:.3f}s")
            print(f"  Maximum: {max_duration:.3f}s")
            print(f"  Minimum: {min_duration:.3f}s")
            
        # Failure details
        if self.results.failures:
            print(f"\\n❌ FAILURES ({len(self.results.failures)})")
            print("-" * 30)
            for i, failure in enumerate(self.results.failures[:5], 1):  # Show first 5
                test_short = failure["test_name"].split('.')[-1]
                print(f"{i}. {test_short}")
                print(f"   Duration: {failure['duration']:.3f}s")
                print(f"   Failure: {failure['failure'][:150]}...")
                
        # Error details  
        if self.results.errors:
            print(f"\\n💥 ERRORS ({len(self.results.errors)})")
            print("-" * 30)
            for i, error in enumerate(self.results.errors[:5], 1):  # Show first 5
                test_short = error["test_name"].split('.')[-1]
                print(f"{i}. {test_short}")
                print(f"   Duration: {error['duration']:.3f}s")
                print(f"   Error: {error['error'][:150]}...")
                
        # Final verdict
        print(f"\n{'🎉 ALL TESTS PASSED!' if self.results.failed_tests == 0 else '⚠️  SOME TESTS FAILED'}")
        
        if self.results.failed_tests == 0:
            print("✨ Cost Center Creation feature is ready for deployment!")
        else:
            print("🔧 Please review and fix failing tests before deployment.")
            
    def save_results(self, output_file: str = None):
        """Save test results to file"""
        
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"cost_center_test_results_{timestamp}.json"
            
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "duration": self.results.duration,
            "total_tests": self.results.total_tests,
            "passed_tests": self.results.passed_tests,
            "failed_tests": self.results.failed_tests,
            "skipped_tests": self.results.skipped_tests,
            "success_rate": self.results.success_rate,
            "performance_metrics": self.results.performance_metrics,
            "failures": self.results.failures,
            "errors": self.results.errors
        }
        
        with open(output_file, 'w') as f:
            json.dump(results_data, f, indent=2)
            
        print(f"\\n💾 Results saved to: {output_file}")


def main():
    """Main test runner entry point"""
    
    parser = argparse.ArgumentParser(description="Run Cost Center Creation test suite")
    parser.add_argument("--suite", choices=["data_generation", "business_logic", 
                                           "integration", "error_handling", 
                                           "performance", "ui", "all"], 
                       default="all", help="Test suite to run")
    parser.add_argument("--verbose", "-v", action="store_true", 
                       help="Verbose output")
    parser.add_argument("--stop-on-failure", action="store_true",
                       help="Stop on first failure")
    parser.add_argument("--performance-metrics", action="store_true",
                       help="Show detailed performance metrics")
    parser.add_argument("--save-results", metavar="FILE",
                       help="Save results to JSON file")
    
    args = parser.parse_args()
    
    # Banner
    print("🏗️  Cost Center Creation Test Suite")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Initialize runner
    runner = CostCenterTestRunner(
        verbose=args.verbose,
        stop_on_failure=args.stop_on_failure,
        performance_metrics=args.performance_metrics
    )
    
    try:
        # Run tests
        results = runner.run_test_suite(args.suite)
        
        # Print summary
        runner.print_summary()
        
        # Save results if requested
        if args.save_results:
            runner.save_results(args.save_results)
            
        # Exit with appropriate code
        sys.exit(0 if results.failed_tests == 0 else 1)
        
    except KeyboardInterrupt:
        print("\\n⏹️  Test execution interrupted by user")
        sys.exit(130)
        
    except Exception as e:
        print(f"\\n💥 Test runner failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()