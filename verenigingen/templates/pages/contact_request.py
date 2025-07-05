"""
Member Contact Request Portal Page
Allows members to submit contact requests which integrate with CRM
"""

import frappe
from frappe import _


def get_context(context):
    """Get context for contact request page"""

    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access this page"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Contact Request")

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        # Show a graceful error message instead of throwing
        context.no_member_record = True
        context.error_title = _("Member Record Not Found")
        context.error_message = _(
            "No member record found for your account. You need to be a member to submit contact requests."
        )
        # Try to get support email from settings, with fallback
        try:
            context.support_email = frappe.db.get_single_value("Verenigingen Settings", "support_email")
        except Exception:
            # If field doesn't exist, try company email or use default
            try:
                company = frappe.db.get_single_value("Verenigingen Settings", "company")
                if company:
                    context.support_email = (
                        frappe.db.get_value("Company", company, "email") or "support@example.com"
                    )
                else:
                    context.support_email = "support@example.com"
            except Exception:
                context.support_email = "support@example.com"
        return context

    context.member = frappe.get_doc("Member", member)
    context.no_member_record = False

    # Get recent contact requests
    context.recent_requests = get_recent_contact_requests(member)

    # Get request types for dropdown
    context.request_types = [
        "General Inquiry",
        "Membership Question",
        "Donation Information",
        "Volunteer Opportunity",
        "Event Information",
        "Complaint",
        "Compliment",
        "Technical Support",
        "Other",
    ]

    context.urgency_levels = ["Low", "Normal", "High", "Urgent"]

    context.contact_methods = ["Email", "Phone", "Either"]

    return context


def has_website_permission(doc, ptype, user, verbose=False):
    """Check website permission for contact request page"""
    # Only logged-in users can access
    if user == "Guest":
        return False

    # Check if user has a member record
    member = frappe.db.get_value("Member", {"email": user})
    return bool(member)


def get_recent_contact_requests(member_name, limit=5):
    """Get recent contact requests for member"""

    requests = frappe.get_all(
        "Member Contact Request",
        filters={"member": member_name},
        fields=["name", "subject", "request_type", "status", "request_date", "response_date", "urgency"],
        order_by="request_date desc",
        limit=limit,
    )

    return requests


@frappe.whitelist()
def submit_contact_request():
    """Handle contact request form submission"""

    # Validate user access
    if frappe.session.user == "Guest":
        frappe.throw(_("Authentication required"))

    # Get form data
    data = frappe.form_dict

    # Get member record
    member = frappe.db.get_value("Member", {"email": frappe.session.user})
    if not member:
        frappe.throw(_("No member record found for your account"))

    # Validate required fields
    required_fields = ["subject", "message", "request_type"]
    for field in required_fields:
        if not data.get(field):
            frappe.throw(_("Field '{0}' is required").format(_(field.replace("_", " ").title())))

    try:
        # Create contact request using the API method from the module
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            create_contact_request,
        )

        result = create_contact_request(
            member=member,
            subject=data.get("subject"),
            message=data.get("message"),
            request_type=data.get("request_type", "General Inquiry"),
            preferred_contact_method=data.get("preferred_contact_method", "Email"),
            urgency=data.get("urgency", "Normal"),
            preferred_time=data.get("preferred_time"),
        )

        frappe.response["message"] = {
            "success": True,
            "title": _("Contact Request Submitted"),
            "message": result.get("message"),
            "redirect": "/contact_request?submitted=1",
        }

    except Exception as e:
        frappe.log_error(f"Error creating contact request: {str(e)}", "Contact Request Error")
        frappe.response["message"] = {
            "success": False,
            "title": _("Error"),
            "message": _("An error occurred while submitting your request. Please try again."),
        }
