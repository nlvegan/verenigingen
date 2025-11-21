# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberChapterDisplayService - Chapter membership display HTML generation

This service handles the generation of HTML displays for member chapter
affiliations, including primary chapter, board membership, and join dates.

Extracted from member.py:
- update_current_chapter_display() - lines 1601-1658 (58 LOC)
- get_current_chapters_optimized() - related helper method

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
from typing import TYPE_CHECKING, List, Dict, Any

import frappe

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberChapterDisplayService:
    """
    Service for generating chapter membership display HTML.

    This service handles:
    - HTML generation for chapter affiliations
    - Primary chapter and board membership badges
    - Join date display
    - Error state handling
    - Empty state (no chapters)
    """

    @staticmethod
    def update_current_chapter_display(member_doc: "Document") -> None:
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
            chapters = MemberChapterDisplayService._get_current_chapters_optimized(member_doc)

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
                    status_badges.append(
                        f'<span class="badge badge-light">Joined: {join_date}</span>'
                    )

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
            frappe.log_error(f"Error updating chapter display: {str(e)}", "Member Chapter Display")
            member_doc.current_chapter_display = (
                '<p style="color: #dc3545;">Error loading chapter information</p>'
            )

    @staticmethod
    def _get_current_chapters_optimized(member_doc: "Document") -> List[Dict[str, Any]]:
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
        return service.get_current_chapters_for_member(member_doc.name)


def get_member_chapter_display_service() -> MemberChapterDisplayService:
    """Get singleton instance of MemberChapterDisplayService"""
    return MemberChapterDisplayService()
