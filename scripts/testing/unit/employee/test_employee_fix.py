#!/usr/bin/env python3
"""
Test the fixed employee creation
Run with: bench --site dev.veganisme.net execute verenigingen.test_employee_fix.test_employee_creation
"""

import frappe


@frappe.whitelist()
def test_employee_creation():
    """Test employee creation with the fixed code"""
    try:
        # Get a volunteer without employee_id
        volunteer = frappe.db.get_value(
            "Volunteer", {"employee_id": ["is", "not set"]}, ["name", "volunteer_name"], as_dict=True
        )

        if not volunteer:
            return {"success": False, "message": "No volunteers without employee_id found for testing"}

        print(f"Testing employee creation for volunteer: {volunteer.volunteer_name}")

        # Get volunteer document
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)

        # Test employee creation
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id:
            return {
                "success": True,
                "message": f"Successfully created employee: {employee_id}",
                "volunteer": volunteer.name,
                "employee_id": employee_id,
            }
        else:
            return {"success": False, "message": "Employee creation returned None"}

    except Exception as e:
        return {"success": False, "message": f"Error: {str(e)}"}


@frappe.whitelist()
def test_designation_creation():
    """Test if we can create the Volunteer designation"""
    try:
        designation_name = "Volunteer"

        if frappe.db.exists("Designation", designation_name):
            return {"success": True, "message": f"Designation {designation_name} already exists"}

        # Create designation
        designation_doc = frappe.get_doc({"doctype": "Designation", "designation_name": designation_name})
        designation_doc.insert(ignore_permissions=True)

        return {"success": True, "message": f"Successfully created designation: {designation_name}"}

    except Exception as e:
        return {"success": False, "message": f"Error creating designation: {str(e)}"}


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("=== Testing Designation Creation ===")
    result = test_designation_creation()
    print(f"Result: {result}")

    print("\n=== Testing Employee Creation ===")
    result = test_employee_creation()
    print(f"Result: {result}")

    frappe.destroy()
