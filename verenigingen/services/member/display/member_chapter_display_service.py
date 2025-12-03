# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberChapterDisplayService - Chapter membership display HTML generation

This service handles the generation of HTML displays for member chapter
affiliations, including primary chapter, board membership, and join dates.

Extracted from member.py:
- update_current_chapter_display() - lines 1601-1658 (58 LOC)
- get_current_chapters_optimized() - related helper method
- should_update_chapter_display() - lines 215-244 (30 LOC, Phase 2D-3)

Architecture:
- Static methods for display generation
- HTML escaping for XSS protection
- Delegates to ChapterManagementService for data queries
- Handles edge cases (no chapters, errors)

Security:
- All database-sourced content is HTML-escaped to prevent XSS attacks
- Chapter names, regions, and dates are escaped before HTML interpolation
- Static badge HTML is safe (no dynamic content interpolation)
- Error handling prevents display of sensitive error details

Dependencies:
- ChapterManagementService - For optimized chapter data queries
"""

from html import escape
from typing import TYPE_CHECKING, Any, Dict, List

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberChapterDisplayService(StatelessService):
    """
    Service for generating chapter membership display HTML.

    This service handles:
    - Change detection for chapter display updates
    - HTML generation for chapter affiliations
    - Primary chapter and board membership badges
    - Join date display
    - Error state handling
    - Empty state (no chapters)
    """

    def __init__(self) -> None:
        """Initialize the member chapter display service."""
        super().__init__(service_name="MemberChapterDisplayService")

    def should_update_chapter_display(self, member_doc: "Document") -> bool:
        """
        Check if chapter display needs updating to avoid unnecessary processing.

        Implements smart change detection to avoid expensive geographic lookups
        and database queries when chapter assignment hasn't changed.

        Args:
            member_doc: Member document instance

        Returns:
            bool: True if chapter display should be updated

        Triggers:
            - Existing records being updated (skip for brand new unsaved records)
            - Address field changes (pincode, city, state)
            - Explicit chapter assignment operations

        Business Logic:
            - Skip for new records that don't exist in DB yet (chapters assigned after creation)
            - Check for changes in geographic fields that affect chapter assignment
            - Allow explicit updates during chapter assignment workflows

        Example:
            >>> member = frappe.get_doc("Member", "MEM-001")
            >>> member.pincode = "1012 AB"  # Changed from "3012 CA"
            >>> MemberChapterDisplayService.should_update_chapter_display(member)
            True  # Postal code changed - chapter may need reassignment
        """
        # Skip for new records that don't exist in DB yet - they won't have chapters
        # Chapters are assigned after the member is created and saved
        if member_doc.is_new():
            return False

        # Check if geographic fields have changed that affect chapter assignment
        chapter_related_fields = ["pincode", "city", "state"]
        for field in chapter_related_fields:
            if hasattr(member_doc, "has_value_changed") and member_doc.has_value_changed(field):
                return True

        # Allow explicit updates during chapter assignment workflows
        if hasattr(member_doc, "_chapter_assignment_in_progress"):
            return True

        return False

    def update_current_chapter_display(self, member_doc: "Document") -> None:
        """
        Update the current chapter display field based on Chapter Member relationships.

        Generates formatted HTML showing all current chapter affiliations with:
        - Chapter name and region
        - Primary chapter badge
        - Board membership badge
        - Join date

        Args:
            member_doc: Member document instance

        Returns:
            None - Updates member_doc.current_chapter_display (or temp field) in place

        Security:
            - All database content HTML-escaped (chapter names, regions, dates)
            - Static HTML badges safe from injection
            - Prevents XSS via malicious chapter names
            - Error messages don't expose sensitive details
            - Handles missing field gracefully

        Example Output:
            <div class="member-chapters">
                <div class="chapter-item" style="...">
                    <strong>Amsterdam (Noord-Holland)</strong>
                    <br><span class="badge badge-success">Primary</span>
                    <span class="badge badge-light">Joined: 2024-01-15</span>
                </div>
            </div>
        """
        try:
            chapters = self._get_current_chapters_optimized(member_doc)

            if not chapters:
                # Use the custom field until the main field is fixed
                field_name = (
                    "current_chapter_display_temp"
                    if hasattr(member_doc, "current_chapter_display_temp")
                    else "current_chapter_display"
                )
                setattr(member_doc, field_name, '<p style="color: #888;"><em>No chapter assignment</em></p>')
                return

            # Build HTML using more efficient string operations
            html_items = ['<div class="member-chapters">']

            for chapter in chapters:
                # Escape all database-sourced content to prevent XSS
                chapter_name = escape(str(chapter["chapter"]))
                chapter_display = chapter_name
                if chapter.get("region"):
                    region = escape(str(chapter["region"]))
                    chapter_display += f" ({region})"

                status_badges = []
                if chapter.get("is_primary"):
                    status_badges.append('<span class="badge badge-success">Primary</span>')
                if chapter.get("is_board"):
                    status_badges.append('<span class="badge badge-info">Board Member</span>')
                if chapter.get("chapter_join_date"):
                    # Escape date value to prevent injection via malformed dates
                    join_date = escape(str(chapter["chapter_join_date"]))
                    status_badges.append(f'<span class="badge badge-light">Joined: {join_date}</span>')

                badges_html = " ".join(status_badges) if status_badges else ""

                html_items.append(
                    f"""
                    <div class="chapter-item" style="margin-bottom: 8px; padding: 8px; border-left: 3px solid #007bff; background-color: #f8f9fa;">
                        <strong>{chapter_display}</strong>
                        {f'<br>{badges_html}' if badges_html else ''}
                    </div>
                """
                )

            html_items.append("</div>")

            # Use the custom field until the main field is fixed
            field_name = (
                "current_chapter_display_temp"
                if hasattr(member_doc, "current_chapter_display_temp")
                else "current_chapter_display"
            )
            setattr(member_doc, field_name, "".join(html_items))

        except Exception as e:
            self.logger.error(f"Error updating chapter display: {str(e)}")
            member_doc.current_chapter_display = (
                '<p style="color: #dc3545;">Error loading chapter information</p>'
            )

    def _get_current_chapters_optimized(self, member_doc: "Document") -> List[Dict[str, Any]]:
        """
        Get current chapter memberships with optimized single query.

        Delegates to ChapterManagementService for optimized query execution.
        This method is maintained for backward compatibility but delegates to service.

        Args:
            member_doc: Member document instance

        Returns:
            List[Dict]: Chapter membership data with keys:
                - chapter: Chapter name
                - region: Region name (optional)
                - is_primary: Primary chapter flag
                - is_board: Board membership flag
                - chapter_join_date: Join date

        Example:
            [
                {
                    "chapter": "Amsterdam",
                    "region": "Noord-Holland",
                    "is_primary": 1,
                    "is_board": 0,
                    "chapter_join_date": "2024-01-15"
                }
            ]
        """
        if not member_doc.name:
            return []

        # Delegate to ChapterManagementService for optimized query
        from verenigingen.services.member.chapter.chapter_management_service import (
            get_chapter_management_service,
        )

        service = get_chapter_management_service()
        return service.get_member_chapters_optimized(member_doc.name)


def get_member_chapter_display_service() -> MemberChapterDisplayService:
    """Get singleton instance of MemberChapterDisplayService"""
    return MemberChapterDisplayService()
