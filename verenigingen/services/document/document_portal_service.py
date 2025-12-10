# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
DocumentPortalService - Unified document upload portal service

Handles authorization and document upload for Chapters, Teams, and Movements.

Permission Model:
- Chapter: Must be active board member
- Team: Must be active team member
- Movement: Must be movement member

Architecture Notes:
- Single service combining authorization and upload (per Martin Fowler feedback)
- Uses existing file_storage utilities for hierarchical paths
- Creates Organization Document records for tracking
"""

import base64
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.document_categories import get_category_icon, get_document_category_options


@dataclass
class DocumentUploadRequest:
    """Request object for document uploads"""

    organization_type: str
    organization_name: str
    document_name: str
    document_type: str
    file_name: str
    file_content: str  # Base64 encoded
    content_type: str
    description: Optional[str] = None
    year: Optional[str] = None


@dataclass
class UploadableOrganization:
    """Organization user can upload to"""

    name: str
    organization_type: str
    display_name: str


class DocumentPortalService(StatelessService):
    """
    Unified service for document upload portal operations.

    Combines authorization checking and document upload functionality
    into a single cohesive service.
    """

    # Maximum file size in bytes (10MB)
    MAX_FILE_SIZE = 10 * 1024 * 1024

    # Allowed file extensions
    ALLOWED_EXTENSIONS = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".jpg",
        ".jpeg",
        ".png",
        ".txt",
        ".odt",
        ".ods",
    }

    # Allowed MIME types
    ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/jpeg",
        "image/png",
        "text/plain",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
    }

    # Extension to MIME type mapping for consistency validation
    # Prevents file type spoofing (e.g., .exe renamed to .pdf with spoofed MIME header)
    EXTENSION_MIME_MAP = {
        ".pdf": ["application/pdf"],
        ".doc": ["application/msword"],
        ".docx": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
        ".xls": ["application/vnd.ms-excel"],
        ".xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        ".ppt": ["application/vnd.ms-powerpoint"],
        ".pptx": ["application/vnd.openxmlformats-officedocument.presentationml.presentation"],
        ".jpg": ["image/jpeg"],
        ".jpeg": ["image/jpeg"],
        ".png": ["image/png"],
        ".txt": ["text/plain"],
        ".odt": ["application/vnd.oasis.opendocument.text"],
        ".ods": ["application/vnd.oasis.opendocument.spreadsheet"],
    }

    def __init__(self) -> None:
        """Initialize the document portal service."""
        super().__init__(service_name="DocumentPortalService")

    # =========================================================================
    # Authorization Methods
    # =========================================================================

    def get_upload_context(self, user: str) -> Dict[str, Any]:
        """
        Get organizations where user can upload documents.

        Args:
            user: User email/ID

        Returns:
            Dict containing:
            - success: bool
            - organizations: List of UploadableOrganization grouped by type
            - categories: Available document categories
            - volunteer_name: User's volunteer name (if exists)
            - member_name: User's member name (if exists)
        """
        start_time = self._start_operation("get_upload_context")

        try:
            # Get user's member and volunteer records
            member_name = self._get_member_for_user(user)
            volunteer_name = self._get_volunteer_for_member(member_name) if member_name else None

            organizations = {
                "chapters": [],
                "teams": [],
                "movements": [],
            }

            # Get chapters where user is board member
            if volunteer_name:
                chapters = self._get_user_chapters(volunteer_name)
                organizations["chapters"] = [
                    {"name": c, "display_name": c, "organization_type": "Chapter"} for c in chapters
                ]

                # Get teams where user is active member
                teams = self._get_user_teams(volunteer_name)
                organizations["teams"] = [
                    {"name": t, "display_name": t, "organization_type": "Team"} for t in teams
                ]

            # Get movements where user is member
            if member_name:
                movements = self._get_user_movements(member_name)
                organizations["movements"] = [
                    {"name": m, "display_name": m, "organization_type": "Movement"} for m in movements
                ]

            # Get document categories
            categories_raw = get_document_category_options()
            categories = [
                {"name": cat, "icon": get_category_icon(cat)} for cat in categories_raw.split("\n") if cat
            ]

            self._end_operation("get_upload_context", start_time, success=True)

            return {
                "success": True,
                "organizations": organizations,
                "categories": categories,
                "volunteer_name": volunteer_name,
                "member_name": member_name,
            }

        except Exception as e:
            self._end_operation("get_upload_context", start_time, success=False)
            return self.handle_error(e, "get_upload_context", raise_error=False)

    def can_upload_to(self, user: str, organization_type: str, organization_name: str) -> bool:
        """
        Check if user can upload documents to an organization.

        Args:
            user: User email/ID
            organization_type: Chapter, Team, or Movement
            organization_name: Name of the organization

        Returns:
            True if user can upload, False otherwise
        """
        # Administrators can upload anywhere
        user_roles = frappe.get_roles(user)
        if "System Manager" in user_roles or "Verenigingen Administrator" in user_roles:
            return True

        member_name = self._get_member_for_user(user)
        volunteer_name = self._get_volunteer_for_member(member_name) if member_name else None

        if organization_type == "Chapter":
            return self._is_chapter_board_member(volunteer_name, organization_name)
        elif organization_type == "Team":
            return self._is_team_member(volunteer_name, organization_name)
        elif organization_type == "Movement":
            return self._is_movement_member(member_name, organization_name)

        return False

    def _get_member_for_user(self, user: str) -> Optional[str]:
        """Get member name for a user"""
        return frappe.db.get_value("Member", {"user": user}, "name")

    def _get_volunteer_for_member(self, member_name: str) -> Optional[str]:
        """Get volunteer name for a member"""
        if not member_name:
            return None
        return frappe.db.get_value("Volunteer", {"member": member_name}, "name")

    def _get_user_chapters(self, volunteer_name: str) -> List[str]:
        """Get chapters where user is an active board member"""
        if not volunteer_name:
            return []

        results = frappe.db.sql(
            """
            SELECT DISTINCT parent as name
            FROM `tabChapter Board Member`
            WHERE volunteer = %s AND is_active = 1
            """,
            (volunteer_name,),
            as_dict=True,
        )
        return [r.name for r in results]

    def _get_user_teams(self, volunteer_name: str) -> List[str]:
        """Get teams where user is an active member"""
        if not volunteer_name:
            return []

        results = frappe.db.sql(
            """
            SELECT DISTINCT parent as name
            FROM `tabTeam Member`
            WHERE volunteer = %s AND status = 'Active'
            """,
            (volunteer_name,),
            as_dict=True,
        )
        return [r.name for r in results]

    def _get_user_movements(self, member_name: str) -> List[str]:
        """Get movements where user is a member"""
        if not member_name:
            return []

        results = frappe.db.sql(
            """
            SELECT DISTINCT parent as name
            FROM `tabMovement Member`
            WHERE member = %s
            """,
            (member_name,),
            as_dict=True,
        )
        return [r.name for r in results]

    def _is_chapter_board_member(self, volunteer_name: str, chapter_name: str) -> bool:
        """Check if volunteer is an active board member of the chapter"""
        if not volunteer_name:
            return False

        return bool(
            frappe.db.exists(
                "Chapter Board Member",
                {"parent": chapter_name, "volunteer": volunteer_name, "is_active": 1},
            )
        )

    def _is_team_member(self, volunteer_name: str, team_name: str) -> bool:
        """Check if volunteer is an active member of the team"""
        if not volunteer_name:
            return False

        return bool(
            frappe.db.exists(
                "Team Member",
                {"parent": team_name, "volunteer": volunteer_name, "status": "Active"},
            )
        )

    def _is_movement_member(self, member_name: str, movement_name: str) -> bool:
        """Check if member is a member of the movement"""
        if not member_name:
            return False

        return bool(frappe.db.exists("Movement Member", {"parent": movement_name, "member": member_name}))

    # =========================================================================
    # Document Upload Methods
    # =========================================================================

    def upload_document(self, request: DocumentUploadRequest) -> Dict[str, Any]:
        """
        Upload a document to an organization.

        Args:
            request: DocumentUploadRequest with upload details

        Returns:
            Dict containing:
            - success: bool
            - document_name: Name of created Organization Document
            - file_url: URL of uploaded file
            - message: Success or error message
        """
        start_time = self._start_operation("upload_document")

        try:
            user = frappe.session.user

            # 1. Authorization re-validation (defense in depth)
            if not self.can_upload_to(user, request.organization_type, request.organization_name):
                self._end_operation("upload_document", start_time, success=False)
                self._log_security_event(
                    "upload_permission_denied",
                    user=user,
                    organization_type=request.organization_type,
                    organization_name=request.organization_name,
                )
                return {
                    "success": False,
                    "error": "permission_denied",
                    "message": _("You do not have permission to upload documents to this organization"),
                }

            # 2. Check for duplicate document
            duplicate = self._check_duplicate_document(request)
            if duplicate:
                self._end_operation("upload_document", start_time, success=False)
                return {
                    "success": False,
                    "error": "duplicate_document",
                    "message": _("A document with this name already exists for this organization"),
                    "existing_document": duplicate,
                }

            # 3. Validate file
            validation_result = self._validate_file(request)
            if not validation_result["valid"]:
                self._end_operation("upload_document", start_time, success=False)
                # Log validation failures as potential exploit attempts
                self._log_security_event(
                    "upload_validation_failed",
                    user=user,
                    organization_type=request.organization_type,
                    organization_name=request.organization_name,
                    details={
                        "error": validation_result["error"],
                        "file_name": request.file_name,
                        "content_type": request.content_type,
                    },
                )
                return {
                    "success": False,
                    "error": validation_result["error"],
                    "message": validation_result["message"],
                }

            # 4. Decode file content
            try:
                file_content = base64.b64decode(request.file_content)
            except Exception as decode_error:
                self._end_operation("upload_document", start_time, success=False)
                # Log decode failures as potential exploit attempts
                self._log_security_event(
                    "upload_decode_failed",
                    user=user,
                    organization_type=request.organization_type,
                    organization_name=request.organization_name,
                    details={
                        "file_name": request.file_name,
                        "error": str(decode_error),
                    },
                )
                return {
                    "success": False,
                    "error": "invalid_encoding",
                    "message": _("File content could not be decoded"),
                }

            # 5. Extract year from document name
            year = request.year or self._extract_year(request.document_name)

            # 6. Save file to hierarchical storage
            from verenigingen.utils.file_storage import save_organization_document

            file_result = save_organization_document(
                content=file_content,
                filename=request.file_name,
                organization_type=request.organization_type,
                organization_name=request.organization_name,
                category=request.document_type,
                year=year,
                is_private=1,
            )

            # 7. Create Organization Document record
            org_doc = frappe.get_doc(
                {
                    "doctype": "Organization Document",
                    "organization_type": request.organization_type,
                    request.organization_type.lower(): request.organization_name,
                    "document_name": request.document_name,
                    "document_type": request.document_type,
                    "document_file": file_result["file_url"],
                    "description": request.description,
                    "upload_date": today(),
                    "uploaded_by": user,
                }
            )
            org_doc.insert()

            self._end_operation("upload_document", start_time, success=True)

            return {
                "success": True,
                "document_name": org_doc.name,
                "file_url": file_result["file_url"],
                "message": _("Document uploaded successfully"),
            }

        except Exception as e:
            self._end_operation("upload_document", start_time, success=False)
            self._log_security_event(
                "upload_failed",
                user=frappe.session.user,
                organization_type=request.organization_type,
                organization_name=request.organization_name,
                details={"error": str(e)},
            )
            return {
                "success": False,
                "error": "server_error",
                "message": _("An error occurred while uploading the document"),
            }

    def _validate_file(self, request: DocumentUploadRequest) -> Dict[str, Any]:
        """
        Validate file before upload.

        Returns:
            Dict with 'valid' boolean and optional 'error'/'message'
        """
        # Check file name
        if not request.file_name:
            return {"valid": False, "error": "missing_filename", "message": _("File name is required")}

        # Check file extension
        file_ext = os.path.splitext(request.file_name.lower())[1]
        if file_ext not in self.ALLOWED_EXTENSIONS:
            allowed_list = ", ".join(sorted(self.ALLOWED_EXTENSIONS))
            return {
                "valid": False,
                "error": "invalid_file_type",
                "message": _("File type '{0}' is not allowed. Accepted: {1}").format(file_ext, allowed_list),
            }

        # Check MIME type if provided
        if request.content_type and request.content_type not in self.ALLOWED_MIME_TYPES:
            return {
                "valid": False,
                "error": "invalid_mime_type",
                "message": _("File content type not recognized"),
            }

        # Check extension/MIME type consistency to prevent file type spoofing
        # e.g., someone uploading malware.exe as document.pdf with spoofed MIME header
        if request.content_type:
            expected_mimes = self.EXTENSION_MIME_MAP.get(file_ext, [])
            if expected_mimes and request.content_type not in expected_mimes:
                return {
                    "valid": False,
                    "error": "mime_extension_mismatch",
                    "message": _(
                        "File type mismatch: extension '{0}' does not match content type '{1}'"
                    ).format(file_ext, request.content_type),
                }

        # Check file size (base64 encoded is ~33% larger)
        if request.file_content:
            # Approximate decoded size
            encoded_size = len(request.file_content)
            estimated_size = encoded_size * 3 / 4  # Base64 decodes to 3/4 the size

            if estimated_size > self.MAX_FILE_SIZE:
                return {
                    "valid": False,
                    "error": "file_too_large",
                    "message": _("File size exceeds {0}MB limit").format(self.MAX_FILE_SIZE // (1024 * 1024)),
                }

        return {"valid": True}

    def _extract_year(self, document_name: str) -> str:
        """Extract year from document name, or return current year"""
        if document_name:
            year_match = re.search(r"\b(20\d{2})\b", document_name)
            if year_match:
                return year_match.group(1)
        return str(frappe.utils.now_datetime().year)

    def _check_duplicate_document(self, request: DocumentUploadRequest) -> Optional[str]:
        """
        Check if a document with the same name already exists for this organization.

        Uses case-insensitive matching and whitespace normalization to catch
        near-duplicates like "Annual Report 2024" vs "annual  report  2024".

        Args:
            request: DocumentUploadRequest with document details

        Returns:
            Existing document name if duplicate found, None otherwise
        """
        # Normalize document name for comparison
        normalized_name = self._normalize_document_name(request.document_name)

        # Query existing documents for this organization
        org_field = request.organization_type.lower()

        # Get all documents for this org and check normalized names
        existing_docs = frappe.db.get_all(
            "Organization Document",
            filters={
                "organization_type": request.organization_type,
                org_field: request.organization_name,
            },
            fields=["name", "document_name"],
        )

        for doc in existing_docs:
            if self._normalize_document_name(doc.document_name) == normalized_name:
                return doc.name

        return None

    def _normalize_document_name(self, name: str) -> str:
        """
        Normalize document name for duplicate comparison.

        - Lowercase
        - Collapse multiple whitespaces to single space
        - Strip leading/trailing whitespace

        Args:
            name: Document name to normalize

        Returns:
            Normalized name for comparison
        """
        if not name:
            return ""
        # Lowercase, collapse whitespace, strip
        return " ".join(name.lower().split())

    def _log_security_event(
        self,
        event_type: str,
        user: str = None,
        organization_type: str = None,
        organization_name: str = None,
        details: Dict[str, Any] = None,
    ):
        """
        Log security events for audit trail.

        Args:
            event_type: Type of security event (e.g., 'upload_permission_denied')
            user: User who triggered the event
            organization_type: Type of organization involved
            organization_name: Name of organization involved
            details: Additional details to log
        """
        try:
            log_message = (
                f"Document Portal Security Event: {event_type} | "
                f"User: {user or frappe.session.user} | "
                f"Org: {organization_type}/{organization_name}"
            )

            if details:
                log_message += f" | Details: {details}"

            frappe.logger("security").info(log_message)

            # Also log to Error Log for visibility in desk
            # Security-relevant events that admins should see
            high_visibility_events = (
                "upload_permission_denied",
                "upload_failed",
                "upload_validation_failed",
                "upload_decode_failed",
            )
            if event_type in high_visibility_events:
                frappe.log_error(
                    message=log_message,
                    title=f"Document Portal: {event_type}",
                )
        except Exception:
            pass  # Don't fail on logging errors

    # =========================================================================
    # Document Query Methods
    # =========================================================================

    def get_organization_documents(
        self, organization_type: str, organization_name: str, user: str = None
    ) -> Dict[str, Any]:
        """
        Get documents for an organization.

        Args:
            organization_type: Chapter, Team, or Movement
            organization_name: Name of the organization
            user: Optional user for permission filtering

        Returns:
            Dict containing:
            - success: bool
            - documents: List of documents grouped by category and year
            - total_count: Total number of documents
        """
        start_time = self._start_operation("get_organization_documents")

        try:
            # Build filters
            filters = {
                "organization_type": organization_type,
                organization_type.lower(): organization_name,
            }

            # Get documents
            documents = frappe.get_all(
                "Organization Document",
                filters=filters,
                fields=[
                    "name",
                    "document_name",
                    "document_type",
                    "document_file",
                    "description",
                    "upload_date",
                    "uploaded_by",
                ],
                order_by="document_type asc, upload_date desc",
            )

            # Group by category and year
            grouped = {}
            for doc in documents:
                category = doc.document_type or "Other"
                year = self._extract_year(doc.document_name)

                if category not in grouped:
                    grouped[category] = {"icon": get_category_icon(category), "years": {}}

                if year not in grouped[category]["years"]:
                    grouped[category]["years"][year] = []

                grouped[category]["years"][year].append(doc)

            self._end_operation("get_organization_documents", start_time, success=True)

            return {
                "success": True,
                "documents": grouped,
                "total_count": len(documents),
            }

        except Exception as e:
            self._end_operation("get_organization_documents", start_time, success=False)
            return self.handle_error(e, "get_organization_documents", raise_error=False)


# Singleton instance
_document_portal_service: Optional[DocumentPortalService] = None


def get_document_portal_service() -> DocumentPortalService:
    """Get singleton instance of DocumentPortalService"""
    global _document_portal_service
    if _document_portal_service is None:
        _document_portal_service = DocumentPortalService()
    return _document_portal_service
