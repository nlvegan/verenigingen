"""
Comprehensive Edge Cases Test Runner
Orchestrates all edge case test suites for the Verenigingen app
"""

import sys
from datetime import datetime

import frappe


def run_all_edge_case_tests():
    """Run all edge case test suites"""
    print("🧪 COMPREHENSIVE EDGE CASE TEST RUNNER")
    print("=" * 50)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    test_suites = [
        ("Security Tests", "test_security_comprehensive", "run_security_tests"),
        ("Financial Edge Cases", "test_financial_integration_edge_cases", "run_financial_edge_case_tests"),
        ("SEPA Mandate Edge Cases", "test_sepa_mandate_edge_cases", "run_sepa_mandate_edge_case_tests"),
        ("Payment Failure Scenarios", "test_payment_failure_scenarios", "run_payment_failure_scenario_tests"),
        ("Member Status Transitions", "test_member_status_transitions", "run_member_status_transition_tests"),
        (
            "Termination Workflow Edge Cases",
            "test_termination_workflow_edge_cases",
            "run_termination_workflow_edge_case_tests",
        ),
        ("Performance Edge Cases", "test_performance_edge_cases", "run_performance_edge_case_tests"),
    ]

    results = {}
    total_passed = 0
    total_failed = 0

    for suite_name, module_name, function_name in test_suites:
        print(f"\n🔍 Running {suite_name}...")
        print("-" * 40)

        try:
            # Import the test module
            module = __import__(f"verenigingen.tests.{module_name}", fromlist=[function_name])
            test_function = getattr(module, function_name)

            # Run the test suite
            success = test_function()
            results[suite_name] = success

            if success:
                print(f"✅ {suite_name}: PASSED")
                total_passed += 1
            else:
                print(f"❌ {suite_name}: FAILED")
                total_failed += 1

        except Exception as e:
            print(f"💥 {suite_name}: ERROR - {str(e)}")
            results[suite_name] = False
            total_failed += 1

    # Summary
    print("\n" + "=" * 50)
    print("📊 COMPREHENSIVE TEST SUMMARY")
    print("=" * 50)

    for suite_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"  {suite_name:<30} {status}")

    print(f"\nTotal Results: {total_passed} PASSED, {total_failed} FAILED")
    print(f"Success Rate: {(total_passed / (total_passed + total_failed) * 100):.1f}%")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    return total_failed == 0


def run_security_only():
    """Run only security tests"""
    print("🔒 Running Security Tests Only...")

    try:
        from verenigingen.tests.test_security_comprehensive import run_security_tests

        return run_security_tests()
    except Exception as e:
        print(f"Error running security tests: {e}")
        return False


def run_financial_only():
    """Run only financial tests"""
    print("💰 Running Financial Tests Only...")

    try:
        from verenigingen.tests.test_financial_integration_edge_cases import run_financial_edge_case_tests
        from verenigingen.tests.test_payment_failure_scenarios import run_payment_failure_scenario_tests
        from verenigingen.tests.test_sepa_mandate_edge_cases import run_sepa_mandate_edge_case_tests

        results = []
        results.append(run_financial_edge_case_tests())
        results.append(run_sepa_mandate_edge_case_tests())
        results.append(run_payment_failure_scenario_tests())

        return all(results)

    except Exception as e:
        print(f"Error running financial tests: {e}")
        return False


def run_business_logic_only():
    """Run only business logic tests"""
    print("🔄 Running Business Logic Tests Only...")

    try:
        from verenigingen.tests.test_member_status_transitions import run_member_status_transition_tests
        from verenigingen.tests.test_termination_workflow_edge_cases import (
            run_termination_workflow_edge_case_tests,
        )

        results = []
        results.append(run_member_status_transition_tests())
        results.append(run_termination_workflow_edge_case_tests())

        return all(results)

    except Exception as e:
        print(f"Error running business logic tests: {e}")
        return False


def run_performance_only():
    """Run only performance tests"""
    print("🚀 Running Performance Tests Only...")

    try:
        from verenigingen.tests.test_performance_edge_cases import run_performance_edge_case_tests

        return run_performance_edge_case_tests()

    except Exception as e:
        print(f"Error running performance tests: {e}")
        return False


def run_environment_check():
    """Run environment validation"""
    print("🔍 Running Environment Validation...")

    try:
        from verenigingen.tests.test_environment_validator import validate_test_environment

        return validate_test_environment()

    except Exception as e:
        print(f"Error running environment check: {e}")
        return False


def run_smoke_edge_cases():
    """Run quick smoke tests for edge cases"""
    print("💨 Running Edge Case Smoke Tests...")

    # Quick validation that test modules load correctly
    test_modules = [
        "verenigingen.tests.test_security_comprehensive",
        "verenigingen.tests.test_financial_integration_edge_cases",
        "verenigingen.tests.test_sepa_mandate_edge_cases",
        "verenigingen.tests.test_payment_failure_scenarios",
        "verenigingen.tests.test_member_status_transitions",
        "verenigingen.tests.test_termination_workflow_edge_cases",
        "verenigingen.tests.test_performance_edge_cases",
        "verenigingen.tests.test_data_factory",
        "verenigingen.tests.test_environment_validator",
    ]

    success_count = 0

    for module_name in test_modules:
        try:
            __import__(module_name)
            print(f"✅ {module_name.split('.')[-1]} - OK")
            success_count += 1
        except Exception as e:
            print(f"❌ {module_name.split('.')[-1]} - ERROR: {e}")

    success_rate = (success_count / len(test_modules)) * 100
    print(f"\nSmoke Test Results: {success_count}/{len(test_modules)} ({success_rate:.1f}%)")

    return success_count == len(test_modules)


# API endpoints for integration with existing test infrastructure
@frappe.whitelist()
def api_run_edge_case_tests():
    """API endpoint to run edge case tests"""
    try:
        result = run_all_edge_case_tests()
        return {"success": True, "all_tests_passed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def api_run_security_tests():
    """API endpoint to run security tests only"""
    try:
        result = run_security_only()
        return {"success": True, "security_tests_passed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def api_run_financial_tests():
    """API endpoint to run financial tests only"""
    try:
        result = run_financial_only()
        return {"success": True, "financial_tests_passed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Additional API endpoints
@frappe.whitelist()
def api_run_business_logic_tests():
    """API endpoint to run business logic tests only"""
    try:
        result = run_business_logic_only()
        return {"success": True, "business_logic_tests_passed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def api_run_performance_tests():
    """API endpoint to run performance tests only"""
    try:
        result = run_performance_only()
        return {"success": True, "performance_tests_passed": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def api_run_environment_check():
    """API endpoint to run environment validation"""
    try:
        result = run_environment_check()
        return {"success": True, "environment_valid": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# Command line interface
def main():
    """Main CLI entry point"""
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()

        if test_type == "all":
            return run_all_edge_case_tests()
        elif test_type == "security":
            return run_security_only()
        elif test_type == "financial":
            return run_financial_only()
        elif test_type == "business":
            return run_business_logic_only()
        elif test_type == "performance":
            return run_performance_only()
        elif test_type == "environment":
            return run_environment_check()
        elif test_type == "smoke":
            return run_smoke_edge_cases()
        else:
            print(
                "Usage: python test_comprehensive_edge_cases.py [all|security|financial|business|performance|environment|smoke]"
            )
            print("  all         - Run all edge case test suites")
            print("  security    - Run security tests only")
            print("  financial   - Run financial edge case tests")
            print("  business    - Run business logic tests")
            print("  performance - Run performance tests")
            print("  environment - Validate test environment")
            print("  smoke       - Quick smoke tests")
            return False
    else:
        # Default to smoke tests
        return run_smoke_edge_cases()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
