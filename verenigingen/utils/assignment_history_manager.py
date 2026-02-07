# Assignment History Manager - Centralized volunteer assignment tracking

import frappe
from frappe.utils import getdate

from verenigingen.utils.base_history_manager import BaseHistoryManager
from verenigingen.utils.history_manager_utils import (
    check_duplicate_entry,
    ensure_doc_exists,
    find_entry_by_criteria,
    log_history_error,
)


class AssignmentHistoryManager(BaseHistoryManager):
    """
    Centralized manager for volunteer assignment history tracking.

    Handles assignment history for both board positions and team assignments
    in a consistent way.
    """

    PARENT_DOCTYPE = "Volunteer"
    CHILD_TABLE = "assignment_history"
    PERMISSION = "Volunteer:write"
    RECURSION_FLAG = "_updating_assignment_history"

    @staticmethod
    def add_assignment_history(
        volunteer_id: str,
        assignment_type: str,
        reference_doctype: str,
        reference_name: str,
        role: str,
        start_date: str,
    ) -> bool:
        """
        Add active assignment to volunteer history when starting a role

        Args:
            volunteer_id: Volunteer ID
            assignment_type: Type of assignment (e.g., "Board Position", "Team")
            reference_doctype: Document type (e.g., "Chapter", "Team")
            reference_name: Document name
            role: Role or position name
            start_date: Start date of assignment

        Returns:
            bool: Success status
        """

        def _callback(volunteer):
            # Check for existing duplicate (Active or Completed)
            match_fields = {
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "role": role,
                "start_date": start_date,
            }
            existing = check_duplicate_entry(volunteer.assignment_history, match_fields)

            if existing:
                if existing.status == "Active":
                    frappe.logger().info(
                        f"Assignment already exists as Active for volunteer {volunteer_id}: "
                        f"{reference_doctype} {reference_name} - {role} (start: {start_date})"
                    )
                    return True  # skip save

                if existing.status == "Completed":
                    # Reactivate the existing completed assignment
                    frappe.logger().warning(
                        f"Assignment already exists as Completed for volunteer {volunteer_id}: "
                        f"{reference_doctype} {reference_name} - {role}. Reactivating instead of duplicating."
                    )
                    existing.status = "Active"
                    existing.end_date = None
                    return None  # save needed

            # Add new active assignment
            volunteer.append(
                AssignmentHistoryManager.CHILD_TABLE,
                {
                    "assignment_type": assignment_type,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "role": role,
                    "start_date": start_date,
                    "status": "Active",
                },
            )
            frappe.logger().info(
                f"Added assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
            )
            return None  # save needed

        return AssignmentHistoryManager._with_doc(
            volunteer_id,
            f"add assignment history: {assignment_type} - {role}",
            _callback,
            error_title="Assignment History Add Failed",
        )

    @staticmethod
    def complete_assignment_history(
        volunteer_id: str,
        assignment_type: str,
        reference_doctype: str,
        reference_name: str,
        role: str,
        start_date: str,
        end_date: str,
    ) -> bool:
        """
        Complete volunteer assignment history when ending a role

        Args:
            volunteer_id: Volunteer ID
            assignment_type: Type of assignment (e.g., "Board Position", "Team")
            reference_doctype: Document type (e.g., "Chapter", "Team")
            reference_name: Document name
            role: Role or position name
            start_date: Start date of original assignment
            end_date: End date of assignment

        Returns:
            bool: Success status
        """

        def _callback(volunteer):
            # Try to find by reference + start_date first (most specific)
            criteria = {
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "start_date": start_date,
            }
            target = find_entry_by_criteria(volunteer.assignment_history, criteria, status_values=["Active"])

            # Fallback: try matching by reference + role
            if not target:
                fallback_criteria = {
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "role": role,
                }
                target = find_entry_by_criteria(
                    volunteer.assignment_history, fallback_criteria, status_values=["Active"]
                )

            if target:
                target.end_date = end_date
                target.status = "Completed"
                frappe.logger().info(
                    f"Updated assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
                )
                return None  # save needed

            # Check if already completed
            completed_criteria = {
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "role": role,
                "start_date": start_date,
            }
            existing_completed = find_entry_by_criteria(
                volunteer.assignment_history, completed_criteria, status_values=["Completed"]
            )

            if existing_completed:
                if getdate(existing_completed.end_date) != getdate(end_date):
                    existing_completed.end_date = end_date
                    frappe.logger().info(
                        f"Updated end_date for existing completed assignment for volunteer {volunteer_id}"
                    )
                    return None  # save needed
                frappe.logger().info(
                    f"Assignment already completed for volunteer {volunteer_id}: "
                    f"{assignment_type} - {role}. No action needed."
                )
                return True  # skip save

            # Create new completed assignment (reconstruct missing history)
            volunteer.append(
                AssignmentHistoryManager.CHILD_TABLE,
                {
                    "assignment_type": assignment_type,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "role": role,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": "Completed",
                },
            )
            frappe.logger().info(
                f"Reconstructed missing assignment history for volunteer {volunteer_id}: "
                f"{assignment_type} - {role}"
            )
            return None  # save needed

        return AssignmentHistoryManager._with_doc(
            volunteer_id,
            f"complete assignment history: {assignment_type} - {role}",
            _callback,
            error_title="Assignment History Complete Failed",
        )

    @staticmethod
    def get_active_assignments(
        volunteer_id: str, assignment_type: str = None, reference_doctype: str = None
    ) -> list:
        """
        Get active assignments for a volunteer

        Args:
            volunteer_id: Volunteer ID
            assignment_type: Filter by assignment type (optional)
            reference_doctype: Filter by reference doctype (optional)

        Returns:
            list: List of active assignments
        """
        try:
            if not ensure_doc_exists("Volunteer", volunteer_id, "get active assignments"):
                return []

            volunteer = frappe.get_doc("Volunteer", volunteer_id)
            active_assignments = []

            for assignment in volunteer.assignment_history or []:
                if assignment.status == "Active":
                    if assignment_type and assignment.assignment_type != assignment_type:
                        continue
                    if reference_doctype and assignment.reference_doctype != reference_doctype:
                        continue
                    active_assignments.append(assignment)

            return active_assignments

        except Exception as e:
            log_history_error(
                title="Assignment History Query Error",
                message=f"Error getting active assignments for volunteer {volunteer_id}: {str(e)}",
            )
            return []

    @staticmethod
    def remove_assignment_history(
        volunteer_id: str,
        assignment_type: str,
        reference_doctype: str,
        reference_name: str,
        role: str,
        start_date: str,
    ) -> bool:
        """
        Remove assignment history entry (for cases where assignment is cancelled before completion)

        Args:
            volunteer_id: Volunteer ID
            assignment_type: Type of assignment
            reference_doctype: Document type
            reference_name: Document name
            role: Role or position name
            start_date: Start date of original assignment

        Returns:
            bool: Success status
        """

        def _callback(volunteer):
            # Find the specific assignment to remove
            criteria = {
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "role": role,
                "start_date": start_date,
            }
            assignment_to_remove = find_entry_by_criteria(
                volunteer.assignment_history, criteria, status_values=["Active"]
            )

            if assignment_to_remove:
                volunteer.assignment_history.remove(assignment_to_remove)
                frappe.logger().info(
                    f"Removed assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
                )
                return None  # save needed

            frappe.logger().warning(
                f"Assignment to remove not found for volunteer {volunteer_id}: {assignment_type} - {role}"
            )
            return False  # not found

        return AssignmentHistoryManager._with_doc(
            volunteer_id,
            f"remove assignment history: {assignment_type} - {role}",
            _callback,
            error_title="Assignment History Remove Failed",
        )
