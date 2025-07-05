"""
My Account Page - Account Settings and Information
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for my account page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access your account"), frappe.PermissionError)

    # Basic context setup
    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("My Account")
    context.page_title = _("Account Settings")

    try:
        # Get member record
        member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        if not member_name:
            member_name = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

        if member_name:
            # Get member document with error handling
            try:
                context.member = frappe.get_doc("Member", member_name)
            except frappe.PermissionError:
                context.member = frappe.get_doc("Member", member_name, ignore_permissions=True)
        else:
            context.member = None
            context.error_message = _("No member record found for your account")

        # Get current user details safely
        try:
            user_doc = frappe.get_doc("User", frappe.session.user)

            # Set individual context variables instead of nested object
            context.user_email = frappe.session.user
            context.user_type = getattr(user_doc, "user_type", "Website User")
            context.user_enabled = getattr(user_doc, "enabled", 1)
            context.user_first_name = getattr(user_doc, "first_name", "")
            context.user_last_name = getattr(user_doc, "last_name", "")
            context.last_login = getattr(user_doc, "last_login", None)
            context.last_active = getattr(user_doc, "last_active", None)
            context.has_user_info = True

        except Exception as e:
            frappe.log_error(f"Error getting user details: {str(e)}")
            context.has_user_info = False
            context.user_email = frappe.session.user
            context.user_type = "Unknown"
            context.user_enabled = False

        # Portal navigation links
        context.portal_links = [
            {"title": _("Member Portal"), "route": "/member_portal", "active": False},
            {"title": _("Dashboard"), "route": "/member_dashboard", "active": False},
            {"title": _("Account Settings"), "route": "/member_portal", "active": True},
            {"title": _("Update Address"), "route": "/address_change", "active": False},
            {"title": _("Bank Details"), "route": "/bank_details", "active": False},
            {"title": _("Personal Details"), "route": "/personal_details", "active": False},
        ]

    except Exception as e:
        frappe.log_error(f"Error in my_account context: {str(e)}")
        context.error_message = _("An error occurred while loading your account information")
        context.member = None
        context.user = None

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for my account page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user}) or frappe.db.get_value("Member", {"user": user})
    return bool(member)
