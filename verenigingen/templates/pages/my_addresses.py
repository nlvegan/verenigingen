import frappe
from frappe import _


def get_context(context):
    """Get context for my addresses portal page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    # Get member record by email OR user field (same logic as address_change)
    member_name = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
    if not member_name:
        member_name = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

    if not member_name:
        frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)

    # Get member document (may need ignore_permissions for portal users)
    try:
        context.member = frappe.get_doc("Member", member_name)
    except frappe.PermissionError:
        context.member = frappe.get_doc("Member", member_name, ignore_permissions=True)

    # Get current address if exists (same logic as address_change)
    current_address = None
    if context.member.primary_address:
        try:
            current_address = frappe.get_doc("Address", context.member.primary_address)
        except frappe.PermissionError:
            # If permission denied, use database access
            try:
                current_address = frappe.get_doc(
                    "Address", context.member.primary_address, ignore_permissions=True
                )
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
