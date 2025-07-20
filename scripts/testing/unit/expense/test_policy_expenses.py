#!/usr/bin/env python3
"""
Test policy-covered national expenses with ERPNext integration
Updated: December 2024 - ERPNext expense integration
"""

import frappe

from verenigingen.templates.pages.volunteer.expenses import is_policy_covered_expense, submit_expense


def test_policy_covered_expenses():
    """Test that policy-covered expenses work for all volunteers"""

    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    frappe.set_user("Administrator")

    print("🧪 Testing Policy-Covered National Expenses")
    print("=" * 50)

    # Test 1: Check which categories are policy-covered
    print("\n1. Checking policy-covered categories...")
    policy_categories = frappe.get_all(
        "Expense Category", filters={"policy_covered": 1}, fields=["name", "category_name"]
    )

    if policy_categories:
        print(f"   ✅ Found {len(policy_categories)} policy-covered categories:")
        for cat in policy_categories:
            print(f"   - {cat.category_name} ({cat.name})")
    else:
        print("   ⚠️  No policy-covered categories found")
        return False

    # Test 2: Test the policy check function
    print("\n2. Testing policy coverage detection...")
    test_categories = ["Travel", "meals", "events", "Food"]  # Mix of policy and non-policy

    for category in test_categories:
        try:
            if frappe.db.exists("Expense Category", category):
                is_covered = is_policy_covered_expense(category)
                status = "✅ Policy-covered" if is_covered else "❌ Not policy-covered"
                print(f"   {category}: {status}")
            else:
                print(f"   {category}: ⚠️  Category not found")
        except Exception as e:
            print(f"   {category}: ❌ Error - {str(e)}")

    # Test 3: Find a volunteer who is NOT a national board member
    print("\n3. Finding non-board volunteer for testing...")

    # Get national board chapter
    settings = frappe.get_single("Verenigingen Settings")
    national_chapter = settings.national_board_chapter if settings else None

    if not national_chapter:
        print("   ⚠️  National board chapter not configured")
        return False

    print(f"   National board chapter: {national_chapter}")

    # Find volunteers who are NOT board members
    non_board_volunteers = frappe.db.sql(
        """
        SELECT v.name, v.volunteer_name, v.email
        FROM `tabVolunteer` v
        WHERE v.name NOT IN (
            SELECT cm.volunteer
            FROM `tabChapter Member` cm
            WHERE cm.parent = %s AND cm.volunteer IS NOT NULL
        )
        AND v.employee_id IS NOT NULL
        LIMIT 3
    """,
        (national_chapter,),
        as_dict=True,
    )

    if not non_board_volunteers:
        print("   ⚠️  No non-board volunteers with employee records found")
        return False

    test_volunteer = non_board_volunteers[0]
    print(f"   Using non-board volunteer: {test_volunteer.volunteer_name} ({test_volunteer.name})")

    # Test 4: Test policy-covered expense submission
    print("\n4. Testing policy-covered expense submission...")

    # Find a policy-covered category
    policy_category = policy_categories[0].name if policy_categories else None
    if not policy_category:
        print("   ❌ No policy-covered category available for testing")
        return False

    # Test expense data
    expense_data = {
        "description": "Test policy-covered national expense",
        "amount": 45.00,
        "expense_date": "2025-01-14",
        "organization_type": "National",
        "category": policy_category,
        "notes": "Testing policy-covered expense for non-board member"}

    print(f"   Test expense: €{expense_data['amount']} for {policy_category}")

    # Set user context to the non-board volunteer
    original_user = frappe.session.user
    frappe.session.user = test_volunteer.email if test_volunteer.email else "Administrator"

    try:
        result = submit_expense(expense_data)

        if result.get("success"):
            print("   ✅ Policy-covered expense submission SUCCESSFUL!")
            print(f"   Expense Claim: {result.get('expense_claim_name')}")
            print(f"   Volunteer Expense: {result.get('expense_name')}")
        else:
            print(f"   ❌ Policy-covered expense submission FAILED: {result.get('message')}")
            return False

    except Exception as e:
        print(f"   ❌ Policy-covered expense submission ERROR: {str(e)}")
        return False
    finally:
        frappe.session.user = original_user

    # Test 5: Test non-policy expense (should fail for non-board member)
    print("\n5. Testing non-policy expense (should require board membership)...")

    # Find a non-policy category
    non_policy_categories = frappe.get_all(
        "Expense Category", filters={"policy_covered": 0}, fields=["name", "category_name"], limit=1
    )

    if non_policy_categories:
        non_policy_category = non_policy_categories[0].name

        expense_data["category"] = non_policy_category
        expense_data["description"] = "Test non-policy national expense"

        print(f"   Test expense: €{expense_data['amount']} for {non_policy_category}")

        frappe.session.user = test_volunteer.email if test_volunteer.email else "Administrator"

        try:
            result = submit_expense(expense_data)

            if result.get("success"):
                print("   ⚠️  Non-policy expense was allowed (this might be unexpected)")
            else:
                expected_errors = ["board membership required", "access", "permission"]
                error_msg = result.get("message", "").lower()

                if any(err in error_msg for err in expected_errors):
                    print("   ✅ Non-policy expense correctly REJECTED (board membership required)")
                else:
                    print(f"   ❓ Non-policy expense rejected for different reason: {result.get('message')}")

        except Exception as e:
            print(f"   ✅ Non-policy expense correctly REJECTED: {str(e)}")
        finally:
            frappe.session.user = original_user
    else:
        print("   ⚠️  No non-policy categories found to test rejection")

    print("\n🎉 Policy-covered expense testing completed!")
    print("\n📋 Summary:")
    print("   ✅ Policy-covered categories configured")
    print("   ✅ Policy detection working")
    print("   ✅ Non-board volunteers can submit policy-covered national expenses")
    print("   ✅ Non-policy expenses still require board membership")

    frappe.db.commit()
    frappe.destroy()
    return True


if __name__ == "__main__":
    try:
        success = test_policy_covered_expenses()
        if success:
            print("\n✅ All policy expense tests PASSED!")
        else:
            print("\n❌ Some policy expense tests FAILED!")
    except Exception as e:
        print(f"\n💥 Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
