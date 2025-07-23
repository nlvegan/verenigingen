"""
Centralized Chapter Membership Manager
Provides a unified interface for all chapter membership operations with proper history tracking
"""

from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.chapter_membership_history_manager import ChapterMembershipHistoryManager


class ChapterMembershipManager:
    """
    Centralized manager for all chapter membership operations.

    This utility ensures that:
    1. All chapter membership changes go through proper history tracking
    2. Member tracking fields are consistently updated
    3. Code duplication is eliminated
    4. Consistent validation and error handling
    """

    @staticmethod
    def join_chapter(
        member_id: str,
        chapter_name: str,
        introduction: str = None,
        website_url: str = None,
        user_email: str = None,
    ) -> Dict[str, Any]:
        """
        Standard method for a member to join a chapter

        Args:
            member_id: Member ID
            chapter_name: Chapter name to join
            introduction: Member introduction text
            website_url: Member website URL
            user_email: Email of user making the request (for validation)

        Returns:
            Dict with operation result
        """
        try:
            # Validate user permissions
            if user_email and user_email != "Administrator":
                member_doc = frappe.get_doc("Member", member_id)
                if user_email != member_doc.email:
                    return {"success": False, "error": _("You don't have permission to perform this action")}

            # Check if member exists
            if not member_id or not member_id.strip():
                return {"success": False, "error": _("Invalid member ID provided")}
            if not frappe.db.exists("Member", member_id):
                return {"success": False, "error": _("Member {0} not found").format(member_id)}

            # Check if chapter exists
            if not frappe.db.exists("Chapter", chapter_name):
                return {"success": False, "error": _("Chapter {0} not found").format(chapter_name)}

            # Get chapter document and use its member manager
            chapter_doc = frappe.get_doc("Chapter", chapter_name)

            # Use the chapter's member manager which handles history tracking
            result = chapter_doc.member_manager.add_member(
                member_id=member_id, introduction=introduction, website_url=website_url, notify=True
            )

            # Update member tracking fields if successful
            if result.get("success"):
                ChapterMembershipManager._update_member_tracking_fields(
                    member_id=member_id,
                    reason="Joined via member portal",
                    assigned_by=user_email or frappe.session.user,
                )

            return result

        except Exception as e:
            frappe.log_error(f"Error in join_chapter: {str(e)}", "ChapterMembershipManager")
            return {"success": False, "error": str(e)}

    @staticmethod
    def leave_chapter(
        member_id: str,
        chapter_name: str,
        leave_reason: str = None,
        user_email: str = None,
        permanent: bool = False,
    ) -> Dict[str, Any]:
        """
        Standard method for a member to leave a chapter

        Args:
            member_id: Member ID
            chapter_name: Chapter name to leave
            leave_reason: Reason for leaving
            user_email: Email of user making the request (for validation)
            permanent: Whether to remove completely or just disable

        Returns:
            Dict with operation result
        """
        try:
            # Validate user permissions
            if user_email and user_email != "Administrator":
                member_doc = frappe.get_doc("Member", member_id)
                if user_email != member_doc.email:
                    return {"success": False, "error": _("You don't have permission to perform this action")}

            # Check if member exists
            if not member_id or not member_id.strip():
                return {"success": False, "error": _("Invalid member ID provided")}
            if not frappe.db.exists("Member", member_id):
                return {"success": False, "error": _("Member {0} not found").format(member_id)}

            # Check if chapter exists
            if not frappe.db.exists("Chapter", chapter_name):
                return {"success": False, "error": _("Chapter {0} not found").format(chapter_name)}

            # Get chapter document and use its member manager
            chapter_doc = frappe.get_doc("Chapter", chapter_name)

            # Use the chapter's member manager which handles history tracking
            result = chapter_doc.member_manager.remove_member(
                member_id=member_id, leave_reason=leave_reason, permanent=permanent, notify=True
            )

            # Update member tracking fields if successful
            if result.get("success"):
                ChapterMembershipManager._update_member_tracking_fields(
                    member_id=member_id,
                    reason="Left chapter: {leave_reason or 'No reason provided'}",
                    assigned_by=user_email or frappe.session.user,
                )

            return result

        except Exception as e:
            frappe.log_error(f"Error in leave_chapter: {str(e)}", "ChapterMembershipManager")
            return {"success": False, "error": str(e)}

    @staticmethod
    def assign_member_to_chapter(
        member_id: str, chapter_name: str, reason: str = None, assigned_by: str = None
    ) -> Dict[str, Any]:
        """
        Administrative method to assign a member to a chapter

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            reason: Reason for assignment
            assigned_by: User making the assignment

        Returns:
            Dict with operation result
        """
        try:
            # Check if member exists
            if not member_id or not member_id.strip():
                return {"success": False, "error": _("Invalid member ID provided")}
            if not frappe.db.exists("Member", member_id):
                return {"success": False, "error": _("Member {0} not found").format(member_id)}

            # Check if chapter exists
            if not frappe.db.exists("Chapter", chapter_name):
                return {"success": False, "error": _("Chapter {0} not found").format(chapter_name)}

            # Get member details for introduction
            frappe.get_doc("Member", member_id)

            # Get chapter document and use its member manager
            chapter_doc = frappe.get_doc("Chapter", chapter_name)

            # Use the chapter's member manager which handles history tracking
            result = chapter_doc.member_manager.add_member(
                member_id=member_id,
                introduction=reason or "Assigned to {chapter_name} by administrator",
                notify=True,
            )

            # Update member tracking fields if successful
            if result.get("success"):
                ChapterMembershipManager._update_member_tracking_fields(
                    member_id=member_id,
                    reason=reason or "Assigned to {chapter_name}",
                    assigned_by=assigned_by or frappe.session.user,
                )

            return result

        except Exception as e:
            frappe.log_error(f"Error in assign_member_to_chapter: {str(e)}", "ChapterMembershipManager")
            return {"success": False, "error": str(e)}

    @staticmethod
    def transfer_member_between_chapters(
        member_id: str, from_chapter: str, to_chapter: str, reason: str = None, assigned_by: str = None
    ) -> Dict[str, Any]:
        """
        Transfer a member from one chapter to another

        Args:
            member_id: Member ID
            from_chapter: Source chapter name
            to_chapter: Destination chapter name
            reason: Reason for transfer
            assigned_by: User making the transfer

        Returns:
            Dict with operation result
        """
        try:
            # First, leave the old chapter
            leave_result = ChapterMembershipManager.leave_chapter(
                member_id=member_id,
                chapter_name=from_chapter,
                leave_reason=reason or "Transferred to {to_chapter}",
                permanent=False,
            )

            if not leave_result.get("success"):
                return {
                    "success": False,
                    "error": "Failed to leave {from_chapter}: {leave_result.get('error')}",
                }

            # Then, join the new chapter
            join_result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=member_id,
                chapter_name=to_chapter,
                reason=reason or "Transferred from {from_chapter}",
                assigned_by=assigned_by,
            )

            if not join_result.get("success"):
                return {"success": False, "error": "Failed to join {to_chapter}: {join_result.get('error')}"}

            # Log the transfer
            frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": member_id,
                    "content": _("Transferred from {0} to {1}. Reason: {2}").format(
                        from_chapter, to_chapter, reason or "Administrative transfer"
                    ),
                }
            ).insert(ignore_permissions=True)

            return {
                "success": True,
                "message": _("Successfully transferred member from {0} to {1}").format(
                    from_chapter, to_chapter
                ),
                "action": "transferred",
            }

        except Exception as e:
            frappe.log_error(
                f"Error in transfer_member_between_chapters: {str(e)}", "ChapterMembershipManager"
            )
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_member_chapter_status(member_id: str) -> Dict[str, Any]:
        """
        Get comprehensive chapter membership status for a member

        Args:
            member_id: Member ID

        Returns:
            Dict with chapter membership information
        """
        try:
            if not frappe.db.exists("Member", member_id):
                return {"success": False, "error": _("Member {0} not found").format(member_id)}

            # Get current chapter memberships
            current_memberships = frappe.db.sql(
                """
                SELECT
                    cm.parent as chapter_name,
                    cm.chapter_join_date,
                    cm.enabled,
                    cm.leave_reason,
                    c.name as display_name
                FROM `tabChapter Member` cm
                INNER JOIN `tabChapter` c ON cm.parent = c.name
                WHERE cm.member = %(member_id)s
                ORDER BY cm.chapter_join_date DESC
            """,
                {"member_id": member_id},
                as_dict=True,
            )

            # Get active history records
            active_history = ChapterMembershipHistoryManager.get_active_memberships(
                member_id=member_id, assignment_type="Member"
            )

            return {
                "success": True,
                "member_id": member_id,
                "current_memberships": current_memberships,
                "active_history": [
                    {
                        "chapter_name": h.chapter_name,
                        "start_date": h.start_date,
                        "status": h.status,
                        "reason": h.reason,
                    }
                    for h in active_history
                ],
                "primary_chapter": current_memberships[0] if current_memberships else None,
            }

        except Exception as e:
            frappe.log_error(f"Error in get_member_chapter_status: {str(e)}", "ChapterMembershipManager")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _update_member_tracking_fields(member_id: str, reason: str, assigned_by: str):
        """
        Update member tracking fields consistently

        Args:
            member_id: Member ID
            reason: Reason for change
            assigned_by: User making the change
        """
        try:
            frappe.db.set_value(
                "Member", member_id, {"chapter_change_reason": reason, "chapter_assigned_by": assigned_by}
            )

        except Exception as e:
            frappe.log_error(
                f"Error updating member tracking fields for {member_id}: {str(e)}", "ChapterMembershipManager"
            )

    @staticmethod
    def validate_chapter_membership_change(
        member_id: str, chapter_name: str, operation: str
    ) -> Dict[str, Any]:
        """
        Validate chapter membership change before executing

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            operation: Operation type ('join', 'leave', 'transfer')

        Returns:
            Dict with validation result
        """
        try:
            # Check if member exists and is active
            member_doc = frappe.get_doc("Member", member_id)
            if member_doc.status != "Active":
                return {
                    "valid": False,
                    "error": _("Member {0} is not active (status: {1})").format(
                        member_doc.full_name, member_doc.status
                    ),
                }

            # Check if chapter exists and is active
            chapter_doc = frappe.get_doc("Chapter", chapter_name)
            # Note: Chapter doctype may not have a status field, so we'll just check if it exists
            # if getattr(chapter_doc, 'status', 'Active') != "Active":
            #     return {
            #         "valid": False,
            #         "error": _("Chapter {0} is not active").format(chapter_name)
            #     }

            # Operation-specific validations
            if operation == "join":
                # Check if already a member
                existing_membership = frappe.db.exists(
                    "Chapter Member", {"member": member_id, "parent": chapter_name, "enabled": 1}
                )

                if existing_membership:
                    return {"valid": False, "error": _("Member is already active in this chapter")}

            elif operation == "leave":
                # Check if actually a member
                existing_membership = frappe.db.exists(
                    "Chapter Member", {"member": member_id, "parent": chapter_name, "enabled": 1}
                )

                if not existing_membership:
                    return {"valid": False, "error": _("Member is not an active member of this chapter")}

            return {"valid": True, "member": member_doc, "chapter": chapter_doc}

        except Exception as e:
            return {"valid": False, "error": str(e)}
