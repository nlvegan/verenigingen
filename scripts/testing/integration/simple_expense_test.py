"""
Simple test script for expense functionality
Run this from bench console
"""

import frappe
from frappe.utils import today


def test_basic_expense_functionality():
    """Test basic expense functionality"""

    print("🧪 Testing Basic Expense Functionality")
    print("=" * 50)

    try:
        # Set administrator user
        frappe.set_user("Administrator")

        # Test 1: Check if HRMS is installed and Expense Claim doctype exists
        print("\n1️⃣ Checking HRMS installation...")
        if frappe.db.exists("DocType", "Expense Claim"):
            print("   ✅ Expense Claim doctype is available")
        else:
            print("   ❌ Expense Claim doctype not found - HRMS may not be installed")
            return False

        # Test 2: Check if Expense Claim Type exists
        print("\n2️⃣ Checking Expense Claim Types...")
        expense_types = frappe.get_all("Expense Claim Type", limit=5)
        if expense_types:
            print(f"   ✅ Found {len(expense_types)} Expense Claim Types")
            for etype in expense_types:
                print(f"      • {etype.name}")
        else:
            print("   ⚠️  No Expense Claim Types found - creating default one...")
            try:
                default_type = frappe.get_doc(
                    {"doctype": "Expense Claim Type", "expense_type": "Travel", "name": "Travel"}
                )
                default_type.insert()
                print("   ✅ Created default 'Travel' expense type")
            except Exception as e:
                print(f"   ❌ Failed to create expense type: {str(e)}")

        # Test 3: Check for employees
        print("\n3️⃣ Checking for employees...")
        employees = frappe.get_all("Employee", fields=["name", "employee_name"], limit=3)
        if employees:
            print(f"   ✅ Found {len(employees)} employees")
            for emp in employees:
                print(f"      • {emp.employee_name} ({emp.name})")
        else:
            print("   ⚠️  No employees found")

        # Test 4: Check companies
        print("\n4️⃣ Checking companies...")
        companies = frappe.get_all("Company", limit=3)
        if companies:
            print(f"   ✅ Found {len(companies)} companies")
            for company in companies:
                print(f"      • {company.name}")
            default_company = companies[0].name
        else:
            print("   ❌ No companies found")
            return False

        # Test 5: Test expense claim creation
        print("\n5️⃣ Testing Expense Claim creation...")
        if employees:
            try:
                test_employee = employees[0].name

                expense_claim = frappe.get_doc(
                    {
                        "doctype": "Expense Claim",
                        "employee": test_employee,
                        "posting_date": today(),
                        "company": default_company,
                        "title": "Test Integration Claim",
                        "remark": "Testing expense claim creation",
                        "status": "Draft"}
                )

                expense_claim.insert()
                print(f"   ✅ Created test expense claim: {expense_claim.name}")

                # Clean up
                frappe.delete_doc("Expense Claim", expense_claim.name)
                print("   🧹 Cleaned up test expense claim")

            except Exception as e:
                print(f"   ❌ Failed to create expense claim: {str(e)}")
                return False

        # Test 6: Check volunteer with employee
        print("\n6️⃣ Checking volunteers with employee records...")
        volunteers_with_employees = frappe.db.sql(
            """
            SELECT v.name, v.volunteer_name, v.employee_id, e.employee_name
            FROM `tabVolunteer` v
            LEFT JOIN `tabEmployee` e ON v.employee_id = e.name
            WHERE v.employee_id IS NOT NULL
            LIMIT 3
        """,
            as_dict=True,
        )

        if volunteers_with_employees:
            print(f"   ✅ Found {len(volunteers_with_employees)} volunteers with employee records")
            for vol in volunteers_with_employees:
                print(f"      • {vol.volunteer_name} → {vol.employee_name}")
        else:
            print("   ⚠️  No volunteers with employee records found")

        print("\n🎉 Basic expense functionality test completed!")
        print("✅ ERPNext Expense Claims integration appears to be working")
        return True

    except Exception as e:
        print(f"\n❌ Error during testing: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_volunteer_expense_workflow():
    """Test the volunteer expense submission workflow"""

    print("\n\n🔬 Testing Volunteer Expense Workflow")
    print("=" * 50)

    try:
        # Find a volunteer with employee record
        volunteer_sql = """
            SELECT v.name, v.volunteer_name, v.employee_id, v.member, m.email_address
            FROM `tabVolunteer` v
            INNER JOIN `tabMember` m ON v.member = m.name
            WHERE v.employee_id IS NOT NULL
            AND m.email_address IS NOT NULL
            LIMIT 1
        """

        volunteers = frappe.db.sql(volunteer_sql, as_dict=True)

        if not volunteers:
            print("❌ No volunteers with employee records and email found for testing")
            return False

        test_volunteer = volunteers[0]
        print(f"🎯 Testing with volunteer: {test_volunteer.volunteer_name}")
        print(f"   Employee ID: {test_volunteer.employee_id}")
        print(f"   Member Email: {test_volunteer.email_address}")

        # Test expense submission
        expense_data = {
            "expense_date": today(),
            "description": "Test expense after account setup",
            "amount": 15.75,
            "expense_type": "Travel",
            "notes": "Testing expense functionality"}

        print("\n💰 Submitting test expense...")

        # Import and test the expense submission
        from verenigingen.templates.pages.volunteer.expenses import submit_expense

        # Temporarily switch user context
        original_user = frappe.session.user
        frappe.set_user(test_volunteer.email_address)

        try:
            result = submit_expense(volunteer_name=test_volunteer.name, expense_data=expense_data)

            if result.get("success"):
                print("✅ Expense submission successful!")
                print(f"   Volunteer Expense: {result.get('volunteer_expense_id')}")
                print(f"   ERPNext Expense Claim: {result.get('erpnext_expense_claim_id')}")

                # Verify the created records
                if result.get("volunteer_expense_id"):
                    vol_expense = frappe.get_doc("Volunteer Expense", result["volunteer_expense_id"])
                    print(f"   ✅ Volunteer Expense created: €{vol_expense.amount}")

                if result.get("erpnext_expense_claim_id"):
                    erp_claim = frappe.get_doc("Expense Claim", result["erpnext_expense_claim_id"])
                    print(f"   ✅ ERPNext Expense Claim created: {erp_claim.title}")

                return True
            else:
                print(f"❌ Expense submission failed: {result.get('message')}")
                return False

        finally:
            frappe.set_user(original_user)

    except Exception as e:
        print(f"❌ Error testing volunteer expense workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


# Run the tests
if __name__ == "__main__":
    basic_test = test_basic_expense_functionality()
    workflow_test = test_volunteer_expense_workflow() if basic_test else False

    print(f"\n📊 Final Results:")
    print(f"Basic functionality: {'✅ PASS' if basic_test else '❌ FAIL'}")
    print(f"Workflow test: {'✅ PASS' if workflow_test else '❌ FAIL'}")

    if basic_test and workflow_test:
        print("\n🎉 All expense functionality tests passed!")
    elif basic_test:
        print("\n⚠️  Basic functionality works, but workflow needs attention")
    else:
        print("\n❌ Expense functionality needs configuration")
