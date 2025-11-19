import frappe


def get_context(context):
    """
    Context for the generate test data page
    """
    # Check if user has permission to create members
    if not frappe.has_permission("Member", "create"):
        frappe.throw("You don't have permission to access this page", frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = False

    # Add any additional context if needed
    context.update(
        {
            "title": "Generate Test Data",
            "description": "Generate test membership applications for Verenigingen",
        }
    )

    return context
