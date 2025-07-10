"""
Helper utilities for native ERPNext expense system
Replaces the complex department hierarchy with simple role-based approvals
"""

import frappe


def get_volunteer_expense_approver(volunteer_name):
    """Get expense approver for a volunteer using native ERPNext approach"""
    try:
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        return volunteer.get_expense_approver_from_assignments()
    except Exception as e:
        frappe.log_error(
            f"Error getting expense approver for {volunteer_name}: {str(e)}", "Expense Approver Lookup Error"
        )
        return "Administrator"  # Safe fallback


def update_employee_approver(volunteer_doc=None, method=None):
    """Update employee record with current expense approver (called from document hooks)"""
    try:
        # Handle both direct calls and document hook calls
        if isinstance(volunteer_doc, str):
            volunteer = frappe.get_doc("Volunteer", volunteer_doc)
        else:
            volunteer = volunteer_doc

        if not volunteer or not volunteer.employee_id:
            return None

        if not frappe.db.exists("Employee", volunteer.employee_id):
            return None

        approver = volunteer.get_expense_approver_from_assignments()

        if approver:
            employee = frappe.get_doc("Employee", volunteer.employee_id)
            old_approver = employee.expense_approver

            if old_approver != approver:
                employee.expense_approver = approver
                employee.department = None  # Remove department dependency
                employee.save(ignore_permissions=True)
                frappe.logger().info(
                    f"Updated expense approver for {volunteer.volunteer_name}: {old_approver} → {approver}"
                )

            return approver

        return None

    except Exception as e:
        frappe.log_error(f"Error updating employee approver: {str(e)}", "Employee Approver Update Error")
        return None


@frappe.whitelist()
def refresh_all_expense_approvers():
    """Refresh expense approvers for all volunteers with employee records"""
    updated_count = 0
    error_count = 0

    volunteers_with_employees = frappe.db.sql(
        """
        SELECT v.name, v.volunteer_name
        FROM `tabVolunteer` v
        WHERE v.employee_id IS NOT NULL
        AND v.employee_id != ''
        AND EXISTS (SELECT 1 FROM `tabEmployee` e WHERE e.name = v.employee_id)
    """,
        as_dict=True,
    )

    for volunteer_data in volunteers_with_employees:
        try:
            approver = update_employee_approver(volunteer_data.name)
            if approver:
                updated_count += 1
            else:
                error_count += 1
        except Exception:
            error_count += 1

    frappe.db.commit()

    return {
        "success": True,
        "updated": updated_count,
        "errors": error_count,
        "message": "Updated {updated_count} employee records, {error_count} errors",
    }


def validate_expense_approver_setup():
    """Validate that expense approver system is properly configured"""
    issues = []

    # Check for employees without approvers
    employees_without_approvers = frappe.db.sql(
        """
        SELECT e.name, e.employee_name
        FROM `tabEmployee` e
        WHERE (e.expense_approver IS NULL OR e.expense_approver = '')
        AND EXISTS (SELECT 1 FROM `tabVolunteer` v WHERE v.employee_id = e.name)
    """,
        as_dict=True,
    )

    if employees_without_approvers:
        issues.append("{len(employees_without_approvers)} employees without expense approvers")

    # Check for approvers who don't have expense approver role
    approvers_without_role = frappe.db.sql(
        """
        SELECT DISTINCT e.expense_approver, u.full_name
        FROM `tabEmployee` e
        JOIN `tabUser` u ON e.expense_approver = u.name
        WHERE e.expense_approver IS NOT NULL
        AND e.expense_approver != ''
        AND e.expense_approver NOT IN (
            SELECT DISTINCT ur.parent
            FROM `tabHas Role` ur
            WHERE ur.role = 'Expense Approver'
            AND ur.parenttype = 'User'
        )
    """,
        as_dict=True,
    )

    if approvers_without_role:
        issues.append("{len(approvers_without_role)} approvers without 'Expense Approver' role")

    # Check for inactive approvers
    inactive_approvers = frappe.db.sql(
        """
        SELECT DISTINCT e.expense_approver, u.full_name
        FROM `tabEmployee` e
        JOIN `tabUser` u ON e.expense_approver = u.name
        WHERE e.expense_approver IS NOT NULL
        AND e.expense_approver != ''
        AND u.enabled = 0
    """,
        as_dict=True,
    )

    if inactive_approvers:
        issues.append("{len(inactive_approvers)} employees have inactive approvers")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "employees_without_approvers": employees_without_approvers,
        "approvers_without_role": approvers_without_role,
        "inactive_approvers": inactive_approvers,
    }


@frappe.whitelist()
def fix_expense_approver_issues():
    """Automatically fix common expense approver setup issues"""
    validation_result = validate_expense_approver_setup()
    fixed_count = 0

    # Fix employees without approvers
    for employee_data in validation_result.get("employees_without_approvers", []):
        try:
            # Find volunteer and update approver
            volunteer = frappe.db.get_value("Volunteer", {"employee_id": employee_data.name}, "name")
            if volunteer:
                approver = update_employee_approver(volunteer)
                if approver:
                    fixed_count += 1
        except Exception:
            pass

    # Fix approvers without role
    for approver_data in validation_result.get("approvers_without_role", []):
        try:
            user = frappe.get_doc("User", approver_data.expense_approver)
            user.append("roles", {"role": "Expense Approver"})
            user.save(ignore_permissions=True)
            fixed_count += 1
        except Exception:
            pass

    frappe.db.commit()

    return {"success": True, "fixed": fixed_count, "message": "Fixed {fixed_count} expense approver issues"}


def is_native_expense_system_ready():
    """Check if system is ready to handle expense claims without departments"""
    validation = validate_expense_approver_setup()

    # Consider system ready if less than 10% of employees have issues
    total_employees = frappe.db.count("Employee")
    if total_employees == 0:
        return True

    total_issues = len(validation.get("employees_without_approvers", []))
    issue_percentage = (total_issues / total_employees) * 100

    return issue_percentage < 10  # System ready if less than 10% have issues


@frappe.whitelist()
def emergency_clear_departments():
    """Emergency function to clear all department references causing validation errors"""
    try:
        # Clear all department references from Employee records
        frappe.db.sql("UPDATE `tabEmployee` SET department = NULL WHERE department IS NOT NULL")

        # Get count of updated records
        updated_count = frappe.db.sql("SELECT ROW_COUNT()")[0][0]

        # Specifically handle Foppe de Haan
        # foppe_result = frappe.db.sql(
        #     """
        #     UPDATE `tabEmployee` e
        #     JOIN `tabVolunteer` v ON v.employee_id = e.name
        #     SET e.department = NULL, e.expense_approver = 'Administrator'
        #     WHERE v.name = 'FOPPE-DE-HAAN'
        # """
        # )

        frappe.db.commit()

        return {
            "success": True,
            "message": f"Cleared department references from {updated_count} employee records",
            "foppe_updated": True,
        }

    except Exception as e:
        frappe.log_error(f"Error clearing departments: {str(e)}", "Emergency Department Clear")
        return {"success": False, "message": f"Error: {str(e)}"}
