#!/usr/bin/env python3
"""
Test expense form with Foppe de Haan's account
"""

import json

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def test_expense_form_with_foppe():
    """Test expense form APIs with Foppe de Haan's account"""

    print("🚀 TESTING EXPENSE FORM WITH FOPPE DE HAAN")
    print("=" * 60)

    # Check if Foppe exists
    foppe_member = frappe.db.get_value(
        "Member", {"email": "foppe@veganisme.org"}, ["name", "first_name", "last_name"], as_dict=True
    )

    if not foppe_member:
        print("❌ Foppe de Haan not found in Member records")
        return {"success": False, "error": "Foppe de Haan not found"}

    print(f"✅ Found Foppe: {foppe_member.first_name} {foppe_member.last_name}")

    # Check if Foppe has a volunteer record
    foppe_volunteer = frappe.db.get_value(
        "Volunteer", {"member": foppe_member.name}, ["name", "volunteer_name", "email"], as_dict=True
    )

    if not foppe_volunteer:
        print("❌ No volunteer record found for Foppe")
        # Create volunteer record for Foppe
        try:
            volunteer_doc = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"{foppe_member.first_name} {foppe_member.last_name}",
                    "email": "foppe@veganisme.org",
                    "member": foppe_member.name,
                    "status": "Active",
                    "start_date": frappe.utils.today()}
            )
            volunteer_doc.insert(ignore_permissions=True)
            foppe_volunteer = {
                "name": volunteer_doc.name,
                "volunteer_name": volunteer_doc.volunteer_name,
                "email": volunteer_doc.email}
            print(f"✅ Created volunteer record for Foppe: {foppe_volunteer['name']}")
        except Exception as e:
            print(f"❌ Failed to create volunteer record: {e}")
            return {"success": False, "error": f"Failed to create volunteer: {e}"}
    else:
        print(f"✅ Found volunteer record: {foppe_volunteer.volunteer_name}")

    # Store original user
    original_user = frappe.session.user

    try:
        # Switch to Foppe's session
        frappe.session.user = "foppe@veganisme.org"
        print(f"🔄 Switched to user: {frappe.session.user}")

        # Test 1: Get volunteer expense context
        print("\n1. Testing get_volunteer_expense_context with Foppe")
        try:
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expense_context"
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: API returns successful response")
                    print(f"   Volunteer: {response.get('volunteer')}")
                    print(f"   User chapters: {len(response.get('user_chapters', []))}")
                    print(f"   User teams: {len(response.get('user_teams', []))}")
                    print(f"   Expense categories: {len(response.get('expense_categories', []))}")
                    context_success = True
                else:
                    print("❌ FAIL: API returns failure response")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    context_success = False
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                context_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            context_success = False

        # Test 2: Submit multiple expenses with Foppe
        print("\n2. Testing submit_multiple_expenses with Foppe")
        try:
            test_expenses = [
                {
                    "description": "Test expense - Office supplies",
                    "amount": 25.50,
                    "expense_date": "2025-01-10",
                    "organization_type": "National",
                    "category": "Office Supplies",
                    "chapter": None,
                    "team": None,
                    "notes": "Test expense submission via API",
                    "receipt_attachment": None}
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=test_expenses,
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: Expenses submitted successfully")
                    print(f"   Created count: {response.get('created_count', 0)}")
                    print(f"   Total amount: €{response.get('total_amount', 0)}")
                    submit_success = True
                else:
                    print("❌ FAIL: Failed to submit expenses")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    submit_success = False
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                submit_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            submit_success = False

        # Test 3: Test validation with invalid data
        print("\n3. Testing form validation with invalid data")
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
                    "receipt_attachment": None}
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=invalid_expenses,
            )

            if response and isinstance(response, dict):
                if not response.get("success"):
                    print("✅ PASS: Form validation correctly rejects invalid data")
                    print(f"   Error: {response.get('message', 'Validation error')}")
                    validation_success = True
                else:
                    print("❌ FAIL: Form validation should reject invalid data")
                    validation_success = False
            else:
                print("❌ FAIL: Invalid response format")
                validation_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            validation_success = False

    finally:
        # Restore original user
        frappe.session.user = original_user
        print(f"🔄 Restored user: {frappe.session.user}")

    # Summary
    print("\n" + "=" * 50)
    print("📊 EXPENSE FORM TEST SUMMARY (FOPPE)")
    print("=" * 50)

    tests_passed = sum([context_success, submit_success, validation_success])
    total_tests = 3

    print(f"Tests Passed: {tests_passed}/{total_tests}")

    if tests_passed == total_tests:
        print("🎉 ALL TESTS PASSED! Expense form works with Foppe's account.")
        success = True
    else:
        print("⚠️  Some tests failed. Check the details above.")
        success = False

    print(f"Test completed at: {now_datetime()}")

    return {
        "success": success,
        "tests_passed": tests_passed,
        "total_tests": total_tests,
        "foppe_member": foppe_member.name if foppe_member else None,
        "foppe_volunteer": foppe_volunteer["name"] if foppe_volunteer else None}


if __name__ == "__main__":
    test_expense_form_with_foppe()
