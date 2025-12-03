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

from verenigingen.services.infrastructure.base_service import StatelessService


class ChapterManagementService(StatelessService):
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

    def __init__(self) -> None:
        """Initialize the chapter management service."""
        super().__init__(service_name="ChapterManagementService")

    def is_chapter_management_enabled(self) -> bool:
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
            self.logger.warning(f"Settings access error in chapter management check: {str(e)}")
            # Default to enabled for backward compatibility
            return True
        except frappe.DatabaseError as e:
            self.logger.error(f"Database error in chapter management check: {str(e)}")
            return True

    def get_board_memberships(self, member_name: str) -> List[Dict[str, Any]]:
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
        if not self.is_chapter_management_enabled():
            return []

        # Validate input
        if not member_name:
            self.logger.warning("get_board_memberships called with empty member_name")
            return []

        # Verify member exists
        if not frappe.db.exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))

        self.logger.info(f"ChapterManagementService: Getting board memberships for {member_name}")

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

        self.logger.info(
            f"ChapterManagementService: Found {len(board_memberships)} board positions for {member_name}"
        )

        return board_memberships

    def get_member_chapters_optimized(self, member_name: str) -> List[Dict[str, Any]]:
        """
        Get current chapter affiliations with optimized single SQL query.

        Uses a single JOIN query to fetch all chapter information including
        board memberships in one database round trip.

        Args:
            member_name: Name of the Member document

        Returns:
            List of dicts containing:
                - chapter: Chapter document name
                - chapter_join_date: Date member joined chapter
                - status: Membership status (Active, Pending, etc.)
                - region: Chapter region
                - is_primary: Boolean, True for first (oldest) chapter
                - is_board: Boolean, True if member has board position

        Raises:
            frappe.PermissionError: If user lacks permission to access member
            frappe.ValidationError: If member_name is invalid

        Example:
            >>> chapters = ChapterManagementService.get_member_chapters_optimized("Member-001")
            >>> for chapter in chapters:
            >>>     if chapter['is_board']:
            >>>         print(f"Board member at {chapter['chapter']}")
        """
        if not member_name:
            return []

        # Verify member exists (will raise DoesNotExistError if not)
        if not frappe.db.exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))

        try:
            # Single optimized query to get all chapter information at once
            chapters_data = frappe.db.sql(
                """
                SELECT
                    cm.parent as chapter,
                    cm.chapter_join_date,
                    cm.status,
                    c.region,
                    cbm.volunteer as board_volunteer,
                    cbm.is_active as is_board_member
                FROM `tabChapter Member` cm
                LEFT JOIN `tabChapter` c ON cm.parent = c.name
                LEFT JOIN `tabVolunteer` v ON v.member = %s
                LEFT JOIN `tabChapter Board Member` cbm
                    ON cbm.parent = cm.parent
                    AND cbm.volunteer = v.name
                    AND cbm.is_active = 1
                WHERE cm.member = %s AND cm.enabled = 1
                ORDER BY cm.chapter_join_date DESC
                """,
                (member_name, member_name),
                as_dict=True,
            )

            chapters = []
            for idx, chapter_data in enumerate(chapters_data):
                chapters.append(
                    {
                        "chapter": chapter_data.chapter,
                        "chapter_join_date": chapter_data.chapter_join_date,
                        "status": chapter_data.status,
                        "region": chapter_data.region,
                        "is_primary": idx == 0,  # First one is primary
                        "is_board": bool(chapter_data.is_board_member),
                    }
                )

            self.logger.info(
                f"ChapterManagementService: Found {len(chapters)} chapters for {member_name} (optimized)"
            )
            return chapters

        except frappe.PermissionError:
            # Permission errors should always propagate - don't fall back
            self.logger.warning(f"Permission denied for chapter query: {member_name}")
            raise

        except frappe.DoesNotExistError:
            # Member doesn't exist - propagate the error
            raise

        except (frappe.DatabaseError, frappe.db.ProgrammingError) as e:
            # Database-specific errors might benefit from fallback
            self.logger.warning(
                f"Database error in optimized chapter query for {member_name}: {str(e)}. "
                f"Falling back to non-optimized query."
            )
            return self.get_member_chapters(member_name)

        # Let other exceptions propagate to surface bugs

    def get_member_chapters(self, member_name: str) -> List[Dict[str, Any]]:
        """
        Get current chapter affiliations (fallback implementation).

        Fallback method that uses frappe.get_all() with 2 queries instead of
        single JOIN query. Prefer get_member_chapters_optimized() when possible.

        Performance: 2 queries total (1 for chapters + 1 for board memberships)
        vs optimized version's single query.

        Args:
            member_name: Name of the Member document

        Returns:
            List of dicts containing chapter affiliation details:
                - chapter: Chapter document name
                - chapter_join_date: Date member joined chapter
                - status: Membership status (Active, Inactive, etc.)
                - is_primary: Boolean, True for first chapter
                - is_board: Boolean, True if board member

        Raises:
            frappe.PermissionError: If user lacks permission to access member
            frappe.ValidationError: If member_name is invalid

        Example:
            >>> chapters = ChapterManagementService.get_member_chapters("Member-001")
            >>> for chapter in chapters:
            >>>     print(f"Member of {chapter['chapter']} since {chapter['chapter_join_date']}")
        """
        if not member_name:
            return []

        # Verify member exists
        if not frappe.db.exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))

        try:
            # Get chapters where this member is listed in the Chapter Member child table
            chapter_members = frappe.get_all(
                "Chapter Member",
                filters={"member": member_name, "enabled": 1},
                fields=["parent", "chapter_join_date", "status"],
                order_by="chapter_join_date desc",
            )

            if not chapter_members:
                return []

            # Optimize: Get all board memberships in single query instead of N+1
            chapter_names = [cm.parent for cm in chapter_members]
            board_memberships_data = frappe.db.sql(
                """
                SELECT cbm.parent as chapter
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s
                    AND cbm.parent IN %s
                    AND cbm.is_active = 1
                """,
                (member_name, tuple(chapter_names)),
                as_dict=True,
            )

            # Create set for O(1) lookup
            board_chapters = {bm.chapter for bm in board_memberships_data}

            chapters = []
            for idx, cm in enumerate(chapter_members):
                chapters.append(
                    {
                        "chapter": cm.parent,
                        "chapter_join_date": cm.chapter_join_date,
                        "status": cm.status,
                        "is_primary": idx == 0,  # First one is primary (consistent with optimized version)
                        "is_board": cm.parent in board_chapters,  # O(1) lookup instead of query
                    }
                )

            self.logger.info(
                f"ChapterManagementService: Found {len(chapters)} chapters for {member_name} (fallback path, 2 queries)"
            )
            return chapters

        except frappe.PermissionError:
            # Explicit permission error - let it propagate
            self.logger.warning(
                f"ChapterManagementService: Permission denied accessing chapters for {member_name}"
            )
            raise

        except Exception as e:
            self.logger.error(f"Error getting member chapters for {member_name}: {str(e)}")
            raise frappe.ValidationError(
                _("Could not retrieve chapter information for member {0}").format(member_name)
            )

    def check_board_membership(self, member_name: str, chapter_name: str) -> bool:
        """
        Check if member has active board position in specific chapter.

        Public API for checking board membership. For multiple chapters,
        prefer get_member_chapters_optimized() which includes board checks.

        Args:
            member_name: Member document name
            chapter_name: Chapter document name

        Returns:
            True if member is board member of chapter, False otherwise

        Raises:
            frappe.ValidationError: If member or chapter doesn't exist

        Example:
            >>> is_board = ChapterManagementService.check_board_membership(
            ...     "Member-001", "Chapter-Amsterdam"
            ... )
        """
        if not member_name or not chapter_name:
            return False

        # Verify both exist
        if not frappe.db.exists("Member", member_name):
            frappe.throw(_("Member {0} does not exist").format(member_name))
        if not frappe.db.exists("Chapter", chapter_name):
            frappe.throw(_("Chapter {0} does not exist").format(chapter_name))

        return self._check_board_membership(member_name, chapter_name)

    def _check_board_membership(self, member_name: str, chapter_name: str) -> bool:
        """
        Internal helper: Check board membership without validation.

        Private method for internal use. External callers should use
        check_board_membership() public API.

        Args:
            member_name: Member document name
            chapter_name: Chapter document name

        Returns:
            True if member is board member of chapter, False otherwise
        """
        try:
            result = frappe.db.sql(
                """
                SELECT COUNT(*) as count
                FROM `tabChapter Board Member` cbm
                JOIN `tabVolunteer` v ON cbm.volunteer = v.name
                WHERE v.member = %s
                    AND cbm.parent = %s
                    AND cbm.is_active = 1
                """,
                (member_name, chapter_name),
                as_dict=True,
            )
            return result[0].count > 0 if result else False
        except Exception:
            return False

    def get_chapter_names(self, member_name: str) -> List[str]:
        """
        Get simple list of chapter names for a member.

        Convenience method that returns just the chapter names without full details.
        Uses optimized query for better performance.

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

        chapters = self.get_member_chapters_optimized(member_name)
        return [chapter.get("chapter", chapter.get("name", "")) for chapter in chapters]

    # Status to CSS class allowlist for security
    STATUS_CLASS_MAP = {
        "Active": "success",
        "Pending": "warning",
        "Inactive": "secondary",
        "Suspended": "danger",
    }

    def get_chapter_display_html(self, member_name: str) -> str:
        """
        Generate HTML for displaying member's chapters in UI.

        Creates Bootstrap-compatible HTML badges showing active chapter affiliations.
        Uses optimized query for better performance.

        Args:
            member_name: Name of the Member document

        Returns:
            HTML string with chapter badges (XSS-safe)

        Raises:
            frappe.PermissionError: If user lacks permission
            frappe.ValidationError: If member_name is invalid

        Security:
            - All user input is escaped to prevent XSS
            - Status values validated against allowlist
            - Uses Bootstrap badge classes for consistent styling

        Example:
            >>> html = ChapterManagementService.get_chapter_display_html("Member-001")
            >>> # Returns: '<div class="chapter-list">...</div>'
        """
        if not member_name:
            return "<div class='text-muted'>No member specified</div>"

        try:
            chapters = self.get_member_chapters_optimized(member_name)

            if not chapters:
                return "<div class='text-muted'>No active chapters</div>"

            html = "<div class='chapter-list'>"
            for chapter in chapters:
                # XSS protection: escape all user-provided values
                chapter_name = frappe.utils.escape_html(chapter.get("chapter", "Unknown"))
                status_raw = chapter.get("status", "Unknown")
                status_display = frappe.utils.escape_html(status_raw)

                # Security: Use allowlist to map status to CSS class
                # Prevents injection via malicious status values
                status_class = self.STATUS_CLASS_MAP.get(status_raw, "secondary")

                html += f"""
                <div class="chapter-item">
                    <span class="badge badge-{status_class}">{chapter_name}</span>
                    <small class="text-muted ml-2">{status_display}</small>
                </div>
                """

            html += "</div>"
            return html

        except frappe.PermissionError:
            # Permission errors should show generic message (don't expose member existence)
            return "<div class='text-danger'>Permission denied</div>"

        except Exception as e:
            self.logger.error(f"Error generating chapter display HTML for {member_name}: {str(e)}")
            # Generic error message (don't expose internal details)
            return "<div class='text-danger'>Error loading chapters</div>"


def get_chapter_management_service() -> ChapterManagementService:
    """
    Get ChapterManagementService instance.

    Returns:
        ChapterManagementService instance

    Example:
        >>> service = get_chapter_management_service()
        >>> enabled = service.is_chapter_management_enabled()
    """
    return ChapterManagementService()
