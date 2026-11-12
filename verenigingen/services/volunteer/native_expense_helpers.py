"""
Helper utilities for native ERPNext expense system
Replaces the complex department hierarchy with simple role-based approvals
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.user_role_grant import ensure_role_survives_profile_resync


def get_volunteer_expense_approver(volunteer_name):
    """Get expense approver for a volunteer using native ERPNext approach.

    None means no financial seat exists for them (#1650: unassigned). An unknown volunteer
    raises rather than being reported as "no approver".
    """
    volunteer = frappe.get_doc("Volunteer", volunteer_name)
    return volunteer.get_expense_approver_from_assignments()


def update_employee_approver(
    volunteer_doc=None, method=None, clear_if_approver_in=(), system_operation=False
):
    """Update employee record with current expense approver (called from document hooks)

    ``clear_if_approver_in`` (#1682): users whose financial seat just ended. When no
    approver is left for the volunteer and the Employee still names one of them, the stale
    approver is cleared (#1650: unassigned). Any other value, e.g. one an admin set by
    hand, is left alone. ``system_operation``: the write is bookkeeping derived from the
    board seats, not the acting user's own Employee edit.
    """
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
        if not approver:
            # No financial seat exists for this volunteer (#1650 ruling): leave the Employee
            # alone, so an approver an admin set by hand survives the refresh. The one
            # exception is the seat holder who just left (#1682): that value is stale.
            if clear_if_approver_in:
                _clear_stale_employee_approver(volunteer, clear_if_approver_in, system_operation)
            return None

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
                system_operation=system_operation,
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

    except Exception as e:
        frappe.log_error(f"Error updating employee approver: {str(e)}", "Employee Approver Update Error")
        return None


def _clear_stale_employee_approver(volunteer, stale_users, system_operation=False):
    """Blank Employee.expense_approver when it names one of ``stale_users``."""
    employee = frappe.get_doc("Employee", volunteer.employee_id)
    if employee.expense_approver not in stale_users:  # ast-skip: ERPNext HR field
        return

    employee.expense_approver = None
    result = secure_document_operation(
        operation="save",
        doc=employee,
        justification=f"Clear departed expense approver for volunteer {volunteer.volunteer_name} - no financial seat left",
        required_permissions=["Employee:write"],
        system_operation=system_operation,
    )
    if not result.success:
        frappe.log_error(
            title="Employee Expense Security",
            message=f"Failed to clear stale employee expense approver: {'; '.join(result.errors)}",
        )


def refresh_expense_approvers_for_chapter(chapter_name, seat_volunteers=()):
    """Refresh the approver rows a chapter's board seats feed, at the moment they change (#1682).

    Same computation as the daily ``refresh_all_expense_approvers`` /
    ``sync_all_department_approvers``, scoped to the people the chapter can affect.
    ``seat_volunteers`` are the volunteers whose seat was added, ended, deleted or
    re-roled: their users are the candidates for a now-stale approver. Runs inside the
    caller's save and never commits (hook context).
    """
    from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

    stale_users = _volunteer_users(seat_volunteers)
    DepartmentHierarchyManager().sync_chapter_approvers_for_chapter(
        chapter_name, remove_approvers=stale_users, system_operation=True
    )
    for volunteer_name in _volunteers_fed_by_chapter(chapter_name, stale_users):
        update_employee_approver(volunteer_name, clear_if_approver_in=stale_users, system_operation=True)


def _volunteer_users(volunteer_names):
    """User ids (email, else personal email) the approver lookup would resolve for these volunteers."""
    users = set()
    for volunteer_name in volunteer_names:
        email, personal_email = frappe.db.get_value(
            "Volunteer", volunteer_name, ["email", "personal_email"]
        ) or (None, None)
        if email or personal_email:
            users.add(email or personal_email)
    return users


def _volunteers_fed_by_chapter(chapter_name, stale_users):
    """Volunteers with an Employee whose approver can depend on this chapter's seats.

    A volunteer's approver comes from their own seat (board), their enabled chapter
    memberships, their teams' chapter, and the national board as the fallback, so the
    national chapter feeds everyone. Anyone whose Employee still names a stale user is
    included so that value is judged too.
    """
    volunteers = {
        row.name: row.employee_id
        for row in frappe.get_all(
            "Volunteer", filters={"employee_id": ["is", "set"]}, fields=["name", "employee_id", "member"]
        )
        if frappe.db.exists("Employee", row.employee_id)
    }
    if chapter_name == frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter"):
        return list(volunteers)

    members = set(
        frappe.get_all("Chapter Member", filters={"parent": chapter_name, "enabled": 1}, pluck="member")
    )
    team_volunteers = set(
        frappe.db.sql(
            """
            SELECT tm.volunteer FROM `tabTeam Member` tm
            JOIN `tabTeam` t ON t.name = tm.parent
            WHERE t.chapter = %s AND tm.status = 'Active'
            """,
            chapter_name,
            pluck=True,
        )
    )
    seated = set(frappe.get_all("Chapter Board Member", filters={"parent": chapter_name}, pluck="volunteer"))
    stale_holders = (
        {
            name
            for name, employee_id in volunteers.items()
            if frappe.db.get_value("Employee", employee_id, "expense_approver") in stale_users
        }
        if stale_users
        else set()
    )
    member_of = (
        {
            row.name
            for row in frappe.get_all("Volunteer", filters={"member": ["in", list(members)]}, fields=["name"])
        }
        if members
        else set()
    )

    fed = member_of | team_volunteers | seated | stale_holders
    return [name for name in volunteers if name in fed]


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def refresh_all_expense_approvers():
    """Refresh expense approvers for all volunteers with employee records"""
    updated_count = 0
    unassigned_count = 0
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
            elif get_volunteer_expense_approver(volunteer_data.name) is None:
                # No Financial seat exists for them (#1650): left alone, not a failure.
                # update_employee_approver also returns None when its write failed, in
                # which case the lookup above finds an approver and it is an error.
                unassigned_count += 1
            else:
                error_count += 1
        except Exception:
            error_count += 1

    frappe.db.commit()

    return {
        "success": True,
        "updated": updated_count,
        "unassigned": unassigned_count,
        "errors": error_count,
        "message": (
            f"Updated {updated_count} employee records, {unassigned_count} unassigned "
            f"(no financial seat), {error_count} errors"
        ),
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
                # #1195: the append above is silently defeated by User.validate()'s
                # role-profile re-derivation whenever the user carries a Role
                # Profile that doesn't include "Expense Approver" -- verify and
                # fall back to a direct Has Role insert.
                ensure_role_survives_profile_resync(approver_data.expense_approver, "Expense Approver")
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
