#!/usr/bin/env python3
"""
Test script for improved API error handling
Tests all the functions that were updated with structured error handling
"""

import json

import frappe
from frappe.utils import now_datetime


def test_improved_apis():
    """Test all the improved API functions"""

    print("🧪 Testing Improved API Error Handling")
    print("=" * 50)

    # Store test results
    results = {"total_tests": 0, "passed": 0, "failed": 0, "details": []}

    # Test 1: Suspension API - Invalid member
    print("\n1. Testing Suspension API - Invalid member")
    try:
        from verenigingen.api.suspension_api import suspend_member

        result = suspend_member("NON_EXISTENT_MEMBER", "Test suspension")
        results["total_tests"] += 1

        if isinstance(result, dict) and result.get("success") == False:
            print("✅ PASS: Returns structured error for non-existent member")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Suspension API - Invalid member: PASS")
        else:
            print("❌ FAIL: Should return structured error")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Suspension API - Invalid member: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Suspension API - Invalid member: FAIL - {e}")

    # Test 2: Suspension API - Missing reason
    print("\n2. Testing Suspension API - Missing reason")
    try:
        result = suspend_member("test-member", "")
        results["total_tests"] += 1

        if (
            isinstance(result, dict)
            and result.get("success") == False
            and "reason" in result.get("error", "").lower()
        ):
            print("✅ PASS: Returns structured error for missing reason")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Suspension API - Missing reason: PASS")
        else:
            print("❌ FAIL: Should return structured error for missing reason")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Suspension API - Missing reason: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Suspension API - Missing reason: FAIL - {e}")

    # Test 3: Termination API - Invalid member
    print("\n3. Testing Termination API - Invalid member")
    try:
        from verenigingen.api.termination_api import execute_safe_termination

        result = execute_safe_termination("NON_EXISTENT_MEMBER", "Voluntary")
        results["total_tests"] += 1

        if isinstance(result, dict) and result.get("success") == False:
            print("✅ PASS: Returns structured error for non-existent member")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Termination API - Invalid member: PASS")
        else:
            print("❌ FAIL: Should return structured error")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Termination API - Invalid member: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Termination API - Invalid member: FAIL - {e}")

    # Test 4: Termination API - Missing termination type
    print("\n4. Testing Termination API - Missing termination type")
    try:
        result = execute_safe_termination("test-member", "")
        results["total_tests"] += 1

        if (
            isinstance(result, dict)
            and result.get("success") == False
            and "termination type" in result.get("error", "").lower()
        ):
            print("✅ PASS: Returns structured error for missing termination type")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Termination API - Missing type: PASS")
        else:
            print("❌ FAIL: Should return structured error for missing termination type")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Termination API - Missing type: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Termination API - Missing type: FAIL - {e}")

    # Test 5: Membership Application Review API - Invalid member
    print("\n5. Testing Application Review API - Invalid member")
    try:
        from verenigingen.api.membership_application_review import approve_membership_application

        result = approve_membership_application("NON_EXISTENT_MEMBER")
        results["total_tests"] += 1

        if isinstance(result, dict) and result.get("success") == False:
            print("✅ PASS: Returns structured error for non-existent member")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Application Review API - Invalid member: PASS")
        else:
            print("❌ FAIL: Should return structured error")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Application Review API - Invalid member: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Application Review API - Invalid member: FAIL - {e}")

    # Test 6: Membership Application Review API - Missing reason for rejection
    print("\n6. Testing Application Review API - Missing rejection reason")
    try:
        from verenigingen.api.membership_application_review import reject_membership_application

        result = reject_membership_application("test-member", "")
        results["total_tests"] += 1

        if (
            isinstance(result, dict)
            and result.get("success") == False
            and "reason" in result.get("error", "").lower()
        ):
            print("✅ PASS: Returns structured error for missing reason")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Application Review API - Missing reason: PASS")
        else:
            print("❌ FAIL: Should return structured error for missing reason")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Application Review API - Missing reason: FAIL")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Application Review API - Missing reason: FAIL - {e}")

    # Test 7: DD Batch Scheduler API - Permission test
    print("\n7. Testing DD Batch Scheduler API - Without admin permissions")
    try:
        from verenigingen.api.dd_batch_scheduler import run_batch_creation_now

        # Temporarily change user to non-admin
        original_user = frappe.session.user
        frappe.session.user = "test@example.com"  # Non-admin user

        result = run_batch_creation_now()
        results["total_tests"] += 1

        # Restore original user
        frappe.session.user = original_user

        if (
            isinstance(result, dict)
            and result.get("success") == False
            and "permission" in result.get("error", "").lower()
        ):
            print("✅ PASS: Returns structured error for insufficient permissions")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ DD Batch Scheduler API - Permissions: PASS")
        else:
            print("❌ FAIL: Should return structured error for permissions")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ DD Batch Scheduler API - Permissions: FAIL")
    except Exception as e:
        # Restore original user in case of exception
        frappe.session.user = original_user
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ DD Batch Scheduler API - Permissions: FAIL - {e}")

    # Test 8: Application Statistics API - Permission test
    print("\n8. Testing Application Statistics API - Without admin permissions")
    try:
        from verenigingen.api.membership_application_review import get_application_stats

        # Temporarily change user to non-admin
        original_user = frappe.session.user
        frappe.session.user = "test@example.com"  # Non-admin user

        result = get_application_stats()
        results["total_tests"] += 1

        # Restore original user
        frappe.session.user = original_user

        if (
            isinstance(result, dict)
            and result.get("success") == False
            and "permission" in result.get("error", "").lower()
        ):
            print("✅ PASS: Returns structured error for insufficient permissions")
            print(f"   Response: {result}")
            results["passed"] += 1
            results["details"].append("✅ Application Statistics API - Permissions: PASS")
        else:
            print("❌ FAIL: Should return structured error for permissions")
            print(f"   Got: {result}")
            results["failed"] += 1
            results["details"].append("❌ Application Statistics API - Permissions: FAIL")
    except Exception as e:
        # Restore original user in case of exception
        frappe.session.user = original_user
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Application Statistics API - Permissions: FAIL - {e}")

    # Test 9: Check response structure consistency
    print("\n9. Testing Response Structure Consistency")
    try:
        # Test multiple functions to ensure consistent response structure
        test_functions = [
            ("suspension_api", "suspend_member", ["", "test"]),
            ("termination_api", "execute_safe_termination", ["", "test"]),
            ("membership_application_review", "approve_membership_application", [""]),
            ("membership_application_review", "reject_membership_application", ["", ""]),
        ]

        consistent_structure = True
        for module, func_name, args in test_functions:
            try:
                module_obj = frappe.get_module(f"verenigingen.api.{module}")
                func = getattr(module_obj, func_name)
                result = func(*args)

                if not isinstance(result, dict):
                    print(f"❌ {func_name}: Not returning dict")
                    consistent_structure = False
                    continue

                if "success" not in result:
                    print(f"❌ {func_name}: Missing 'success' field")
                    consistent_structure = False
                    continue

                if result.get("success") == False and "error" not in result:
                    print(f"❌ {func_name}: Missing 'error' field for failed response")
                    consistent_structure = False
                    continue

            except Exception as e:
                print(f"❌ {func_name}: Exception during structure test: {e}")
                consistent_structure = False

        results["total_tests"] += 1
        if consistent_structure:
            print("✅ PASS: All functions return consistent response structure")
            results["passed"] += 1
            results["details"].append("✅ Response Structure Consistency: PASS")
        else:
            print("❌ FAIL: Inconsistent response structure found")
            results["failed"] += 1
            results["details"].append("❌ Response Structure Consistency: FAIL")

    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Response Structure Consistency: FAIL - {e}")

    # Print summary
    print("\n" + "=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    print(f"Total Tests: {results['total_tests']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")
    print(f"Success Rate: {(results['passed'] / results['total_tests'] * 100):.1f}%")

    print("\n📋 DETAILED RESULTS:")
    for detail in results["details"]:
        print(f"  {detail}")

    if results["failed"] == 0:
        print("\n🎉 ALL TESTS PASSED! Error handling improvements are working correctly.")
    else:
        print(f"\n⚠️  {results['failed']} tests failed. Review the failures above.")

    print(f"\nTest completed at: {now_datetime()}")
    return results


if __name__ == "__main__":
    test_improved_apis()
