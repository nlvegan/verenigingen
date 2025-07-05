import frappe
from frappe import _


def get_context(context):
    # Check if user is logged in
    if frappe.session.user == "Guest":
        frappe.throw(_("You need to be logged in to access this page"), frappe.PermissionError)

    # Check if user has appropriate permissions
    is_member = frappe.db.exists("Has Role", {"parent": frappe.session.user, "role": "Verenigingen Member"})
    is_admin = frappe.db.exists(
        "Has Role",
        {
            "parent": frappe.session.user,
            "role": ["in", ["System Manager", "Verenigingen Manager", "Verenigingen Administrator"]],
        },
    )

    if not is_member and not is_admin:
        frappe.throw(_("You don't have permission to access this page"), frappe.PermissionError)

    # Get member parameter from URL if admin is viewing
    member_param = frappe.form_dict.get("member")

    if is_admin and member_param:
        # Admin viewing specific member's dashboard
        if frappe.db.exists("Member", member_param):
            context.member = member_param
            context.viewing_as_admin = True
            member_doc = frappe.get_doc("Member", member_param)
            context.member_name = member_doc.full_name
        else:
            frappe.throw(_("Member {0} not found").format(member_param), frappe.DoesNotExistError)
    else:
        # Get member record for logged in user
        member = frappe.db.get_value("Member", {"email": frappe.session.user}, "name")
        if not member:
            member = frappe.db.get_value("Member", {"user": frappe.session.user}, "name")

        if not member and is_member:
            frappe.throw(_("No member record found for your account"), frappe.DoesNotExistError)
        elif not member and is_admin:
            # Admin without member record - show member selection
            context.show_member_selection = True
            context.members = frappe.get_all(
                "Member", fields=["name", "full_name", "email"], order_by="full_name"
            )
        else:
            context.member = member

    context.title = _("Payment Dashboard")
    context.is_admin = is_admin

    # Add brand CSS
    context.brand_css = "/brand_css"

    return context
