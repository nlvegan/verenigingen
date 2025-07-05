#!/usr/bin/env python3
"""
Final validation test for chapter membership fix - confirms Foppe can submit expenses to Zeist
"""

import frappe


def test_chapter_membership_final():
    """Final test to confirm chapter membership validation fix works"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("🎯 Final Chapter Membership Validation Test")
    print("=" * 60)

    try:
        # Test 1: Verify Foppe's volunteer record has member field
        print("\n1. Testing get_user_volunteer_record() function...")

        # Simulate session as Foppe
        original_user = frappe.session.user
        frappe.session.user = "test@example.com"

        from verenigingen.templates.pages.volunteer.expenses import get_user_volunteer_record

        volunteer_record = get_user_volunteer_record()

        if volunteer_record and volunteer_record.member:
            print(f"   ✅ Volunteer lookup returns member field: {volunteer_record.member}")
        else:
            print(f"   ❌ Volunteer lookup failed or missing member field")
            return False

        # Test 2: Test actual expense submission
        print("\n2. Testing expense submission for Zeist chapter...")

        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        expense_data = {
            "description": "Final test - Office supplies for Zeist chapter",
            "amount": 15.50,
            "expense_date": "2024-12-14",
            "organization_type": "Chapter",
            "chapter": "Zeist",
            "category": "Travel",
            "notes": "Final validation test for chapter membership fix",
        }

        result = submit_expense(expense_data)

        if result.get("success"):
            print(f"   ✅ Expense submission SUCCESSFUL")
            print(f"   Message: {result.get('message')}")
            print(f"   Expense Claim: {result.get('expense_claim_name')}")
        else:
            print(f"   ❌ Expense submission FAILED")
            print(f"   Error: {result.get('message')}")
            return False

        # Restore session
        frappe.session.user = original_user

        print(f"\n🎉 Chapter membership validation fix CONFIRMED WORKING!")
        print(f"✅ Foppe de Haan can now successfully submit expenses for Zeist chapter")
        print(f"✅ The issue was fixed by including 'member' field in get_user_volunteer_record()")

        return True

    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        frappe.destroy()


if __name__ == "__main__":
    success = test_chapter_membership_final()
    if success:
        print("\n✅ FINAL TEST PASSED - Chapter membership validation is working correctly!")
    else:
        print("\n❌ FINAL TEST FAILED - Issues remain with chapter membership validation")
