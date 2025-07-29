"""
Master Test Runner for All Workflow Tests
Executes all phases of the comprehensive test coverage improvements:
Phase 1: Critical Business Workflows
Phase 2: Integration Testing
Phase 3: Advanced Security and Performance
"""

import sys
import time
from datetime import datetime

# Import all test runners
from test_member_lifecycle_complete import run_member_lifecycle_tests
from test_financial_workflows_complete import run_financial_workflow_tests
from test_sepa_processing_pipeline import run_sepa_pipeline_tests
from test_erpnext_integration_comprehensive import run_erpnext_integration_tests
from test_communication_system_integration import run_communication_system_tests
from test_portal_functionality_integration import run_portal_functionality_tests
from test_security_comprehensive_advanced import run_security_comprehensive_tests
from test_performance_comprehensive import run_performance_comprehensive_tests
from test_regression_infrastructure import run_regression_infrastructure_tests


def run_phase_1_tests():
    """Run Phase 1: Critical Business Workflow Tests"""
    print("\n" + "="*80)
    print("🚀 PHASE 1: CRITICAL BUSINESS WORKFLOW TESTS")
    print("="*80)

    phase_1_results = []

    # Test 1: Member Lifecycle
    print("\n📋 Running Member Lifecycle Tests...")
    start_time = time.time()
    result = run_member_lifecycle_tests()
    duration = time.time() - start_time
    phase_1_results.append(("Member Lifecycle", result, duration))

    # Test 2: Financial Workflows
    print("\n💰 Running Financial Workflow Tests...")
    start_time = time.time()
    result = run_financial_workflow_tests()
    duration = time.time() - start_time
    phase_1_results.append(("Financial Workflows", result, duration))

    # Test 3: SEPA Processing Pipeline
    print("\n🏦 Running SEPA Processing Pipeline Tests...")
    start_time = time.time()
    result = run_sepa_pipeline_tests()
    duration = time.time() - start_time
    phase_1_results.append(("SEPA Processing", result, duration))

    return phase_1_results


def run_phase_2_tests():
    """Run Phase 2: Comprehensive Integration Testing"""
    print("\n" + "="*80)
    print("🔗 PHASE 2: COMPREHENSIVE INTEGRATION TESTING")
    print("="*80)

    phase_2_results = []

    # Test 1: ERPNext Integration
    print("\n🏢 Running ERPNext Integration Tests...")
    start_time = time.time()
    result = run_erpnext_integration_tests()
    duration = time.time() - start_time
    phase_2_results.append(("ERPNext Integration", result, duration))

    # Test 2: Communication System Integration
    print("\n📧 Running Communication System Tests...")
    start_time = time.time()
    result = run_communication_system_tests()
    duration = time.time() - start_time
    phase_2_results.append(("Communication System", result, duration))

    # Test 3: Portal Functionality Integration
    print("\n🌐 Running Portal Functionality Tests...")
    start_time = time.time()
    result = run_portal_functionality_tests()
    duration = time.time() - start_time
    phase_2_results.append(("Portal Functionality", result, duration))

    return phase_2_results


def run_phase_3_tests():
    """Run Phase 3: Advanced Security and Performance Testing"""
    print("\n" + "="*80)
    print("🛡️ PHASE 3: ADVANCED SECURITY AND PERFORMANCE TESTING")
    print("="*80)

    phase_3_results = []

    # Test 1: Advanced Security
    print("\n🔒 Running Advanced Security Tests...")
    start_time = time.time()
    result = run_security_comprehensive_tests()
    duration = time.time() - start_time
    phase_3_results.append(("Advanced Security", result, duration))

    # Test 2: Performance and Load Testing
    print("\n⚡ Running Performance Tests...")
    start_time = time.time()
    result = run_performance_comprehensive_tests()
    duration = time.time() - start_time
    phase_3_results.append(("Performance Testing", result, duration))

    # Test 3: Regression Infrastructure
    print("\n🔄 Running Regression Infrastructure Tests...")
    start_time = time.time()
    result = run_regression_infrastructure_tests()
    duration = time.time() - start_time
    phase_3_results.append(("Regression Infrastructure", result, duration))

    return phase_3_results


def print_phase_summary(phase_name, results):
    """Print summary for a test phase"""
    print(f"\n📊 {phase_name} SUMMARY:")
    print("-" * 60)

    total_tests = len(results)
    passed_tests = sum(1 for _, result, _ in results if result)
    failed_tests = total_tests - passed_tests
    total_duration = sum(duration for _, _, duration in results)

    for test_name, result, duration in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {test_name:<30} {status:<10} ({duration:.1f}s)")

    print("-" * 60)
    print(f"  Total: {total_tests} | Passed: {passed_tests} | Failed: {failed_tests} | Duration: {total_duration:.1f}s")

    return passed_tests, failed_tests, total_duration


def print_final_summary(all_results):
    """Print final test execution summary"""
    print("\n" + "="*80)
    print("🎯 FINAL TEST EXECUTION SUMMARY")
    print("="*80)

    grand_total_tests = 0
    grand_total_passed = 0
    grand_total_failed = 0
    grand_total_duration = 0

    for phase_name, results in all_results:
        passed, failed, duration = print_phase_summary(phase_name, results)
        grand_total_tests += len(results)
        grand_total_passed += passed
        grand_total_failed += failed
        grand_total_duration += duration

    print("\n" + "="*80)
    print("🏆 GRAND TOTALS:")
    print(f"   Total Test Suites: {grand_total_tests}")
    print(f"   Passed: {grand_total_passed}")
    print(f"   Failed: {grand_total_failed}")
    print(f"   Success Rate: {grand_total_passed/grand_total_tests*100:.1f}%")
    print(f"   Total Duration: {grand_total_duration:.1f}s ({grand_total_duration/60:.1f} minutes)")
    print("="*80)

    return grand_total_failed == 0


def main():
    """Main test execution function"""
    print("🧪 VERENIGINGEN COMPREHENSIVE TEST SUITE")
    print("📅 Started at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("🔬 Testing all critical business workflows, integrations, and performance")

    overall_start_time = time.time()
    all_results = []

    try:
        # Phase 1: Critical Business Workflows
        phase_1_results = run_phase_1_tests()
        all_results.append(("PHASE 1: CRITICAL BUSINESS WORKFLOWS", phase_1_results))

        # Phase 2: Integration Testing
        phase_2_results = run_phase_2_tests()
        all_results.append(("PHASE 2: INTEGRATION TESTING", phase_2_results))

        # Phase 3: Advanced Security and Performance
        phase_3_results = run_phase_3_tests()
        all_results.append(("PHASE 3: SECURITY & PERFORMANCE", phase_3_results))

        # Print final summary
        overall_success = print_final_summary(all_results)

        overall_duration = time.time() - overall_start_time
        print(f"\n⏱️ Overall execution time: {overall_duration:.1f}s ({overall_duration/60:.1f} minutes)")
        print("🏁 Completed at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        if overall_success:
            print("\n🎉 ALL TESTS PASSED! The system is ready for production deployment.")
            return 0
        else:
            print("\n⚠️ SOME TESTS FAILED! Please review the failed tests before deployment.")
            return 1

    except KeyboardInterrupt:
        print("\n\n⚠️ Test execution interrupted by user")
        return 130
    except Exception as e:
        print(f"\n\n❌ Test execution failed with error: {e}")
        return 1


def run_specific_phase(phase_number):
    """Run a specific test phase"""
    if phase_number == 1:
        results = run_phase_1_tests()
        print_phase_summary("PHASE 1: CRITICAL BUSINESS WORKFLOWS", results)
    elif phase_number == 2:
        results = run_phase_2_tests()
        print_phase_summary("PHASE 2: INTEGRATION TESTING", results)
    elif phase_number == 3:
        results = run_phase_3_tests()
        print_phase_summary("PHASE 3: SECURITY & PERFORMANCE", results)
    else:
        print(f"❌ Invalid phase number: {phase_number}. Valid phases are 1, 2, or 3.")
        return 1

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            phase = int(sys.argv[1])
            exit_code = run_specific_phase(phase)
        except ValueError:
            print("❌ Invalid phase number. Usage: python run_all_workflow_tests.py [1|2|3]")
            exit_code = 1
    else:
        exit_code = main()

    sys.exit(exit_code)
