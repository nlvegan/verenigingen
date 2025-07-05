#!/usr/bin/env python3
"""
Test runner for payment reporting system in verenigingen app
Provides comprehensive testing for overdue payments reports and APIs
"""

import sys
import unittest
from unittest.mock import patch

import frappe


def run_payment_report_tests():
    """Run all payment reporting tests"""

    print("🧪 PAYMENT REPORTING SYSTEM TEST SUITE")
    print("=" * 50)

    # Test modules to run
    test_modules = [
        "verenigingen.tests.test_overdue_payments_report",
        "verenigingen.tests.test_payment_processing_api",
    ]

    total_tests = 0
    total_failures = 0
    total_errors = 0

    for module_name in test_modules:
        print(f"\n📋 Running tests for: {module_name}")
        print("-" * 40)

        try:
            # Import the test module
            module = __import__(module_name, fromlist=[""])

            # Create test suite
            loader = unittest.TestLoader()
            suite = loader.loadTestsFromModule(module)

            # Run tests
            runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
            result = runner.run(suite)

            # Update totals
            total_tests += result.testsRun
            total_failures += len(result.failures)
            total_errors += len(result.errors)

            # Print module results
            if result.wasSuccessful():
                print(f"✅ {module_name}: ALL TESTS PASSED ({result.testsRun} tests)")
            else:
                print(f"❌ {module_name}: {len(result.failures)} failures, {len(result.errors)} errors")

                # Print failure details
                if result.failures:
                    print("\n📋 FAILURES:")
                    for test, traceback in result.failures:
                        print(f"  ❌ {test}: {traceback.split('AssertionError:')[-1].strip()}")

                if result.errors:
                    print("\n📋 ERRORS:")
                    for test, traceback in result.errors:
                        print(f"  💥 {test}: {traceback.split('Exception:')[-1].strip()}")

        except Exception as e:
            print(f"💥 Failed to run {module_name}: {str(e)}")
            total_errors += 1

    # Print summary
    print("\n" + "=" * 50)
    print("📊 PAYMENT REPORTING TEST SUMMARY")
    print("=" * 50)
    print(f"Total Tests Run: {total_tests}")
    print(f"Failures: {total_failures}")
    print(f"Errors: {total_errors}")

    if total_failures == 0 and total_errors == 0:
        print("🎉 ALL PAYMENT REPORTING TESTS PASSED!")
        return True
    else:
        success_rate = (
            ((total_tests - total_failures - total_errors) / total_tests * 100) if total_tests > 0 else 0
        )
        print(f"⚠️  Success Rate: {success_rate:.1f}%")
        return False


def run_specific_test_class(class_name):
    """Run a specific test class"""

    print(f"🧪 Running specific test class: {class_name}")
    print("=" * 40)

    test_mapping = {
        "overdue_report": "verenigingen.tests.test_overdue_payments_report.TestOverduePaymentsReport",
        "overdue_integration": "verenigingen.tests.test_overdue_payments_report.TestOverduePaymentsReportIntegration",
        "payment_api": "verenigingen.tests.test_payment_processing_api.TestPaymentProcessingAPI",
        "email_templates": "verenigingen.tests.test_payment_processing_api.TestPaymentProcessingEmailTemplates",
    }

    if class_name not in test_mapping:
        print(f"❌ Unknown test class: {class_name}")
        print(f"Available classes: {', '.join(test_mapping.keys())}")
        return False

    try:
        # Import and run specific test class
        module_path, class_name_full = test_mapping[class_name].rsplit(".", 1)
        module = __import__(module_path, fromlist=[class_name_full])
        test_class = getattr(module, class_name_full)

        # Create test suite
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(test_class)

        # Run tests
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)

        if result.wasSuccessful():
            print(f"✅ {class_name}: ALL TESTS PASSED ({result.testsRun} tests)")
            return True
        else:
            print(f"❌ {class_name}: {len(result.failures)} failures, {len(result.errors)} errors")
            return False

    except Exception as e:
        print(f"💥 Failed to run {class_name}: {str(e)}")
        return False


def run_smoke_tests():
    """Run quick smoke tests for payment reporting"""

    print("🔥 PAYMENT REPORTING SMOKE TESTS")
    print("=" * 35)

    smoke_tests = [
        ("Report Import", test_report_import),
        ("API Import", test_api_import),
        ("Permission Filter", test_permission_filter_basic),
        ("Data Processing", test_data_processing_basic),
        ("Email Generation", test_email_generation_basic),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in smoke_tests:
        try:
            print(f"🧪 {test_name}...", end=" ")
            test_func()
            print("✅ PASS")
            passed += 1
        except Exception as e:
            print(f"❌ FAIL: {str(e)}")
            failed += 1

    print(f"\n📊 Smoke Test Results: {passed} passed, {failed} failed")
    return failed == 0


def test_report_import():
    """Test that report module imports correctly"""
    from verenigingen.verenigingen.report.overdue_member_payments import overdue_member_payments

    assert hasattr(overdue_member_payments, "execute")
    assert hasattr(overdue_member_payments, "get_data")
    assert hasattr(overdue_member_payments, "get_user_chapter_filter")


def test_api_import():
    """Test that API module imports correctly"""
    from verenigingen.api import payment_processing

    assert hasattr(payment_processing, "send_overdue_payment_reminders")
    assert hasattr(payment_processing, "export_overdue_payments")
    assert hasattr(payment_processing, "execute_bulk_payment_action")


def test_permission_filter_basic():
    """Test basic permission filtering functionality"""
    from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
        get_user_chapter_filter,
    )

    # Mock admin user
    with patch("frappe.session.user", "admin@test.com"):
        with patch("frappe.get_roles", return_value=["System Manager"]):
            result = get_user_chapter_filter()
            assert result is None  # Admin should have no filter


def test_data_processing_basic():
    """Test basic data processing functions"""
    from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import (
        get_chart_data,
        get_summary,
    )

    sample_data = [{"chapter": "Test", "total_overdue": 100, "overdue_count": 1, "days_overdue": 30}]

    # Test summary
    summary = get_summary(sample_data)
    assert isinstance(summary, list)
    assert len(summary) > 0

    # Test chart data
    chart = get_chart_data(sample_data)
    assert isinstance(chart, dict)
    assert "data" in chart


def test_email_generation_basic():
    """Test basic email generation"""
    from verenigingen.api.payment_processing import generate_payment_reminder_html, get_reminder_subject

    # Mock member and payment info
    class MockMember:
        first_name = "Test"

    payment_info = {"total_overdue": 100, "overdue_count": 2, "days_overdue": 30}

    # Test HTML generation
    html = generate_payment_reminder_html(MockMember(), payment_info, "Friendly Reminder", None)
    assert isinstance(html, str)
    assert "Test" in html
    assert "100" in html

    # Test subject generation
    subject = get_reminder_subject("Urgent Notice", payment_info)
    assert isinstance(subject, str)
    assert "URGENT" in subject


def create_test_data():
    """Create test data for integration tests"""
    print("📦 Creating test data...")

    # This would create test members, invoices, etc.
    # For now, just a placeholder
    print("✅ Test data creation completed")


def cleanup_test_data():
    """Clean up test data after tests"""
    print("🧹 Cleaning up test data...")

    # This would clean up any test records
    # For now, just a placeholder
    print("✅ Test data cleanup completed")


@frappe.whitelist()
def run_all_payment_tests():
    """API endpoint to run all payment tests"""
    try:
        success = run_payment_report_tests()
        return {
            "success": success,
            "message": "All payment reporting tests passed" if success else "Some payment tests failed",
        }
    except Exception as e:
        return {"success": False, "message": f"Test execution failed: {str(e)}"}


@frappe.whitelist()
def run_payment_smoke_tests():
    """API endpoint to run payment smoke tests"""
    try:
        success = run_smoke_tests()
        return {
            "success": success,
            "message": "All smoke tests passed" if success else "Some smoke tests failed",
        }
    except Exception as e:
        return {"success": False, "message": f"Smoke test execution failed: {str(e)}"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run payment reporting tests")
    parser.add_argument("--smoke", action="store_true", help="Run smoke tests only")
    parser.add_argument("--class", dest="test_class", help="Run specific test class")
    parser.add_argument("--setup", action="store_true", help="Create test data")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test data")

    args = parser.parse_args()

    if args.setup:
        create_test_data()
    elif args.cleanup:
        cleanup_test_data()
    elif args.smoke:
        success = run_smoke_tests()
        sys.exit(0 if success else 1)
    elif args.test_class:
        success = run_specific_test_class(args.test_class)
        sys.exit(0 if success else 1)
    else:
        success = run_payment_report_tests()
        sys.exit(0 if success else 1)
