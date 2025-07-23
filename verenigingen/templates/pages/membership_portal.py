import frappe
from frappe import _


def get_context(context):
    """Get context for enhanced portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Get enhanced portal menu
    from verenigingen.utils.portal_menu_enhancer import generate_portal_menu_html, get_user_portal_menu

    menu_data = get_user_portal_menu()
    if menu_data["success"]:
        context.menu_items = menu_data["menu_items"]

        # Generate HTML for the menu
        html_data = generate_portal_menu_html()
        if html_data["success"]:
            context.enhanced_menu_html = html_data["html"]
        else:
            context.enhanced_menu_html = "<p>Error loading menu</p>"
    else:
        context.menu_items = []
        context.enhanced_menu_html = "<p>Error loading menu</p>"

    context.page_title = _("Portal")
    context.parent_template = "templates/web.html"

    return context
