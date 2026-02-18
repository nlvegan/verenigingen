# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Document Upload Portal - Context Handler

Provides context for the organization document upload portal page.
"""

import frappe
from frappe import _

from verenigingen.services.document.document_portal_service import get_document_portal_service
from verenigingen.utils.document_categories import get_category_icon, get_document_category_options


def get_context(context):
    """
    Get context for document upload portal page.

    Sets up:
    - User authentication check
    - Organizations user can upload to (chapters, teams, movements)
    - Document categories
    - Error handling for users without proper access
    """
    # Require login
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to access the document upload portal"), frappe.PermissionError)

    context.no_cache = 1
    context.show_sidebar = False
    context.title = _("Upload Documents")

    # Get upload context from service
    service = get_document_portal_service()
    upload_context = service.get_upload_context(frappe.session.user)

    if not upload_context.get("success"):
        context.error_message = upload_context.get("message", _("Unable to load upload context"))
        context.organizations = {"chapters": [], "teams": [], "movements": []}
        context.categories = []
        context.has_organizations = False
        return context

    # Set context variables
    context.organizations = upload_context.get("organizations", {})
    context.categories = upload_context.get("categories", [])
    context.volunteer_name = upload_context.get("volunteer_name")
    context.member_name = upload_context.get("member_name")

    # Check if user has any organizations to upload to
    total_orgs = (
        len(context.organizations.get("chapters", []))
        + len(context.organizations.get("teams", []))
        + len(context.organizations.get("movements", []))
    )
    context.has_organizations = total_orgs > 0

    if not context.has_organizations:
        context.error_message = _(
            "You are not a board member of any chapter, team member of any team, "
            "or member of any movement. You cannot upload documents."
        )

    # Get preselected organization from query params (for links from dashboards)
    context.preselected_org_type = frappe.form_dict.get("org_type", "")
    context.preselected_org_name = frappe.form_dict.get("org_name", "")

    # Get existing documents for preselected organization
    context.existing_documents = None
    if context.preselected_org_type and context.preselected_org_name:
        try:
            docs_result = service.get_organization_documents(
                context.preselected_org_type, context.preselected_org_name, frappe.session.user
            )
            if docs_result.get("success"):
                context.existing_documents = docs_result.get("documents", {})
                context.existing_documents_count = docs_result.get("total_count", 0)
        except Exception:
            # Don't fail page load if documents can't be fetched
            pass

    return context
