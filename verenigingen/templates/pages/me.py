import frappe
from frappe import _


def get_context(context):
    """Enhanced /me portal page with submenu items"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Get enhanced portal menu for both sidebar and main content
    from verenigingen.utils.portal_menu_enhancer import generate_portal_menu_html, get_user_portal_menu

    menu_data = get_user_portal_menu()
    if menu_data["success"]:
        # For main content area
        context.menu_items = menu_data["menu_items"]

        # For sidebar with submenu items
        context.sidebar_items = menu_data["menu_items"]
        context.show_sidebar = True

        # Generate HTML for the main content menu
        html_data = generate_portal_menu_html()
        if html_data["success"]:
            context.enhanced_menu_html = html_data["html"]
        else:
            context.enhanced_menu_html = "<p>Error loading menu</p>"
    else:
        context.menu_items = []
        context.sidebar_items = []
        context.show_sidebar = False
        context.enhanced_menu_html = "<p>Error loading menu</p>"

    # Get user info
    context.user_email = frappe.session.user

    # Try to get member info
    member = frappe.db.get_value(
        "Member", {"email": frappe.session.user}, ["name", "first_name", "last_name"]
    )
    if member:
        context.member_name = f"{member[1]} {member[2]}" if len(member) > 2 and member[2] else member[1]
        context.is_member = True
    else:
        context.member_name = frappe.session.user
        context.is_member = False

    context.page_title = _("Portal")
    context.parent_template = "templates/base_portal.html"

    return context
