# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Document Browser Portal - Context Handler

Provides context for the organization document browser portal page.
Allows members to browse and download documents they have access to.
"""

import frappe
from frappe import _

from verenigingen.services.document.document_portal_service import get_document_portal_service
from verenigingen.utils.document_categories import get_category_icon, get_document_category_options


def get_context(context):
    """
    Get context for document browser portal page.

    Sets up:
    - User authentication check
    - Organizations user can view documents from
    - Document categories for filtering
    - Recent documents preview
    """
    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to browse documents"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = True
    context.title = _("Browse Documents")

    # Get browsable documents from service
    service = get_document_portal_service()

    # Get initial documents (recent 20)
    browse_result = service.get_all_accessible_documents(
        user=frappe.session.user,
        limit=20,
        offset=0,
    )

    if not browse_result.get("success"):
        context.error_message = browse_result.get("message", _("Unable to load documents"))
        context.organizations = []
        context.documents = []
        context.categories = []
        context.has_documents = False
        context.total_count = 0
        return context

    # Set context variables
    context.organizations = browse_result.get("organizations", [])
    context.total_count = browse_result.get("total_count", 0)
    context.has_documents = context.total_count > 0

    # Serialize dates for JSON in template
    from verenigingen.templates.pages import serialize_dates

    context.documents = serialize_dates(browse_result.get("documents", []))

    # Get document categories for filter dropdown
    categories_raw = get_document_category_options()
    context.categories = [
        {"name": cat, "icon": get_category_icon(cat)} for cat in categories_raw.split("\n") if cat
    ]

    # Group organizations by type for filter dropdowns
    context.org_types = []
    org_by_type = {}
    for org in context.organizations:
        org_type = org.get("organization_type")
        if org_type not in org_by_type:
            org_by_type[org_type] = []
            context.org_types.append(org_type)
        org_by_type[org_type].append(org)
    context.organizations_by_type = org_by_type

    # Check if user can upload to any organization (for showing upload link)
    upload_context = service.get_upload_context(frappe.session.user)
    if upload_context.get("success"):
        upload_orgs = upload_context.get("organizations", {})
        context.can_upload = (
            len(upload_orgs.get("chapters", []))
            + len(upload_orgs.get("teams", []))
            + len(upload_orgs.get("movements", []))
        ) > 0
    else:
        context.can_upload = False

    # Get preselected filters from query params
    context.preselected_org_type = frappe.form_dict.get("org_type", "")
    context.preselected_org_name = frappe.form_dict.get("org_name", "")
    context.preselected_category = frappe.form_dict.get("category", "")

    return context
