#!/usr/bin/env python3

import os
import sys

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_smoke_tests():
    """Run smoke tests to verify test infrastructure"""
    print("💨 Running Edge Case Smoke Tests...")

    # Quick validation that test modules load correctly
    test_modules = [
        "verenigingen.tests.test_comprehensive_edge_cases",
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


if __name__ == "__main__":
    success = run_smoke_tests()
    sys.exit(0 if success else 1)
