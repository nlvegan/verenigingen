"""
Add necessary permissions for Chapter Board Members to access related DocTypes
"""
import frappe


def execute():
    """Grant Chapter Board Members read access to Address, Customer, and Page"""

    # Address - needed to view member addresses
    add_permission_if_missing("Address", "Verenigingen Chapter Board Member", read=1)

    # Customer - needed for ERPNext integration (members linked to customers)
    add_permission_if_missing("Customer", "Verenigingen Chapter Board Member", read=1)

    # Page - needed for custom pages like member portals
    add_permission_if_missing("Page", "Verenigingen Chapter Board Member", read=1)

    frappe.db.commit()
    print("Chapter Board Member permissions added successfully")


def add_permission_if_missing(doctype, role, **permissions):
    """Add permission if it doesn't already exist"""

    # Check if permission already exists
    existing = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role}, "name")

    if existing:
        # Update existing permission
        doc = frappe.get_doc("Custom DocPerm", existing)
        for key, value in permissions.items():
            setattr(doc, key, value)
        doc.save()
        print(f"Updated {role} permissions for {doctype}")
    else:
        # Create new permission
        frappe.get_doc(
            {
                "doctype": "Custom DocPerm",
                "parent": doctype,
                "parenttype": "DocType",
                "parentfield": "permissions",
                "role": role,
                "permlevel": 0,
                **permissions,
            }
        ).insert(ignore_permissions=True)
        print(f"Added {role} permissions for {doctype}")
