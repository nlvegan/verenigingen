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
import hashlib
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

    # Whitelist of allowed organization field names (SQL injection prevention)
    ALLOWED_ORG_FIELDS = {"chapter", "team", "movement"}

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

            # Get movements where user is member (via volunteer record)
            if volunteer_name:
                movements = self._get_user_movements(volunteer_name)
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
            return self._is_movement_member(volunteer_name, organization_name)

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

    def _get_user_movements(self, volunteer_name: str) -> List[str]:
        """Get movements where user is a member (via volunteer record)"""
        if not volunteer_name:
            return []

        results = frappe.db.sql(
            """
            SELECT DISTINCT parent as name
            FROM `tabMovement Member`
            WHERE volunteer = %s
            """,
            (volunteer_name,),
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

    def _is_movement_member(self, volunteer_name: str, movement_name: str) -> bool:
        """Check if volunteer is a member of the movement"""
        if not volunteer_name:
            return False

        return bool(
            frappe.db.exists("Movement Member", {"parent": movement_name, "volunteer": volunteer_name})
        )

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

            # 5. Compute file hash and check for content duplicates
            file_hash = self._compute_file_hash(file_content)

            # Validate hash integrity (defensive check)
            if not file_hash or not re.match(r"^[a-f0-9]{64}$", file_hash):
                self._end_operation("upload_document", start_time, success=False)
                self._log_security_event(
                    "invalid_file_hash",
                    user=user,
                    organization_type=request.organization_type,
                    organization_name=request.organization_name,
                    details={"file_name": request.file_name, "hash": file_hash},
                )
                return {
                    "success": False,
                    "error": "hash_computation_failed",
                    "message": _("File integrity check failed"),
                }

            duplicate_by_hash = self._check_duplicate_hash(
                file_hash, request.organization_type, request.organization_name
            )
            if duplicate_by_hash:
                self._end_operation("upload_document", start_time, success=False)
                return {
                    "success": False,
                    "error": "duplicate_content",
                    "message": _("This file has already been uploaded as '{0}'").format(duplicate_by_hash),
                    "existing_document": duplicate_by_hash,
                }

            # 6. Extract year from document name
            year = request.year or self._extract_year(request.document_name)

            # 7. Save file to hierarchical storage
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

            # 8. Clean document title and create Organization Document record
            cleaned_title = self._clean_document_title(request.document_name)
            org_doc = frappe.get_doc(
                {
                    "doctype": "Organization Document",
                    "organization_type": request.organization_type,
                    request.organization_type.lower(): request.organization_name,
                    "document_name": cleaned_title,
                    "document_type": request.document_type,
                    "document_file": file_result["file_url"],
                    "description": request.description,
                    "upload_date": today(),
                    "uploaded_by": user,
                    "file_hash": file_hash,
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

    def delete_document(self, document_name: str) -> Dict[str, Any]:
        """
        Delete an organization document.

        Args:
            document_name: Name of the Organization Document to delete

        Returns:
            Dict containing:
            - success: bool
            - message: Success or error message
        """
        start_time = self._start_operation("delete_document")

        try:
            user = frappe.session.user

            # 1. Get the document
            if not frappe.db.exists("Organization Document", document_name):
                self._end_operation("delete_document", start_time, success=False)
                return {
                    "success": False,
                    "error": "not_found",
                    "message": _("Document not found"),
                }

            doc = frappe.get_doc("Organization Document", document_name)

            # 2. Get organization details from document
            org_type = doc.organization_type
            if org_type == "Chapter":
                org_name = doc.chapter
            elif org_type == "Team":
                org_name = doc.team
            elif org_type == "Movement":
                org_name = doc.movement
            else:
                org_name = None

            # 3. Check permission (same as upload permission)
            if not self.can_upload_to(user, org_type, org_name):
                self._end_operation("delete_document", start_time, success=False)
                self._log_security_event(
                    "delete_permission_denied",
                    user=user,
                    organization_type=org_type,
                    organization_name=org_name,
                    details={"document_name": document_name},
                )
                return {
                    "success": False,
                    "error": "permission_denied",
                    "message": _("You do not have permission to delete documents from this organization"),
                }

            # 4. Delete the associated file
            if doc.document_file:
                file_doc = frappe.db.get_value("File", {"file_url": doc.document_file}, "name")
                if file_doc:
                    frappe.delete_doc("File", file_doc, ignore_permissions=True)

            # 5. Delete the Organization Document
            doc_display_name = doc.document_name  # Store for message before deletion
            frappe.delete_doc("Organization Document", document_name, ignore_permissions=True)

            self._end_operation("delete_document", start_time, success=True)

            return {
                "success": True,
                "message": _("Document '{0}' deleted successfully").format(doc_display_name),
            }

        except Exception as e:
            self._end_operation("delete_document", start_time, success=False)
            self._log_security_event(
                "delete_failed",
                user=frappe.session.user,
                details={"document_name": document_name, "error": str(e)},
            )
            return {
                "success": False,
                "error": "server_error",
                "message": _("An error occurred while deleting the document"),
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
        """Extract year from document name, or return current year.

        Handles multiple formats:
        - YYYYMMDD at start of filename (e.g., 20230128-document.pdf)
        - Standalone year with word boundaries (e.g., Report 2023.pdf)
        """
        if document_name:
            # First try YYYYMMDD format at start of filename
            date_match = re.search(r"^(20\d{2})\d{4}", document_name)
            if date_match:
                return date_match.group(1)
            # Then try standalone year with word boundaries
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

    def _clean_document_title(self, title: str) -> str:
        """
        Clean document title by replacing obvious space replacements.

        If the title contains only dashes or underscores as separators (no actual spaces),
        replace them with regular spaces for readability. Only applies to Latin-script
        filenames to preserve CJK and other scripts where separators may be intentional.

        Examples:
            "20250524-Intern-Bulletin-39" → "20250524 Intern Bulletin 39"
            "Annual_Report_2024" → "Annual Report 2024"
            "Report - 2024" → "Report - 2024" (unchanged - already has spaces)
            "年度報告_2024" → "年度報告_2024" (unchanged - non-Latin script)
            "---" → "---" (unchanged - would produce empty result)

        Args:
            title: Original document title

        Returns:
            Cleaned title with space replacements normalized
        """
        if not title:
            return title

        # Check for ANY whitespace (Unicode-aware), not just ASCII space
        # This preserves intentional formatting in titles that already have spacing
        if any(c.isspace() for c in title):
            return title

        # Only apply cleanup to titles containing ASCII letters (Latin script)
        # Preserves CJK and other scripts where - or _ may be intentional separators
        if not re.search(r"[a-zA-Z]", title):
            return title

        # Only clean if title contains separators
        if "-" not in title and "_" not in title:
            return title

        # Replace dashes and underscores with spaces
        cleaned = title.replace("-", " ").replace("_", " ")

        # Collapse multiple spaces to single space and strip
        cleaned = " ".join(cleaned.split())

        # If cleanup produces empty result, preserve original (edge case: "---" or "___")
        if not cleaned:
            return title

        return cleaned

    def _compute_file_hash(self, file_content: bytes) -> str:
        """
        Compute SHA256 hash of file content for duplicate detection.

        Args:
            file_content: Raw file bytes

        Returns:
            Hex-encoded SHA256 hash string
        """
        return hashlib.sha256(file_content).hexdigest()

    def _check_duplicate_hash(
        self, file_hash: str, organization_type: str, organization_name: str
    ) -> Optional[str]:
        """
        Check if a document with the same file hash already exists for this organization.

        Args:
            file_hash: SHA256 hash of the file content
            organization_type: Chapter, Team, or Movement
            organization_name: Name of the organization

        Returns:
            Existing document name if duplicate found, None otherwise
        """
        org_field = organization_type.lower()

        existing_doc = frappe.db.get_value(
            "Organization Document",
            filters={
                "organization_type": organization_type,
                org_field: organization_name,
                "file_hash": file_hash,
            },
            fieldname=["name", "document_name"],
            as_dict=True,
        )

        if existing_doc:
            return existing_doc.document_name

        return None

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

    # =========================================================================
    # Document Browsing Methods (View Permissions)
    # =========================================================================

    def get_all_accessible_documents(
        self,
        user: str,
        org_type: Optional[str] = None,
        organization: Optional[str] = None,
        category: Optional[str] = None,
        search_term: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """
        Get all documents the user has permission to view.

        View Permission Model:
        - Chapter: User is active chapter member, OR chapter is published, OR chapter is national
        - Team: User is active team member
        - Movement: User is movement member

        Args:
            user: User email/ID
            org_type: Filter by organization type (Chapter/Team/Movement)
            organization: Filter by specific organization name
            category: Filter by document_type
            search_term: Search in document_name
            limit: Max results to return
            offset: Results offset for pagination

        Returns:
            Dict containing:
            - success: bool
            - documents: List of document dicts
            - total_count: Total count (for pagination)
            - organizations: List of accessible organizations
        """
        start_time = self._start_operation("get_all_accessible_documents")

        try:
            # Get user's access context
            member_name = self._get_member_for_user(user)
            volunteer_name = self._get_volunteer_for_member(member_name) if member_name else None
            user_roles = frappe.get_roles(user)
            is_admin = "System Manager" in user_roles or "Verenigingen Administrator" in user_roles
            is_member = "Verenigingen Member" in user_roles

            # Get accessible organizations
            accessible_orgs = self._get_viewable_organizations(
                user=user,
                member_name=member_name,
                volunteer_name=volunteer_name,
                is_admin=is_admin,
                is_member=is_member,
            )

            # Build document query filters
            filter_values = []

            # Organization type filter
            if org_type:
                if org_type not in ["Chapter", "Team", "Movement"]:
                    return {
                        "success": False,
                        "error": "invalid_org_type",
                        "message": _("Invalid organization type"),
                    }
                # Filter accessible orgs by type
                type_orgs = [o for o in accessible_orgs if o["organization_type"] == org_type]
                if not type_orgs:
                    self._end_operation("get_all_accessible_documents", start_time, success=True)
                    return {
                        "success": True,
                        "documents": [],
                        "total_count": 0,
                        "organizations": accessible_orgs,
                    }
                accessible_orgs = type_orgs

            # Specific organization filter
            if organization:
                org_match = [o for o in accessible_orgs if o["name"] == organization]
                if not org_match:
                    self._end_operation("get_all_accessible_documents", start_time, success=True)
                    return {
                        "success": True,
                        "documents": [],
                        "total_count": 0,
                        "organizations": accessible_orgs,
                    }
                accessible_orgs = org_match

            # Build OR conditions for accessible organizations
            org_conditions = []
            for org in accessible_orgs:
                org_field = org["organization_type"].lower()
                # Whitelist validation to prevent SQL injection
                if org_field not in self.ALLOWED_ORG_FIELDS:
                    continue
                org_conditions.append(f"(organization_type = %s AND {org_field} = %s)")
                filter_values.extend([org["organization_type"], org["name"]])

            if not org_conditions:
                self._end_operation("get_all_accessible_documents", start_time, success=True)
                return {
                    "success": True,
                    "documents": [],
                    "total_count": 0,
                    "organizations": [],
                }

            where_clause = f"({' OR '.join(org_conditions)})"

            # Category filter
            if category:
                where_clause += " AND document_type = %s"
                filter_values.append(category)

            # Search filter - searches document name and organization names
            if search_term:
                search_pattern = f"%{search_term}%"
                where_clause += (
                    " AND (document_name LIKE %s OR chapter LIKE %s OR team LIKE %s OR movement LIKE %s)"
                )
                filter_values.extend([search_pattern, search_pattern, search_pattern, search_pattern])

            # Get total count
            count_query = f"""
                SELECT COUNT(*) as count
                FROM `tabOrganization Document`
                WHERE {where_clause}
            """
            total_count = frappe.db.sql(count_query, filter_values, as_dict=True)[0].count

            # Get documents with pagination
            doc_query = f"""
                SELECT
                    name,
                    document_name,
                    document_type,
                    document_file,
                    description,
                    upload_date,
                    uploaded_by,
                    organization_type,
                    chapter,
                    team,
                    movement
                FROM `tabOrganization Document`
                WHERE {where_clause}
                ORDER BY upload_date DESC
                LIMIT %s OFFSET %s
            """
            filter_values.extend([limit, offset])
            documents = frappe.db.sql(doc_query, filter_values, as_dict=True)

            # Add organization name and icon to each document
            for doc in documents:
                doc["organization_name"] = doc.get(doc["organization_type"].lower()) or ""
                doc["category_icon"] = get_category_icon(doc.get("document_type") or "Other")

            self._end_operation("get_all_accessible_documents", start_time, success=True)

            return {
                "success": True,
                "documents": documents,
                "total_count": total_count,
                "organizations": accessible_orgs,
            }

        except Exception as e:
            self._end_operation("get_all_accessible_documents", start_time, success=False)
            return self.handle_error(e, "get_all_accessible_documents", raise_error=False)

    def _get_viewable_organizations(
        self,
        user: str,
        member_name: Optional[str],
        volunteer_name: Optional[str],
        is_admin: bool,
        is_member: bool,
    ) -> List[Dict[str, str]]:
        """
        Get all organizations the user can view documents from.

        View permissions differ from upload permissions:
        - Chapters: Any chapter member, OR published chapters for any member, OR national chapter
        - Teams: Any team member
        - Movements: Any movement member
        - Admins: All organizations

        Returns:
            List of dicts with name, organization_type, display_name
        """
        organizations = []

        # Get settings for national chapter
        national_chapter = None
        try:
            national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        except Exception:
            pass

        if is_admin:
            # Admins can view all
            for org_type, table in [
                ("Chapter", "Chapter"),
                ("Team", "Team"),
                ("Movement", "Movement"),
            ]:
                orgs = frappe.db.get_all(table, fields=["name"], pluck="name")
                organizations.extend(
                    [{"name": o, "organization_type": org_type, "display_name": o} for o in orgs]
                )
            return organizations

        # Chapters: member's chapters + published chapters + national chapter
        viewable_chapters = set()

        # 1. Chapters where user is a member (via Chapter Member child table)
        if member_name:
            member_chapters = frappe.db.sql(
                """
                SELECT DISTINCT parent as name
                FROM `tabChapter Member`
                WHERE member = %s AND status = 'Active' AND enabled = 1
                """,
                (member_name,),
                as_dict=True,
            )
            viewable_chapters.update(c.name for c in member_chapters)

        # 2. Published chapters (if user has Verenigingen Member role)
        if is_member:
            published_chapters = frappe.db.get_all(
                "Chapter",
                filters={"published": 1},
                fields=["name"],
                pluck="name",
            )
            viewable_chapters.update(published_chapters)

            # 3. National chapter (always visible to members)
            if national_chapter:
                viewable_chapters.add(national_chapter)

        organizations.extend(
            [{"name": c, "organization_type": "Chapter", "display_name": c} for c in viewable_chapters]
        )

        # Teams: where user is active team member
        if volunteer_name:
            teams = self._get_user_teams(volunteer_name)
            organizations.extend([{"name": t, "organization_type": "Team", "display_name": t} for t in teams])

        # Movements: where user is movement member (via volunteer record)
        if volunteer_name:
            movements = self._get_user_movements(volunteer_name)
            organizations.extend(
                [{"name": m, "organization_type": "Movement", "display_name": m} for m in movements]
            )

        return organizations

    def can_view_organization_documents(
        self, user: str, organization_type: str, organization_name: str
    ) -> bool:
        """
        Check if user can view documents from an organization.

        View permissions (broader than upload):
        - Chapter: Member of chapter, OR chapter is published, OR chapter is national
        - Team: Team member
        - Movement: Movement member
        - Admins: Always

        Args:
            user: User email/ID
            organization_type: Chapter, Team, or Movement
            organization_name: Name of the organization

        Returns:
            True if user can view, False otherwise
        """
        user_roles = frappe.get_roles(user)

        # Admins can view anything
        if "System Manager" in user_roles or "Verenigingen Administrator" in user_roles:
            return True

        member_name = self._get_member_for_user(user)
        volunteer_name = self._get_volunteer_for_member(member_name) if member_name else None
        is_member = "Verenigingen Member" in user_roles

        if organization_type == "Chapter":
            # Check if user is chapter member
            if member_name:
                is_chapter_member = frappe.db.exists(
                    "Chapter Member",
                    {
                        "parent": organization_name,
                        "member": member_name,
                        "status": "Active",
                        "enabled": 1,
                    },
                )
                if is_chapter_member:
                    return True

            # Check if chapter is published (for any member)
            if is_member:
                is_published = frappe.db.get_value("Chapter", organization_name, "published")
                if is_published:
                    return True

                # Check if it's the national chapter
                national_chapter = frappe.db.get_single_value(
                    "Verenigingen Settings", "national_board_chapter"
                )
                if organization_name == national_chapter:
                    return True

            return False

        elif organization_type == "Team":
            return self._is_team_member(volunteer_name, organization_name)

        elif organization_type == "Movement":
            return self._is_movement_member(volunteer_name, organization_name)

        return False


# Singleton instance
_document_portal_service: Optional[DocumentPortalService] = None


def get_document_portal_service() -> DocumentPortalService:
    """Get singleton instance of DocumentPortalService"""
    global _document_portal_service
    if _document_portal_service is None:
        _document_portal_service = DocumentPortalService()
    return _document_portal_service


def get_organization_documents_for_template(
    organization_type: str,
    organization_name: str,
) -> Dict[str, Any]:
    """
    Get organization documents formatted for template display.

    This is a convenience function that combines fetching documents from
    the DocumentPortalService with formatting them for template consumption.

    Args:
        organization_type: "Chapter", "Team", or "Movement"
        organization_name: Name of the organization

    Returns:
        Dict with:
            - by_type_and_year: {category: {year: [docs]}}
            - total_count: int
            - category_icons: {category: icon}
    """
    from collections import defaultdict

    from verenigingen.utils.document_categories import get_document_category_options

    try:
        # Get available categories (default + custom)
        available_categories = {}
        for category in get_document_category_options():
            available_categories[category] = get_category_icon(category)

        # Use DocumentPortalService to get documents
        service = get_document_portal_service()
        try:
            result = service.get_organization_documents(
                organization_type=organization_type,
                organization_name=organization_name,
            )
        except Exception as service_error:
            frappe.log_error(
                f"DocumentPortalService error for {organization_name}: {str(service_error)}",
                "Organization Documents Service Error",
            )
            return {
                "by_type_and_year": {cat: {} for cat in available_categories.keys()},
                "total_count": 0,
                "category_icons": available_categories,
            }

        if not result.get("success"):
            frappe.log_error(f"Failed to fetch documents for {organization_name}: {result.get('message')}")
            return {
                "by_type_and_year": {cat: {} for cat in available_categories.keys()},
                "total_count": 0,
                "category_icons": available_categories,
            }

        # Transform service response to template-expected structure
        # Service returns: {category: {icon: "...", years: {year: [docs]}}}
        # Template expects: by_type_and_year: {category: {year: [docs]}}, category_icons: {category: icon}
        service_docs = result.get("documents", {})
        organized_docs = defaultdict(dict)
        category_icons = dict(available_categories)  # Start with defaults

        for category, category_data in service_docs.items():
            # Extract icon if provided by service
            if isinstance(category_data, dict) and "icon" in category_data:
                category_icons[category] = category_data["icon"]
                years_dict = category_data.get("years", {})
            else:
                years_dict = category_data if isinstance(category_data, dict) else {}

            # Sort years descending (newest first)
            for year in sorted(years_dict.keys(), reverse=True):
                docs = years_dict[year]
                # Sort documents within year by name (descending)
                organized_docs[category][year] = sorted(
                    docs, key=lambda x: x.get("document_name", ""), reverse=True
                )

        # Ensure all available categories are present (even if empty)
        for cat in available_categories.keys():
            if cat not in organized_docs:
                organized_docs[cat] = {}

        return {
            "by_type_and_year": dict(organized_docs),
            "total_count": result.get("total_count", 0),
            "category_icons": category_icons,
        }

    except Exception as e:
        frappe.log_error(f"Error fetching documents for {organization_name}: {str(e)}")
        # Get available categories for error case too
        available_categories = {}
        for category in get_document_category_options():
            available_categories[category] = get_category_icon(category)
        return {
            "by_type_and_year": {cat: {} for cat in available_categories.keys()},
            "total_count": 0,
            "category_icons": available_categories,
        }
