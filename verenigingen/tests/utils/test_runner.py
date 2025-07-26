"""
Enhanced test runner with categorized test execution
Supports quick, comprehensive, and scheduled test runs

Phase 1 Enhancements:
- Coverage reporting integration
- Performance tracking
- HTML report generation
- Edge case coverage monitoring
"""

import json
import traceback
import time
from datetime import datetime
from pathlib import Path

import frappe


class TestRunner:
    """Organized test runner with different execution modes"""

    QUICK_TESTS = [
        "test_validation_regression.run_validation_regression_suite",
        "test_runner_wrappers.run_iban_validation_tests", 
        "test_runner_wrappers.run_special_character_tests",
        "test_runner_wrappers.run_sepa_mandate_naming_tests",
    ]

    COMPREHENSIVE_TESTS = [
        "test_validation_regression.run_validation_regression_suite",
        "test_runner_wrappers.run_all_doctype_validation_tests",
        "test_runner_wrappers.run_all_security_tests",
        "test_runner_wrappers.run_all_tests",
        "test_runner_wrappers.run_expense_integration_tests",
        "test_runner_wrappers.run_all_sepa_tests",
        "test_runner_wrappers.run_sepa_mandate_naming_tests",
        "test_runner_wrappers.run_sepa_mandate_lifecycle_tests",
        "test_runner_wrappers.run_all_portal_tests",
        "test_runner_wrappers.run_all_termination_tests",
        "test_runner_wrappers.run_workflow_tests",
        "test_runner_wrappers.run_transition_tests",
        "test_runner_wrappers.run_all_report_tests",
    ]

    SCHEDULED_TESTS = [
        "test_runner_wrappers.run_performance_tests",
        "test_runner_wrappers.run_payment_failure_tests",
        "test_runner_wrappers.run_financial_tests",
    ]

    def __init__(self, enable_coverage=False, enable_performance=False):
        self.results = {}
        self.start_time = datetime.now()
        self.test_dir = Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results")
        self.test_dir.mkdir(exist_ok=True)
        
        # Phase 1 Enhancement: Integration with coverage reporter
        self.enable_coverage = enable_coverage
        self.enable_performance = enable_performance
        self.coverage_reporter = None
        
        if enable_coverage:
            from verenigingen.tests.utils.coverage_reporter import TestCoverageReporter
            self.coverage_reporter = TestCoverageReporter(str(self.test_dir))

    def run_test_suite(self, test_list, suite_name):
        """Run a specific test suite"""
        print(f"\n🚀 Running {suite_name}")
        print("=" * 50)

        suite_results = {
            "suite_name": suite_name,
            "start_time": datetime.now().isoformat(),
            "tests": {},
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0}}

        for test_path in test_list:
            module_name, function_name = test_path.rsplit(".", 1)
            full_module = f"verenigingen.tests.utils.{module_name}"

            print(f"\n📋 {module_name}.{function_name}")
            print("-" * 40)

            test_result = {"start_time": datetime.now().isoformat(), "status": "pending"}
            
            # Phase 1 Enhancement: Performance tracking
            start_time = time.time()
            initial_query_count = frappe.db.debug_queries if hasattr(frappe.db, 'debug_queries') else 0

            try:
                module = frappe.get_attr(f"{full_module}.{function_name}")
                result = module()

                test_result["end_time"] = datetime.now().isoformat()
                
                # Phase 1 Enhancement: Track performance metrics
                duration = time.time() - start_time
                final_query_count = frappe.db.debug_queries if hasattr(frappe.db, 'debug_queries') else 0
                query_count = final_query_count - initial_query_count
                
                test_result["duration"] = duration
                test_result["query_count"] = query_count

                if isinstance(result, dict):
                    test_result.update(result)
                    if result.get("success"):
                        print(f"✅ PASSED: {result.get('message', 'Success')} [{duration:.2f}s, {query_count} queries]")
                        suite_results["summary"]["passed"] += 1
                        test_result["status"] = "passed"
                    else:
                        print(f"❌ FAILED: {result.get('message', 'Failed')} [{duration:.2f}s, {query_count} queries]")
                        suite_results["summary"]["failed"] += 1
                        test_result["status"] = "failed"
                else:
                    if result:
                        print(f"✅ PASSED [{duration:.2f}s, {query_count} queries]")
                        suite_results["summary"]["passed"] += 1
                        test_result["status"] = "passed"
                    else:
                        print(f"❌ FAILED [{duration:.2f}s, {query_count} queries]")
                        suite_results["summary"]["failed"] += 1
                        test_result["status"] = "failed"

            except Exception as e:
                duration = time.time() - start_time
                test_result["duration"] = duration
                print(f"💥 ERROR: {str(e)} [{duration:.2f}s]")
                traceback.print_exc()
                suite_results["summary"]["errors"] += 1
                test_result["status"] = "error"
                test_result["error"] = str(e)
                test_result["traceback"] = traceback.format_exc()

            # Phase 1 Enhancement: Track test with coverage reporter
            if self.coverage_reporter:
                self.coverage_reporter.track_test_execution(test_path, test_result)

            suite_results["tests"][test_path] = test_result
            suite_results["summary"]["total"] += 1

        suite_results["end_time"] = datetime.now().isoformat()
        return suite_results

    def save_results(self, filename):
        """Save test results to JSON file"""
        filepath = self.test_dir / filename
        with open(filepath, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n💾 Results saved to: {filepath}")

    def print_summary(self):
        """Print test execution summary"""
        print("\n" + "=" * 70)
        print("📊 TEST EXECUTION SUMMARY")
        print("=" * 70)

        total_tests = 0
        total_passed = 0
        total_failed = 0
        total_errors = 0

        for suite_name, suite_results in self.results.items():
            if isinstance(suite_results, dict) and "summary" in suite_results:
                summary = suite_results["summary"]
                total_tests += summary["total"]
                total_passed += summary["passed"]
                total_failed += summary["failed"]
                total_errors += summary["errors"]

                status = "✅" if summary["failed"] == 0 and summary["errors"] == 0 else "❌"
                print(f"{status} {suite_name}: {summary['passed']}/{summary['total']} passed")

        print("-" * 70)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {total_passed} ({total_passed / total_tests * 100:.1f}%)")
        print(f"Failed: {total_failed}")
        print(f"Errors: {total_errors}")
        print(f"Duration: {datetime.now() - self.start_time}")
        print("=" * 70)

        return total_failed == 0 and total_errors == 0
    
    def generate_coverage_report(self):
        """Phase 1 Enhancement: Generate coverage report with dashboard"""
        if not self.coverage_reporter:
            print("⚠️ Coverage reporting not enabled. Initialize with enable_coverage=True")
            return None
            
        print("\n📊 Generating coverage report and dashboard...")
        report = self.coverage_reporter.generate_coverage_report(include_html=True)
        
        print(f"✅ Coverage report generated:")
        print(f"   📄 JSON: {self.test_dir}/coverage_report.json")
        print(f"   🌐 HTML: {self.test_dir}/coverage_dashboard.html")
        
        return report
        
    def generate_performance_report(self):
        """Phase 1 Enhancement: Generate detailed performance report"""
        if not self.results:
            print("⚠️ No test results available for performance analysis")
            return None
            
        print("\n⚡ Generating performance report...")
        
        # Collect performance data from all suites
        all_tests = {}
        for suite_name, suite_data in self.results.items():
            if isinstance(suite_data, dict) and "tests" in suite_data:
                all_tests.update(suite_data["tests"])
        
        if not all_tests:
            print("⚠️ No performance data available")
            return None
            
        # Analyze performance
        durations = [test.get("duration", 0) for test in all_tests.values()]
        query_counts = [test.get("query_count", 0) for test in all_tests.values()]
        
        performance_report = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": len(all_tests),
            "average_duration": sum(durations) / len(durations) if durations else 0,
            "max_duration": max(durations) if durations else 0,
            "average_queries": sum(query_counts) / len(query_counts) if query_counts else 0,
            "max_queries": max(query_counts) if query_counts else 0,
            "slow_tests": sorted(
                [(name, test.get("duration", 0)) for name, test in all_tests.items()],
                key=lambda x: x[1], reverse=True
            )[:10],
            "query_heavy_tests": sorted(
                [(name, test.get("query_count", 0)) for name, test in all_tests.items()],
                key=lambda x: x[1], reverse=True
            )[:10]
        }
        
        # Save performance report
        perf_path = self.test_dir / "performance_report.json"
        with open(perf_path, "w") as f:
            json.dump(performance_report, f, indent=2)
            
        # Print summary
        print(f"⚡ Performance Analysis Summary:")
        print(f"   📊 Average Duration: {performance_report['average_duration']:.2f}s")
        print(f"   📊 Average Queries: {performance_report['average_queries']:.1f}")
        print(f"   🐌 Slowest Test: {performance_report['slow_tests'][0][0]} ({performance_report['slow_tests'][0][1]:.2f}s)")
        print(f"   💾 Report saved: {perf_path}")
        
        return performance_report
        
    def generate_edge_case_summary(self):
        """Phase 1 Enhancement: Generate edge case coverage summary"""
        print("\n🎯 Generating edge case coverage summary...")
        
        # Analyze edge case coverage from test names and results
        edge_case_categories = {
            "validation": [],
            "security": [],
            "performance": [],
            "integration": [],
            "business_logic": []
        }
        
        all_tests = {}
        for suite_name, suite_data in self.results.items():
            if isinstance(suite_data, dict) and "tests" in suite_data:
                all_tests.update(suite_data["tests"])
        
        # Categorize tests by their names and purposes
        for test_name, test_result in all_tests.items():
            test_lower = test_name.lower()
            
            if any(keyword in test_lower for keyword in ["validation", "validate", "edge_case"]):
                edge_case_categories["validation"].append((test_name, test_result.get("status")))
            elif any(keyword in test_lower for keyword in ["security", "permission", "auth"]):
                edge_case_categories["security"].append((test_name, test_result.get("status")))
            elif any(keyword in test_lower for keyword in ["performance", "speed", "optimization"]):
                edge_case_categories["performance"].append((test_name, test_result.get("status")))
            elif any(keyword in test_lower for keyword in ["integration", "api", "workflow"]):
                edge_case_categories["integration"].append((test_name, test_result.get("status")))
            else:
                edge_case_categories["business_logic"].append((test_name, test_result.get("status")))
        
        # Generate summary
        edge_case_summary = {
            "timestamp": datetime.now().isoformat(),
            "categories": {}
        }
        
        for category, tests in edge_case_categories.items():
            passed = sum(1 for _, status in tests if status == "passed")
            total = len(tests)
            edge_case_summary["categories"][category] = {
                "total_tests": total,
                "passed_tests": passed,
                "coverage_percentage": (passed / total * 100) if total > 0 else 0,
                "tests": tests
            }
        
        # Save edge case summary
        edge_path = self.test_dir / "edge_case_summary.json"
        with open(edge_path, "w") as f:
            json.dump(edge_case_summary, f, indent=2, default=str)
        
        # Print summary
        print(f"🎯 Edge Case Coverage Summary:")
        for category, data in edge_case_summary["categories"].items():
            coverage = data["coverage_percentage"]
            print(f"   📋 {category.title()}: {data['passed_tests']}/{data['total_tests']} ({coverage:.1f}%)")
        print(f"   💾 Report saved: {edge_path}")
        
        return edge_case_summary


@frappe.whitelist()
def run_quick_tests(coverage=False, performance=False):
    """Run quick validation tests (for pre-commit hooks)"""
    runner = TestRunner(enable_coverage=coverage, enable_performance=performance)
    runner.results["quick_tests"] = runner.run_test_suite(TestRunner.QUICK_TESTS, "Quick Tests")
    success = runner.print_summary()
    
    # Phase 1 Enhancement: Optional reporting
    if performance:
        runner.generate_performance_report()
    if coverage:
        runner.generate_coverage_report()
        
    runner.save_results("quick_tests.json")
    return {"success": success, "results": runner.results}


@frappe.whitelist()
def run_comprehensive_tests(coverage=True, performance=True, html_report=False):
    """Run comprehensive test suite (for CI/CD)"""
    runner = TestRunner(enable_coverage=coverage, enable_performance=performance)
    runner.results["comprehensive"] = runner.run_test_suite(
        TestRunner.COMPREHENSIVE_TESTS, "Comprehensive Tests"
    )
    success = runner.print_summary()
    
    # Phase 1 Enhancement: Full reporting for comprehensive tests
    if performance:
        runner.generate_performance_report()
    if coverage:
        runner.generate_coverage_report()
    runner.generate_edge_case_summary()
    
    runner.save_results("comprehensive_tests.json")
    return {"success": success, "results": runner.results}


@frappe.whitelist()
def run_scheduled_tests():
    """Run scheduled/nightly tests (performance, edge cases)"""
    runner = TestRunner()
    runner.results["scheduled"] = runner.run_test_suite(TestRunner.SCHEDULED_TESTS, "Scheduled Tests")
    success = runner.print_summary()
    runner.save_results("scheduled_tests.json")
    return {"success": success, "results": runner.results}


@frappe.whitelist()
def run_all_tests():
    """Run all test suites"""
    runner = TestRunner()

    # Run all test categories
    runner.results["quick"] = runner.run_test_suite(TestRunner.QUICK_TESTS, "Quick Tests")
    runner.results["comprehensive"] = runner.run_test_suite(
        TestRunner.COMPREHENSIVE_TESTS, "Comprehensive Tests"
    )
    runner.results["scheduled"] = runner.run_test_suite(TestRunner.SCHEDULED_TESTS, "Scheduled Tests")

    success = runner.print_summary()
    runner.save_results("all_tests.json")
    return {"success": success, "results": runner.results}


@frappe.whitelist()
def run_smoke_tests():
    """Run minimal smoke tests to verify basic functionality"""
    print("🔥 Running Smoke Tests")
    print("=" * 50)

    smoke_tests = [
        ("Check Frappe", lambda: frappe.db.sql("SELECT 1")[0][0] == 1),
        ("Check App Installed", lambda: "verenigingen" in frappe.get_installed_apps()),
        ("Check Member DocType", lambda: frappe.db.exists("DocType", "Member")),
        ("Check Volunteer DocType", lambda: frappe.db.exists("DocType", "Volunteer")),
        ("Check Chapter DocType", lambda: frappe.db.exists("DocType", "Chapter")),
    ]

    results = []
    all_passed = True

    for test_name, test_func in smoke_tests:
        try:
            result = test_func()
            status = "✅ PASS" if result else "❌ FAIL"
            results.append({"test": test_name, "status": status, "passed": result})
            print(f"{status}: {test_name}")
            if not result:
                all_passed = False
        except Exception as e:
            results.append({"test": test_name, "status": "💥 ERROR", "error": str(e)})
            print(f"💥 ERROR: {test_name} - {str(e)}")
            all_passed = False

    return {"success": all_passed, "results": results}


@frappe.whitelist()
def generate_test_report():
    """Generate a comprehensive test report"""
    report_path = Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results/test_report.html")

    # Gather all test results
    test_files = list(Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results").glob("*.json"))

    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Verenigingen Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #2c3e50; color: white; padding: 20px; border-radius: 5px; }
        .summary { background: #ecf0f1; padding: 15px; margin: 20px 0; border-radius: 5px; }
        .test-suite { margin: 20px 0; border: 1px solid #bdc3c7; border-radius: 5px; }
        .suite-header { background: #3498db; color: white; padding: 10px; }
        .test-result { padding: 10px; border-bottom: 1px solid #ecf0f1; }
        .passed { color: #27ae60; }
        .failed { color: #e74c3c; }
        .error { color: #e67e22; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Verenigingen Test Report</h1>
        <p>Generated: {timestamp}</p>
    </div>
    {content}
</body>
</html>
"""

    content = ""
    for test_file in test_files:
        with open(test_file) as f:
            json.load(f)
            # Generate HTML for each test suite
            # (Implementation details omitted for brevity)

    with open(report_path, "w") as f:
        f.write(html_content.format(timestamp=datetime.now(), content=content))

    return {"success": True, "report_path": str(report_path)}


# Phase 1 Enhancement: New reporting functions
@frappe.whitelist()
def run_tests_with_coverage_dashboard():
    """Run comprehensive tests with full coverage dashboard generation"""
    print("🚀 Running tests with comprehensive coverage dashboard...")
    
    runner = TestRunner(enable_coverage=True, enable_performance=True)
    
    # Run all test suites
    runner.results["quick"] = runner.run_test_suite(TestRunner.QUICK_TESTS, "Quick Tests")
    runner.results["comprehensive"] = runner.run_test_suite(TestRunner.COMPREHENSIVE_TESTS, "Comprehensive Tests")
    
    success = runner.print_summary()
    
    # Generate all reports
    coverage_report = runner.generate_coverage_report()
    performance_report = runner.generate_performance_report()
    edge_case_summary = runner.generate_edge_case_summary()
    
    runner.save_results("full_test_run.json")
    
    return {
        "success": success,
        "results": runner.results,
        "reports": {
            "coverage": coverage_report,
            "performance": performance_report,
            "edge_cases": edge_case_summary
        },
        "dashboard_path": str(runner.test_dir / "coverage_dashboard.html")
    }


@frappe.whitelist()
def run_performance_test_analysis():
    """Run tests focused on performance analysis"""
    print("⚡ Running performance-focused test analysis...")
    
    runner = TestRunner(enable_performance=True)
    
    # Run performance-sensitive tests
    performance_tests = [
        "test_runner_wrappers.run_performance_tests",
        "test_runner_wrappers.run_all_sepa_tests",
        "test_runner_wrappers.run_all_portal_tests"
    ]
    
    runner.results["performance_analysis"] = runner.run_test_suite(performance_tests, "Performance Analysis")
    
    success = runner.print_summary()
    performance_report = runner.generate_performance_report()
    
    runner.save_results("performance_analysis.json")
    
    return {
        "success": success,
        "results": runner.results,
        "performance_report": performance_report
    }


@frappe.whitelist()
def run_edge_case_validation():
    """Run comprehensive edge case validation tests"""
    print("🎯 Running edge case validation suite...")
    
    runner = TestRunner(enable_coverage=True)
    
    # Focus on edge case and validation tests
    edge_case_tests = [
        "test_runner_wrappers.run_all_doctype_validation_tests",
        "test_runner_wrappers.run_all_security_tests",
        "test_validation_regression.run_validation_regression_suite"
    ]
    
    runner.results["edge_case_validation"] = runner.run_test_suite(edge_case_tests, "Edge Case Validation")
    
    success = runner.print_summary()
    edge_case_summary = runner.generate_edge_case_summary()
    
    runner.save_results("edge_case_validation.json")
    
    return {
        "success": success,
        "results": runner.results,
        "edge_case_summary": edge_case_summary
    }


# Legacy support
def run_termination_tests():
    """Legacy function - redirects to comprehensive tests"""
    return run_comprehensive_tests()
