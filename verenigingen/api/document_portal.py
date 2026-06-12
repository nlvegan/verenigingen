# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Document Portal API

Whitelisted API endpoints for the organization document upload portal.
"""

import json

import frappe
from frappe import _

from verenigingen.services.document.document_portal_service import (
    DocumentUploadRequest,
    get_document_portal_service,
)
from verenigingen.utils.security.api_security_framework import standard_api
from verenigingen.utils.security.types import OperationType

# Input length limits to prevent DoS via large payloads
MAX_NAME_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 1000


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_upload_context():
    """
    Get organizations where current user can upload documents.

    Returns:
        dict: Upload context with organizations, categories, and user info
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": False,
            "error": "authentication_required",
            "message": _("Please log in to access the document portal"),
        }

    service = get_document_portal_service()
    return service.get_upload_context(user)


@frappe.whitelist()
@standard_api(
    operation_type=OperationType.MEMBER_DATA, max_request_size=15 * 1024 * 1024
)  # 15MB for 10MB file + base64 overhead
def upload_document(
    organization_type,
    organization_name: str,
    document_name: str,
    document_type: str,
    file_name: str,
    file_content,
    content_type=None,
    description=None,
    year=None,
):
    """
    Upload a document to an organization.

    Args:
        organization_type: Chapter, Team, or Movement
        organization_name: Name of the organization
        document_name: Human-readable document name
        document_type: Category (Policy, Meeting Minutes, etc.)
        file_name: Original filename
        file_content: Base64 encoded file content
        content_type: MIME type (optional)
        description: Document description (optional)
        year: Document year (optional, auto-extracted from name)

    Returns:
        dict: Result with document_name and file_url on success
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": False,
            "error": "authentication_required",
            "message": _("Please log in to upload documents"),
        }

    # Validate required fields
    if not all([organization_type, organization_name, document_name, document_type, file_name, file_content]):
        return {
            "success": False,
            "error": "missing_required_fields",
            "message": _("Missing required fields"),
        }

    # Validate organization type
    if organization_type not in ["Chapter", "Team", "Movement"]:
        return {
            "success": False,
            "error": "invalid_organization_type",
            "message": _("Invalid organization type"),
        }

    # Validate field lengths to prevent DoS
    if len(document_name) > MAX_NAME_LENGTH:
        return {
            "success": False,
            "error": "document_name_too_long",
            "message": _("Document name too long (max {0} characters)").format(MAX_NAME_LENGTH),
        }

    if len(organization_name) > MAX_NAME_LENGTH:
        return {
            "success": False,
            "error": "organization_name_too_long",
            "message": _("Organization name too long (max {0} characters)").format(MAX_NAME_LENGTH),
        }

    if len(file_name) > MAX_NAME_LENGTH:
        return {
            "success": False,
            "error": "file_name_too_long",
            "message": _("File name too long (max {0} characters)").format(MAX_NAME_LENGTH),
        }

    if description and len(description) > MAX_DESCRIPTION_LENGTH:
        return {
            "success": False,
            "error": "description_too_long",
            "message": _("Description too long (max {0} characters)").format(MAX_DESCRIPTION_LENGTH),
        }

    # Create request object
    request = DocumentUploadRequest(
        organization_type=organization_type,
        organization_name=organization_name,
        document_name=document_name,
        document_type=document_type,
        file_name=file_name,
        file_content=file_content,
        content_type=content_type or "",
        description=description,
        year=year,
    )

    service = get_document_portal_service()
    return service.upload_document(request)


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_organization_documents(organization_type, organization_name: str):
    """
    Get documents for an organization.

    Args:
        organization_type: Chapter, Team, or Movement
        organization_name: Name of the organization

    Returns:
        dict: Documents grouped by category and year
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": False,
            "error": "authentication_required",
            "message": _("Please log in to view documents"),
        }

    # Validate organization type
    if organization_type not in ["Chapter", "Team", "Movement"]:
        return {
            "success": False,
            "error": "invalid_organization_type",
            "message": _("Invalid organization type"),
        }

    service = get_document_portal_service()

    # Check if user can view documents (same check as upload - member of org)
    if not service.can_upload_to(user, organization_type, organization_name):
        return {
            "success": False,
            "error": "permission_denied",
            "message": _("You do not have permission to view documents for this organization"),
        }

    return service.get_organization_documents(organization_type, organization_name, user)


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def can_upload_to_organization(organization_type, organization_name: str):
    """
    Check if current user can upload to an organization.

    Args:
        organization_type: Chapter, Team, or Movement
        organization_name: Name of the organization

    Returns:
        dict: Result with 'can_upload' boolean
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": True,
            "can_upload": False,
        }

    service = get_document_portal_service()
    can_upload = service.can_upload_to(user, organization_type, organization_name)

    return {
        "success": True,
        "can_upload": can_upload,
    }


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_browsable_documents(
    org_type=None,
    organization=None,
    category=None,
    search_term=None,
    limit=50,
    offset=0,
):
    """
    Get all documents the current user has permission to view.

    View permissions are broader than upload permissions:
    - Chapters: User is chapter member, OR chapter is published, OR national chapter
    - Teams: User is team member
    - Movements: User is movement member

    Args:
        org_type: Filter by organization type (Chapter/Team/Movement)
        organization: Filter by specific organization name
        category: Filter by document_type
        search_term: Search in document_name
        limit: Max results (default 50, max 100)
        offset: Pagination offset

    Returns:
        dict: Documents list with pagination info and accessible organizations
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": False,
            "error": "authentication_required",
            "message": _("Please log in to browse documents"),
        }

    # Validate and sanitize pagination
    try:
        limit = min(int(limit), 100)  # Cap at 100
        offset = max(int(offset), 0)
    except (ValueError, TypeError):
        limit = 50
        offset = 0

    # Validate org_type if provided
    if org_type and org_type not in ["Chapter", "Team", "Movement"]:
        return {
            "success": False,
            "error": "invalid_org_type",
            "message": _("Invalid organization type"),
        }

    # Validate search term length
    if search_term and len(search_term) > MAX_NAME_LENGTH:
        return {
            "success": False,
            "error": "search_term_too_long",
            "message": _("Search term too long (max {0} characters)").format(MAX_NAME_LENGTH),
        }

    service = get_document_portal_service()
    return service.get_all_accessible_documents(
        user=user,
        org_type=org_type,
        organization=organization,
        category=category,
        search_term=search_term,
        limit=limit,
        offset=offset,
    )


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def delete_document(document_name: str):
    """
    Delete an organization document.

    Args:
        document_name: Name of the Organization Document to delete

    Returns:
        dict: Result with success status and message
    """
    user = frappe.session.user

    if user == "Guest":
        return {
            "success": False,
            "error": "authentication_required",
            "message": _("Please log in to delete documents"),
        }

    if not document_name:
        return {
            "success": False,
            "error": "missing_document_name",
            "message": _("Document name is required"),
        }

    if len(document_name) > MAX_NAME_LENGTH:
        return {
            "success": False,
            "error": "document_name_too_long",
            "message": _("Document name too long"),
        }

    service = get_document_portal_service()
    return service.delete_document(document_name)
