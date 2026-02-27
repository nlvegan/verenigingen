"""
Department Approver Sync Hooks

Syncs Chapter Board Member changes to Department.expense_approvers
for native ERPNext Expense Claim approval workflow.

When a chapter board member is added, updated, or removed, this module
synchronizes the chapter's financial officers (Treasurer, Financial Officer,
Secretary-Treasurer, Board Chair) to the corresponding Department's
expense_approvers child table.

This enables the native HRMS Expense Claim approval workflow to use
chapter-based approvers as a fallback when Employee.expense_approver
is not set.

Author: Verenigingen Development Team
"""

import frappe


def on_board_member_change(doc, method):
    """
    Sync department approvers when board member changes.

    Triggered on after_insert, on_update, on_trash of Chapter Board Member.

    Only syncs when the changed board member has a financial role
    (Treasurer, Financial Officer, Secretary-Treasurer, Board Chair).

    Args:
        doc: Chapter Board Member document
        method: Hook method name (after_insert, on_update, on_trash)
    """
    try:
        # Get parent chapter from the board member's parent field
        chapter_name = doc.parent
        if not chapter_name:
            frappe.logger().debug(f"Department approver sync: No parent chapter for board member {doc.name}")
            return

        # Only sync if this is a financial role
        financial_roles = get_financial_roles()
        if doc.chapter_role not in financial_roles:
            frappe.logger().debug(
                f"Department approver sync: {doc.chapter_role} is not a financial role, skipping sync"
            )
            return

        # Sync this chapter's approvers
        frappe.logger().info(
            f"Department approver sync: Syncing approvers for chapter {chapter_name} "
            f"due to {method} of board member with role {doc.chapter_role}"
        )

        sync_chapter_department_approvers(chapter_name)

    except Exception as e:
        frappe.log_error(
            f"Department approver sync failed for board member {doc.name}: {str(e)}",
            "Department Approver Sync",
        )


def get_financial_roles():
    """
    Get list of chapter roles that have financial approval authority.

    Returns:
        list: Role names that can approve expenses
    """
    return ["Treasurer", "Financial Officer", "Secretary-Treasurer", "Board Chair"]


def sync_chapter_department_approvers(chapter_name):
    """
    Sync approvers for a single chapter to its department.

    Looks up financial board members and updates the corresponding
    Department.expense_approvers child table.

    Args:
        chapter_name: Name of the chapter to sync
    """
    from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

    try:
        manager = DepartmentHierarchyManager()
        manager.sync_chapter_approvers_for_chapter(chapter_name)
    except Exception as e:
        frappe.log_error(
            f"Failed to sync department approvers for chapter {chapter_name}: {str(e)}",
            "Department Approver Sync",
        )


def sync_all_department_approvers():
    """
    Sync department approvers for all chapters.

    Called by scheduled task as a safety net to ensure
    department approvers stay in sync with chapter board members.

    Returns:
        dict: Summary of sync operation
    """
    from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

    try:
        manager = DepartmentHierarchyManager()
        manager.sync_all_approvers()

        return {"success": True, "message": "Department approvers synced successfully"}
    except Exception as e:
        frappe.log_error(
            f"Failed to sync all department approvers: {str(e)}", "Department Approver Sync Scheduled Task"
        )
        return {"success": False, "error": str(e)}
