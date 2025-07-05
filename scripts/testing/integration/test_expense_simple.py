import frappe
from frappe.utils import today


def quick_expense_test():
    """Quick test of expense functionality"""
    frappe.set_user("Administrator")

    print("Testing expense functionality...")

    # Check HRMS
    if not frappe.db.exists("DocType", "Expense Claim"):
        print("❌ HRMS not available")
        return

    # Check employees
    employees = frappe.get_all("Employee", limit=1)
    if not employees:
        print("❌ No employees found")
        return

    # Check companies
    companies = frappe.get_all("Company", limit=1)
    if not companies:
        print("❌ No companies found")
        return

    # Try creating expense claim
    try:
        expense_claim = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employees[0].name,
                "posting_date": today(),
                "company": companies[0].name,
                "title": "Test Claim",
                "status": "Draft",
            }
        )
        expense_claim.insert()
        print(f"✅ Created expense claim: {expense_claim.name}")

        # Clean up
        frappe.delete_doc("Expense Claim", expense_claim.name)
        print("✅ Expense functionality is working!")

    except Exception as e:
        print(f"❌ Error: {str(e)}")


def test_volunteer_with_employee():
    """Test volunteer with employee record"""
    frappe.set_user("Administrator")

    # Find volunteer with employee
    volunteers = frappe.db.sql(
        """
        SELECT v.name, v.volunteer_name, v.employee_id
        FROM `tabVolunteer` v
        WHERE v.employee_id IS NOT NULL
        LIMIT 1
    """,
        as_dict=True,
    )

    if volunteers:
        vol = volunteers[0]
        print(f"✅ Found volunteer with employee: {vol.volunteer_name} ({vol.employee_id})")

        # Try to create expense for this volunteer
        try:
            companies = frappe.get_all("Company", limit=1)
            if companies:
                expense_claim = frappe.get_doc(
                    {
                        "doctype": "Expense Claim",
                        "employee": vol.employee_id,
                        "posting_date": today(),
                        "company": companies[0].name,
                        "title": f"Volunteer expense for {vol.volunteer_name}",
                        "status": "Draft",
                    }
                )
                expense_claim.insert()
                print(f"✅ Created volunteer expense claim: {expense_claim.name}")

                # Clean up
                frappe.delete_doc("Expense Claim", expense_claim.name)
                print("✅ Volunteer expense workflow is working!")

        except Exception as e:
            print(f"❌ Volunteer expense error: {str(e)}")
    else:
        print("❌ No volunteers with employee records found")
