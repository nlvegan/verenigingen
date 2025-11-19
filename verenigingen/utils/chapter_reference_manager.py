"""
Chapter Reference Manager

Dedicated manager for handling chapter reference validation and cleanup.
This separates chapter management concerns from financial history operations.
"""

from typing import List

import frappe


class ChapterReferenceManager:
    """
    Dedicated manager for chapter reference validation and cleanup.

    This handles the specific issue where members have references to deleted
    chapters in their chapter_membership_history, which causes link validation
    failures during document saves.
    """

    def __init__(self, member_doc):
        """Initialize with member document."""
        self.member = member_doc

    def validate_chapter_references(self) -> List[str]:
        """
        Validate all chapter references in member's chapter history.

        Returns:
            List[str]: List of invalid chapter names
        """
        invalid_chapters = []

        for entry in self.member.chapter_membership_history or []:
            chapter_name = getattr(entry, "chapter_name", None)
            if chapter_name and not frappe.db.exists("Chapter", chapter_name):
                invalid_chapters.append(chapter_name)

        return invalid_chapters

    def cleanup_invalid_chapter_references(self) -> int:
        """
        Remove invalid chapter references from member's chapter history.

        Returns:
            int: Number of invalid references removed
        """
        try:
            chapter_history = getattr(self.member, "chapter_membership_history", []) or []
            if not chapter_history:
                return 0

            # Get list of valid chapters from database
            valid_chapters = set()
            try:
                valid_chapter_records = frappe.get_all("Chapter", fields=["name"])
                valid_chapters = {ch.name for ch in valid_chapter_records}
            except Exception:
                # If we can't get valid chapters, we can't clean up
                frappe.logger().warning("Could not fetch valid chapters for cleanup")
                return 0

            # Filter out invalid chapter references
            cleaned_history = []
            removed_count = 0

            for entry in chapter_history:
                chapter_name = getattr(entry, "chapter_name", None)
                if chapter_name and chapter_name in valid_chapters:
                    cleaned_history.append(entry)
                else:
                    removed_count += 1
                    frappe.logger().warning(
                        f"Removing invalid chapter reference '{chapter_name}' from {self.member.name}"
                    )

            if removed_count > 0:
                # Clear the child table and rebuild with valid entries only
                self.member.set("chapter_membership_history", [])
                for entry in cleaned_history:
                    self.member.append("chapter_membership_history", entry)

                frappe.logger().info(
                    f"Cleaned up {removed_count} invalid chapter references from {self.member.name}"
                )

            return removed_count

        except Exception as e:
            frappe.log_error(
                f"Error cleaning up chapter references for {self.member.name}: {str(e)}",
                "Chapter Cleanup Error",
            )
            return 0

    def has_invalid_chapter_references(self) -> bool:
        """
        Quick check if member has any invalid chapter references.

        Returns:
            bool: True if invalid references exist
        """
        return len(self.validate_chapter_references()) > 0


def cleanup_member_chapter_references(member_name: str) -> int:
    """
    Utility function to clean up chapter references for a specific member.

    Args:
        member_name: Name of the member document

    Returns:
        int: Number of invalid references removed
    """
    try:
        member = frappe.get_doc("Member", member_name)
        manager = ChapterReferenceManager(member)
        return manager.cleanup_invalid_chapter_references()
    except Exception as e:
        frappe.log_error(
            f"Error cleaning up chapter references for {member_name}: {str(e)}",
            "Chapter Cleanup Utility Error",
        )
        return 0
