import frappe


def execute():
    """Add National Board Member role if it doesn't exist"""
    if not frappe.db.exists("Role", "National Board Member"):
        role = frappe.get_doc(
            {"doctype": "Role", "role_name": "National Board Member", "desk_access": 1, "disabled": 0}
        )
        role.insert(ignore_permissions=True)
        frappe.db.commit()
        print("Created National Board Member role")
