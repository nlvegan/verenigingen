#!/usr/bin/env python3
"""
Simple ERPNext Integration Test - to be run via bench console
"""


def test_basic_integration():
    """Test basic ERPNext integration components"""
    import frappe
    from frappe.utils import today

    print("Testing ERPNext Expense Claims Integration...")

    # Test 1: Check if ERPNext app is available
    try:
        apps = frappe.get_installed_apps()
        if "erpnext" in apps:
            print("✅ ERPNext app is installed")
        else:
            print("❌ ERPNext app not found")
            return False
    except Exception as e:
        print(f"❌ Error checking apps: {str(e)}")
        return False

    # Test 2: Check if Cost Center doctype exists
    try:
        if frappe.db.exists("DocType", "Cost Center"):
            print("✅ Cost Center doctype exists")
        else:
            print("❌ Cost Center doctype not found")
    except Exception as e:
        print(f"❌ Error checking Cost Center: {str(e)}")

    # Test 3: Check if Expense Claim doctype exists
    try:
        if frappe.db.exists("DocType", "Expense Claim"):
            print("✅ Expense Claim doctype exists")
        else:
            print("❌ Expense Claim doctype not found")
    except Exception as e:
        print(f"❌ Error checking Expense Claim: {str(e)}")

    # Test 4: Check if Employee doctype exists
    try:
        if frappe.db.exists("DocType", "Employee"):
            print("✅ Employee doctype exists")
        else:
            print("❌ Employee doctype not found")
    except Exception as e:
        print(f"❌ Error checking Employee: {str(e)}")

    # Test 5: Test expense submission function import
    try:
        from verenigingen.templates.pages.volunteer.expenses import get_expense_statistics, submit_expense

        print("✅ Expense functions import successfully")
    except Exception as e:
        print(f"❌ Error importing expense functions: {str(e)}")

    # Test 6: Test cost center functions
    try:
        from verenigingen.templates.pages.volunteer.expenses import get_organization_cost_center

        print("✅ Cost center functions import successfully")
    except Exception as e:
        print(f"❌ Error importing cost center functions: {str(e)}")

    # Test 7: Check if we have test data
    try:
        volunteer_count = frappe.db.count("Volunteer")
        member_count = frappe.db.count("Member")
        chapter_count = frappe.db.count("Chapter")

        print(f"📊 Data available:")
        print(f"   - Volunteers: {volunteer_count}")
        print(f"   - Members: {member_count}")
        print(f"   - Chapters: {chapter_count}")

        if volunteer_count > 0 and member_count > 0:
            print("✅ Test data available")
        else:
            print("⚠️ Limited test data available")

    except Exception as e:
        print(f"❌ Error checking test data: {str(e)}")

    print("\nBasic integration test completed.")
    return True


if __name__ == "__main__":
    test_basic_integration()
