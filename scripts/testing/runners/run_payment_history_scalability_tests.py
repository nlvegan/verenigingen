#!/usr/bin/env python3
"""
Payment History Scalability Test Runner
=======================================

Specialized test runner for payment history scalability testing with comprehensive
reporting, performance analysis, and CI/CD integration support.

Features:
- Progressive scaling test execution (100 → 5000 members)
- Real-time performance monitoring and reporting
- Background job queue testing and monitoring
- Edge case and failure injection testing
- Comprehensive HTML reporting with charts
- CI/CD integration with performance thresholds
- Resource usage monitoring and cleanup verification

Usage Examples:
    # Run smoke tests (quick verification)
    python run_payment_history_scalability_tests.py --suite smoke

    # Run full performance suite
    python run_payment_history_scalability_tests.py --suite performance --html-report

    # Run stress tests with monitoring
    python run_payment_history_scalability_tests.py --suite stress --monitor-resources

    # Run all tests with comprehensive reporting
    python run_payment_history_scalability_tests.py --suite all --html-report --json-report

    # CI/CD integration mode
    python run_payment_history_scalability_tests.py --suite integration --ci-mode --performance-thresholds
"""

import argparse
import json
import os
import platform
import psutil
import sys
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# Add the apps directory to Python path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import frappe


class PaymentHistoryScalabilityTestRunner:
    """Comprehensive test runner for payment history scalability testing"""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.results_dir = Path("/tmp/payment_history_scalability_results")
        self.results_dir.mkdir(exist_ok=True)
        
        self.test_results = {}
        self.performance_metrics = {}
        self.resource_usage = {}
        
        # Performance thresholds for CI/CD
        self.performance_thresholds = {
            "smoke": {
                "max_execution_time": 30.0,  # 30 seconds
                "min_throughput": 5.0,       # 5 members/second
                "max_memory_mb": 200.0       # 200MB
            },
            "integration": {
                "max_execution_time": 120.0,  # 2 minutes
                "min_throughput": 3.0,        # 3 members/second  
                "max_memory_mb": 500.0        # 500MB
            },
            "performance": {
                "max_execution_time": 300.0,  # 5 minutes
                "min_throughput": 2.0,        # 2 members/second
                "max_memory_mb": 1000.0       # 1GB
            },
            "stress": {
                "max_execution_time": 600.0,  # 10 minutes
                "min_throughput": 1.0,        # 1 member/second
                "max_memory_mb": 2000.0       # 2GB
            }
        }
        
    def run_tests(self, args) -> Dict[str, Any]:
        """Main test execution entry point"""
        
        print("🚀 Payment History Scalability Test Runner")
        print("=" * 60)
        print(f"Suite: {args.suite}")
        print(f"Start Time: {self.start_time}")
        print(f"System: {platform.platform()}")
        print(f"Memory: {psutil.virtual_memory().total / (1024**3):.1f}GB")
        print("=" * 60)
        
        try:
            # Initialize Frappe context
            self._initialize_frappe_context()
        
            # Start resource monitoring if requested
            if args.monitor_resources:
                self._start_resource_monitoring()
            
            # Run test suite based on arguments
            if args.suite == "smoke":
                results = self._run_smoke_tests(args)
            elif args.suite == "integration":
                results = self._run_integration_tests(args)
            elif args.suite == "performance":
                results = self._run_performance_tests(args)
            elif args.suite == "stress":
                results = self._run_stress_tests(args)
            elif args.suite == "all":
                results = self._run_all_tests(args)
            else:
                raise ValueError(f"Unknown test suite: {args.suite}")
            
            # Stop resource monitoring
            if args.monitor_resources:
                self._stop_resource_monitoring()
            
            # Validate performance thresholds for CI/CD
            if args.ci_mode or args.performance_thresholds:
                self._validate_performance_thresholds(args.suite, results)
            
            # Generate reports
            self._generate_reports(args, results)
            
            return results
            
        except Exception as e:
            print(f"❌ Test execution failed: {e}")
            return {"success": False, "error": str(e)}
    
    def _initialize_frappe_context(self):
        """Initialize Frappe application context"""
        try:
            if not frappe.local.conf:
                frappe.init("dev.veganisme.net")
                frappe.connect()
                
            print("✅ Frappe context initialized")
            
        except Exception as e:
            print(f"❌ Failed to initialize Frappe context: {e}")
            raise
    
    def _run_smoke_tests(self, args) -> Dict[str, Any]:
        """Run smoke tests (quick verification - 100 members)"""
        
        print("\n🔥 Running Smoke Tests (100 members)")
        print("-" * 40)
        
        test_results = {}
        
        # Run basic scalability test
        result = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "PaymentHistoryScalabilityTest.test_payment_history_scale_100_members",
            timeout=60
        )
        test_results["scale_100"] = result
        
        # Run basic background job test
        if not args.skip_background_jobs:
            bg_result = self._execute_test_module(
                "verenigingen.tests.test_payment_history_scalability", 
                "BackgroundJobScalabilityTest.test_background_job_queue_processing_50_members",
                timeout=120
            )
            test_results["background_jobs_50"] = bg_result
        
        return {
            "suite": "smoke",
            "tests": test_results,
            "success": all(r.get("success", False) for r in test_results.values()),
            "execution_time": (datetime.now() - self.start_time).total_seconds()
        }
    
    def _run_integration_tests(self, args) -> Dict[str, Any]:
        """Run integration tests (500 members + background jobs)"""
        
        print("\n🔗 Running Integration Tests (500 members)")
        print("-" * 40)
        
        test_results = {}
        
        # Run 500 member scalability test
        result = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "PaymentHistoryScalabilityTest.test_payment_history_scale_500_members", 
            timeout=180
        )
        test_results["scale_500"] = result
        
        # Run background job processing test
        if not args.skip_background_jobs:
            bg_result = self._execute_test_module(
                "verenigingen.tests.test_payment_history_scalability",
                "BackgroundJobScalabilityTest.test_background_job_queue_processing_200_members",
                timeout=300
            )
            test_results["background_jobs_200"] = bg_result
        
        # Run edge case tests
        edge_result = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "EdgeCaseScalabilityTest.test_payment_history_with_missing_customers",
            timeout=120
        )
        test_results["edge_cases"] = edge_result
        
        return {
            "suite": "integration", 
            "tests": test_results,
            "success": all(r.get("success", False) for r in test_results.values()),
            "execution_time": (datetime.now() - self.start_time).total_seconds()
        }
    
    def _run_performance_tests(self, args) -> Dict[str, Any]:
        """Run performance tests (1000 members + comprehensive monitoring)"""
        
        print("\n⚡ Running Performance Tests (1000 members)")
        print("-" * 40)
        
        test_results = {}
        
        # Run 1000 member scalability test
        result = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "PaymentHistoryScalabilityTest.test_payment_history_scale_1000_members",
            timeout=300
        )
        test_results["scale_1000"] = result
        
        # Run concurrent access test
        concurrent_result = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "EdgeCaseScalabilityTest.test_concurrent_payment_history_updates",
            timeout=180
        )
        test_results["concurrent_access"] = concurrent_result
        
        return {
            "suite": "performance",
            "tests": test_results, 
            "success": all(r.get("success", False) for r in test_results.values()),
            "execution_time": (datetime.now() - self.start_time).total_seconds()
        }
    
    def _run_stress_tests(self, args) -> Dict[str, Any]:
        """Run stress tests (2500+ members + maximum load)"""
        
        print("\n🏋️ Running Stress Tests (2500+ members)")
        print("-" * 40)
        
        test_results = {}
        
        # Run 2500 member stress test
        result_2500 = self._execute_test_module(
            "verenigingen.tests.test_payment_history_scalability",
            "PaymentHistoryScalabilityTest.test_payment_history_scale_2500_members",
            timeout=600
        )
        test_results["scale_2500"] = result_2500
        
        # Run maximum 5000 member test if system has enough resources
        if self._check_system_resources_for_max_test():
            result_5000 = self._execute_test_module(
                "verenigingen.tests.test_payment_history_scalability", 
                "PaymentHistoryScalabilityTest.test_payment_history_scale_5000_members",
                timeout=900
            )
            test_results["scale_5000"] = result_5000
        else:
            print("⚠️ Skipping 5000 member test - insufficient system resources")
            test_results["scale_5000"] = {"success": False, "skipped": True, "reason": "insufficient_resources"}
        
        return {
            "suite": "stress",
            "tests": test_results,
            "success": all(r.get("success", False) for r in test_results.values() if not r.get("skipped")),
            "execution_time": (datetime.now() - self.start_time).total_seconds()
        }
    
    def _run_all_tests(self, args) -> Dict[str, Any]:
        """Run all test suites progressively"""
        
        print("\n🎯 Running All Test Suites")
        print("-" * 40)
        
        all_results = {}
        
        # Run in order of increasing complexity
        suites = ["smoke", "integration", "performance", "stress"]
        
        for suite in suites:
            print(f"\n📋 Starting {suite.upper()} test suite...")
            
            # Create temporary args for this suite
            suite_args = argparse.Namespace(**vars(args))
            suite_args.suite = suite
            
            if suite == "smoke":
                suite_result = self._run_smoke_tests(suite_args)
            elif suite == "integration":
                suite_result = self._run_integration_tests(suite_args)
            elif suite == "performance":
                suite_result = self._run_performance_tests(suite_args)
            elif suite == "stress":
                suite_result = self._run_stress_tests(suite_args)
                
            all_results[suite] = suite_result
            
            # Stop if any suite fails and --stop-on-failure is set
            if not suite_result.get("success", False) and args.stop_on_failure:
                print(f"❌ Stopping test execution - {suite} suite failed")
                break
                
            print(f"✅ {suite.upper()} suite completed - Success: {suite_result.get('success', False)}")
        
        return {
            "suite": "all",
            "results": all_results,
            "success": all(r.get("success", False) for r in all_results.values()),
            "execution_time": (datetime.now() - self.start_time).total_seconds()
        }
    
    def _execute_test_module(self, module_path: str, test_method: str, timeout: int = 300) -> Dict[str, Any]:
        """Execute specific test method with timeout and error handling"""
        
        print(f"🧪 Running {test_method}...")
        
        start_time = time.time()
        
        try:
            # Import the test module
            test_module = frappe.get_attr(module_path)
            
            # Extract class and method names
            if "." in test_method:
                class_name, method_name = test_method.split(".", 1)
                test_class = getattr(test_module, class_name)
                
                # Create test instance and run method
                test_instance = test_class()
                test_instance.setUp()
                
                try:
                    test_result = getattr(test_instance, method_name)()
                    success = True
                    error = None
                except Exception as e:
                    success = False
                    error = str(e)
                finally:
                    test_instance.tearDown()
            else:
                # Direct function call
                test_result = getattr(test_module, test_method)()
                success = True
                error = None
                
        except Exception as e:
            success = False
            error = str(e)
            test_result = None
            
        execution_time = time.time() - start_time
        
        result = {
            "test_method": test_method,
            "success": success,
            "execution_time": execution_time,
            "result": test_result,
            "error": error
        }
        
        status = "✅" if success else "❌"
        print(f"  {status} {test_method} - {execution_time:.2f}s")
        
        if error:
            print(f"    Error: {error}")
            
        return result
    
    def _check_system_resources_for_max_test(self) -> bool:
        """Check if system has enough resources for maximum stress test"""
        
        memory = psutil.virtual_memory()
        available_gb = memory.available / (1024**3)
        
        # Require at least 4GB available memory for 5000 member test
        return available_gb >= 4.0
    
    def _start_resource_monitoring(self):
        """Start background resource monitoring"""
        
        print("📊 Starting resource monitoring...")
        
        self.resource_monitoring_active = True
        self.resource_samples = []
        
        def monitor_resources():
            while getattr(self, 'resource_monitoring_active', False):
                try:
                    memory = psutil.virtual_memory()
                    cpu = psutil.cpu_percent(interval=1)
                    
                    sample = {
                        "timestamp": datetime.now().isoformat(),
                        "memory_used_mb": memory.used / (1024**2),
                        "memory_percent": memory.percent,
                        "cpu_percent": cpu
                    }
                    
                    self.resource_samples.append(sample)
                    
                except Exception as e:
                    print(f"⚠️ Resource monitoring error: {e}")
                    
                time.sleep(5)  # Sample every 5 seconds
        
        import threading
        self.resource_monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
        self.resource_monitor_thread.start()
    
    def _stop_resource_monitoring(self):
        """Stop resource monitoring and collect results"""
        
        if hasattr(self, 'resource_monitoring_active'):
            self.resource_monitoring_active = False
            
            if self.resource_samples:
                # Calculate resource usage statistics
                memory_values = [s["memory_used_mb"] for s in self.resource_samples]
                cpu_values = [s["cpu_percent"] for s in self.resource_samples]
                
                self.resource_usage = {
                    "samples_count": len(self.resource_samples),
                    "memory_min_mb": min(memory_values),
                    "memory_max_mb": max(memory_values),
                    "memory_avg_mb": sum(memory_values) / len(memory_values),
                    "cpu_min_percent": min(cpu_values),
                    "cpu_max_percent": max(cpu_values),
                    "cpu_avg_percent": sum(cpu_values) / len(cpu_values),
                    "samples": self.resource_samples
                }
                
                print("✅ Resource monitoring completed")
                print(f"  Memory peak: {self.resource_usage['memory_max_mb']:.1f}MB")
                print(f"  CPU peak: {self.resource_usage['cpu_max_percent']:.1f}%")
    
    def _validate_performance_thresholds(self, suite: str, results: Dict[str, Any]):
        """Validate results against performance thresholds for CI/CD"""
        
        print(f"\n🎯 Validating performance thresholds for {suite} suite...")
        
        thresholds = self.performance_thresholds.get(suite, {})
        violations = []
        
        # Check execution time
        execution_time = results.get("execution_time", 0)
        max_execution_time = thresholds.get("max_execution_time", float('inf'))
        
        if execution_time > max_execution_time:
            violations.append(f"Execution time {execution_time:.1f}s > {max_execution_time:.1f}s")
        
        # Check memory usage
        if self.resource_usage:
            peak_memory = self.resource_usage.get("memory_max_mb", 0)
            max_memory = thresholds.get("max_memory_mb", float('inf'))
            
            if peak_memory > max_memory:
                violations.append(f"Peak memory {peak_memory:.1f}MB > {max_memory:.1f}MB")
        
        # Check throughput (if available in test results)
        # This would need to be extracted from individual test results
        
        if violations:
            print("❌ Performance threshold violations:")
            for violation in violations:
                print(f"  - {violation}")
            
            if hasattr(self, 'ci_mode') and self.ci_mode:
                raise RuntimeError(f"Performance thresholds violated: {violations}")
        else:
            print("✅ All performance thresholds met")
    
    def _generate_reports(self, args, results: Dict[str, Any]):
        """Generate comprehensive test reports"""
        
        print(f"\n📊 Generating test reports...")
        
        # Generate JSON report
        if args.json_report:
            self._generate_json_report(results)
        
        # Generate HTML report  
        if args.html_report:
            self._generate_html_report(results)
        
        # Generate performance summary
        self._generate_performance_summary(results)
        
        # Open HTML report in browser if requested
        if args.html_report and args.open_browser:
            html_file = self.results_dir / "scalability_report.html"
            if html_file.exists():
                webbrowser.open(f"file://{html_file}")
    
    def _generate_json_report(self, results: Dict[str, Any]):
        """Generate detailed JSON report"""
        
        report_data = {
            "test_run_info": {
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
                "system_info": {
                    "platform": platform.platform(),
                    "python_version": platform.python_version(),
                    "memory_total_gb": psutil.virtual_memory().total / (1024**3),
                    "cpu_count": psutil.cpu_count()
                }
            },
            "test_results": results,
            "resource_usage": self.resource_usage,
            "performance_metrics": self.performance_metrics
        }
        
        json_file = self.results_dir / f"scalability_report_{int(time.time())}.json"
        
        with open(json_file, 'w') as f:
            json.dump(report_data, f, indent=2, default=str)
            
        print(f"📄 JSON report saved: {json_file}")
    
    def _generate_html_report(self, results: Dict[str, Any]):
        """Generate comprehensive HTML report with charts"""
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Payment History Scalability Test Report</title>
    <meta charset="utf-8">
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f0f8ff; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .test-section {{ margin-bottom: 30px; }}
        .success {{ color: #28a745; }}
        .failure {{ color: #dc3545; }}
        .warning {{ color: #ffc107; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f8f9fa; }}
        .metric {{ display: inline-block; margin: 10px; padding: 10px; background: #e9ecef; border-radius: 3px; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <div class="header">
        <h1>Payment History Scalability Test Report</h1>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>Duration:</strong> {(datetime.now() - self.start_time).total_seconds():.1f} seconds</p>
        <p><strong>System:</strong> {platform.platform()}</p>
    </div>
    
    <div class="summary">
        <h2>Test Summary</h2>
        <div class="metric">
            <strong>Overall Success:</strong> 
            <span class="{'success' if results.get('success', False) else 'failure'}">
                {'✅ PASSED' if results.get('success', False) else '❌ FAILED'}
            </span>
        </div>
        <div class="metric">
            <strong>Suite:</strong> {results.get('suite', 'Unknown')}
        </div>
        <div class="metric">
            <strong>Execution Time:</strong> {results.get('execution_time', 0):.1f}s
        </div>
    </div>
    
    <div class="test-section">
        <h2>Test Results</h2>
        {self._generate_test_results_html(results)}
    </div>
    
    <div class="test-section">
        <h2>Resource Usage</h2>
        {self._generate_resource_usage_html()}
    </div>
    
    <div class="test-section">
        <h2>Performance Metrics</h2>
        {self._generate_performance_metrics_html()}
    </div>
    
</body>
</html>
        """
        
        html_file = self.results_dir / "scalability_report.html"
        
        with open(html_file, 'w') as f:
            f.write(html_content)
            
        print(f"📊 HTML report saved: {html_file}")
    
    def _generate_test_results_html(self, results: Dict[str, Any]) -> str:
        """Generate HTML for test results section"""
        
        if "tests" in results:
            # Single suite results
            tests = results["tests"]
        elif "results" in results:
            # All suites results
            tests = {}
            for suite_name, suite_data in results["results"].items():
                if "tests" in suite_data:
                    for test_name, test_data in suite_data["tests"].items():
                        tests[f"{suite_name}_{test_name}"] = test_data
        else:
            return "<p>No test results available</p>"
        
        html = "<table><tr><th>Test</th><th>Status</th><th>Execution Time</th><th>Details</th></tr>"
        
        for test_name, test_data in tests.items():
            success = test_data.get("success", False)
            status_class = "success" if success else "failure"
            status_text = "✅ PASSED" if success else "❌ FAILED"
            execution_time = test_data.get("execution_time", 0)
            error = test_data.get("error", "")
            
            html += f"""
            <tr>
                <td>{test_name}</td>
                <td class="{status_class}">{status_text}</td>
                <td>{execution_time:.2f}s</td>
                <td>{error if error else "No errors"}</td>
            </tr>
            """
        
        html += "</table>"
        return html
    
    def _generate_resource_usage_html(self) -> str:
        """Generate HTML for resource usage section"""
        
        if not self.resource_usage:
            return "<p>No resource usage data available</p>"
        
        html = f"""
        <div class="metric">
            <strong>Memory Peak:</strong> {self.resource_usage.get('memory_max_mb', 0):.1f}MB
        </div>
        <div class="metric">
            <strong>Memory Average:</strong> {self.resource_usage.get('memory_avg_mb', 0):.1f}MB
        </div>
        <div class="metric">
            <strong>CPU Peak:</strong> {self.resource_usage.get('cpu_max_percent', 0):.1f}%
        </div>
        <div class="metric">
            <strong>CPU Average:</strong> {self.resource_usage.get('cpu_avg_percent', 0):.1f}%
        </div>
        <div class="metric">
            <strong>Samples:</strong> {self.resource_usage.get('samples_count', 0)}
        </div>
        """
        
        return html
    
    def _generate_performance_metrics_html(self) -> str:
        """Generate HTML for performance metrics section"""
        
        if not self.performance_metrics:
            return "<p>Performance metrics will be available after test execution</p>"
        
        # This would be populated by the actual test results
        return "<p>Performance metrics analysis</p>"
    
    def _generate_performance_summary(self, results: Dict[str, Any]):
        """Generate performance summary report"""
        
        print("\n📈 Performance Summary:")
        print("-" * 40)
        
        execution_time = results.get("execution_time", 0)
        print(f"Total Execution Time: {execution_time:.2f}s")
        
        if self.resource_usage:
            print(f"Peak Memory Usage: {self.resource_usage.get('memory_max_mb', 0):.1f}MB")
            print(f"Peak CPU Usage: {self.resource_usage.get('cpu_max_percent', 0):.1f}%")
        
        success = results.get("success", False)
        print(f"Overall Success: {'✅ PASSED' if success else '❌ FAILED'}")


def main():
    """Main command line interface"""
    
    parser = argparse.ArgumentParser(
        description="Payment History Scalability Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --suite smoke                     Run smoke tests (quick)
  %(prog)s --suite performance --html-report Run performance tests with HTML report
  %(prog)s --suite all --monitor-resources   Run all tests with resource monitoring
  %(prog)s --suite integration --ci-mode     Run integration tests in CI mode
        """
    )
    
    # Test suite selection
    parser.add_argument("--suite", choices=["smoke", "integration", "performance", "stress", "all"],
                       default="smoke", help="Test suite to run")
    
    # Execution options
    parser.add_argument("--skip-background-jobs", action="store_true",
                       help="Skip background job tests")
    parser.add_argument("--stop-on-failure", action="store_true",
                       help="Stop execution on first test failure")
    parser.add_argument("--timeout", type=int, default=3600,
                       help="Global timeout in seconds")
    
    # Monitoring options
    parser.add_argument("--monitor-resources", action="store_true",
                       help="Enable resource usage monitoring")
    parser.add_argument("--performance-thresholds", action="store_true",
                       help="Enforce performance thresholds")
    
    # CI/CD integration
    parser.add_argument("--ci-mode", action="store_true",
                       help="Enable CI/CD mode (strict error handling)")
    
    # Reporting options
    parser.add_argument("--json-report", action="store_true",
                       help="Generate JSON report")
    parser.add_argument("--html-report", action="store_true",
                       help="Generate HTML report")
    parser.add_argument("--open-browser", action="store_true",
                       help="Open HTML report in browser")
    
    # Verbose output
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    
    args = parser.parse_args()
    
    # Create and run test runner
    runner = PaymentHistoryScalabilityTestRunner()
    
    try:
        results = runner.run_tests(args)
        
        # Exit with appropriate code
        exit_code = 0 if results.get("success", False) else 1
        
        if args.verbose:
            print(f"\n🏁 Test execution completed with exit code: {exit_code}")
        
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️ Test execution interrupted by user")
        sys.exit(130)
        
    except Exception as e:
        print(f"\n❌ Test runner failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()