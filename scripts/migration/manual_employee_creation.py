#!/usr/bin/env python3
"""
Manual Employee Creation Utility for Volunteers
Run with: bench --site dev.veganisme.net execute verenigingen.manual_employee_creation.create_employee_for_volunteer --args "volunteer_name"
"""

import frappe
from frappe.utils import today


@frappe.whitelist()
def create_employee_for_volunteer(volunteer_name):
    """Manually create an employee record for a volunteer"""
    try:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)

        if volunteer_doc.employee_id:
            return {
                "success": True,
                "message": f"Volunteer {volunteer_name} already has employee record: {volunteer_doc.employee_id}",
                "employee_id": volunteer_doc.employee_id,
            }

        # Get default company
        company = frappe.db.get_value("Company", {"is_group": 0}, "name")
        if not company:
            return {
                "success": False,
                "message": "No company found in the system. Please create a company first.",
            }

        # Create basic employee record
        employee_data = {
            "doctype": "Employee",
            "employee_name": volunteer_doc.volunteer_name,
            "first_name": volunteer_doc.volunteer_name.split(" ")[0]
            if volunteer_doc.volunteer_name
            else "Volunteer",
            "company": company,
            "status": "Active",
            "date_of_joining": today(),
        }

        # Add last name if available
        if volunteer_doc.volunteer_name and " " in volunteer_doc.volunteer_name:
            name_parts = volunteer_doc.volunteer_name.split(" ", 1)
            employee_data["last_name"] = name_parts[1]

        # Add email if available
        if volunteer_doc.personal_email:
            employee_data["personal_email"] = volunteer_doc.personal_email

        employee_doc = frappe.get_doc(employee_data)
        employee_doc.insert(ignore_permissions=True)

        # Link to volunteer
        frappe.db.set_value("Volunteer", volunteer_name, "employee_id", employee_doc.name)

        return {
            "success": True,
            "message": f"Successfully created employee {employee_doc.name} for volunteer {volunteer_name}",
            "employee_id": employee_doc.name,
            "employee_number": employee_doc.employee,
        }

    except Exception as e:
        frappe.log_error(
            f"Manual employee creation failed for {volunteer_name}: {str(e)}", "Manual Employee Creation"
        )
        return {"success": False, "message": f"Failed to create employee: {str(e)}"}


@frappe.whitelist()
def create_employees_for_all_volunteers():
    """Create employee records for all volunteers who don't have them"""
    volunteers_without_employees = frappe.get_all(
        "Volunteer", filters={"employee_id": ["is", "not set"]}, fields=["name", "volunteer_name"]
    )

    results = []
    success_count = 0

    for volunteer in volunteers_without_employees:
        result = create_employee_for_volunteer(volunteer.name)
        results.append(
            {"volunteer": volunteer.name, "volunteer_name": volunteer.volunteer_name, "result": result}
        )

        if result.get("success"):
            success_count += 1

    return {
        "total_processed": len(volunteers_without_employees),
        "success_count": success_count,
        "failed_count": len(volunteers_without_employees) - success_count,
        "details": results,
    }


@frappe.whitelist()
def check_volunteer_employee_status():
    """Check the employee status of all volunteers"""
    volunteers = frappe.get_all(
        "Volunteer", fields=["name", "volunteer_name", "employee_id", "personal_email"]
    )

    with_employees = []
    without_employees = []

    for volunteer in volunteers:
        if volunteer.employee_id:
            # Verify employee exists
            employee_exists = frappe.db.exists("Employee", volunteer.employee_id)
            with_employees.append(
                {
                    "volunteer": volunteer.name,
                    "volunteer_name": volunteer.volunteer_name,
                    "employee_id": volunteer.employee_id,
                    "employee_exists": employee_exists,
                }
            )
        else:
            without_employees.append(
                {
                    "volunteer": volunteer.name,
                    "volunteer_name": volunteer.volunteer_name,
                    "email": volunteer.personal_email,
                }
            )

    return {
        "total_volunteers": len(volunteers),
        "with_employees": len(with_employees),
        "without_employees": len(without_employees),
        "volunteers_with_employees": with_employees,
        "volunteers_without_employees": without_employees,
    }


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    print("=== Volunteer Employee Status Check ===")
    status = check_volunteer_employee_status()

    print(f"Total volunteers: {status['total_volunteers']}")
    print(f"With employees: {status['with_employees']}")
    print(f"Without employees: {status['without_employees']}")

    if status["without_employees"] > 0:
        print(f"\nVolunteers needing employee records:")
        for vol in status["volunteers_without_employees"]:
            print(f"  - {vol['volunteer_name']} ({vol['volunteer']})")

    frappe.destroy()
