# Chapter Membership History Manager - Centralized chapter membership tracking
from typing import Dict

import frappe
from frappe.utils import now


class ChapterMembershipHistoryManager:
    """
    Centralized manager for chapter membership history tracking.

    Handles chapter membership history for both regular members and board members
    in a consistent way, similar to volunteer assignment history.
    """

    @staticmethod
    def add_membership_history(
        member_id: str,
        chapter_name: str,
        assignment_type: str,
        start_date: str,
        reason: str = None,
        status: str = "Active",
    ) -> bool:
        """
        Add membership to member history when starting a chapter relationship

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            assignment_type: Type of assignment ("Member" or "Board Member")
            start_date: Start date of membership
            reason: Reason for assignment (optional)
            status: Status of the membership ("Active", "Pending", etc.)

        Returns:
            bool: Success status
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Check if this exact membership already exists with the same status
            for membership in member.chapter_membership_history or []:
                if (
                    membership.chapter_name == chapter_name
                    and membership.assignment_type == assignment_type
                    and membership.status == status
                    and str(membership.start_date) == str(start_date)
                ):
                    print(f"Membership already exists in history for member {member_id}")
                    return True  # This exact membership already exists

            # ENHANCED: Check if we're trying to add an "Active" record when a "Pending" one exists
            # This should not happen - use update_membership_status() instead
            if status == "Active":
                for membership in member.chapter_membership_history or []:
                    if (
                        membership.chapter_name == chapter_name
                        and membership.assignment_type == assignment_type
                        and membership.status == "Pending"
                    ):
                        print(
                            f"WARNING: Attempted to add Active membership when Pending exists for member {member_id} in {chapter_name}"
                        )
                        print(
                            "Use update_membership_status() instead of add_membership_history() to activate pending memberships"
                        )
                        return False  # Prevent duplicate creation

            # Add new membership with specified status
            member.append(
                "chapter_membership_history",
                {
                    "chapter_name": chapter_name,
                    "assignment_type": assignment_type,
                    "start_date": start_date,
                    "status": status,
                    "reason": reason or f"Assigned to {chapter_name} as {assignment_type}",
                },
            )

            member.save(ignore_permissions=True)

            print(f"Added membership history for member {member_id}: {assignment_type} at {chapter_name}")
            return True

        except Exception as e:
            print(f"Error adding membership history for member {member_id}: {str(e)}")
            import traceback

            traceback.print_exc()
            return False

    @staticmethod
    def end_chapter_membership(
        member_id: str,
        chapter_name: str,
        assignment_type: str,
        start_date: str,
        end_date: str,
        reason: str = None,
    ) -> bool:
        """
        End member chapter membership history when ending a relationship normally

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            assignment_type: Type of assignment ("Member" or "Board Member")
            start_date: Start date of original membership
            end_date: End date of membership
            reason: Reason for ending (optional)

        Returns:
            bool: Success status
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Look for the specific membership that matches all criteria
            target_membership = None
            for membership in member.chapter_membership_history or []:
                if (
                    membership.chapter_name == chapter_name
                    and membership.assignment_type == assignment_type
                    and str(membership.start_date) == str(start_date)
                    and membership.status == "Active"
                ):
                    target_membership = membership
                    break

            if target_membership:
                # Update the specific membership to completed
                target_membership.end_date = end_date
                target_membership.status = "Completed"
                if reason:
                    target_membership.reason = reason

                # Success: Log as info, not error
                frappe.logger().info(
                    f"Updated membership history for member {member_id}: {assignment_type} at {chapter_name}"
                )
            else:
                # If we can't find the exact membership, look for any active one
                fallback_membership = None
                for membership in member.chapter_membership_history or []:
                    if (
                        membership.chapter_name == chapter_name
                        and membership.assignment_type == assignment_type
                        and membership.status == "Active"
                    ):
                        fallback_membership = membership
                        break

                if fallback_membership:
                    fallback_membership.end_date = end_date
                    fallback_membership.status = "Completed"
                    if reason:
                        fallback_membership.reason = reason

                    # Success: Log as info, not error
                    frappe.logger().info(
                        f"Updated fallback membership history for member {member_id}: {assignment_type} at {chapter_name}"
                    )
                else:
                    # Create a new completed membership if nothing exists
                    member.append(
                        "chapter_membership_history",
                        {
                            "chapter_name": chapter_name,
                            "assignment_type": assignment_type,
                            "start_date": start_date,
                            "end_date": end_date,
                            "status": "Completed",
                            "reason": reason or f"Left {chapter_name} as {assignment_type}",
                        },
                    )

                    # Success: Log as info, not error
                    frappe.logger().info(
                        f"Created new completed membership history for member {member_id}: {assignment_type} at {chapter_name}"
                    )

            member.save(ignore_permissions=True)
            return True

        except Exception as e:
            frappe.log_error(
                f"Error completing membership history for member {member_id}: {str(e)}",
                "Chapter Membership History Manager",
            )
            return False

    @staticmethod
    def get_active_memberships(member_id: str, assignment_type: str = None, chapter_name: str = None) -> list:
        """
        Get active chapter memberships for a member

        Args:
            member_id: Member ID
            assignment_type: Filter by assignment type (optional)
            chapter_name: Filter by chapter name (optional)

        Returns:
            list: List of active memberships
        """
        try:
            member = frappe.get_doc("Member", member_id)
            active_memberships = []

            for membership in member.chapter_membership_history or []:
                if membership.status == "Active":
                    if assignment_type and membership.assignment_type != assignment_type:
                        continue
                    if chapter_name and membership.chapter_name != chapter_name:
                        continue
                    active_memberships.append(membership)

            return active_memberships

        except Exception as e:
            frappe.log_error(
                f"Error getting active memberships for member {member_id}: {str(e)}",
                "Chapter Membership History Manager",
            )
            return []

    @staticmethod
    def cancel_chapter_membership(
        member_id: str, chapter_name: str, assignment_type: str, start_date: str
    ) -> bool:
        """
        Cancel membership history entry (for cases where membership is cancelled before completion)

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            assignment_type: Type of assignment
            start_date: Start date of original membership

        Returns:
            bool: Success status
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Find and remove the specific membership
            membership_to_remove = None
            for membership in member.chapter_membership_history or []:
                if (
                    membership.chapter_name == chapter_name
                    and membership.assignment_type == assignment_type
                    and str(membership.start_date) == str(start_date)
                    and membership.status == "Active"
                ):
                    membership_to_remove = membership
                    break

            if membership_to_remove:
                member.chapter_membership_history.remove(membership_to_remove)
                member.save(ignore_permissions=True)

                frappe.logger().info(
                    f"Removed membership history for member {member_id}: {assignment_type} at {chapter_name}"
                )
                return True
            else:
                frappe.logger().info(
                    f"Membership to remove not found for member {member_id}: {assignment_type} at {chapter_name}"
                )
                return False

        except Exception as e:
            frappe.log_error(
                f"Error removing membership history for member {member_id}: {str(e)}",
                "Chapter Membership History Manager",
            )
            return False

    @staticmethod
    def terminate_chapter_membership(
        member_id: str, chapter_name: str, assignment_type: str, end_date: str, reason: str
    ) -> bool:
        """
        Terminate chapter membership (different from normal end - implies involuntary end)

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            assignment_type: Type of assignment
            end_date: End date of membership
            reason: Reason for termination

        Returns:
            bool: Success status
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Find the active membership to terminate
            target_membership = None
            for membership in member.chapter_membership_history or []:
                if (
                    membership.chapter_name == chapter_name
                    and membership.assignment_type == assignment_type
                    and membership.status == "Active"
                ):
                    target_membership = membership
                    break

            if target_membership:
                target_membership.end_date = end_date
                target_membership.status = "Terminated"
                target_membership.reason = reason

                member.save(ignore_permissions=True)

                frappe.logger().info(
                    f"Terminated membership history for member {member_id}: {assignment_type} at {chapter_name}"
                )
                return True
            else:
                frappe.logger().info(
                    f"No active membership found to terminate for member {member_id}: {assignment_type} at {chapter_name}"
                )
                return False

        except Exception as e:
            frappe.log_error(
                f"Error terminating membership history for member {member_id}: {str(e)}",
                "Chapter Membership History Manager",
            )
            return False

    @staticmethod
    def get_membership_history_summary(member_id: str) -> Dict:
        """
        Get summary of member's chapter membership history

        Args:
            member_id: Member ID

        Returns:
            Dict: Summary information
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Safe handling of chapter membership history
            membership_history = getattr(member, "chapter_membership_history", None)
            if not membership_history or not isinstance(membership_history, list):
                membership_history = []

            total_memberships = len(membership_history)
            active_memberships = len(
                [m for m in membership_history if hasattr(m, "status") and m.status == "Active"]
            )
            completed_memberships = len(
                [m for m in membership_history if hasattr(m, "status") and m.status == "Completed"]
            )
            terminated_memberships = len(
                [m for m in membership_history if hasattr(m, "status") and m.status == "Terminated"]
            )

            # Get chapters the member has been associated with
            # Get unique chapters the member has been associated with\n            chapters = list(set([m.chapter_name for m in membership_history if hasattr(m, 'chapter_name') and m.chapter_name]))

            return {
                "total_memberships": total_memberships,
                "active_memberships": active_memberships,
                "completed_memberships": completed_memberships,
                "terminated_memberships": terminated_memberships,
                "chapters_associated": chapters,
                "last_updated": now(),
            }

        except Exception as e:
            frappe.log_error(
                f"Error getting membership history summary for member {member_id}: {str(e)}",
                "Chapter Membership History Manager",
            )
            return {
                "total_memberships": 0,
                "active_memberships": 0,
                "completed_memberships": 0,
                "terminated_memberships": 0,
                "chapters_associated": [],
                "error": str(e),
            }

    @staticmethod
    def update_membership_status(
        member_id: str, chapter_name: str, assignment_type: str, new_status: str, reason: str = None
    ) -> bool:
        """
        Update the status of an existing membership history entry

        Args:
            member_id: Member ID
            chapter_name: Chapter name
            assignment_type: Type of assignment ("Member" or "Board Member")
            new_status: New status ("Active", "Pending", "Completed", etc.)
            reason: Reason for status change (optional)

        Returns:
            bool: Success status
        """
        try:
            member = frappe.get_doc("Member", member_id)

            # Look for existing pending membership to update
            target_membership = None
            for membership in member.chapter_membership_history or []:
                if (
                    membership.chapter_name == chapter_name
                    and membership.assignment_type == assignment_type
                    and membership.status == "Pending"
                ):
                    target_membership = membership
                    break

            if target_membership:
                # Update the existing pending membership to new status
                target_membership.status = new_status
                if reason:
                    target_membership.reason = reason

                member.save(ignore_permissions=True)

                frappe.logger().info(
                    f"Updated membership status for member {member_id}: {assignment_type} at {chapter_name} from Pending to {new_status}"
                )
                return True
            else:
                print(f"No pending membership found to update for member {member_id} in {chapter_name}")
                return False

        except Exception as e:
            print(f"Error updating membership status for member {member_id}: {str(e)}")
            import traceback

            traceback.print_exc()
            return False
