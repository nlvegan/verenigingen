import frappe
from frappe.model.db_query import check_parent_permission as original_check_parent_permission


def override_parent_permission_check():
    def patched_check_parent_permission(parent, doctype=None):
        # Skip permission check for Member and Membership doctypes
        if doctype in ["Member", "Membership"]:
            return
        # Fall back to original function for other doctypes
        return original_check_parent_permission(parent, doctype)

    # Replace the function
    frappe.model.db_query.check_parent_permission = patched_check_parent_permission


# Apply the patch when this module is imported
override_parent_permission_check()
