#!/usr/bin/env python3
"""
Test ERPNext Expense Claims functionality after account setup
"""

import sys

import frappe
from frappe.utils import now, today


def test_expense_claim_types_setup():
    """Test that Expense Claim Types are properly configured"""
    print("🔍 Testing Expense Claim Types setup...")

    try:
        # Check if Expense Claim Type doctype exists
        if not frappe.db.exists("DocType", "Expense Claim Type"):
            print("❌ Expense Claim Type doctype not available")
            return False

        # Get default expense claim types
        expense_types = frappe.get_all("Expense Claim Type", fields=["name", "default_account"], limit=5)

        if not expense_types:
            print("⚠️  No Expense Claim Types found - creating default types")
            return create_default_expense_types()
        else:
            print(f"✅ Found {len(expense_types)} Expense Claim Types")

            # Check if they have default accounts
            types_with_accounts = [t for t in expense_types if t.default_account]
            if types_with_accounts:
                print(f"✅ {len(types_with_accounts)} types have default accounts configured")
                return True
            else:
                print("⚠️  Expense Claim Types found but no default accounts configured")
                return False

    except Exception as e:
        print(f"❌ Error checking Expense Claim Types: {str(e)}")
        return False


def create_default_expense_types():
    """Create default expense claim types if none exist"""
    try:
        default_types = [
            "Travel",
            "Meals",
            "Accommodation",
            "Office Supplies",
            "Communications",
            "Marketing",
            "Training",
        ]

        created_count = 0
        for expense_type in default_types:
            if not frappe.db.exists("Expense Claim Type", expense_type):
                expense_type_doc = frappe.get_doc(
                    {"doctype": "Expense Claim Type", "expense_type": expense_type, "name": expense_type}
                )
                expense_type_doc.insert(ignore_permissions=True)
                created_count += 1
                print(f"   ✅ Created Expense Claim Type: {expense_type}")

        if created_count > 0:
            print(f"✅ Created {created_count} default Expense Claim Types")
            frappe.db.commit()
            return True
        else:
            print("✅ All default Expense Claim Types already exist")
            return True

    except Exception as e:
        print(f"❌ Error creating default Expense Claim Types: {str(e)}")
        return False


def test_volunteer_expense_submission():
    """Test volunteer expense submission workflow"""
    print("\n🔍 Testing volunteer expense submission...")

    try:
        # Find a test volunteer
        volunteers = frappe.get_all(
            "Volunteer", filters={"member": ["!=", ""]}, fields=["name", "volunteer_name", "member"], limit=1
        )

        if not volunteers:
            print("❌ No volunteers found for testing")
            return False

        test_volunteer = volunteers[0]
        print(f"   🎯 Using volunteer: {test_volunteer.volunteer_name}")

        # Get or create employee record for volunteer
        volunteer_doc = frappe.get_doc("Volunteer", test_volunteer.name)

        if not volunteer_doc.employee_id:
            print("   🔧 Creating employee record for volunteer...")
            try:
                volunteer_doc.create_minimal_employee()
                volunteer_doc.save(ignore_permissions=True)
                frappe.db.commit()
                print(f"   ✅ Created employee: {volunteer_doc.employee_id}")
            except Exception as e:
                print(f"   ❌ Failed to create employee: {str(e)}")
                return False
        else:
            print(f"   ✅ Volunteer has employee record: {volunteer_doc.employee_id}")

        # Test expense submission
        expense_data = {
            "expense_date": today(),
            "description": "Test expense for ERPNext integration",
            "amount": 25.50,
            "expense_type": "Travel",
            "notes": "Testing expense submission after account setup"}

        print("   💰 Submitting test expense...")

        # Import the expense submission function
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Mock the session user to be the volunteer's member
        member_email = frappe.db.get_value("Member", volunteer_doc.member, "email_address")
        if member_email:
            original_user = frappe.session.user
            frappe.set_user(member_email)

            try:
                result = submit_expense(volunteer_name=test_volunteer.name, expense_data=expense_data)

                if result.get("success"):
                    print(f"   ✅ Expense submitted successfully!")
                    print(f"   📄 Volunteer Expense: {result.get('volunteer_expense_id')}")
                    print(f"   💼 ERPNext Expense Claim: {result.get('erpnext_expense_claim_id')}")
                    return True
                else:
                    print(f"   ❌ Expense submission failed: {result.get('message')}")
                    return False

            finally:
                frappe.set_user(original_user)
        else:
            print("   ❌ No email found for member - cannot test submission")
            return False

    except Exception as e:
        print(f"❌ Error testing expense submission: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_expense_claim_creation():
    """Test direct ERPNext Expense Claim creation"""
    print("\n🔍 Testing direct ERPNext Expense Claim creation...")

    try:
        # Find an employee to test with
        employees = frappe.get_all("Employee", fields=["name", "employee_name"], limit=1)

        if not employees:
            print("❌ No employees found for testing")
            return False

        test_employee = employees[0]
        print(f"   👤 Using employee: {test_employee.employee_name}")

        # Get default company
        default_company = frappe.defaults.get_defaults().get("company")
        if not default_company:
            companies = frappe.get_all("Company", limit=1)
            if companies:
                default_company = companies[0].name
            else:
                print("❌ No company found")
                return False

        print(f"   🏢 Using company: {default_company}")

        # Create a test expense claim
        expense_claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": test_employee.name,
                "posting_date": today(),
                "company": default_company,
                "title": "Test ERPNext Integration",
                "remark": "Testing direct expense claim creation",
                "status": "Draft"}
        )

        expense_claim.insert(ignore_permissions=True)
        print(f"   ✅ Created Expense Claim: {expense_claim.name}")

        # Clean up the test expense claim
        frappe.delete_doc("Expense Claim", expense_claim.name, ignore_permissions=True)
        print("   🧹 Cleaned up test expense claim")

        return True

    except Exception as e:
        print(f"❌ Error testing Expense Claim creation: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_expense_accounts_setup():
    """Test that expense accounts are properly configured"""
    print("\n🔍 Testing expense accounts setup...")

    try:
        # Check for expense accounts
        expense_accounts = frappe.get_all(
            "Account",
            filters={"account_type": "Expense Account", "is_group": 0},
            fields=["name", "account_name"],
            limit=10,
        )

        if expense_accounts:
            print(f"   ✅ Found {len(expense_accounts)} expense accounts")
            for account in expense_accounts[:3]:  # Show first 3
                print(f"      • {account.account_name}")
            if len(expense_accounts) > 3:
                print(f"      ... and {len(expense_accounts) - 3} more")
            return True
        else:
            print("   ❌ No expense accounts found")
            return False

    except Exception as e:
        print(f"❌ Error checking expense accounts: {str(e)}")
        return False


def run_expense_functionality_tests():
    """Run all expense functionality tests"""
    print("🧪 Testing ERPNext Expense Functionality")
    print("=" * 50)

    frappe.set_user("Administrator")

    tests = [
        ("Expense Claim Types Setup", test_expense_claim_types_setup),
        ("Expense Accounts Setup", test_expense_accounts_setup),
        ("Direct Expense Claim Creation", test_expense_claim_creation),
        ("Volunteer Expense Submission", test_volunteer_expense_submission),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        print(f"\n🔬 {test_name}")
        print("-" * 40)

        try:
            if test_func():
                passed += 1
                print(f"✅ {test_name}: PASSED")
            else:
                failed += 1
                print(f"❌ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            print(f"💥 {test_name}: ERROR - {str(e)}")

    print(f"\n📊 Test Results")
    print("=" * 30)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"📈 Success Rate: {(passed/(passed+failed)*100):.1f}%")

    if failed == 0:
        print("\n🎉 All expense functionality tests passed!")
        print("💡 ERPNext Expense Claims integration is working correctly")
        return True
    else:
        print(f"\n⚠️  {failed} tests failed - please review the issues above")
        return False


if __name__ == "__main__":
    try:
        success = run_expense_functionality_tests()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n💥 Fatal error: {str(e)}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
