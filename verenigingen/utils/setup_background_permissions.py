"""
Setup Background Service Permissions
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_background_service_permissions():
    """Setup permissions for background service role"""
    role_name = "Verenigingen Background Service"

    # Create permission for Member doctype
    if not frappe.db.exists("Custom DocPerm", {"parent": "Member", "role": role_name}):
        # Create the permission record
        frappe.get_doc(
            {
                "doctype": "Custom DocPerm",
                "parent": "Member",
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role_name,
                "read": 1,
                "write": 1,
                "create": 0,
                "delete": 0,
                "submit": 0,
                "cancel": 0,
                "amend": 0,
            }
        ).insert(ignore_permissions=True)

        frappe.db.commit()
        return f"Created Member permissions for {role_name}"
    else:
        return f"Member permissions already exist for {role_name}"
