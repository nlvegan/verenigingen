# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterValidationService - Chapter validation and auto-fix logic

This service handles validation and automatic field correction for Chapter records,
including security access validation and required field auto-fixing.

Extracted from chapter.py:
- validate_chapter_access() - Lines 352-373 (22 LOC)
- _auto_fix_required_fields() - Lines 636-668 (34 LOC)

Architecture:
- Static methods for stateless operations
- Chapter document passed as parameter
- Comprehensive error handling with logging

Security:
- Validates access to national board chapter
- Prevents Verenigingen Administrators from editing national board
- Administrator and System Manager bypass checks

Dependencies:
- frappe.session for user context
- Verenigingen Settings for national board configuration
"""

from typing import TYPE_CHECKING

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.constants import Roles

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterValidationService(StatelessService):
    """
    Service for validating Chapter records and auto-fixing required fields.

    This service handles:
    - Chapter access permission validation
    - National board chapter protection
    - Required field auto-fixing for test and production data
    """

    def __init__(self) -> None:
        """Initialize the chapter validation service."""
        super().__init__(service_name="ChapterValidationService")

    def validate_chapter_access(self, chapter_doc: "Document") -> None:
        """
        Validate chapter access permissions to prevent unauthorized edits.

        Security Rules:
            - Administrator: Full access to all chapters
            - System Manager: Full access to all chapters
            - Verenigingen Administrator: Cannot edit national board chapter
            - Other roles: Standard permission framework applies

        Args:
            chapter_doc: Chapter document instance

        Raises:
            frappe.exceptions.PermissionError: If Verenigingen Admin tries to edit national board

        Example:
            >>> ChapterValidationService.validate_chapter_access(chapter_doc)
            # Validates access or throws PermissionError
        """
        try:
            # Administrator and System Manager always have access
            if frappe.session.user == "Administrator" or Roles.SYSTEM_MANAGER in frappe.get_roles():
                return

            # Get national board chapter configuration
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.get("national_board_chapter"):
                return

            # Block Verenigingen Administrators from editing national board chapter
            if chapter_doc.name == settings.national_board_chapter:
                user_roles = frappe.get_roles()
                if Roles.VERENIGINGEN_ADMIN in user_roles and Roles.SYSTEM_MANAGER not in user_roles:
                    frappe.throw(
                        _(
                            "Verenigingen Administrators cannot edit the National Board chapter. "
                            "Please contact an administrator."
                        ),
                        frappe.PermissionError,
                    )

        except frappe.PermissionError:
            # Deliberate security denial — must propagate. The broad except below
            # is a fail-open guard for *unexpected* errors during the settings/role
            # lookup (don't lock everyone out on a misconfiguration); it must not
            # swallow the intentional access block raised just above.
            raise
        except Exception as e:
            self.logger.error(f"Error validating chapter access for {chapter_doc.name}: {str(e)}")
            # Don't block access on unexpected validation errors (fail-open by design)

    def auto_fix_required_fields(self, chapter_doc: "Document") -> None:
        """
        Auto-fix missing required fields if possible to prevent validation errors.

        Auto-Fix Rules:
            - Region: Set to test region for test chapters, "Unspecified Region" for existing,
              "General" for new chapters
            - Introduction: Set placeholder text for unpublished chapters without introduction

        Args:
            chapter_doc: Chapter document instance

        Business Logic:
            - Test chapters (name contains "test"): Use test region and test introduction
            - Existing chapters: Use "Unspecified Region" and generic introduction
            - New chapters: Use "General" region
            - Only fix introduction if chapter is unpublished

        Example:
            >>> ChapterValidationService.auto_fix_required_fields(chapter_doc)
            # Automatically fixes missing region and introduction fields
        """
        try:
            # Auto-fix missing status. Chapter.status is reqd=1 with default
            # 'Active' in the JSON, but Frappe applies field defaults at the
            # form layer — not for frappe.get_doc({...}).insert(). Without this,
            # raw-dict test fixtures fail with MandatoryError in setUpClass.
            if not chapter_doc.status:
                chapter_doc.status = "Active"

            # Auto-fix missing status on Chapter Member child rows. Chapter Member.status
            # is reqd=1 with JSON default 'Active', but Frappe (v16) only applies field
            # defaults at the form layer — not for child rows appended via
            # parent.append({...}) / get_doc({...}) without an explicit status, and child
            # controller validate() is never invoked by Frappe. The parent's validate()
            # runs before the mandatory check, so default member-row status here. 'Active'
            # is the correct initial state for a member on a chapter roster.
            for member_row in chapter_doc.get("members") or []:
                if not member_row.status:
                    member_row.status = "Active"

            # Auto-fix missing region
            if not chapter_doc.region:
                if hasattr(chapter_doc, "name") and chapter_doc.name:
                    if "test" in chapter_doc.name.lower():
                        # Use the actual test region name from database
                        test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
                        chapter_doc.region = test_region or "test-region"
                        self.logger.info(f"Auto-fixed missing region for test chapter {chapter_doc.name}")
                    elif not chapter_doc.get("__islocal"):  # If not a new document
                        # For existing documents, use a generic region
                        chapter_doc.region = "Unspecified Region"
                        self.logger.info(f"Auto-fixed missing region for existing chapter {chapter_doc.name}")
                else:
                    # For new documents without region, set default
                    chapter_doc.region = "General"
                    self.logger.info("Auto-fixed missing region for new chapter")

            # Auto-fix missing introduction for unpublished chapters
            if not chapter_doc.introduction and not chapter_doc.published:
                if hasattr(chapter_doc, "name") and chapter_doc.name and "test" in chapter_doc.name.lower():
                    chapter_doc.introduction = f"This is a test chapter: {chapter_doc.name}"
                    self.logger.info(f"Auto-fixed missing introduction for test chapter {chapter_doc.name}")
                else:
                    chapter_doc.introduction = "Chapter introduction will be added soon."
                    self.logger.info(
                        f"Auto-fixed missing introduction for chapter {getattr(chapter_doc, 'name', 'unnamed')}"
                    )

        except Exception as e:
            self.logger.error(f"Error auto-fixing chapter fields: {str(e)}")


def get_chapter_validation_service() -> ChapterValidationService:
    """Get singleton instance of ChapterValidationService"""
    return ChapterValidationService()
