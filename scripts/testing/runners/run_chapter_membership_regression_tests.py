#!/usr/bin/env python3
"""
Test runner specifically for chapter membership validation regression tests
"""

import os
import sys
import unittest
from datetime import datetime

import frappe

# Add the app to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def run_chapter_membership_regression_tests():
    """Run all chapter membership validation regression tests"""

    print("🧪 Chapter Membership Validation Regression Test Suite")
    print("=" * 70)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Initialize Frappe
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")
    
    # Enable test mode and email mocking
    frappe.flags.in_test = True
    from verenigingen.tests.test_config import setup_global_test_config, enable_test_email_mocking
    setup_global_test_config()
    enable_test_email_mocking()

    try:
        # Import test modules
        from verenigingen.tests.test_chapter_membership_validation_edge_cases import (
            TestChapterMembershipValidationEdgeCases,
        )
        from verenigingen.tests.test_get_user_volunteer_record_unit import TestGetUserVolunteerRecordUnit
        from verenigingen.tests.test_volunteer_expense_validation_regression import (
            TestVolunteerExpenseValidationRegression,
        )

        # Create test suite
        test_suite = unittest.TestSuite()

        # Add regression tests
        print("📋 Loading Regression Tests...")
        test_suite.addTest(
            unittest.TestLoader().loadTestsFromTestCase(TestVolunteerExpenseValidationRegression)
        )
        print("   ✅ Volunteer Expense Validation Regression Tests")

        # Add unit tests
        print("📋 Loading Unit Tests...")
        test_suite.addTest(unittest.TestLoader().loadTestsFromTestCase(TestGetUserVolunteerRecordUnit))
        print("   ✅ get_user_volunteer_record Unit Tests")

        # Add edge case tests
        print("📋 Loading Edge Case Tests...")
        test_suite.addTest(
            unittest.TestLoader().loadTestsFromTestCase(TestChapterMembershipValidationEdgeCases)
        )
        print("   ✅ Chapter Membership Validation Edge Case Tests")

        print(f"\n🚀 Running {test_suite.countTestCases()} tests...")
        print("-" * 70)

        # Run tests with detailed output
        runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout, buffer=True, failfast=False)

        result = runner.run(test_suite)

        # Print summary
        print("\n" + "=" * 70)
        print("📊 TEST SUMMARY")
        print("=" * 70)

        total_tests = result.testsRun
        failures = len(result.failures)
        errors = len(result.errors)
        skipped = len(result.skipped) if hasattr(result, "skipped") else 0
        success = total_tests - failures - errors - skipped

        print(f"Total Tests:    {total_tests}")
        print(f"✅ Passed:      {success}")
        print(f"❌ Failed:      {failures}")
        print(f"💥 Errors:      {errors}")
        print(f"⏭️  Skipped:     {skipped}")

        success_rate = (success / total_tests) * 100 if total_tests > 0 else 0
        print(f"📈 Success Rate: {success_rate:.1f}%")

        if result.wasSuccessful():
            print("\n🎉 ALL TESTS PASSED! Chapter membership validation is working correctly.")
            print("✅ The regression fix is confirmed and protected against future breaks.")
        else:
            print("\n⚠️  SOME TESTS FAILED! Chapter membership validation may have issues.")

            if result.failures:
                print("\n❌ FAILURES:")
                for test, traceback in result.failures:
                    # Fix f-string backslash issue by extracting the logic
                    if "AssertionError:" in traceback:
                        error_msg = traceback.split("AssertionError: ")[-1].split("\n")[0]
                    else:
                        error_msg = "Unknown failure"
                    print(f"   - {test}: {error_msg}")

            if result.errors:
                print("\n💥 ERRORS:")
                for test, traceback in result.errors:
                    # Fix f-string backslash issue by extracting the logic
                    if "\n" in traceback:
                        error_msg = traceback.split("\n")[-2]
                    else:
                        error_msg = traceback
                    print(f"   - {test}: {error_msg}")

        print(f"\nCompleted at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        return result.wasSuccessful()

    except Exception as e:
        print(f"\n💥 Test runner failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        frappe.destroy()


def run_quick_validation():
    """Run a quick validation test to check if the core fix is working"""
    print("⚡ Quick Validation Test")
    print("-" * 30)

    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        from unittest.mock import patch

        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        # Check if function includes member field
        with patch("frappe.session.user", "test@example.com"):
            with patch("frappe.db.get_value") as mock_get_value:
                mock_get_value.side_effect = [
                    "TEST-MEMBER",
                    frappe._dict({"name": "TEST-VOL", "volunteer_name": "Test", "member": "TEST-MEMBER"}),
                ]

                result = get_user_volunteer_record()

                # Check that the second call (volunteer lookup) included member field
                calls = mock_get_value.call_args_list
                if len(calls) >= 2:
                    volunteer_call = calls[1]
                    args = volunteer_call[0]
                    if len(args) > 2:
                        fields = args[2]
                        if "member" in fields:
                            print("✅ QUICK CHECK PASSED - get_user_volunteer_record includes member field")
                            return True
                        else:
                            print("❌ QUICK CHECK FAILED - member field missing from query")
                            return False

        print("⚠️  Quick check inconclusive")
        return None

    except Exception as e:
        print(f"❌ Quick check failed: {str(e)}")
        return False
    finally:
        frappe.destroy()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Chapter Membership Validation Regression Test Runner")
    parser.add_argument("--quick", action="store_true", help="Run quick validation check only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.quick:
        success = run_quick_validation()
        sys.exit(0 if success else 1)
    else:
        success = run_chapter_membership_regression_tests()
        sys.exit(0 if success else 1)
