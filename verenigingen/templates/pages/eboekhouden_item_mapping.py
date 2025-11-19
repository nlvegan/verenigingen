import frappe


def get_context(context):
    """Context for the E-boekhouden Item Mapping page"""
    # Check permissions
    if not frappe.has_permission("E-Boekhouden Item Mapping", "read"):
        frappe.throw("You don't have permission to access this page", frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = False

    # Add page title
    context.title = "E-Boekhouden Item Mapping Tool"

    # Get the default company
    settings = frappe.get_single("E-Boekhouden Settings")
    context.default_company = settings.default_company if settings else None

    # Get existing items for dropdown
    context.items = frappe.db.get_all(
        "Item", filters={"is_stock_item": 0}, fields=["name", "item_name"], order_by="item_name"
    )

    return context
