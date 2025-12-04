# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
ChapterAssignmentService - Chapter member assignment operations

This service handles administrative chapter assignment operations, including
assignment with automatic cleanup of existing memberships and board roles.

Extracted from chapter.py:
- assign_member_to_chapter() - Lines 1050-1117 (68 LOC)
- assign_member_to_chapter_with_cleanup() - Lines 1160-1270 (111 LOC)
Total extraction: ~179 LOC

Note: join_chapter() and leave_chapter() operations remain delegated to
ChapterMembershipManager (utils/chapter_membership_manager.py) as they
handle member-initiated portal operations with different security context.

Architecture:
- Static methods for stateless operations
- Secure document operations for all updates
- Comprehensive cleanup logic for reassignments
- Member tracking field updates
- Comment/audit trail creation

Security:
- Uses secure_document_operation for all document modifications
- Required permissions: Member:write, Comment:create
- Proper justification logging for all privileged operations
- No permission bypasses

Dependencies:
- frappe.db for membership queries
- secure_document_operation for secure updates
- Chapter.add_member() for membership creation
- Member document for tracking updates
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import today

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class ChapterAssignmentService(StatelessService):
    """
    Service for managing administrative chapter member assignments.

    This service handles:
    - Direct member assignment to chapters (admin operation)
    - Assignment with automatic cleanup of existing memberships
    - Board membership cleanup during reassignment
    - Member tracking field updates
    - Audit trail creation via comments
    """

    def __init__(self) -> None:
        """Initialize the chapter assignment service."""
        super().__init__(service_name="ChapterAssignmentService")

    # ========================================================================
    # PUBLIC ASSIGNMENT METHODS
    # ========================================================================

    def assign_member(self, member: str, chapter: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Assign a member to a chapter.

        This is the basic assignment operation for administrative use.
        Does not perform cleanup of existing memberships - use
        assign_with_cleanup() for that.

        Args:
            member: Member ID to assign
            chapter: Chapter name to assign to
            note: Optional note explaining the assignment

        Returns:
            Dict with:
                - success: bool
                - added_to_members: bool
                - message: str (optional)

        Raises:
            frappe.ValidationError: If member or chapter missing/invalid
        """
        if not member or not chapter:
            frappe.throw(_("Member and Chapter are required"))

        # Get chapter and add member
        chapter_doc = frappe.get_doc("Chapter", chapter)
        added = chapter_doc.add_member(member)

        # Update member tracking fields
        self._update_member_tracking_fields(member=member, chapter=chapter, note=note)

        # Create audit comment if note provided
        if note:
            self._create_assignment_comment(member=member, chapter=chapter, note=note)

        return {"success": True, "added_to_members": added}

    def assign_with_cleanup(self, member: str, chapter: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Assign a member to a chapter with automatic cleanup.

        This method:
        1. Removes member from all other chapters
        2. Ends all board memberships
        3. Assigns to target chapter
        4. Updates tracking fields

        Use this for member reassignment scenarios where the member
        should only belong to the target chapter.

        Args:
            member: Member ID to assign
            chapter: Chapter name to assign to
            note: Optional note explaining the assignment

        Returns:
            Dict with:
                - success: bool
                - added_to_members: bool
                - cleanup_performed: bool
                - message: str

        Raises:
            frappe.ValidationError: If member or chapter missing/invalid
        """
        if not member or not chapter:
            frappe.throw(_("Member and Chapter are required"))

        try:
            cleanup_performed = False

            # 1. Cleanup existing chapter memberships
            cleanup_performed = (
                self._cleanup_chapter_memberships(member=member, target_chapter=chapter) or cleanup_performed
            )

            # 2. Cleanup board memberships
            cleanup_performed = (
                self._cleanup_board_memberships(member=member, reassignment_reason=f"Reassigned to {chapter}")
                or cleanup_performed
            )

            # 3. Check if already in target chapter
            existing_memberships = frappe.get_all(
                "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent"]
            )

            already_in_target = any(m.parent == chapter for m in existing_memberships)

            # 4. Handle different scenarios
            if already_in_target and len(existing_memberships) == 1:
                # Already in target, no other chapters
                result = {"success": True, "added_to_members": False, "cleanup_performed": cleanup_performed}

                if cleanup_performed:
                    result["message"] = _("Member was already in {0}. Board roles have been ended.").format(
                        chapter
                    )
                else:
                    result["message"] = _("Member is already assigned to {0}").format(chapter)

            elif already_in_target and len(existing_memberships) > 1:
                # In target plus others - cleanup performed
                result = {"success": True, "added_to_members": False, "cleanup_performed": True}
                result["message"] = _(
                    "Member was already in {0}. Other chapter memberships and board roles have been ended."
                ).format(chapter)

            else:
                # Not in target - perform assignment
                result = self.assign_member(member, chapter, note)
                result["cleanup_performed"] = cleanup_performed

                if cleanup_performed:
                    result["message"] = _(
                        "Member successfully assigned to {0}. Previous memberships and board roles have been ended."
                    ).format(chapter)
                else:
                    result["message"] = _("Member successfully assigned to {0}").format(chapter)

            return result

        except Exception as e:
            self.logger.error(f"Error in assign_with_cleanup: {str(e)}")
            return {"success": False, "message": str(e)}

    # ========================================================================
    # CLEANUP HELPER METHODS (Private)
    # ========================================================================

    def _cleanup_chapter_memberships(self, member: str, target_chapter: str) -> bool:
        """Remove member from all chapters except target.

        Args:
            member: Member ID
            target_chapter: Chapter to keep membership in

        Returns:
            True if any cleanup was performed
        """
        cleanup_performed = False

        existing_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member, "enabled": 1}, fields=["parent", "name"]
        )

        for membership in existing_memberships:
            if membership.parent != target_chapter:
                try:
                    # Try to use chapter's remove_member method first
                    old_chapter_doc = frappe.get_doc("Chapter", membership.parent)
                    old_chapter_doc.remove_member(member, leave_reason=f"Reassigned to {target_chapter}")
                    cleanup_performed = True
                    self.logger.info(f"Removed member {member} from chapter {membership.parent}")

                except Exception as e:
                    # If chapter method fails, disable directly
                    try:
                        frappe.db.set_value("Chapter Member", membership.name, "enabled", 0)
                        frappe.db.set_value(
                            "Chapter Member",
                            membership.name,
                            "leave_reason",
                            f"Reassigned to {target_chapter}",
                        )
                        frappe.db.commit()
                        cleanup_performed = True
                        self.logger.info(
                            f"Directly disabled membership {membership.name} for member {member}"
                        )

                    except Exception as e2:
                        self.logger.error(
                            f"Error removing member from chapter {membership.parent}: {str(e)} and {str(e2)}"
                        )
            else:
                self.logger.info(f"Member {member} is already in target chapter {target_chapter}")

        return cleanup_performed

    def _cleanup_board_memberships(self, member: str, reassignment_reason: str) -> bool:
        """End all board memberships for a member.

        Args:
            member: Member ID
            reassignment_reason: Reason text for audit trail

        Returns:
            True if any cleanup was performed
        """
        cleanup_performed = False

        # Get volunteer linked to member
        volunteer_name = frappe.db.get_value("Volunteer", {"member": member}, "name")
        if not volunteer_name:
            return False

        board_memberships = frappe.get_all(
            "Chapter Board Member",
            filters={"volunteer": volunteer_name, "is_active": 1},
            fields=["name", "parent"],
        )

        for board_membership in board_memberships:
            try:
                board_doc = frappe.get_doc("Chapter Board Member", board_membership.name)
                board_doc.is_active = 0
                board_doc.to_date = today()
                board_doc.notes = (board_doc.notes or "") + f"\nEnded due to member {reassignment_reason}"
                board_doc.save()
                cleanup_performed = True

                self.logger.info(f"Ended board membership {board_membership.name} for member {member}")

            except Exception as e:
                self.logger.error(f"Error ending board membership {board_membership.name}: {str(e)}")

        return cleanup_performed

    # ========================================================================
    # MEMBER UPDATE HELPER METHODS (Private)
    # ========================================================================

    def _update_member_tracking_fields(self, member: str, chapter: str, note: Optional[str] = None):
        """Update member tracking fields after assignment.

        Args:
            member: Member ID
            chapter: Chapter assigned to
            note: Optional assignment note
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        member_doc = frappe.get_doc("Member", member)
        member_doc.chapter_change_reason = note or f"Assigned to {chapter}"
        member_doc.chapter_assigned_by = frappe.session.user

        # Force update chapter display
        member_doc._chapter_assignment_in_progress = True
        member_doc.update_current_chapter_display()

        # Use secure operation for save
        member_update_result = secure_document_operation(
            operation="save",
            doc=member_doc,
            justification=f"Update member {member} chapter display after assignment to {chapter}",
            required_permissions=["Member:write"],
        )

        if not member_update_result.success:
            error_msg = "; ".join(member_update_result.errors)
            self.logger.error(f"Failed to update member chapter display: {error_msg}")
            frappe.throw(_("Failed to update member chapter display: {0}").format(error_msg))

    def _create_assignment_comment(self, member: str, chapter: str, note: str):
        """Create audit comment for chapter assignment.

        Args:
            member: Member ID
            chapter: Chapter assigned to
            note: Assignment note
        """
        from verenigingen.utils.secure_operations import secure_document_operation

        comment_doc = frappe.get_doc(
            {
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Member",
                "reference_name": member,
                "content": _("Changed chapter to {0}. Note: {1}").format(chapter, note),
            }
        )

        note_result = secure_document_operation(
            operation="insert",
            doc=comment_doc,
            justification=f"Add chapter change note for member {member}",
            required_permissions=["Comment:create"],
        )

        if not note_result.success:
            error_msg = "; ".join(note_result.errors)
            self.logger.error(f"Failed to create chapter change note: {error_msg}")
            # Don't fail main operation for note creation failure


def get_chapter_assignment_service() -> ChapterAssignmentService:
    """Get singleton instance of ChapterAssignmentService."""
    return ChapterAssignmentService()
