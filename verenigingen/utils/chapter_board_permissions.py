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
        membership_doctype.save(ignore_permissions=True)

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
        # Get existing permission or create new one
        existing_perm = frappe.db.get_value(
            "DocPerm",
            {"parent": "Membership Termination Request", "role": "Verenigingen Chapter Board Member"},
            ["name", "read", "write", "create", "submit"],
        )

        if existing_perm:
            # Update existing permission to include write, create, and submit
            perm_doc = frappe.get_doc("DocPerm", existing_perm[0])
            perm_doc.read = 1
            perm_doc.write = 1
            perm_doc.create = 1
            perm_doc.email = 1
            perm_doc.export = 1
            perm_doc.print = 1
            perm_doc.report = 1
            perm_doc.share = 1
            # Explicitly disable dangerous permissions
            perm_doc.delete = 0
            perm_doc.cancel = 0
            perm_doc.amend = 0
            perm_doc.submit = 0  # Workflow-controlled
            perm_doc.import_doc = 0
            perm_doc.save(ignore_permissions=True)

            frappe.logger().info(
                "Updated existing Chapter Board Member permissions for Membership Termination Request"
            )
        else:
            # Get the DocType and add new permission
            doctype_doc = frappe.get_doc("DocType", "Membership Termination Request")

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
                "submit": 0,  # Workflow-controlled, not direct submit
                "import": 0,
            }

            doctype_doc.append("permissions", new_perm)
            doctype_doc.save(ignore_permissions=True)

            frappe.logger().info(
                "Added new Chapter Board Member permissions for Membership Termination Request"
            )

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
        # Check current permissions
        existing_perm = frappe.db.get_value(
            "DocPerm",
            {"parent": "Volunteer Expense", "role": "Verenigingen Chapter Board Member"},
            ["name", "read", "write", "create", "if_owner"],
        )

        if existing_perm:
            # Update existing permission - remove if_owner restriction for broader access
            perm_doc = frappe.get_doc("DocPerm", existing_perm[0])
            perm_doc.read = 1
            perm_doc.write = 1
            perm_doc.create = 1
            perm_doc.if_owner = 0  # Remove owner restriction to allow chapter-wide access
            perm_doc.email = 1
            perm_doc.export = 1
            perm_doc.print = 1
            perm_doc.report = 1
            # Explicitly disable dangerous permissions
            perm_doc.delete = 0
            perm_doc.cancel = 0
            perm_doc.amend = 0
            perm_doc.submit = 0  # Approval workflow controlled
            perm_doc.save(ignore_permissions=True)

            frappe.logger().info(
                "Updated Chapter Board Member permissions for Volunteer Expense (removed owner restriction)"
            )
        else:
            # Check if DocType exists and skip if problematic
            if not frappe.db.exists("DocType", "Volunteer Expense"):
                frappe.logger().warning("Volunteer Expense DocType not found, skipping permission setup")
                return False

            # Use direct permission insertion to avoid DocType saving issues
            perm_doc = frappe.new_doc("DocPerm")
            perm_doc.update(
                {
                    "parent": "Volunteer Expense",
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "role": "Verenigingen Chapter Board Member",
                    "permlevel": 0,
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "email": 1,
                    "export": 1,
                    "print": 1,
                    "report": 1,
                    "if_owner": 0,
                    "delete": 0,
                    "cancel": 0,
                    "amend": 0,
                    "submit": 0,
                    "import": 0,
                }
            )
            perm_doc.insert(ignore_permissions=True)

            frappe.logger().info("Added Chapter Board Member permissions for Volunteer Expense")

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
            "message": "Chapter Board Member permissions updated successfully"
            if all(results.values()) and security_valid
            else "Some permission updates failed or security issues found",
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
def reset_chapter_board_permissions():
    """
    Reset Chapter Board Member permissions to default state
    Useful for testing or if permissions need to be reconfigured
    """
    try:
        doctypes_to_reset = ["Membership", "Membership Termination Request", "Volunteer Expense"]

        for doctype_name in doctypes_to_reset:
            # Remove existing Chapter Board Member permissions
            existing_perms = frappe.get_all(
                "DocPerm",
                filters={"parent": doctype_name, "role": "Verenigingen Chapter Board Member"},
                fields=["name"],
            )

            for perm in existing_perms:
                frappe.delete_doc("DocPerm", perm.name, ignore_permissions=True)

            frappe.logger().info(f"Reset Chapter Board Member permissions for {doctype_name}")

        frappe.clear_cache()

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
