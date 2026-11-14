"""
Helper utilities for native ERPNext expense system
Replaces the complex department hierarchy with simple role-based approvals
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api, high_security_api
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS
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

    except NON_RESUMABLE_DB_ERRORS:
        # #1682: this handler is now load-bearing for seat changes. A deadlock or lock
        # timeout means the transaction is gone; logging it and returning None would let
        # the seat change report success over a refresh that never happened.
        raise
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


def refresh_expense_approvers_for_chapter(chapter_name, departed_volunteers=(), inline=False):
    """Refresh the approver rows a chapter's board seats feed, at the moment they change (#1682).

    Same computation as the daily ``refresh_all_expense_approvers`` /
    ``sync_all_department_approvers``, scoped to the people the chapter can affect.
    ``departed_volunteers`` are those who held a Financial seat here before the change: the
    ones that no longer hold one have their user treated as a stale approver (a seat that
    was added or never Financial cannot make an approver stale). Runs inside the caller's
    save and never commits (hook context).

    The chapter's own Department rows are written inline (a handful of rows). The Employee
    refresh is inline for an ordinary chapter, but ENQUEUED for the national chapter: its
    seats feed every volunteer, and one ``Employee.save`` per volunteer inside a Chapter
    save was measured at ~2.4s each. ``inline=True`` is for code already in a job.
    """
    from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

    stale_users = sorted(_users_who_left_a_financial_seat(chapter_name, departed_volunteers))
    DepartmentHierarchyManager().sync_chapter_approvers_for_chapter(
        chapter_name, remove_approvers=stale_users, system_operation=True
    )
    if not inline and _is_national_chapter(chapter_name):
        _enqueue_once(
            f"{_JOBS}refresh_employee_approvers_for_chapter",
            f"chapter|{chapter_name}|{_digest(stale_users)}",
            chapter_name=chapter_name,
            stale_users=stale_users,
        )
        return
    refresh_employee_approvers_for_chapter(chapter_name, stale_users)


def refresh_employee_approvers_for_chapter(chapter_name, stale_users=()):
    """Recompute Employee.expense_approver for every volunteer the chapter's seats feed.

    Also the queued job for the national chapter. A deadlock or lock timeout propagates
    (``update_employee_approver`` re-raises it): the caller owns the transaction.
    """
    for volunteer_name in _volunteers_fed_by_chapter(chapter_name, stale_users):
        update_employee_approver(volunteer_name, clear_if_approver_in=stale_users, system_operation=True)


def refresh_expense_approvers_for_role(role_name, left_financial=False):
    """Queued job: re-point every chapter that holds ``role_name`` after the role changed (#1682).

    ``left_financial``: the role was an active Financial role and no longer is, so its
    holders are the candidates for a stale approver.
    """
    seats = frappe.get_all(
        "Chapter Board Member",
        filters={"chapter_role": role_name, "is_active": 1},
        fields=["parent", "volunteer"],
    )
    for chapter_name in dict.fromkeys(seat.parent for seat in seats):
        holders = [seat.volunteer for seat in seats if seat.parent == chapter_name] if left_financial else ()
        refresh_expense_approvers_for_chapter(chapter_name, holders, inline=True)


def enqueue_expense_approver_refresh_for_role(role_name, left_financial):
    """One job per Chapter Role change, however many chapters hold the role (#1682)."""
    _enqueue_once(
        f"{_JOBS}refresh_expense_approvers_for_role",
        f"role|{role_name}|{int(bool(left_financial))}",
        role_name=role_name,
        left_financial=bool(left_financial),
    )


_JOBS = "verenigingen.services.volunteer.native_expense_helpers."


def _enqueue_once(method, job_key, **kwargs):
    """Enqueue after the caller's commit, unless an identical job still waits in the queue.

    ``deduplicate=True`` is inert together with ``enqueue_after_commit`` (the check runs
    when the callback fires, after the job id was already chosen), so the check is made here.
    Only a QUEUED job counts: one already running may have read state older than this change.
    """
    job_id = f"expense_approver_refresh|{job_key}"
    if _job_is_queued(job_id):
        return
    frappe.enqueue(
        method,
        queue="long",
        timeout=1800,
        job_id=job_id,
        enqueue_after_commit=True,
        **kwargs,
    )


def _job_is_queued(job_id):
    from frappe.utils.background_jobs import JobStatus, get_job_status

    return get_job_status(job_id) == JobStatus.QUEUED


def _digest(values):
    import hashlib

    return hashlib.sha1("|".join(values).encode()).hexdigest()[:10]


def _is_national_chapter(chapter_name):
    return chapter_name == frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")


def _users_who_left_a_financial_seat(chapter_name, departed_volunteers):
    """Users of the ``departed_volunteers`` who hold no active Financial seat in the chapter now."""
    departed = [name for name in dict.fromkeys(departed_volunteers) if name]
    if not departed:
        return set()
    still_financial = set(
        frappe.db.sql(
            """
            SELECT DISTINCT cbm.volunteer
            FROM `tabChapter Board Member` cbm
            JOIN `tabChapter Role` cr ON cr.name = cbm.chapter_role
            WHERE cbm.parent = %(chapter)s AND cbm.is_active = 1
                AND cr.permissions_level = 'Financial' AND cr.is_active = 1
                AND cbm.volunteer IN %(volunteers)s
            """,
            {"chapter": chapter_name, "volunteers": departed},
            pluck=True,
        )
    )
    return _volunteer_users([name for name in departed if name not in still_financial])


def _volunteer_users(volunteer_names):
    """User ids (email, else personal email) the approver lookup would resolve for these volunteers."""
    if not volunteer_names:
        return set()
    rows = frappe.get_all(
        "Volunteer", filters={"name": ["in", list(volunteer_names)]}, fields=["email", "personal_email"]
    )
    return {row.email or row.personal_email for row in rows if row.email or row.personal_email}


def _volunteers_fed_by_chapter(chapter_name, stale_users):
    """Volunteers with an Employee whose approver can depend on this chapter's seats.

    A volunteer's approver comes from their own seat (board), their enabled chapter
    memberships, their teams' chapter, and the national board as the fallback, so the
    national chapter feeds everyone. Anyone whose Employee still names a stale user is
    included so that value is judged too. One query, however many volunteers there are.
    """
    fed = ""
    if not _is_national_chapter(chapter_name):
        stale = "OR e.expense_approver IN %(stale)s" if stale_users else ""
        fed = f"""
            AND (
                v.member IN (
                    SELECT cm.member FROM `tabChapter Member` cm
                    WHERE cm.parent = %(chapter)s AND cm.enabled = 1
                )
                OR v.name IN (
                    SELECT tm.volunteer FROM `tabTeam Member` tm
                    JOIN `tabTeam` t ON t.name = tm.parent
                    WHERE t.chapter = %(chapter)s AND tm.status = 'Active'
                )
                OR v.name IN (
                    SELECT cbm.volunteer FROM `tabChapter Board Member` cbm WHERE cbm.parent = %(chapter)s
                )
                {stale}
            )
        """
    return frappe.db.sql(
        f"""
        SELECT v.name
        FROM `tabVolunteer` v
        JOIN `tabEmployee` e ON e.name = v.employee_id
        WHERE v.employee_id IS NOT NULL AND v.employee_id != ''
        {fed}
        ORDER BY v.name
        """,
        {"chapter": chapter_name, "stale": tuple(stale_users) or ("",)},
        pluck=True,
    )


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
