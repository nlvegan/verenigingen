"""
Setup Background Service Permissions
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_background_service_permissions():
    """Setup permissions for background service role to handle membership applications"""
    role_name = "Verenigingen Background Service"

    # Define permissions needed for membership application processing
    permissions_config = {
        "Member": {"read": 1, "write": 1, "create": 1, "delete": 0},
        "Customer": {"read": 1, "write": 1, "create": 1, "delete": 0},
        "Address": {"read": 1, "write": 1, "create": 1, "delete": 0},
        "Volunteer": {"read": 1, "write": 1, "create": 1, "delete": 0},
        "Chapter": {"read": 1, "write": 0, "create": 0, "delete": 0},
        "Membership Type": {"read": 1, "write": 0, "create": 0, "delete": 0},
    }

    results = []

    for doctype, perms in permissions_config.items():
        # Check if permission already exists
        existing = frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role_name})

        if existing:
            # Update existing permission
            doc = frappe.get_doc("Custom DocPerm", existing)
            doc.read = perms["read"]
            doc.write = perms["write"]
            doc.create = perms["create"]
            doc.delete = perms["delete"]
            doc.submit = 0
            doc.cancel = 0
            doc.amend = 0
            doc.save(ignore_permissions=True)
            results.append(f"Updated {doctype} permissions")
        else:
            # Create new permission
            frappe.get_doc({
                "doctype": "Custom DocPerm",
                "parent": doctype,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role_name,
                "read": perms["read"],
                "write": perms["write"],
                "create": perms["create"],
                "delete": perms["delete"],
                "submit": 0,
                "cancel": 0,
                "amend": 0,
            }).insert(ignore_permissions=True)
            results.append(f"Created {doctype} permissions")

    frappe.db.commit()
    return f"Background service permissions setup complete:\n" + "\n".join(results)
