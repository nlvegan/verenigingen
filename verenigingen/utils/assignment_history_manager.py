# Assignment History Manager - Centralized volunteer assignment tracking

import frappe

from verenigingen.utils.history_manager_utils import (
    check_duplicate_entry,
    ensure_doc_exists,
    find_entry_by_criteria,
    log_history_error,
    recursion_guard,
    safe_child_table_update,
)


class AssignmentHistoryManager:
    """
    Centralized manager for volunteer assignment history tracking.

    Handles assignment history for both board positions and team assignments
    in a consistent way.
    """

    CHILD_TABLE = "assignment_history"

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
        try:
            if not ensure_doc_exists("Volunteer", volunteer_id, "add assignment history"):
                return False

            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # Recursion guard - prevent infinite loops
            with recursion_guard(volunteer, "_updating_assignment_history") as should_proceed:
                if not should_proceed:
                    return True

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
                        return True
                    elif existing.status == "Completed":
                        # Reactivate the existing completed assignment
                        frappe.logger().warning(
                            f"Assignment already exists as Completed for volunteer {volunteer_id}: "
                            f"{reference_doctype} {reference_name} - {role}. Reactivating instead of duplicating."
                        )
                        existing.status = "Active"
                        existing.end_date = None

                        result = safe_child_table_update(
                            doc=volunteer,
                            child_table_name=AssignmentHistoryManager.CHILD_TABLE,
                            justification=f"Reactivate assignment for volunteer {volunteer_id}: {assignment_type} - {role}",
                            doctype_permission="Volunteer:write",
                            auto_cleanup=True,
                        )

                        if result.success:
                            frappe.logger().info(
                                f"Reactivated existing assignment for volunteer {volunteer_id}"
                            )
                            return True
                        else:
                            log_history_error(
                                title="Assignment Reactivation Failed",
                                message=f"Failed to reactivate assignment: {'; '.join(result.errors)}",
                            )
                            return False

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

                result = safe_child_table_update(
                    doc=volunteer,
                    child_table_name=AssignmentHistoryManager.CHILD_TABLE,
                    justification=f"Add assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                    doctype_permission="Volunteer:write",
                    auto_cleanup=True,
                )

                if not result.success:
                    log_history_error(
                        title="Assignment History Add Failed",
                        message=f"Failed to add assignment history for volunteer {volunteer_id}: {'; '.join(result.errors)}",
                    )
                    return False

                frappe.logger().info(
                    f"Added assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
                )
                return True

        except Exception as e:
            log_history_error(
                title="Assignment History Error",
                message=f"Error adding assignment history for volunteer {volunteer_id}: {str(e)}",
                include_traceback=True,
            )
            return False

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
        try:
            if not ensure_doc_exists("Volunteer", volunteer_id, "complete assignment history"):
                return False

            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            with recursion_guard(volunteer, "_updating_assignment_history") as should_proceed:
                if not should_proceed:
                    return True

                # Try to find by reference + start_date first (most specific)
                criteria = {
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "start_date": start_date,
                }
                target = find_entry_by_criteria(
                    volunteer.assignment_history, criteria, status_values=["Active"]
                )

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
                else:
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
                        if str(existing_completed.end_date) != str(end_date):
                            existing_completed.end_date = end_date
                            frappe.logger().info(
                                f"Updated end_date for existing completed assignment for volunteer {volunteer_id}"
                            )
                        else:
                            frappe.logger().info(
                                f"Assignment already completed for volunteer {volunteer_id}: {assignment_type} - {role}. No action needed."
                            )
                            return True
                    else:
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
                            f"Reconstructed missing assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
                        )

                result = safe_child_table_update(
                    doc=volunteer,
                    child_table_name=AssignmentHistoryManager.CHILD_TABLE,
                    justification=f"Complete assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                    doctype_permission="Volunteer:write",
                    auto_cleanup=True,
                )

                if not result.success:
                    log_history_error(
                        title="Assignment History Complete Failed",
                        message=f"Failed to complete assignment history for volunteer {volunteer_id}: {'; '.join(result.errors)}",
                    )
                    return False

                return True

        except Exception as e:
            log_history_error(
                title="Assignment History Error",
                message=f"Error completing assignment history for volunteer {volunteer_id}: {str(e)}",
                include_traceback=True,
            )
            return False

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
        try:
            if not ensure_doc_exists("Volunteer", volunteer_id, "remove assignment history"):
                return False

            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            with recursion_guard(volunteer, "_updating_assignment_history") as should_proceed:
                if not should_proceed:
                    return True

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

                    result = safe_child_table_update(
                        doc=volunteer,
                        child_table_name=AssignmentHistoryManager.CHILD_TABLE,
                        justification=f"Remove assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                        doctype_permission="Volunteer:write",
                        auto_cleanup=True,
                    )

                    if not result.success:
                        log_history_error(
                            title="Assignment History Remove Failed",
                            message=f"Failed to remove assignment history for volunteer {volunteer_id}: {'; '.join(result.errors)}",
                        )
                        return False

                    frappe.logger().info(
                        f"Removed assignment history for volunteer {volunteer_id}: {assignment_type} - {role}"
                    )
                    return True
                else:
                    frappe.logger().info(
                        f"Assignment to remove not found for volunteer {volunteer_id}: {assignment_type} - {role}"
                    )
                    return False

        except Exception as e:
            log_history_error(
                title="Assignment History Error",
                message=f"Error removing assignment history for volunteer {volunteer_id}: {str(e)}",
                include_traceback=True,
            )
            return False
