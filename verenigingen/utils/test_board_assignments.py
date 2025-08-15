"""
Test board assignments specifically for refactoring verification
"""

import frappe


@frappe.whitelist()
def test_board_assignment_refactoring():
    """Test board assignment functionality specifically"""

    # Find a volunteer with board assignments
    board_volunteers = frappe.db.sql(
        """
        SELECT v.name
        FROM `tabVolunteer` v
        INNER JOIN `tabChapter Board Member` cbm ON cbm.volunteer = v.name
        WHERE cbm.is_active = 1
        LIMIT 1
    """,
        as_dict=True,
    )

    if not board_volunteers:
        return {"success": False, "message": "No volunteers with board assignments found"}

    volunteer = frappe.get_doc("Volunteer", board_volunteers[0].name)

    try:
        # Test the refactored method
        board_assignments = volunteer.get_board_assignments()

        result = {
            "volunteer_name": volunteer.volunteer_name,
            "volunteer_id": volunteer.name,
            "board_assignments_count": len(board_assignments),
            "board_assignments": board_assignments,
            "success": True,
        }

        # Verify structure
        for assignment in board_assignments:
            if not isinstance(assignment.get("is_active"), bool):
                result["warning"] = f"is_active field is {type(assignment.get('is_active'))} instead of bool"

        return result

    except Exception as e:
        return {"success": False, "error": str(e), "volunteer": volunteer.name}
