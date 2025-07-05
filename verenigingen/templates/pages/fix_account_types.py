import frappe


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False

    # Check if user has permission
    if not frappe.has_permission("Account", "write"):
        frappe.throw("You do not have permission to fix account types", frappe.PermissionError)

    return context
