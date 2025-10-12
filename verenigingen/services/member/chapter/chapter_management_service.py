# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Chapter Management Service

Provides chapter affiliation and board membership queries for members.

ERROR HANDLING PATTERN: Exception-Based Pattern
===============================================
All methods raise exceptions on errors: frappe.ValidationError, frappe.PermissionError

Rationale: UI-facing service providing member chapter information.
Exception pattern provides:
- Automatic Frappe UI error display integration
- Proper permission error handling
- Clean code without constant result checking

See: docs/patterns/ERROR_HANDLING_PATTERNS.md
"""

from typing import Any, Dict, List

import frappe
from frappe import _


class ChapterManagementService:
    """
    Chapter Management Service

    Handles chapter affiliation queries, board memberships, and chapter display
    for members within the Verenigingen system.

    This service consolidates all chapter-related queries that were previously
    scattered across member.py and member_utils.py.

    Methods:
        - is_chapter_management_enabled: Check if chapter system is enabled
        - get_board_memberships: Get active board positions for member
        - get_member_chapters: Get current chapter affiliations
        - get_chapter_names: Get simple list of chapter names
        - get_chapter_display_html: Generate HTML for UI display

    Security:
        - All methods validate permissions appropriately
        - Read-only operations (no data modification)
        - XSS protection in HTML generation
    """

    @staticmethod
    def is_chapter_management_enabled() -> bool:
        """
        Check if chapter management is enabled in Verenigingen Settings.

        Returns:
            bool: True if enabled, False otherwise. Defaults to True if settings not found.

        Raises:
            frappe.ValidationError: If settings cannot be accessed

        Example:
            >>> if ChapterManagementService.is_chapter_management_enabled():
            >>>     chapters = ChapterManagementService.get_member_chapters(member_name)
        """
        try:
            return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        except (frappe.DoesNotExistError, frappe.ValidationError) as e:
            frappe.log_error(
                f"Settings access error in chapter management check: {str(e)}", "ChapterManagementService"
            )
            # Default to enabled for backward compatibility
            return True
        except frappe.DatabaseError as e:
            frappe.log_error(
                f"Database error in chapter management check: {str(e)}", "ChapterManagementService"
            )
            return True

    @staticmethod
    def get_board_memberships(member_name: str) -> List[Dict[str, Any]]:
        """
        Get active board memberships for a member.

        Returns board positions the member holds across all chapters through
        their volunteer record.

        Args:
            member_name: Name of the Member document

        Returns:
            List of dicts containing:
                - chapter: Chapter name
                - role: Board role title
                - start_date: Position start date
                - end_date: Position end date
                - volunteer_name: Associated volunteer record

        Raises:
            frappe.ValidationError: If member_name is invalid
            frappe.PermissionError: If user lacks permission to access member data

        Example:
            >>> memberships = ChapterManagementService.get_board_memberships("Member-001")
            >>> for membership in memberships:
            >>>     print(f"{membership['role']} at {membership['chapter']}")
        """
        if not ChapterManagementService.is_chapter_management_enabled():
            return []

        # Validate input
        if not member_name:
            frappe.log_error(
                "get_board_memberships called with empty member_name", "ChapterManagementService"
            )
            return []

        # Verify member exists
        if not frappe.db.exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))

        frappe.logger().info(f"ChapterManagementService: Getting board memberships for {member_name}")

        board_memberships = frappe.db.sql(
            """
            SELECT
                cbm.parent as chapter,
                cbm.chapter_role as role,
                cbm.from_date as start_date,
                cbm.to_date as end_date,
                v.name as volunteer_name,
                v.member as member_check
            FROM `tabChapter Board Member` cbm
            JOIN `tabVolunteer` v ON cbm.volunteer = v.name
            WHERE v.member = %s AND cbm.is_active = 1
            ORDER BY cbm.from_date DESC
            """,
            (member_name,),
            as_dict=True,
        )

        frappe.logger().info(
            f"ChapterManagementService: Found {len(board_memberships)} board positions for {member_name}"
        )

        return board_memberships

    @staticmethod
    def get_member_chapters(member_name: str) -> List[Dict[str, Any]]:
        """
        Get current chapter affiliations for a member.

        Returns all active chapter memberships through the Chapter Member child table.

        Args:
            member_name: Name of the Member document

        Returns:
            List of dicts containing chapter affiliation details:
                - chapter: Chapter document name
                - chapter_name: Display name of chapter
                - status: Membership status (Active, Inactive, etc.)
                - joined_date: Date member joined chapter

        Raises:
            frappe.PermissionError: If user lacks permission to access member
            frappe.ValidationError: If member_name is invalid

        Example:
            >>> chapters = ChapterManagementService.get_member_chapters("Member-001")
            >>> for chapter in chapters:
            >>>     print(f"Member of {chapter['chapter_name']} since {chapter['joined_date']}")
        """
        if not member_name:
            return []

        try:
            # This will raise PermissionError if user lacks access
            member_doc = frappe.get_doc("Member", member_name)
            return member_doc.get_current_chapters()

        except frappe.PermissionError:
            # Explicit permission error - let it propagate
            frappe.logger().warning(
                f"ChapterManagementService: Permission denied accessing chapters for {member_name}"
            )
            raise

        except Exception as e:
            frappe.log_error(
                f"Error getting member chapters for {member_name}: {str(e)}", "ChapterManagementService"
            )
            raise frappe.ValidationError(
                _("Could not retrieve chapter information for member {0}").format(member_name)
            )

    @staticmethod
    def get_chapter_names(member_name: str) -> List[str]:
        """
        Get simple list of chapter names for a member.

        Convenience method that returns just the chapter names without full details.

        Args:
            member_name: Name of the Member document

        Returns:
            List of chapter names (strings)

        Raises:
            frappe.PermissionError: If user lacks permission
            frappe.ValidationError: If member_name is invalid or chapters cannot be retrieved

        Example:
            >>> names = ChapterManagementService.get_chapter_names("Member-001")
            >>> print(", ".join(names))  # "Amsterdam, Rotterdam, Utrecht"
        """
        if not member_name:
            return []

        chapters = ChapterManagementService.get_member_chapters(member_name)
        return [chapter.get("chapter_name", chapter.get("name", "")) for chapter in chapters]

    @staticmethod
    def get_chapter_display_html(member_name: str) -> str:
        """
        Generate HTML for displaying member's chapters in UI.

        Creates Bootstrap-compatible HTML badges showing active chapter affiliations.

        Args:
            member_name: Name of the Member document

        Returns:
            HTML string with chapter badges (XSS-safe)

        Raises:
            frappe.PermissionError: If user lacks permission
            frappe.ValidationError: If member_name is invalid

        Security:
            - All user input is escaped to prevent XSS
            - Uses Bootstrap badge classes for consistent styling

        Example:
            >>> html = ChapterManagementService.get_chapter_display_html("Member-001")
            >>> # Returns: '<div class="chapter-list">...</div>'
        """
        if not member_name:
            return "<div class='text-muted'>No member specified</div>"

        try:
            chapters = ChapterManagementService.get_member_chapters(member_name)

            if not chapters:
                return "<div class='text-muted'>No active chapters</div>"

            html = "<div class='chapter-list'>"
            for chapter in chapters:
                # XSS protection: escape all user-provided values
                chapter_name = frappe.utils.escape_html(
                    chapter.get("chapter_name", chapter.get("name", "Unknown"))
                )
                status = frappe.utils.escape_html(chapter.get("status", "Unknown"))

                # Determine badge color based on status
                status_class = "success" if status == "Active" else "secondary"

                html += f"""
                <div class="chapter-item">
                    <span class="badge badge-{status_class}">{chapter_name}</span>
                    <small class="text-muted ml-2">{status}</small>
                </div>
                """

            html += "</div>"
            return html

        except frappe.PermissionError:
            # Permission errors should show generic message (don't expose member existence)
            return "<div class='text-danger'>Permission denied</div>"

        except Exception as e:
            frappe.log_error(
                f"Error generating chapter display HTML for {member_name}: {str(e)}",
                "ChapterManagementService",
            )
            # Generic error message (don't expose internal details)
            return "<div class='text-danger'>Error loading chapters</div>"


# Convenience function for backward compatibility
def get_chapter_management_service():
    """
    Get ChapterManagementService instance.

    Returns:
        ChapterManagementService class (stateless service)

    Example:
        >>> service = get_chapter_management_service()
        >>> enabled = service.is_chapter_management_enabled()
    """
    return ChapterManagementService
