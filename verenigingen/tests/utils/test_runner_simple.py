"""
Simplified test runner for Verenigingen tests
"""

import json
from datetime import datetime
from pathlib import Path

import frappe

# Direct function mappings
TEST_FUNCTIONS = {
    "quick": [
        "verenigingen.tests.backend.validation.test_validation_regression.run_validation_regression_suite",
        "verenigingen.tests.utils.test_runner_wrappers.run_iban_validation_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_special_character_tests",
    ],
    "comprehensive": [
        "verenigingen.tests.backend.validation.test_validation_regression.run_validation_regression_suite",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_doctype_validation_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_security_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_expense_integration_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_sepa_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_portal_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_all_termination_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_workflow_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_transition_tests",
    ],
    "scheduled": [
        "verenigingen.tests.utils.test_runner_wrappers.run_performance_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_payment_failure_tests",
        "verenigingen.tests.utils.test_runner_wrappers.run_financial_tests",
    ]}


def run_test_suite(test_category, suite_name):
    """Run a specific test suite"""
    print(f"\n🚀 Running {suite_name}")
    print("=" * 50)

    start_time = datetime.now()
    results = {
        "suite_name": suite_name,
        "start_time": start_time.isoformat(),
        "tests": {},
        "summary": {"total": 0, "passed": 0, "failed": 0, "errors": 0}}

    test_list = TEST_FUNCTIONS.get(test_category, [])

    for test_function in test_list:
        print(f"\n📋 {test_function.split('.')[-1]}")
        print("-" * 40)

        test_result = {"start_time": datetime.now().isoformat(), "status": "pending"}

        try:
            # Use frappe.get_attr to get the function
            func = frappe.get_attr(test_function)
            result = func()

            test_result["end_time"] = datetime.now().isoformat()

            if isinstance(result, dict):
                test_result.update(result)
                if result.get("success"):
                    print(f"✅ PASSED: {result.get('message', 'Success')}")
                    results["summary"]["passed"] += 1
                    test_result["status"] = "passed"
                else:
                    print(f"❌ FAILED: {result.get('message', 'Failed')}")
                    results["summary"]["failed"] += 1
                    test_result["status"] = "failed"
            else:
                if result:
                    print("✅ PASSED")
                    results["summary"]["passed"] += 1
                    test_result["status"] = "passed"
                else:
                    print("❌ FAILED")
                    results["summary"]["failed"] += 1
                    test_result["status"] = "failed"

        except Exception as e:
            print(f"💥 ERROR: {str(e)}")
            results["summary"]["errors"] += 1
            test_result["status"] = "error"
            test_result["error"] = str(e)
            import traceback

            test_result["traceback"] = traceback.format_exc()

        results["tests"][test_function] = test_result
        results["summary"]["total"] += 1

    results["end_time"] = datetime.now().isoformat()
    results["duration"] = str(datetime.now() - start_time)

    # Save results
    test_dir = Path("/home/frappe/frappe-bench/sites/dev.veganisme.net/test-results")
    test_dir.mkdir(exist_ok=True)

    with open(test_dir / f"{test_category}_tests.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("📊 TEST EXECUTION SUMMARY")
    print("=" * 70)
    print(f"Total Tests: {results['summary']['total']}")
    print(
        f"Passed: {results['summary']['passed']} ({results['summary']['passed'] / results['summary']['total'] * 100:.1f}%)"
    )
    print(f"Failed: {results['summary']['failed']}")
    print(f"Errors: {results['summary']['errors']}")
    print(f"Duration: {results['duration']}")
    print("=" * 70)

    success = not results["summary"]["failed"] and not results["summary"]["errors"]
    return {"success": success, "results": results}


@frappe.whitelist()
def run_quick_tests():
    """Run quick validation tests"""
    return run_test_suite("quick", "Quick Tests")


@frappe.whitelist()
def run_comprehensive_tests():
    """Run comprehensive test suite"""
    return run_test_suite("comprehensive", "Comprehensive Tests")


@frappe.whitelist()
def run_scheduled_tests():
    """Run scheduled/nightly tests"""
    return run_test_suite("scheduled", "Scheduled Tests")


@frappe.whitelist()
def run_all_tests():
    """Run all test suites"""
    all_results = {}
    all_results["quick"] = run_test_suite("quick", "Quick Tests")["results"]
    all_results["comprehensive"] = run_test_suite("comprehensive", "Comprehensive Tests")["results"]
    all_results["scheduled"] = run_test_suite("scheduled", "Scheduled Tests")["results"]

    # Calculate overall summary
    total_tests = sum(r["summary"]["total"] for r in all_results.values())
    total_passed = sum(r["summary"]["passed"] for r in all_results.values())
    total_failed = sum(r["summary"]["failed"] for r in all_results.values())
    total_errors = sum(r["summary"]["errors"] for r in all_results.values())

    print("\n" + "=" * 70)
    print("📊 OVERALL TEST SUMMARY")
    print("=" * 70)
    print(f"Total Test Suites: {len(all_results)}")
    print(f"Total Tests: {total_tests}")
    print(f"Total Passed: {total_passed}")
    print(f"Total Failed: {total_failed}")
    print(f"Total Errors: {total_errors}")
    print("=" * 70)

    success = not total_failed and not total_errors
    return {"success": success, "results": all_results}
