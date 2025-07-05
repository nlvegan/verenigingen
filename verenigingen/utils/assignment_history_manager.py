# Assignment History Manager - Centralized volunteer assignment tracking

import frappe


class AssignmentHistoryManager:
    """
    Centralized manager for volunteer assignment history tracking.

    Handles assignment history for both board positions and team assignments
    in a consistent way.
    """

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
            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # Check if this exact assignment already exists as active
            # Allow multiple stints by checking all fields including start_date
            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == reference_doctype
                    and assignment.reference_name == reference_name
                    and assignment.role == role
                    and assignment.status == "Active"
                    and str(assignment.start_date) == str(start_date)
                ):
                    print(f"Assignment already exists in history for volunteer {volunteer_id}")
                    return True  # This exact assignment already exists

            # Add new active assignment (allow multiple separate stints)
            volunteer.append(
                "assignment_history",
                {
                    "assignment_type": assignment_type,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "role": role,
                    "start_date": start_date,
                    "status": "Active",
                },
            )

            volunteer.save(ignore_permissions=True)

            print(f"Added assignment history for volunteer {volunteer_id}: {assignment_type} - {role}")
            return True

        except Exception as e:
            print(f"Error adding assignment history for volunteer {volunteer_id}: {str(e)}")
            import traceback

            traceback.print_exc()
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
            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # Look for the specific assignment that matches all criteria
            # This ensures we update the correct stint for volunteers with multiple terms
            target_assignment = None
            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == reference_doctype
                    and assignment.reference_name == reference_name
                    and assignment.role == role
                    and str(assignment.start_date) == str(start_date)
                    and assignment.status == "Active"
                ):
                    target_assignment = assignment
                    break

            if target_assignment:
                # Update the specific assignment to completed
                target_assignment.end_date = end_date
                target_assignment.status = "Completed"

                frappe.log_error(
                    f"Updated specific assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                    "Assignment History Manager",
                )
            else:
                # If we can't find the exact assignment, look for any active one
                # This is a fallback for data inconsistencies
                fallback_assignment = None
                for assignment in volunteer.assignment_history or []:
                    if (
                        assignment.reference_doctype == reference_doctype
                        and assignment.reference_name == reference_name
                        and assignment.role == role
                        and assignment.status == "Active"
                    ):
                        fallback_assignment = assignment
                        break

                if fallback_assignment:
                    fallback_assignment.end_date = end_date
                    fallback_assignment.status = "Completed"

                    frappe.log_error(
                        f"Updated fallback assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                        "Assignment History Manager",
                    )
                else:
                    # Create a new completed assignment if nothing exists
                    volunteer.append(
                        "assignment_history",
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

                    frappe.log_error(
                        f"Created new completed assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                        "Assignment History Manager",
                    )

            volunteer.save(ignore_permissions=True)
            return True

        except Exception as e:
            frappe.log_error(
                f"Error completing assignment history for volunteer {volunteer_id}: {str(e)}",
                "Assignment History Manager",
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
            frappe.log_error(
                f"Error getting active assignments for volunteer {volunteer_id}: {str(e)}",
                "Assignment History Manager",
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
            volunteer = frappe.get_doc("Volunteer", volunteer_id)

            # Find and remove the specific assignment
            assignment_to_remove = None
            for assignment in volunteer.assignment_history or []:
                if (
                    assignment.reference_doctype == reference_doctype
                    and assignment.reference_name == reference_name
                    and assignment.role == role
                    and str(assignment.start_date) == str(start_date)
                    and assignment.status == "Active"
                ):
                    assignment_to_remove = assignment
                    break

            if assignment_to_remove:
                volunteer.assignment_history.remove(assignment_to_remove)
                volunteer.save(ignore_permissions=True)

                frappe.log_error(
                    f"Removed assignment history for volunteer {volunteer_id}: {assignment_type} - {role}",
                    "Assignment History Manager",
                )
                return True
            else:
                frappe.log_error(
                    f"Assignment to remove not found for volunteer {volunteer_id}: {assignment_type} - {role}",
                    "Assignment History Manager",
                )
                return False

        except Exception as e:
            frappe.log_error(
                f"Error removing assignment history for volunteer {volunteer_id}: {str(e)}",
                "Assignment History Manager",
            )
            return False
