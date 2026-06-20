"""
Helper utilities for native ERPNext expense system
Replaces the complex department hierarchy with simple role-based approvals
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


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
            old_approver = employee.expense_approver  # ast-skip: ERPNext HR field

            if old_approver != approver:
                employee.expense_approver = approver
                employee.department = None  # Remove department dependency

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="save",
                    doc=employee,
                    justification=f"Update expense approver for volunteer {volunteer.volunteer_name} employee record - HR management for expense workflow",
                    required_permissions=["Employee:write"],
                )

                if not result.success:
                    frappe.log_error(
                        f"Failed to update employee expense approver: {'; '.join(result.errors)}",
                        "Employee Expense Security",
                    )
                    return None
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
        "message": f"Updated {updated_count} employee records, {error_count} errors",
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
        issues.append(f"{len(employees_without_approvers)} employees without expense approvers")

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
        issues.append(f"{len(approvers_without_role)} approvers without 'Expense Approver' role")

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
        issues.append(f"{len(inactive_approvers)} employees have inactive approvers")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "employees_without_approvers": employees_without_approvers,
        "approvers_without_role": approvers_without_role,
        "inactive_approvers": inactive_approvers,
    }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def fix_expense_approver_issues():
    """Automatically fix common expense approver setup issues.

    Security: this is an administrative maintenance operation that reassigns
    expense approvers and grants the Expense Approver role. It is gated to
    CRITICAL (admin role profiles only); the role-grant branch additionally
    enforces User:write via secure_document_operation.
    """
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

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="save",
                doc=user,
                justification=f"Add Expense Approver role to user {approver_data.expense_approver} - HR role management for expense workflow setup",
                required_permissions=["User:write"],
            )

            if result.success:
                fixed_count += 1
            else:
                frappe.log_error(
                    f"Failed to add Expense Approver role to user: {'; '.join(result.errors)}",
                    "User Role Security",
                )
        except Exception:
            pass

    frappe.db.commit()

    return {"success": True, "fixed": fixed_count, "message": f"Fixed {fixed_count} expense approver issues"}


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
