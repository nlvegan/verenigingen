#!/usr/bin/env python3
"""
Test employee creation workflow
Run this with: bench --site dev.veganisme.net execute verenigingen.test_employee_creation.test_create_employee
"""


def test_create_employee():
    import frappe
    from frappe.utils import today

    print("Testing Employee Creation...")

    # Get a volunteer without employee_id
    volunteer = frappe.db.get_value(
        "Verenigingen Volunteer",
        {"employee_id": ["is", "not set"]},
        ["name", "volunteer_name", "personal_email"],
        as_dict=True,
    )

    if not volunteer:
        print("No volunteers without employee records found")
        return False

    print(f"Testing with volunteer: {volunteer.volunteer_name}")

    # Get the volunteer document
    vol_doc = frappe.get_doc("Volunteer", volunteer.name)

    # Test employee creation
    try:
        employee_id = vol_doc.create_minimal_employee()

        if employee_id:
            print(f"✅ Employee created successfully: {employee_id}")

            # Verify employee exists
            if frappe.db.exists("Employee", employee_id):
                employee = frappe.get_doc("Employee", employee_id)
                print(f"✅ Employee verified: {employee.employee_name}")
                print(f"   Company: {employee.company}")
                print(f"   Status: {employee.status}")
                return True
            else:
                print(f"❌ Employee {employee_id} not found in database")
                return False
        else:
            print("❌ Employee creation returned no ID")
            return False

    except Exception as e:
        print(f"❌ Error creating employee: {str(e)}")
        return False


if __name__ == "__main__":
    test_create_employee()
