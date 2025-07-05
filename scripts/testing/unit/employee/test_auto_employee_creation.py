#!/usr/bin/env python3
"""
Test automatic employee creation during expense submission
"""


def test_auto_employee_creation():
    """Test that employee records are created automatically during expense submission"""
    import frappe
    from frappe.utils import today

    print("Testing automatic employee creation during expense submission...")

    # Find a volunteer without employee_id
    volunteer = frappe.db.get_value(
        "Volunteer", {"employee_id": ["is", "not set"]}, ["name", "volunteer_name", "member"], as_dict=True
    )

    if not volunteer:
        print("❌ No volunteers without employee records found for testing")
        return False

    print(f"Testing with volunteer: {volunteer.volunteer_name}")

    # Check if volunteer has a member record (needed for employee creation)
    if not volunteer.member:
        print("❌ Volunteer has no linked member record, cannot test employee creation")
        return False

    # Get member for email context
    member = frappe.get_doc("Member", volunteer.member)
    if not member.email:
        print("❌ Member has no email, cannot test expense submission")
        return False

    # Test the create_minimal_employee function directly first
    volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

    try:
        print(f"Testing direct employee creation...")
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id:
            print(f"✅ Employee created successfully: {employee_id}")

            # Verify employee exists and has correct data
            if frappe.db.exists("Employee", employee_id):
                employee = frappe.get_doc("Employee", employee_id)
                print(f"✅ Employee verified:")
                print(f"   - Name: {employee.employee_name}")
                print(f"   - Company: {employee.company}")
                print(f"   - Status: {employee.status}")
                print(f"   - Employment Type: {getattr(employee, 'employment_type', 'Not set')}")

                # Check that volunteer now has the employee_id
                volunteer_doc.reload()
                if volunteer_doc.employee_id == employee_id:
                    print(f"✅ Volunteer now linked to employee: {volunteer_doc.employee_id}")
                    return True
                else:
                    print(f"❌ Volunteer not properly linked to employee")
                    return False
            else:
                print(f"❌ Employee {employee_id} not found in database")
                return False
        else:
            print("❌ Employee creation returned no ID")
            return False

    except Exception as e:
        print(f"❌ Error during employee creation test: {str(e)}")
        return False


def test_expense_submission_workflow():
    """Test the full expense submission workflow with auto employee creation"""
    import frappe
    from frappe.utils import today

    print("\nTesting full expense submission workflow...")

    # Find a volunteer without employee_id but with member record
    volunteer = frappe.db.get_value(
        "Volunteer",
        {"employee_id": ["is", "not set"], "member": ["is", "set"]},
        ["name", "volunteer_name", "member"],
        as_dict=True,
    )

    if not volunteer:
        print("❌ No suitable volunteer found for expense submission test")
        return False

    print(f"Testing expense submission for volunteer: {volunteer.volunteer_name}")

    # Get a valid chapter for the expense
    chapter = frappe.db.get_value("Chapter", {"status": "Active"}, "name")
    if not chapter:
        print("❌ No active chapter found for expense submission")
        return False

    # Get a valid expense category
    category = frappe.db.get_value("Expense Category", {}, "category_name")
    if not category:
        print("❌ No expense category found for expense submission")
        return False

    # Prepare test expense data
    expense_data = {
        "description": "Test Expense for Auto Employee Creation",
        "amount": 15.75,
        "expense_date": today(),
        "organization_type": "Chapter",
        "chapter": chapter,
        "category": category,
        "notes": "Testing automatic employee creation during expense submission",
    }

    try:
        # Mock session user as the volunteer's member
        member = frappe.get_doc("Member", volunteer.member)
        original_user = frappe.session.user

        if member.user:
            frappe.session.user = member.user
        else:
            # Create temporary session context
            frappe.session.user = member.email

        # Import and test the submit_expense function
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        result = submit_expense(expense_data)

        # Restore original user
        frappe.session.user = original_user

        if result and result.get("success"):
            print(f"✅ Expense submission successful: {result.get('expense_claim_name')}")

            if result.get("employee_created"):
                print(f"✅ Employee was automatically created during submission")
            else:
                print(f"ℹ️ Employee already existed, no creation needed")

            # Verify expense claim was created in ERPNext
            expense_claim_name = result.get("expense_claim_name")
            if frappe.db.exists("Expense Claim", expense_claim_name):
                expense_claim = frappe.get_doc("Expense Claim", expense_claim_name)
                print(f"✅ ERPNext Expense Claim verified:")
                print(f"   - Employee: {expense_claim.employee}")
                print(f"   - Amount: {expense_claim.total_claimed_amount}")
                print(f"   - Status: {expense_claim.approval_status}")
                return True
            else:
                print(f"❌ Expense claim {expense_claim_name} not found in ERPNext")
                return False
        else:
            error_msg = result.get("message", "Unknown error") if result else "No result returned"
            print(f"❌ Expense submission failed: {error_msg}")
            return False

    except Exception as e:
        print(f"❌ Error during expense submission test: {str(e)}")
        return False


if __name__ == "__main__":
    import frappe

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("🧪 Testing Automatic Employee Creation")
    print("=" * 50)

    success_count = 0
    total_tests = 2

    # Test 1: Direct employee creation
    if test_auto_employee_creation():
        success_count += 1

    # Test 2: Full expense submission workflow
    if test_expense_submission_workflow():
        success_count += 1

    print("\n" + "=" * 50)
    print(f"🎯 Test Results: {success_count}/{total_tests} tests passed")

    if success_count == total_tests:
        print("✅ All automatic employee creation tests PASSED!")
    else:
        print(f"❌ {total_tests - success_count} tests FAILED")

    frappe.destroy()
