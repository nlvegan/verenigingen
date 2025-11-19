"""Utility to delete all cancelled and draft Sales Invoices"""

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def validate_cleanup_permissions():
    """
    Strict permission validation for cleanup operations.
    Implements defense-in-depth security checks.
    """
    user = frappe.session.user

    # Level 1: Must be in developer mode
    if frappe.conf.get("developer_mode") != 1:
        frappe.throw(_("Cleanup operations can only be run in developer mode for safety"))

    # Level 2: User must be Administrator or have System Manager role
    if user != "Administrator":
        user_roles = frappe.get_roles()
        required_roles = {"System Manager", "Verenigingen Administrator"}

        if not any(role in user_roles for role in required_roles):
            frappe.throw(
                _(
                    "Insufficient permissions. You need Administrator access or System Manager/Verenigingen Administrator role."
                ),
                frappe.PermissionError,
            )

    # Level 3: Additional validation for destructive operations
    if not frappe.has_permission("Sales Invoice", "delete"):
        frappe.throw(
            _("You don't have delete permissions for Sales Invoice"),
            frappe.PermissionError,
        )

    # Level 4: Log the permission check for audit
    frappe.logger("verenigingen.security").info(
        f"Invoice cleanup permission validation passed for user: {user} with roles: {frappe.get_roles()}"
    )

    return True


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def delete_all_draft_invoices():
    """Delete all draft (unsaved/unsubmitted) sales invoices from the system

    Security: Requires developer mode, System Manager role, and delete permissions.
    """
    # Validate permissions
    validate_cleanup_permissions()

    # Get all draft sales invoices
    draft_invoices = frappe.db.sql(
        """
        SELECT name
        FROM `tabSales Invoice`
        WHERE docstatus = 0
        ORDER BY creation DESC
    """,
        as_dict=True,
    )

    total = len(draft_invoices)
    deleted = 0
    errors = []

    print(f"Found {total} draft sales invoices to delete")

    # Delete in batches
    batch_size = 100
    for i in range(0, total, batch_size):
        batch = draft_invoices[i : i + batch_size]

        for invoice in batch:
            try:
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, ignore_permissions=True)
                deleted += 1
                if deleted % 50 == 0:
                    print(f"Progress: {deleted}/{total} deleted...")
            except Exception as e:
                errors.append(f"{invoice.name}: {str(e)}")

        # Commit each batch
        frappe.db.commit()
        print(f"Committed batch {i//batch_size + 1}/{(total//batch_size) + 1}")

    result = {
        "total": total,
        "deleted": deleted,
        "errors": len(errors),
        "error_samples": errors[:10] if errors else [],
    }

    print(f"\n{'='*60}")
    print(f"Draft Invoice Deletion Summary:")
    print(f"  Total found: {total}")
    print(f"  Successfully deleted: {deleted}")
    print(f"  Errors: {len(errors)}")
    print(f"{'='*60}")

    if errors:
        print("\nFirst 10 errors:")
        for error in errors[:10]:
            print(f"  - {error}")

    return result


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def delete_all_cancelled_invoices():
    """Delete all cancelled sales invoices from the system

    Security: Requires developer mode, System Manager role, and delete permissions.
    """
    # Validate permissions
    validate_cleanup_permissions()

    # Get all cancelled sales invoices
    cancelled_invoices = frappe.db.sql(
        """
        SELECT name
        FROM `tabSales Invoice`
        WHERE docstatus = 2
        ORDER BY creation DESC
    """,
        as_dict=True,
    )

    total = len(cancelled_invoices)
    deleted = 0
    errors = []

    print(f"Found {total} cancelled sales invoices to delete")

    # Delete in batches
    batch_size = 100
    for i in range(0, total, batch_size):
        batch = cancelled_invoices[i : i + batch_size]

        for invoice in batch:
            try:
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, ignore_permissions=True)
                deleted += 1
                if deleted % 50 == 0:
                    print(f"Progress: {deleted}/{total} deleted...")
            except Exception as e:
                errors.append(f"{invoice.name}: {str(e)}")

        # Commit each batch
        frappe.db.commit()
        print(f"Committed batch {i//batch_size + 1}/{(total//batch_size) + 1}")

    result = {
        "total": total,
        "deleted": deleted,
        "errors": len(errors),
        "error_samples": errors[:10] if errors else [],
    }

    print(f"\n{'='*60}")
    print(f"Deletion Summary:")
    print(f"  Total found: {total}")
    print(f"  Successfully deleted: {deleted}")
    print(f"  Errors: {len(errors)}")
    print(f"{'='*60}")

    if errors:
        print("\nFirst 10 errors:")
        for error in errors[:10]:
            print(f"  - {error}")

    return result
