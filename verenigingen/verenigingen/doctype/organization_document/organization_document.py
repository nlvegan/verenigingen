# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Organization Document DocType

Unified document storage for Chapters, Teams, and Movements.
Replaces the need for separate child tables per organization type.

Permission Model:
- Chapter documents: Only board members can create/edit
- Team documents: All team members can create/edit
- Movement documents: All movement members can create/edit

File Organization:
Documents are stored in hierarchical paths:
/documents/{org_type}s/{org_name}/{category}/{year}/{filename}
"""

import os
from typing import Optional

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

from verenigingen.utils.constants import Roles


class OrganizationDocument(Document):
    """Organization Document for Chapters, Teams, and Movements"""

    # Allowed file extensions for document uploads
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

    def validate(self):
        """Validate document before save"""
        self._validate_organization_reference()
        self._validate_file_extension()
        self._populate_metadata_fields()
        self._validate_upload_permission()

    def before_save(self):
        """Actions before saving"""
        self._organize_file_storage()

    def _validate_organization_reference(self):
        """Ensure exactly one organization reference is set based on type"""
        org_type = self.organization_type

        if org_type == "Chapter":
            if not self.chapter:
                frappe.throw(_("Chapter is required when Organization Type is Chapter"))
            # Clear other refs
            self.team = None
            self.movement = None
        elif org_type == "Team":
            if not self.team:
                frappe.throw(_("Team is required when Organization Type is Team"))
            self.chapter = None
            self.movement = None
        elif org_type == "Movement":
            if not self.movement:
                frappe.throw(_("Movement is required when Organization Type is Movement"))
            self.chapter = None
            self.team = None
        else:
            frappe.throw(_("Invalid Organization Type"))

    def _validate_file_extension(self):
        """Validate that the uploaded file has an allowed extension"""
        if not self.document_file:
            return

        file_ext = os.path.splitext(self.document_file.lower())[1]
        if file_ext and file_ext not in self.ALLOWED_EXTENSIONS:
            allowed_list = ", ".join(sorted(self.ALLOWED_EXTENSIONS))
            frappe.throw(
                _("File type '{0}' is not allowed. Accepted types: {1}").format(file_ext, allowed_list)
            )

    def _populate_metadata_fields(self):
        """Auto-populate upload_date and uploaded_by if not set"""
        if not self.upload_date:
            self.upload_date = today()

        if not self.uploaded_by:
            self.uploaded_by = frappe.session.user

    def _validate_upload_permission(self):
        """
        Validate user has permission to upload to this organization.

        Permission rules:
        - Chapter: Must be active board member
        - Team: Must be active team member
        - Movement: Must be movement member
        """
        # Skip for administrators
        if Roles.ADMIN_PAIR & set(frappe.get_roles()):
            return

        user = frappe.session.user
        volunteer_name = self._get_volunteer_for_user(user)
        member_name = self._get_member_for_user(user)

        if self.organization_type == "Chapter":
            if not self._is_chapter_board_member(volunteer_name, self.chapter):
                frappe.throw(
                    _("You must be an active board member of {0} to upload documents").format(self.chapter)
                )

        elif self.organization_type == "Team":
            if not self._is_team_member(volunteer_name, self.team):
                frappe.throw(
                    _("You must be an active member of team {0} to upload documents").format(self.team)
                )

        elif self.organization_type == "Movement":
            if not self._is_movement_member(member_name, self.movement):
                frappe.throw(
                    _("You must be a member of movement {0} to upload documents").format(self.movement)
                )

    def _get_volunteer_for_user(self, user: str) -> Optional[str]:
        """Get volunteer name for a user"""
        member_name = self._get_member_for_user(user)
        if not member_name:
            return None

        volunteer = frappe.db.get_value("Volunteer", {"member": member_name}, "name")
        return volunteer

    def _get_member_for_user(self, user: str) -> Optional[str]:
        """Get member name for a user"""
        return frappe.db.get_value("Member", {"user": user}, "name")

    def _is_chapter_board_member(self, volunteer_name: str, chapter_name: str) -> bool:
        """Check if volunteer is an active board member of the chapter"""
        if not volunteer_name:
            return False

        return frappe.db.exists(
            "Chapter Board Member",
            {"parent": chapter_name, "volunteer": volunteer_name, "is_active": 1},
        )

    def _is_team_member(self, volunteer_name: str, team_name: str) -> bool:
        """Check if volunteer is an active member of the team"""
        if not volunteer_name:
            return False

        return frappe.db.exists(
            "Team Member",
            {"parent": team_name, "volunteer": volunteer_name, "status": "Active"},
        )

    def _is_movement_member(self, member_name: str, movement_name: str) -> bool:
        """Check if member is a member of the movement"""
        if not member_name:
            return False

        return frappe.db.exists("Movement Member", {"parent": movement_name, "member": member_name})

    def _organize_file_storage(self):
        """
        Organize file into hierarchical storage structure.

        Path: /documents/{org_type}s/{org_name}/{category}/{year}/{filename}
        """
        if not self.document_file:
            return

        # Skip if already in organized structure
        if (
            "/documents/" in self.document_file
            and f"/{self.organization_type.lower()}s/" in self.document_file
        ):
            return

        try:
            from verenigingen.utils.file_storage import organize_organization_document

            org_name = self._get_organization_name()
            year = self._extract_year_from_document_name()

            new_file_url = organize_organization_document(
                file_url=self.document_file,
                organization_type=self.organization_type,
                organization_name=org_name,
                category=self.document_type or "Other",
                year=year,
            )

            if new_file_url and new_file_url != self.document_file:
                self.document_file = new_file_url

        except Exception as e:
            # Log but don't block save - file remains in original location
            frappe.log_error(
                f"Failed to organize document file: {str(e)}",
                "Organization Document File Organization Error",
            )

    def _get_organization_name(self) -> str:
        """Get the organization name based on type"""
        if self.organization_type == "Chapter":
            return self.chapter
        elif self.organization_type == "Team":
            return self.team
        elif self.organization_type == "Movement":
            return self.movement
        return "unknown"

    def _extract_year_from_document_name(self) -> str:
        """Extract year from document name, or return 'Other' if not found.

        Delegates to shared date_extraction utility for comprehensive
        pattern matching (ISO, European, Dutch month names, etc.).
        """
        from verenigingen.utils.date_extraction import extract_year_from_text

        return extract_year_from_text(self.document_name or "", default="Other")

    def get_organization_display_name(self) -> str:
        """Get a human-readable organization name for display"""
        org_name = self._get_organization_name()
        return f"{self.organization_type}: {org_name}"
