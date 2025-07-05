#!/usr/bin/env python3
"""
Debug employee creation issues
Run with: bench --site dev.veganisme.net console
Then: exec(open('debug_employee_creation.py').read())
"""


def debug_employee_creation():
    import frappe
    from frappe.utils import today

    print("=== DEBUG: Employee Creation ===")

    # Test basic employee creation with minimal data
    try:
        company = frappe.db.get_value("Company", {"is_group": 0}, "name")
        print(f"Using company: {company}")

        employee_data = {
            "doctype": "Employee",
            "employee_name": "Test Volunteer Employee",
            "first_name": "Test",
            "last_name": "Volunteer",
            "company": company,
            "status": "Active",
            "date_of_joining": today(),
        }

        print("Creating test employee with data:", employee_data)

        employee_doc = frappe.get_doc(employee_data)
        employee_doc.insert(ignore_permissions=True)

        print(f"✅ Successfully created employee: {employee_doc.name}")
        print(f"   Employee ID: {employee_doc.employee}")
        print(f"   Employee Name: {employee_doc.employee_name}")

        # Clean up test employee
        frappe.delete_doc("Employee", employee_doc.name, ignore_permissions=True)
        print("✅ Test employee cleaned up")

        return True

    except Exception as e:
        print(f"❌ Error creating test employee: {str(e)}")
        import traceback

        print("Traceback:")
        print(traceback.format_exc())
        return False


def test_volunteer_employee_creation():
    import frappe

    print("\n=== DEBUG: Volunteer Employee Creation ===")

    # Get a volunteer without employee_id
    volunteer = frappe.db.get_value(
        "Volunteer",
        {"employee_id": ["is", "not set"]},
        ["name", "volunteer_name", "personal_email"],
        as_dict=True,
    )

    if not volunteer:
        print("❌ No volunteers without employee_id found")
        return False

    print(f"Testing with volunteer: {volunteer.volunteer_name}")

    volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

    try:
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id:
            print(f"✅ Successfully created employee: {employee_id}")
            return True
        else:
            print("❌ Employee creation returned None")
            return False

    except Exception as e:
        print(f"❌ Error in volunteer employee creation: {str(e)}")
        import traceback

        print("Traceback:")
        print(traceback.format_exc())
        return False


if __name__ == "__main__":
    debug_employee_creation()
    test_volunteer_employee_creation()
