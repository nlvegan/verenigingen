#!/usr/bin/env python3
"""
Run expense form tests - standalone version
"""

import json
import os

import frappe
from frappe.utils import now_datetime


def test_expense_form_complete():
    """Run complete expense form test"""

    print("🚀 EXPENSE FORM TEST SUITE")
    print("=" * 60)

    # Initialize frappe context
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    results = {"total_tests": 0, "passed": 0, "failed": 0, "details": []}

    # Test 1: Get volunteer expense context
    print("\n1. Testing get_volunteer_expense_context API")
    try:
        response = frappe.call(
            "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expense_context"
        )
        results["total_tests"] += 1

        if response and "message" in response:
            data = response["message"]
            if data.get("success"):
                print("✅ PASS: API returns successful response")
                print(f"   User chapters: {len(data.get('user_chapters', []))}")
                print(f"   User teams: {len(data.get('user_teams', []))}")
                print(f"   Expense categories: {len(data.get('expense_categories', []))}")
                results["passed"] += 1
                results["details"].append("✅ get_volunteer_expense_context: PASS")
            else:
                print("❌ FAIL: API returns failure response")
                print(f"   Error: {data.get('error', 'Unknown error')}")
                results["failed"] += 1
                results["details"].append("❌ get_volunteer_expense_context: FAIL")
        else:
            print("❌ FAIL: Invalid response format")
            results["failed"] += 1
            results["details"].append("❌ get_volunteer_expense_context: FAIL - Invalid response")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ get_volunteer_expense_context: FAIL - {e}")

    # Test 2: Submit multiple expenses (with mock data)
    print("\n2. Testing submit_multiple_expenses API")
    try:
        mock_expenses = [
            {
                "description": "Test expense 1",
                "amount": 25.50,
                "expense_date": "2025-01-10",
                "organization_type": "National",
                "category": "Travel",
                "chapter": None,
                "team": None,
                "notes": "Test expense for API validation",
                "receipt_attachment": None,
            }
        ]

        response = frappe.call(
            "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses", expenses=mock_expenses
        )
        results["total_tests"] += 1

        if response and "message" in response:
            data = response["message"]
            if data.get("success"):
                print("✅ PASS: Multiple expenses submitted successfully")
                print(f"   Created count: {data.get('created_count', 0)}")
                print(f"   Total amount: €{data.get('total_amount', 0)}")
                results["passed"] += 1
                results["details"].append("✅ submit_multiple_expenses: PASS")
            else:
                print("❌ FAIL: Failed to submit expenses")
                print(f"   Error: {data.get('error', 'Unknown error')}")
                results["failed"] += 1
                results["details"].append("❌ submit_multiple_expenses: FAIL")
        else:
            print("❌ FAIL: Invalid response format")
            results["failed"] += 1
            results["details"].append("❌ submit_multiple_expenses: FAIL - Invalid response")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ submit_multiple_expenses: FAIL - {e}")

    # Test 3: Check file existence
    print("\n3. Testing file existence")
    files_to_check = [
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/expense_claim_new.html",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/public/js/expense_claim_form.vue",
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/templates/pages/volunteer/expenses.py",
    ]

    for file_path in files_to_check:
        results["total_tests"] += 1
        if os.path.exists(file_path):
            print(f"✅ PASS: {os.path.basename(file_path)} exists")
            results["passed"] += 1
            results["details"].append(f"✅ {os.path.basename(file_path)}: PASS")
        else:
            print(f"❌ FAIL: {os.path.basename(file_path)} missing")
            results["failed"] += 1
            results["details"].append(f"❌ {os.path.basename(file_path)}: FAIL")

    # Test 4: Test form validation with invalid data
    print("\n4. Testing form validation with invalid data")
    try:
        invalid_expenses = [
            {
                "description": "",  # Empty description
                "amount": 0,  # Zero amount
                "expense_date": "",  # Empty date
                "organization_type": "",
                "category": "",
                "chapter": None,
                "team": None,
                "notes": "",
                "receipt_attachment": None,
            }
        ]

        response = frappe.call(
            "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
            expenses=invalid_expenses,
        )
        results["total_tests"] += 1

        if response and "message" in response:
            data = response["message"]
            if not data.get("success"):
                print("✅ PASS: Form validation correctly rejects invalid data")
                print(f"   Error: {data.get('error', 'Validation error')}")
                results["passed"] += 1
                results["details"].append("✅ Form validation: PASS")
            else:
                print("❌ FAIL: Form validation should reject invalid data")
                results["failed"] += 1
                results["details"].append("❌ Form validation: FAIL")
        else:
            print("❌ FAIL: Invalid response format")
            results["failed"] += 1
            results["details"].append("❌ Form validation: FAIL - Invalid response")
    except Exception as e:
        print(f"❌ FAIL: Exception occurred: {e}")
        results["failed"] += 1
        results["details"].append(f"❌ Form validation: FAIL - {e}")

    # Print summary
    print("\n" + "=" * 50)
    print("📊 EXPENSE FORM TEST SUMMARY")
    print("=" * 50)
    print(f"Total Tests: {results['total_tests']}")
    print(f"Passed: {results['passed']}")
    print(f"Failed: {results['failed']}")

    if results["total_tests"] > 0:
        success_rate = results["passed"] / results["total_tests"] * 100
        print(f"Success Rate: {success_rate:.1f}%")

    print("\n📋 DETAILED RESULTS:")
    for detail in results["details"]:
        print(f"  {detail}")

    if results["failed"] == 0:
        print("\n🎉 ALL TESTS PASSED! Expense form is working correctly.")
    else:
        print(f"\n⚠️  {results['failed']} tests failed. Review the failures above.")

    print(f"\nTest completed at: {now_datetime()}")
    return results


if __name__ == "__main__":
    test_expense_form_complete()
