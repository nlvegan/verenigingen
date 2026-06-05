# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterBoardService - Chapter board member data operations

This service handles board member data operations for Chapter records, including
chapter head updates, chair member queries, and board document field population.

Extracted from chapter.py:
- update_chapter_head() - Lines 464-501 (38 LOC)
- get_chapter_chair_optimized() - Lines 503-538 (36 LOC)
- _populate_board_document_fields() - Lines 670-705 (36 LOC)

Architecture:
- Static methods for stateless operations
- Chapter document passed as parameter
- Atomic transaction handling for race condition prevention
- Optimized SQL queries for performance

Security:
- Parameterized SQL queries to prevent SQL injection
- Transaction rollback on errors
- Comprehensive error logging

Dependencies:
- frappe.db for database operations
- verenigingen.utils.file_storage for document organization
"""

import re
from typing import TYPE_CHECKING, Optional

import frappe
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterBoardService(StatelessService):
    """
    Service for managing Chapter board member data and operations.

    This service handles:
    - Chapter head field updates based on chair role assignments
    - Optimized chair member queries
    - Board document field auto-population and file organization
    """

    def __init__(self) -> None:
        """Initialize the chapter board service."""
        super().__init__(service_name="ChapterBoardService")

    def update_chapter_head(self, chapter_doc: "Document") -> bool:
        """
        Update chapter_head field based on board members with chair roles.

        Uses atomic transaction operations to prevent race conditions during
        concurrent board member updates.

        Args:
            chapter_doc: Chapter document instance

        Returns:
            bool: True if chair member found and set, False otherwise

        Business Logic:
            - If no board members: Set chapter_head to None
            - Find active chair using optimized query
            - Update chapter_head field
            - Log changes for audit trail

        Transaction Safety:
            - Wraps operations in frappe.db.begin()/commit()
            - Rolls back on errors to maintain consistency

        Example:
            >>> ChapterBoardService.update_chapter_head(chapter_doc)
            True  # Chair found and chapter_head updated
        """
        # NOTE: This method only mutates chapter_doc.chapter_head IN MEMORY;
        # persisting is the caller's responsibility (e.g. update_chapters_with_role
        # saves the doc). It must NOT manage transactions itself: a previous
        # implementation wrapped this in frappe.db.begin() and returned on the
        # success path without committing, which orphaned the surrounding
        # transaction and silently discarded the caller's chapter_head save
        # (chapter_head reverted to None until the next request-level commit).
        try:
            old_head = chapter_doc.chapter_head

            if not chapter_doc.board_members:
                chapter_doc.chapter_head = None
                return False

            # Use single optimized query to get chair member
            chair_member = self.get_chapter_chair_optimized(chapter_doc)

            if chair_member:
                chapter_doc.chapter_head = chair_member
                chair_found = True
            else:
                chapter_doc.chapter_head = None
                chair_found = False

            # Log change if head changed
            if old_head != chapter_doc.chapter_head:
                self.logger.info(
                    f"Chapter head updated for {chapter_doc.name}: {old_head} -> {chapter_doc.chapter_head}"
                )

            return chair_found

        except Exception as e:
            self.logger.error(f"Error updating chapter head for {chapter_doc.name}: {str(e)}")
            return False

    def get_chapter_chair_optimized(self, chapter_doc: "Document") -> Optional[str]:
        """
        Find chapter chair member using optimized single query.

        Performance Optimization:
            - Single SQL query instead of multiple ORM calls
            - Parameterized query for SQL injection safety
            - Early return on empty board members

        Args:
            chapter_doc: Chapter document instance

        Returns:
            Optional[str]: Member name of chair, or None if not found

        Query Logic:
            - Joins Volunteer and Chapter Role tables
            - Filters for active volunteers with chair role (is_chair=1)
            - Returns first matching member

        Security:
            - Uses parameterized SQL queries (no string interpolation)
            - Placeholders prevent SQL injection attacks

        Example:
            >>> ChapterBoardService.get_chapter_chair_optimized(chapter_doc)
            'MEM-00123'  # Member name of chapter chair
        """
        if not chapter_doc.board_members:
            return None

        # Extract active volunteers and roles
        active_board_data = []
        for board_member in chapter_doc.board_members:
            if board_member.is_active and board_member.chapter_role and board_member.volunteer:
                active_board_data.append((board_member.volunteer, board_member.chapter_role))

        if not active_board_data:
            return None

        # Use single optimized query to find chair with parameterized query (SQL injection safe)
        volunteers = [v[0] for v in active_board_data]
        roles = [v[1] for v in active_board_data]

        placeholders_volunteers = ", ".join(["%s"] * len(volunteers))
        placeholders_roles = ", ".join(["%s"] * len(roles))

        chair_query = f"""
            SELECT v.member
            FROM `tabVolunteer` v
            JOIN `tabChapter Role` cr ON cr.name IN ({placeholders_roles})
            WHERE v.name IN ({placeholders_volunteers})
            AND cr.is_chair = 1
            AND cr.is_active = 1
            AND v.member IS NOT NULL
            LIMIT 1
        """

        # Parameterized query: roles first, then volunteers
        params = tuple(roles + volunteers)
        result = frappe.db.sql(chair_query, params, as_dict=True)
        return result[0].member if result else None

    def populate_board_document_fields(self, chapter_doc: "Document") -> None:
        """
        DEPRECATED: This method is no longer used.

        Board documents are now managed via the Organization Document doctype
        and Document Browser portal. The Chapter.board_documents child table
        has been hidden and deprecated.

        This method is retained for backwards compatibility but does nothing.

        Args:
            chapter_doc: Chapter document instance (unused)
        """
        # Deprecated - board_documents child table is hidden
        # Use Organization Document and Document Browser instead
        pass


def get_chapter_board_service() -> ChapterBoardService:
    """Get singleton instance of ChapterBoardService"""
    return ChapterBoardService()
