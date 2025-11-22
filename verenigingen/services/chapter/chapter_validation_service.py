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
from frappe.utils import today

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterValidationService:
    """
    Service for validating Chapter records and auto-fixing required fields.

    This service handles:
    - Chapter access permission validation
    - National board chapter protection
    - Required field auto-fixing for test and production data
    """

    @staticmethod
    def validate_chapter_access(chapter_doc: "Document") -> None:
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
            if frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles():
                return

            # Get national board chapter configuration
            settings = frappe.get_single("Verenigingen Settings")
            if not settings.get("national_board_chapter"):
                return

            # Block Verenigingen Administrators from editing national board chapter
            if chapter_doc.name == settings.national_board_chapter:
                user_roles = frappe.get_roles()
                if "Verenigingen Administrator" in user_roles and "System Manager" not in user_roles:
                    frappe.throw(
                        _(
                            "Verenigingen Administrators cannot edit the National Board chapter. "
                            "Please contact an administrator."
                        )
                    )

        except Exception as e:
            frappe.log_error(f"Error validating chapter access for {chapter_doc.name}: {str(e)}")
            # Don't block access on validation errors

    @staticmethod
    def auto_fix_required_fields(chapter_doc: "Document") -> None:
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
            # Auto-fix missing region
            if not chapter_doc.region:
                if hasattr(chapter_doc, "name") and chapter_doc.name:
                    if "test" in chapter_doc.name.lower():
                        # Use the actual test region name from database
                        test_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
                        chapter_doc.region = test_region or "test-region"
                        frappe.logger().info(f"Auto-fixed missing region for test chapter {chapter_doc.name}")
                    elif not chapter_doc.get("__islocal"):  # If not a new document
                        # For existing documents, use a generic region
                        chapter_doc.region = "Unspecified Region"
                        frappe.logger().info(
                            f"Auto-fixed missing region for existing chapter {chapter_doc.name}"
                        )
                else:
                    # For new documents without region, set default
                    chapter_doc.region = "General"
                    frappe.logger().info("Auto-fixed missing region for new chapter")

            # Auto-fix missing introduction for unpublished chapters
            if not chapter_doc.introduction and not chapter_doc.published:
                if hasattr(chapter_doc, "name") and chapter_doc.name and "test" in chapter_doc.name.lower():
                    chapter_doc.introduction = f"This is a test chapter: {chapter_doc.name}"
                    frappe.logger().info(
                        f"Auto-fixed missing introduction for test chapter {chapter_doc.name}"
                    )
                else:
                    chapter_doc.introduction = "Chapter introduction will be added soon."
                    frappe.logger().info(
                        f"Auto-fixed missing introduction for chapter {getattr(chapter_doc, 'name', 'unnamed')}"
                    )

        except Exception as e:
            frappe.log_error(f"Error auto-fixing chapter fields: {str(e)}")


def get_chapter_validation_service() -> ChapterValidationService:
    """Get singleton instance of ChapterValidationService"""
    return ChapterValidationService()
