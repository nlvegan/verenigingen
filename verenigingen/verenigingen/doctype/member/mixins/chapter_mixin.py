import frappe


class ChapterMixin:
    """Mixin for chapter-related functionality"""

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
        """Get all chapters this member belongs to based on Chapter Member child table"""
        if not self._is_chapter_management_enabled():
            return []

        chapters = []

        # Get chapters from Chapter Member child table
        member_chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": self.name, "enabled": 1},
            fields=["parent as chapter", "chapter_join_date"],
            order_by="chapter_join_date desc",
        )

        for i, mc in enumerate(member_chapters):
            chapters.append(
                {
                    "chapter": mc.chapter,
                    "is_primary": i == 0,  # First (most recent) is primary
                    "chapter_join_date": mc.chapter_join_date,
                }
            )

        # Add board member chapters if not already included
        # Get volunteer linked to this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": self.name}, "name")
        board_chapters = []
        if volunteer_name:
            board_chapters = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_name, "is_active": 1},
                fields=["parent as chapter"],
            )

        for bc in board_chapters:
            if not any(c["chapter"] == bc.chapter for c in chapters):
                chapters.append({"chapter": bc.chapter, "is_primary": 0, "is_board": 1})

        return chapters

    def is_board_member(self, chapter=None):
        """Check if member is a board member of any chapter or a specific chapter"""
        if not self._is_chapter_management_enabled():
            return False

        filters = {"member": self.name, "is_active": 1}

        if chapter:
            filters["parent"] = chapter

        return frappe.db.exists("Chapter Board Member", filters)

    def get_board_roles(self):
        """Get all board roles for this member"""
        if not self._is_chapter_management_enabled():
            return []

        # Get volunteer linked to this member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": self.name}, "name")
        board_roles = []
        if volunteer_name:
            board_roles = frappe.get_all(
                "Chapter Board Member",
                filters={"volunteer": volunteer_name, "is_active": 1},
                fields=["parent as chapter", "chapter_role as role"],
            )

        return board_roles

    def _is_chapter_management_enabled(self):
        """Check if chapter management is enabled"""
        try:
            return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        except Exception:
            return True
