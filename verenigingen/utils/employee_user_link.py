"""
Employee User Linking Utilities

Handles creation and linking of User accounts for Employees created from Volunteers
"""

import frappe
from frappe import _
from frappe.utils import cint


def create_user_for_volunteer(volunteer_doc):
    """Create a User account for a volunteer if it doesn't exist"""
    try:
        # Check if user already exists with this email
        if not volunteer_doc.email:
            frappe.logger().info(f"Volunteer {volunteer_doc.name} has no email, skipping user creation")
            return None

        existing_user = frappe.db.get_value("User", {"email": volunteer_doc.email}, "name")
        if existing_user:
            frappe.logger().info(f"User already exists for email {volunteer_doc.email}")
            return existing_user

        # Create new user
        user = frappe.new_doc("User")
        user.email = volunteer_doc.email
        user.first_name = (
            volunteer_doc.volunteer_name.split()[0]
            if volunteer_doc.volunteer_name
            else "Verenigingen Volunteer"
        )
        user.last_name = (
            " ".join(volunteer_doc.volunteer_name.split()[1:])
            if len(volunteer_doc.volunteer_name.split()) > 1
            else ""
        )
        user.send_welcome_email = 0  # Don't send welcome email yet
        user.enabled = 1

        # Add appropriate roles
        user.append("roles", {"role": "Employee"})
        user.append("roles", {"role": "Verenigingen Volunteer"})

        user.insert(ignore_permissions=True)
        frappe.logger().info(f"Created user {user.name} for volunteer {volunteer_doc.name}")

        return user.name

    except Exception as e:
        frappe.log_error(f"Error creating user for volunteer {volunteer_doc.name}: {str(e)}")
        return None


def update_employee_with_user(employee_name, user_id):
    """Update employee record with user_id"""
    try:
        employee = frappe.get_doc("Employee", employee_name)
        employee.user_id = user_id
        employee.save(ignore_permissions=True)
        frappe.logger().info(f"Updated employee {employee_name} with user_id {user_id}")
        return True
    except Exception as e:
        frappe.log_error(f"Error updating employee {employee_name} with user_id: {str(e)}")
        return False


def create_employee_for_approved_volunteer(volunteer_doc):
    """Create employee for volunteer when membership is approved"""
    try:
        # Check if employee already exists
        if volunteer_doc.employee_id and frappe.db.exists("Employee", volunteer_doc.employee_id):
            frappe.logger().info(
                f"Employee {volunteer_doc.employee_id} already exists for volunteer {volunteer_doc.name}"
            )
            return volunteer_doc.employee_id

        # Create employee using the existing method
        employee_id = volunteer_doc.create_minimal_employee()

        # Create user if needed and link to employee
        if volunteer_doc.email:
            user_id = create_user_for_volunteer(volunteer_doc)
            if user_id and employee_id:
                update_employee_with_user(employee_id, user_id)

        return employee_id

    except Exception as e:
        frappe.log_error(f"Error creating employee for approved volunteer {volunteer_doc.name}: {str(e)}")
        return None


@frappe.whitelist()
def fix_existing_employee_user_links():
    """Fix existing employees without user_id links"""
    try:
        # Get all employees created from volunteers
        employees_without_users = frappe.db.sql(
            """
            SELECT
                e.name as employee_id,
                e.personal_email,
                e.company_email,
                v.name as volunteer_id,
                v.email as volunteer_email,
                v.volunteer_name
            FROM `tabEmployee` e
            LEFT JOIN `tabVolunteer` v ON v.employee_id = e.name
            WHERE e.user_id IS NULL OR e.user_id = ''
            AND v.name IS NOT NULL
        """,
            as_dict=True,
        )

        fixed_count = 0
        errors = []

        for record in employees_without_users:
            try:
                # Determine which email to use
                email = record.volunteer_email or record.personal_email or record.company_email
                if not email:
                    errors.append(f"No email found for volunteer {record.volunteer_id}")
                    continue

                # Check if user exists
                existing_user = frappe.db.get_value("User", {"email": email}, "name")

                if existing_user:
                    # Link existing user
                    if update_employee_with_user(record.employee_id, existing_user):
                        fixed_count += 1
                else:
                    # Create new user
                    volunteer_doc = frappe.get_doc("Volunteer", record.volunteer_id)
                    user_id = create_user_for_volunteer(volunteer_doc)
                    if user_id and update_employee_with_user(record.employee_id, user_id):
                        fixed_count += 1

            except Exception as e:
                errors.append(f"Error processing employee {record.employee_id}: {str(e)}")

        return {
            "success": True,
            "fixed_count": fixed_count,
            "total_processed": len(employees_without_users),
            "errors": errors,
        }

    except Exception as e:
        frappe.log_error(f"Error fixing employee user links: {str(e)}")
        return {"success": False, "error": str(e)}


def enhanced_create_minimal_employee(volunteer_doc):
    """Enhanced version of create_minimal_employee that includes user creation"""
    try:
        # First create the employee using the existing method
        employee_id = volunteer_doc.create_minimal_employee()

        if employee_id and volunteer_doc.email:
            # Create or link user
            user_id = create_user_for_volunteer(volunteer_doc)
            if user_id:
                update_employee_with_user(employee_id, user_id)

        return employee_id

    except Exception as e:
        frappe.log_error(f"Error in enhanced employee creation: {str(e)}")
        raise
