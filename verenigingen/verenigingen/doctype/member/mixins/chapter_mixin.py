import frappe


class ChapterMixin:
    """
    Mixin for chapter-related functionality.

    This mixin provides chapter management methods for Member DocType.
    Read operations delegate to ChapterManagementService for optimized queries.
    Domain logic methods (tracking, assignment) remain here.
    """

    def handle_chapter_assignment(self):
        """Handle chapter assignment changes - now managed through Chapter Member child table"""
        # This method is now simplified since chapter assignment is managed
        # through the Chapter Member child table instead of primary_chapter field

    def update_chapter_tracking_fields(self, old_chapter, new_chapter):
        """Update chapter tracking fields when chapter changes"""

        # Set previous chapter
        if old_chapter:
            self.previous_chapter = old_chapter

        # Set assignment tracking fields
        if new_chapter:
            self.chapter_assigned_by = frappe.session.user

            # Set a default reason if not provided
            if not self.chapter_change_reason:
                if old_chapter:
                    self.chapter_change_reason = f"Changed from {old_chapter} to {new_chapter}"
                else:
                    self.chapter_change_reason = f"Initial assignment to {new_chapter}"

    def get_chapters(self):
        """
        Get all chapters this member belongs to (delegates to service).

        Uses ChapterManagementService.get_member_chapters_optimized() for
        efficient single-query retrieval. Falls back to service on error.

        Returns:
            List of dicts with chapter details
        """
        if not self._is_chapter_management_enabled():
            return []

        try:
            from verenigingen.services.member.chapter.chapter_management_service import (
                get_chapter_management_service,
            )

            return get_chapter_management_service().get_member_chapters_optimized(self.name)
        except Exception as e:
            frappe.log_error(f"Error in ChapterMixin.get_chapters for {self.name}: {str(e)}", "ChapterMixin")
            return []

    def is_board_member(self, chapter=None):
        """
        Check if member is a board member of any chapter or a specific chapter.

        Args:
            chapter: Optional chapter name to check specific chapter

        Returns:
            Boolean indicating board membership
        """
        if not self._is_chapter_management_enabled():
            return False

        try:
            from verenigingen.services.member.chapter.chapter_management_service import (
                get_chapter_management_service,
            )

            if chapter:
                # Check specific chapter using public API
                return get_chapter_management_service().check_board_membership(self.name, chapter)
            else:
                # Check any board membership
                board_positions = get_chapter_management_service().get_board_memberships(self.name)
                return len(board_positions) > 0
        except Exception as e:
            frappe.log_error(f"Error checking board membership for {self.name}: {str(e)}", "ChapterMixin")
            return False

    def get_board_roles(self):
        """
        Get all board roles for this member (delegates to service).

        Returns:
            List of dicts with chapter and role information
        """
        if not self._is_chapter_management_enabled():
            return []

        try:
            from verenigingen.services.member.chapter.chapter_management_service import (
                get_chapter_management_service,
            )

            board_memberships = get_chapter_management_service().get_board_memberships(self.name)
            # Transform to expected format
            return [{"chapter": bm.get("chapter"), "role": bm.get("role")} for bm in board_memberships]
        except Exception as e:
            frappe.log_error(f"Error getting board roles for {self.name}: {str(e)}", "ChapterMixin")
            return []

    def _is_chapter_management_enabled(self):
        """Check if chapter management is enabled (delegates to service)"""
        try:
            from verenigingen.services.member.chapter.chapter_management_service import (
                get_chapter_management_service,
            )

            return get_chapter_management_service().is_chapter_management_enabled()
        except Exception:
            # Default to enabled for backward compatibility
            return True
