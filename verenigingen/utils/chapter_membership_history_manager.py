# Chapter Membership History Manager - Centralized chapter membership tracking
from typing import Dict

import frappe
from frappe.utils import now

from verenigingen.utils.history_manager_utils import (
    HistoryOperationResult,
    check_duplicate_entry,
    ensure_doc_exists,
    find_entry_by_criteria,
    get_request_cache,
    log_history_error,
    make_cache_key,
    recursion_guard,
    safe_child_table_update,
)


class ChapterMembershipHistoryManager:
    """
    Centralized manager for chapter membership history tracking.

    Handles chapter membership history for both regular members and board members
    in a consistent way, similar to volunteer assignment history.
    """

    CHILD_TABLE = "chapter_membership_history"
    CACHE_NAME = "chapter_history_cache"

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
            # Check for duplicates within same request using request-level cache
            cache = get_request_cache(ChapterMembershipHistoryManager.CACHE_NAME)
            history_key = make_cache_key(member_id, chapter_name, assignment_type, status, start_date)
            if history_key in cache:
                frappe.logger().debug(
                    f"Skipping duplicate membership history within same request: {member_id} at {chapter_name}"
                )
                return True

            # Check if member still exists
            if not ensure_doc_exists("Member", member_id, "add chapter membership history"):
                return False

            member = frappe.get_doc("Member", member_id)

            # Recursion guard - prevent infinite loops from hooks
            with recursion_guard(member, "_updating_chapter_membership_history") as should_proceed:
                if not should_proceed:
                    return True

                # Check for existing duplicate in database
                match_fields = {
                    "chapter_name": chapter_name,
                    "assignment_type": assignment_type,
                    "status": status,
                    "start_date": start_date,
                }
                existing = check_duplicate_entry(member.chapter_membership_history, match_fields)
                if existing:
                    frappe.logger().debug(
                        f"Skipping duplicate membership history for member {member_id} at {chapter_name}"
                    )
                    return True

                # Check if we're trying to add "Active" when "Pending" exists
                if status == "Active":
                    pending_match = {
                        "chapter_name": chapter_name,
                        "assignment_type": assignment_type,
                        "status": "Pending",
                    }
                    if check_duplicate_entry(member.chapter_membership_history, pending_match):
                        frappe.logger().warning(
                            f"Attempted to add Active membership when Pending exists for member {member_id} in {chapter_name}. "
                            "Use update_membership_status() instead."
                        )
                        return False

                # Add new membership
                member.append(
                    ChapterMembershipHistoryManager.CHILD_TABLE,
                    {
                        "chapter_name": chapter_name,
                        "assignment_type": assignment_type,
                        "start_date": start_date,
                        "status": status,
                        "reason": reason or f"Assigned to {chapter_name} as {assignment_type}",
                    },
                )

                # Use safe child table update - avoids validating unrelated child tables
                result = safe_child_table_update(
                    doc=member,
                    child_table_name=ChapterMembershipHistoryManager.CHILD_TABLE,
                    justification=f"Add membership history for member {member_id} joining {chapter_name} as {assignment_type}",
                    doctype_permission="Member:write",
                    auto_cleanup=True,
                )

                if not result.success:
                    log_history_error(
                        title="Chapter Membership History Add Failed",
                        message=f"Failed to save membership history for member {member_id}: {'; '.join(result.errors)}",
                    )
                    return False

                # Add to cache to prevent duplicates within same request
                cache.add(history_key)

                frappe.logger().info(
                    f"Added membership history for member {member_id}: {assignment_type} at {chapter_name} with status {status}"
                )
                return True

        except Exception as e:
            log_history_error(
                title="Chapter Membership History Error",
                message=f"Error adding membership history for member {member_id}: {str(e)}",
                include_traceback=True,
            )
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
        End member chapter membership history when ending a relationship normally.

        Handles both Active and Pending memberships - both should be ended when
        a member leaves or is disabled.

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
            if not ensure_doc_exists("Member", member_id, "end chapter membership"):
                return False

            member = frappe.get_doc("Member", member_id)

            # Recursion guard - prevent infinite loops from hooks
            with recursion_guard(member, "_updating_chapter_membership_history") as should_proceed:
                if not should_proceed:
                    return True

                # Look for matching membership (Active or Pending)
                criteria = {
                    "chapter_name": chapter_name,
                    "assignment_type": assignment_type,
                    "start_date": start_date,
                }
                target = find_entry_by_criteria(
                    member.chapter_membership_history, criteria, status_values=["Active", "Pending"]
                )

                if target:
                    original_status = target.status
                    target.end_date = end_date
                    target.status = "Terminated"
                    if reason:
                        target.reason = reason

                    frappe.logger().info(
                        f"Updated membership history for member {member_id}: {assignment_type} at {chapter_name} "
                        f"(was {original_status})"
                    )
                else:
                    # Fallback: look for any Active/Pending membership at this chapter
                    fallback_criteria = {"chapter_name": chapter_name, "assignment_type": assignment_type}
                    fallback = find_entry_by_criteria(
                        member.chapter_membership_history,
                        fallback_criteria,
                        status_values=["Active", "Pending"],
                    )

                    if fallback:
                        original_status = fallback.status
                        fallback.end_date = end_date
                        fallback.status = "Terminated"
                        if reason:
                            fallback.reason = reason

                        frappe.logger().info(
                            f"Updated fallback membership history for member {member_id}: {assignment_type} at {chapter_name} "
                            f"(was {original_status})"
                        )
                    else:
                        # Check if already terminated (idempotency)
                        terminated = find_entry_by_criteria(
                            member.chapter_membership_history,
                            fallback_criteria,
                            status_values=["Terminated", "Completed"],
                        )
                        if terminated:
                            frappe.logger().info(
                                f"Membership already ended for member {member_id}: {assignment_type} at {chapter_name} "
                                f"(status={terminated.status})"
                            )
                            return True

                        # Create new completed entry
                        member.append(
                            ChapterMembershipHistoryManager.CHILD_TABLE,
                            {
                                "chapter_name": chapter_name,
                                "assignment_type": assignment_type,
                                "start_date": start_date,
                                "end_date": end_date,
                                "status": "Completed",
                                "reason": reason or f"Left {chapter_name} as {assignment_type}",
                            },
                        )
                        frappe.logger().info(
                            f"Created new completed membership history for member {member_id}: {assignment_type} at {chapter_name}"
                        )

                # Use safe child table update
                result = safe_child_table_update(
                    doc=member,
                    child_table_name=ChapterMembershipHistoryManager.CHILD_TABLE,
                    justification=f"Complete membership history for member {member_id} leaving {chapter_name} as {assignment_type}",
                    doctype_permission="Member:write",
                    auto_cleanup=True,
                )

                if not result.success:
                    log_history_error(
                        title="Chapter Membership End Failed",
                        message=f"Failed to save membership completion for member {member_id}: {'; '.join(result.errors)}",
                    )
                    return False

                return True

        except Exception as e:
            log_history_error(
                title="Chapter Membership History Error",
                message=f"Error completing membership history for member {member_id}: {str(e)}",
                include_traceback=True,
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
            if not ensure_doc_exists("Member", member_id, "get active memberships"):
                return []

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
            log_history_error(
                title="Chapter Membership Query Error",
                message=f"Error getting active memberships for member {member_id}: {str(e)}",
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
            if not ensure_doc_exists("Member", member_id, "cancel chapter membership"):
                return False

            member = frappe.get_doc("Member", member_id)

            # Recursion guard - prevent infinite loops from hooks
            with recursion_guard(member, "_updating_chapter_membership_history") as should_proceed:
                if not should_proceed:
                    return True

                # Find the specific membership to remove
                criteria = {
                    "chapter_name": chapter_name,
                    "assignment_type": assignment_type,
                    "start_date": start_date,
                }
                membership_to_remove = find_entry_by_criteria(
                    member.chapter_membership_history, criteria, status_values=["Active"]
                )

                if membership_to_remove:
                    member.chapter_membership_history.remove(membership_to_remove)

                    result = safe_child_table_update(
                        doc=member,
                        child_table_name=ChapterMembershipHistoryManager.CHILD_TABLE,
                        justification=f"Remove membership history for member {member_id} from {chapter_name} as {assignment_type}",
                        doctype_permission="Member:write",
                        auto_cleanup=True,
                    )

                    if not result.success:
                        log_history_error(
                            title="Chapter Membership Cancel Failed",
                            message=f"Failed to save membership history removal for member {member_id}: {'; '.join(result.errors)}",
                        )
                        return False

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
            log_history_error(
                title="Chapter Membership History Error",
                message=f"Error removing membership history for member {member_id}: {str(e)}",
                include_traceback=True,
            )
            return False

    @staticmethod
    def terminate_chapter_membership(
        member_id: str, chapter_name: str, assignment_type: str, end_date: str, reason: str
    ) -> bool:
        """
        Terminate chapter membership (different from normal end - implies involuntary end)

        Handles both Active and Pending memberships - both should be terminated when
        a member is terminated.

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
            if not ensure_doc_exists("Member", member_id, "terminate chapter membership"):
                return False

            member = frappe.get_doc("Member", member_id)

            # Recursion guard - prevent infinite loops from hooks
            with recursion_guard(member, "_updating_chapter_membership_history") as should_proceed:
                if not should_proceed:
                    return True

                # Find membership to terminate (Active or Pending)
                criteria = {"chapter_name": chapter_name, "assignment_type": assignment_type}
                target = find_entry_by_criteria(
                    member.chapter_membership_history, criteria, status_values=["Active", "Pending"]
                )

                if target:
                    original_status = target.status
                    target.end_date = end_date
                    target.status = "Terminated"
                    target.reason = reason

                    result = safe_child_table_update(
                        doc=member,
                        child_table_name=ChapterMembershipHistoryManager.CHILD_TABLE,
                        justification=f"Terminate membership history for member {member_id} leaving {chapter_name} as {assignment_type}",
                        doctype_permission="Member:write",
                        auto_cleanup=True,
                    )

                    if not result.success:
                        log_history_error(
                            title="Chapter Membership Terminate Failed",
                            message=f"Failed to save membership termination for member {member_id}: {'; '.join(result.errors)}",
                        )
                        return False

                    frappe.logger().info(
                        f"Terminated membership history for member {member_id}: {assignment_type} at {chapter_name} "
                        f"(was {original_status})"
                    )
                    return True
                else:
                    # Check if already terminated (idempotency)
                    terminated = find_entry_by_criteria(
                        member.chapter_membership_history, criteria, status_values=["Terminated"]
                    )
                    if terminated:
                        frappe.logger().info(
                            f"Membership already terminated for member {member_id}: {assignment_type} at {chapter_name}"
                        )
                        return True

                    frappe.logger().info(
                        f"No active/pending membership found to terminate for member {member_id}: {assignment_type} at {chapter_name}"
                    )
                    return False

        except Exception as e:
            log_history_error(
                title="Chapter Membership History Error",
                message=f"Error terminating membership history for member {member_id}: {str(e)}",
                include_traceback=True,
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
            if not ensure_doc_exists("Member", member_id, "get membership history summary"):
                return {
                    "total_memberships": 0,
                    "active_memberships": 0,
                    "completed_memberships": 0,
                    "terminated_memberships": 0,
                    "chapters_associated": [],
                    "error": "Member does not exist",
                }

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

            # Get unique chapters the member has been associated with
            chapters = list(
                set(
                    [
                        m.chapter_name
                        for m in membership_history
                        if hasattr(m, "chapter_name") and m.chapter_name
                    ]
                )
            )

            return {
                "total_memberships": total_memberships,
                "active_memberships": active_memberships,
                "completed_memberships": completed_memberships,
                "terminated_memberships": terminated_memberships,
                "chapters_associated": chapters,
                "last_updated": now(),
            }

        except Exception as e:
            log_history_error(
                title="Chapter Membership Summary Error",
                message=f"Error getting membership history summary for member {member_id}: {str(e)}",
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
            if not ensure_doc_exists("Member", member_id, "update membership status"):
                return False

            member = frappe.get_doc("Member", member_id)

            # Recursion guard - prevent infinite loops from hooks
            with recursion_guard(member, "_updating_chapter_membership_history") as should_proceed:
                if not should_proceed:
                    return True

                # Look for existing pending membership to update
                criteria = {"chapter_name": chapter_name, "assignment_type": assignment_type}
                target = find_entry_by_criteria(
                    member.chapter_membership_history, criteria, status_values=["Pending"]
                )

                if target:
                    target.status = new_status
                    if reason:
                        target.reason = reason

                    result = safe_child_table_update(
                        doc=member,
                        child_table_name=ChapterMembershipHistoryManager.CHILD_TABLE,
                        justification=f"Update membership status for member {member_id} in {chapter_name} as {assignment_type} to {new_status}",
                        doctype_permission="Member:write",
                        auto_cleanup=True,
                    )

                    if not result.success:
                        log_history_error(
                            title="Chapter Membership Status Update Failed",
                            message=f"Failed to save membership status update for member {member_id}: {'; '.join(result.errors)}",
                        )
                        return False

                    frappe.logger().info(
                        f"Updated membership status for member {member_id}: {assignment_type} at {chapter_name} from Pending to {new_status}"
                    )
                    return True
                else:
                    # Check if there's already an entry with the desired status
                    existing = find_entry_by_criteria(
                        member.chapter_membership_history, criteria, status_values=[new_status]
                    )
                    if existing:
                        frappe.logger().info(
                            f"Membership already has status {new_status} for member {member_id} in {chapter_name} - no update needed"
                        )
                        return True

                    frappe.logger().warning(
                        f"No pending membership found to update for member {member_id} in {chapter_name} "
                        f"(assignment_type={assignment_type}). Available entries: "
                        f"{[(m.chapter_name, m.assignment_type, m.status) for m in member.chapter_membership_history or []]}"
                    )
                    return False

        except Exception as e:
            log_history_error(
                title="Chapter Membership Status Error",
                message=f"Error updating membership status for member {member_id}: {str(e)}",
                include_traceback=True,
            )
            return False
