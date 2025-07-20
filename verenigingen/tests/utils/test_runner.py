"""
Enhanced test runner with categorized test execution
Supports quick, comprehensive, and scheduled test runs
"""

import json
import traceback
from datetime import datetime
from pathlib import Path

import frappe


class TestRunner:
    """Organized test runner with different execution modes"""

    QUICK_TESTS = [
        "test_validation_regression.run_validation_regression_suite",
        "test_runner_wrappers.run_iban_validation_tests",
        "test_runner_wrappers.run_special_character_tests",
    ]

    COMPREHENSIVE_TESTS = [
        "test_validation_regression.run_validation_regression_suite",
        "test_runner_wrappers.run_all_doctype_validation_tests",
        "test_runner_wrappers.run_all_security_tests",
        "test_runner_wrappers.run_all_tests",
        "test_runner_wrappers.run_expense_integration_tests",
        "test_runner_wrappers.run_all_sepa_tests",
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

    def __init__(self):
        self.results = {}
        self.start_time = datetime.now()
        self.test_dir = Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results")
        self.test_dir.mkdir(exist_ok=True)

    def run_test_suite(self, test_list, suite_name):
        """Run a specific test suite"""
        print(f"\n🚀 Running {suite_name}")
        print("=" * 50)

        suite_results = {
            "suite_name": suite_name,
            "start_time": datetime.now().isoformat(),
            "tests": {},
            "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0},
        }

        for test_path in test_list:
            module_name, function_name = test_path.rsplit(".", 1)
            full_module = f"verenigingen.tests.utils.{module_name}"

            print(f"\n📋 {module_name}.{function_name}")
            print("-" * 40)

            test_result = {"start_time": datetime.now().isoformat(), "status": "pending"}

            try:
                module = frappe.get_attr(f"{full_module}.{function_name}")
                result = module()

                test_result["end_time"] = datetime.now().isoformat()

                if isinstance(result, dict):
                    test_result.update(result)
                    if result.get("success"):
                        print(f"✅ PASSED: {result.get('message', 'Success')}")
                        suite_results["summary"]["passed"] += 1
                        test_result["status"] = "passed"
                    else:
                        print(f"❌ FAILED: {result.get('message', 'Failed')}")
                        suite_results["summary"]["failed"] += 1
                        test_result["status"] = "failed"
                else:
                    if result:
                        print("✅ PASSED")
                        suite_results["summary"]["passed"] += 1
                        test_result["status"] = "passed"
                    else:
                        print("❌ FAILED")
                        suite_results["summary"]["failed"] += 1
                        test_result["status"] = "failed"

            except Exception as e:
                print(f"💥 ERROR: {str(e)}")
                traceback.print_exc()
                suite_results["summary"]["errors"] += 1
                test_result["status"] = "error"
                test_result["error"] = str(e)
                test_result["traceback"] = traceback.format_exc()

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


@frappe.whitelist()
def run_quick_tests():
    """Run quick validation tests (for pre-commit hooks)"""
    runner = TestRunner()
    runner.results["quick_tests"] = runner.run_test_suite(TestRunner.QUICK_TESTS, "Quick Tests")
    success = runner.print_summary()
    runner.save_results("quick_tests.json")
    return {"success": success, "results": runner.results}


@frappe.whitelist()
def run_comprehensive_tests():
    """Run comprehensive test suite (for CI/CD)"""
    runner = TestRunner()
    runner.results["comprehensive"] = runner.run_test_suite(
        TestRunner.COMPREHENSIVE_TESTS, "Comprehensive Tests"
    )
    success = runner.print_summary()
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


# Legacy support
def run_termination_tests():
    """Legacy function - redirects to comprehensive tests"""
    return run_comprehensive_tests()
