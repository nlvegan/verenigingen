import frappe
from frappe import _

from verenigingen.utils.member_utils import get_current_user_member_name


def get_context(context):
    """Get context for my addresses portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Get member record using standardized utility
    member_name = get_current_user_member_name()
    if not member_name:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    # Get member document (may need ignore_permissions for portal users)
    try:
        context.member = frappe.get_doc("Member", member_name)
    except frappe.PermissionError:
        # CORRECTED SECURE VERSION: Verify member ownership and use proper permissions
        member_data = frappe.db.get_value("Member", member_name, ["user", "email"], as_dict=True)
        if not member_data or (
            member_data.user != frappe.session.user and member_data.email != frappe.session.user
        ):
            frappe.throw(
                _("Access denied: You can only access your own member record"), frappe.PermissionError
            )

        context.member = frappe.get_doc("Member", member_name)
        if not frappe.has_permission("Member", "read", context.member):
            frappe.throw(_("Access denied to member record"), frappe.PermissionError)

    # Get current address if exists (same logic as address_change)
    current_address = None
    if context.member.primary_address:
        try:
            current_address = frappe.get_doc("Address", context.member.primary_address)
        except frappe.PermissionError:
            # If permission denied, use database access
            try:
                # Verify address belongs to member before access
                if not frappe.has_permission("Address", "read", context.member.primary_address):
                    frappe.throw(_("Access denied to address record"), frappe.PermissionError)

                current_address = frappe.get_doc("Address", context.member.primary_address)
            except frappe.DoesNotExistError:
                # Address was deleted, clear the reference
                frappe.db.set_value("Member", member_name, "primary_address", None)
                frappe.db.commit()
        except frappe.DoesNotExistError:
            # Address was deleted, clear the reference
            frappe.db.set_value("Member", member_name, "primary_address", None)
            frappe.db.commit()

    context.current_address = current_address

    # Format address for display using Dutch conventions
    if current_address:
        from verenigingen.utils.address_formatter import format_address_for_country

        context.address_display = format_address_for_country(current_address)
    else:
        context.address_display = None

    context.page_title = _("My Addresses")
    context.parent_template = "templates/web.html"

    return context
