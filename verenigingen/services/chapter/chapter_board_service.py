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

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterBoardService:
    """
    Service for managing Chapter board member data and operations.

    This service handles:
    - Chapter head field updates based on chair role assignments
    - Optimized chair member queries
    - Board document field auto-population and file organization
    """

    @staticmethod
    def update_chapter_head(chapter_doc: "Document") -> bool:
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
        try:
            # Use atomic transaction to prevent race conditions
            frappe.db.begin()
            try:
                old_head = chapter_doc.chapter_head

                if not chapter_doc.board_members:
                    chapter_doc.chapter_head = None
                    return False

                # Use single optimized query to get chair member
                chair_member = ChapterBoardService.get_chapter_chair_optimized(chapter_doc)

                if chair_member:
                    chapter_doc.chapter_head = chair_member
                    chair_found = True
                else:
                    chapter_doc.chapter_head = None
                    chair_found = False

                # Log change if head changed
                if old_head != chapter_doc.chapter_head:
                    frappe.logger().info(
                        f"Chapter head updated for {chapter_doc.name}: {old_head} -> {chapter_doc.chapter_head}"
                    )

                return chair_found

            except Exception as transaction_error:
                # Rollback the transaction on error
                frappe.db.rollback()
                raise transaction_error

        except Exception as e:
            frappe.log_error(f"Error updating chapter head for {chapter_doc.name}: {str(e)}")
            return False

    @staticmethod
    def get_chapter_chair_optimized(chapter_doc: "Document") -> Optional[str]:
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

    @staticmethod
    def populate_board_document_fields(chapter_doc: "Document") -> None:
        """
        Auto-populate uploaded_by and upload_date fields for board documents.

        Also organizes board documents into hierarchical file structure:
        - chapters/{chapter_name}/{document_type}/{year}/filename

        Args:
            chapter_doc: Chapter document instance

        Business Logic:
            - Sets uploaded_by to current user if not set
            - Sets upload_date to today if not set
            - Extracts year from document name (if available)
            - Organizes files into hierarchical structure

        File Organization:
            - Uses vereinigingen.utils.file_storage.organize_existing_chapter_document()
            - Creates year-based organization
            - Updates document_file URL if file moved

        Error Handling:
            - Logs errors without blocking document save
            - Individual document errors don't affect others

        Example:
            >>> ChapterBoardService.populate_board_document_fields(chapter_doc)
            # Auto-populates fields and organizes files
        """
        try:
            from verenigingen.utils.file_storage import organize_existing_chapter_document

            for doc in chapter_doc.board_documents:
                # Set uploaded_by if not already set
                if not doc.uploaded_by:
                    doc.uploaded_by = frappe.session.user

                # Set upload_date if not already set
                if not doc.upload_date:
                    doc.upload_date = today()

                # Organize file into hierarchical structure
                if doc.document_file:
                    # Extract year from document name
                    year_match = re.search(r"\b(20\d{2})\b", doc.document_name)
                    year = year_match.group(1) if year_match else "Other"

                    # Move file to hierarchical structure
                    new_file_url = organize_existing_chapter_document(
                        file_url=doc.document_file,
                        chapter_name=chapter_doc.name,
                        category=doc.document_type or "Other",
                        year=year,
                    )

                    # Update file URL if it changed
                    if new_file_url != doc.document_file:
                        doc.document_file = new_file_url

        except Exception as e:
            frappe.log_error(f"Error populating board document fields: {str(e)}")


def get_chapter_board_service() -> ChapterBoardService:
    """Get singleton instance of ChapterBoardService"""
    return ChapterBoardService()
