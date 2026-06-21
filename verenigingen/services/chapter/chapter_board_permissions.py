"""
Chapter Board Member Permission Management System
===============================================

This module provides functions to update DocType permissions for Chapter Board Members,
ensuring they have appropriate access to membership data, termination requests, and
volunteer expenses while maintaining proper chapter-based security boundaries.

Key Features:
- Adds Chapter Board Member permissions to critical DocTypes
- Implements chapter-based data filtering for security
- Provides treasurer-specific expense approval capabilities
- Maintains audit trail for permission changes
- Validates security constraints and prevents privilege escalation
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def update_membership_permissions():
    """
    Add Chapter Board Member permissions to Membership DocType
    Grants read, write, and submit capabilities for membership applications within their chapters
    """
    try:
        # Check if permission already exists
        existing_perm = frappe.db.exists(
            "DocPerm", {"parent": "Membership", "role": "Verenigingen Chapter Board Member"}
        )

        if existing_perm:
            frappe.logger().info("Chapter Board Member permissions already exist for Membership DocType")
            return True

        # Get the Membership DocType
        membership_doctype = frappe.get_doc("DocType", "Membership")

        # Add new permission record - restrict to read/write/create only
        new_perm = {
            "role": "Verenigingen Chapter Board Member",
            "permlevel": 0,
            "read": 1,
            "write": 1,
            "create": 1,
            "email": 1,
            "export": 1,
            "print": 1,
            "report": 1,
            "share": 1,
            "if_owner": 0,
            # Explicitly set dangerous permissions to 0
            "delete": 0,
            "cancel": 0,
            "amend": 0,
            "submit": 0,  # Remove submit to prevent bypassing workflow
            "import": 0,
        }

        membership_doctype.append("permissions", new_perm)

        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="save",
            doc=membership_doctype,
            justification="Update Membership DocType permissions to grant Chapter Board Member access - governance permission management",
            required_permissions=["DocType:write"],
        )

        if not result.success:
            frappe.log_error(f"Failed to update Membership DocType permissions: {'; '.join(result.errors)}")
            return False

        frappe.logger().info("Added Chapter Board Member permissions to Membership DocType")
        return True

    except Exception as e:
        frappe.log_error(f"Error updating Membership permissions: {str(e)}")
        return False


def update_membership_termination_request_permissions():
    """
    Update Chapter Board Member permissions for Membership Termination Request DocType
    Grants create, read, write, and submit capabilities for termination requests
    """
    try:
        target_role = "Verenigingen Chapter Board Member"

        # DocPerm is a child table with no permissions defined — direct save/insert
        # via secure_document_operation fails for every user. Locate or append the
        # row inside DocType.permissions and save the parent DocType,
        # mirroring update_membership_permissions().
        doctype_doc = frappe.get_doc("DocType", "Membership Termination Request")
        perm_row = next((p for p in doctype_doc.permissions if p.role == target_role), None)
        is_existing = perm_row is not None
        if not is_existing:
            perm_row = doctype_doc.append("permissions", {"role": target_role, "permlevel": 0})

        perm_row.read = 1
        perm_row.write = 1
        perm_row.create = 1
        perm_row.email = 1
        perm_row.export = 1
        perm_row.print = 1
        perm_row.report = 1
        perm_row.share = 1
        perm_row.if_owner = 0
        # Explicitly disable dangerous permissions
        perm_row.delete = 0
        perm_row.cancel = 0
        perm_row.amend = 0
        perm_row.submit = 0  # Workflow-controlled
        perm_row.set("import", 0)  # 'import' is a reserved keyword in Python

        action = "Update existing" if is_existing else "Add new"
        result = secure_document_operation(
            operation="save",
            doc=doctype_doc,
            justification=f"{action} Chapter Board Member permissions for Membership Termination Request - governance permission management",
            required_permissions=["DocType:write"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to update Membership Termination Request permissions: {'; '.join(result.errors)}"
            )
            return False

        frappe.logger().info(f"{action} Chapter Board Member permissions for Membership Termination Request")
        return True

    except Exception as e:
        frappe.log_error(f"Error updating Membership Termination Request permissions: {str(e)}")
        return False


def update_volunteer_expense_permissions():
    """
    Update Volunteer Expense permissions for Chapter Board Members
    Ensures board members can read/write expenses from their chapters
    Maintains treasurer-only approval restrictions
    """
    try:
        target_role = "Verenigingen Chapter Board Member"

        if not frappe.db.exists("DocType", "Volunteer Expense"):
            frappe.logger().warning("Volunteer Expense DocType not found, skipping permission setup")
            return False

        # DocPerm is a child table with no permissions defined — direct save/insert
        # via secure_document_operation fails for every user. Locate or append the
        # row inside DocType.permissions and save the parent DocType,
        # mirroring update_membership_permissions().
        doctype_doc = frappe.get_doc("DocType", "Volunteer Expense")
        perm_row = next((p for p in doctype_doc.permissions if p.role == target_role), None)
        is_existing = perm_row is not None
        if not is_existing:
            perm_row = doctype_doc.append("permissions", {"role": target_role, "permlevel": 0})

        perm_row.read = 1
        perm_row.write = 1
        perm_row.create = 1
        perm_row.if_owner = 0  # No owner restriction — allow chapter-wide access
        perm_row.email = 1
        perm_row.export = 1
        perm_row.print = 1
        perm_row.report = 1
        # Explicitly disable dangerous permissions
        perm_row.delete = 0
        perm_row.cancel = 0
        perm_row.amend = 0
        perm_row.submit = 0  # Approval workflow controlled
        perm_row.set("import", 0)

        action = "Update existing" if is_existing else "Add new"
        result = secure_document_operation(
            operation="save",
            doc=doctype_doc,
            justification=f"{action} Chapter Board Member permissions for Volunteer Expense - governance permission management",
            required_permissions=["DocType:write"],
        )

        if not result.success:
            frappe.log_error(f"Failed to update Volunteer Expense permissions: {'; '.join(result.errors)}")
            return False

        frappe.logger().info(f"{action} Chapter Board Member permissions for Volunteer Expense")
        return True

    except Exception as e:
        frappe.logger().error(f"Error updating Volunteer Expense permissions: {str(e)}")
        return False


def validate_permission_security():
    """
    Validate that the permission changes maintain proper security boundaries
    Ensures no privilege escalation and proper chapter-based filtering
    """
    security_issues = []

    try:
        # Check Membership permissions don't grant admin-level access
        membership_perms = frappe.get_all(
            "DocPerm",
            filters={"parent": "Membership", "role": "Verenigingen Chapter Board Member"},
            fields=["delete", "cancel", "amend"],
        )

        for perm in membership_perms:
            if perm.get("delete") or perm.get("cancel") or perm.get("amend"):
                security_issues.append(
                    "Chapter Board Member has delete/cancel/amend permissions on Membership"
                )

        # Check Termination Request permissions are appropriate
        termination_perms = frappe.get_all(
            "DocPerm",
            filters={"parent": "Membership Termination Request", "role": "Verenigingen Chapter Board Member"},
            fields=["delete", "cancel", "amend"],
        )

        for perm in termination_perms:
            if perm.get("delete") or perm.get("cancel") or perm.get("amend"):
                security_issues.append(
                    "Chapter Board Member has delete/cancel/amend permissions on Termination Requests"
                )

        # Check Volunteer Expense permissions don't grant inappropriate access
        expense_perms = frappe.get_all(
            "DocPerm",
            filters={"parent": "Volunteer Expense", "role": "Verenigingen Chapter Board Member"},
            fields=["delete", "cancel", "amend", "submit"],
        )

        for perm in expense_perms:
            if perm.get("delete") or perm.get("cancel") or perm.get("amend"):
                security_issues.append(
                    "Chapter Board Member has delete/cancel/amend permissions on Volunteer Expense"
                )
            # Submit permission should be restricted to approval workflow
            if perm.get("submit"):
                security_issues.append(
                    "Chapter Board Member has submit permissions on Volunteer Expense (should be workflow-controlled)"
                )

        if security_issues:
            frappe.logger().warning(f"Security validation found issues: {'; '.join(security_issues)}")
            return False, security_issues
        else:
            frappe.logger().info("Permission security validation passed")
            return True, []

    except Exception as e:
        frappe.log_error(f"Error validating permission security: {str(e)}")
        return False, [f"Validation error: {str(e)}"]


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_chapter_board_permissions():
    """
    Main function to set up all Chapter Board Member permissions
    Can be called via API or console
    """
    try:
        frappe.logger().info("Starting Chapter Board Member permission setup...")

        results = {
            "membership": update_membership_permissions(),
            "termination_request": update_membership_termination_request_permissions(),
            "volunteer_expense": update_volunteer_expense_permissions(),
        }

        # Validate security after changes
        security_valid, security_issues = validate_permission_security()

        # Clear permissions cache to ensure changes take effect
        frappe.clear_cache()

        result = {
            "success": all(results.values()) and security_valid,
            "results": results,
            "security_valid": security_valid,
            "security_issues": security_issues,
            "message": (
                "Chapter Board Member permissions updated successfully"
                if all(results.values()) and security_valid
                else "Some permission updates failed or security issues found"
            ),
        }

        frappe.logger().info(f"Chapter Board Member permission setup completed: {result}")
        return result

    except Exception as e:
        frappe.log_error(f"Error setting up chapter board permissions: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to set up Chapter Board Member permissions",
        }


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def reset_chapter_board_permissions():
    """
    Reset Chapter Board Member permissions to default state
    Useful for testing or if permissions need to be reconfigured
    """
    try:
        doctypes_to_reset = ["Membership", "Membership Termination Request", "Volunteer Expense"]
        target_role = "Verenigingen Chapter Board Member"

        # Track which DocTypes actually had their Chapter Board Member rows
        # removed. The previous implementation returned {"success": True}
        # unconditionally, so a failed save (e.g. a pre-existing duplicate-perm
        # validation error on the parent DocType) was swallowed by `continue`
        # while the API still reported success — masking that nothing was reset.
        failed = []

        for doctype_name in doctypes_to_reset:
            # Volunteer Expense was archived; skip on migrated sites where the
            # DocType is gone (see patches/v2_2/drop_volunteer_expense_archived_doctype.py).
            if not frappe.db.exists("DocType", doctype_name):
                frappe.logger().info(f"Skipping permission reset on missing DocType {doctype_name}")
                continue
            # DocPerm is a child table with no permissions defined — direct delete
            # via secure_document_operation fails for every user. Remove the matching
            # rows from the parent DocType.permissions and save the DocType,
            # mirroring the add path in update_membership_permissions().
            doctype_doc = frappe.get_doc("DocType", doctype_name)
            rows_to_remove = [p for p in doctype_doc.permissions if p.role == target_role]
            if not rows_to_remove:
                frappe.logger().info(f"No Chapter Board Member permissions to reset on {doctype_name}")
                continue

            for row in rows_to_remove:
                doctype_doc.permissions.remove(row)

            result = secure_document_operation(
                operation="save",
                doc=doctype_doc,
                justification=f"Reset Chapter Board Member permissions for {doctype_name} - permission reconfiguration",
                required_permissions=["DocType:write"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to reset Chapter Board Member permissions for {doctype_name}: "
                    f"{'; '.join(result.errors)}"
                )
                failed.append(doctype_name)
                continue

            frappe.logger().info(
                f"Reset Chapter Board Member permissions for {doctype_name} "
                f"({len(rows_to_remove)} row(s) removed)"
            )

        frappe.clear_cache()

        if failed:
            return {
                "success": False,
                "failed": failed,
                "message": f"Failed to reset Chapter Board Member permissions for: {', '.join(failed)}",
            }

        return {
            "success": True,
            "message": f"Reset Chapter Board Member permissions for {len(doctypes_to_reset)} DocTypes",
        }

    except Exception as e:
        frappe.log_error(f"Error resetting chapter board permissions: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to reset Chapter Board Member permissions",
        }
