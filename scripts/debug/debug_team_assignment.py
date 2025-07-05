#!/usr/bin/env python3

import frappe


def debug_team_assignment():
    """Debug team assignment for Foppe de Haan"""

    print("=== Debugging Team Assignment History ===")

    # Check Foppe de Haan's volunteer record
    try:
        volunteer = frappe.get_doc("Volunteer", "Foppe de Haan")
        print(f"Volunteer: {volunteer.volunteer_name}")
        print("Assignment history:")
        for i, assignment in enumerate(volunteer.assignment_history or []):
            print(
                f"  {i+1}. {assignment.assignment_type}: {assignment.reference_doctype} {assignment.reference_name} - {assignment.role} ({assignment.status})"
            )
            if hasattr(assignment, "start_date"):
                print(f"      Start: {assignment.start_date}, End: {assignment.end_date}")
        if not volunteer.assignment_history:
            print("  No assignment history found")
    except Exception as e:
        print(f"Error getting volunteer: {e}")

    # Check Team Socmed
    try:
        team = frappe.get_doc("Team", "Team Socmed")
        print(f"\nTeam: {team.team_name}")
        print("Team members:")
        for member in team.team_members:
            print(
                f"  - {member.volunteer} ({member.volunteer_name}): {member.role} - Active: {member.is_active}"
            )
            print(f"    From: {member.from_date}, To: {member.to_date}")
        if not team.team_members:
            print("  No team members found")
    except Exception as e:
        print(f"Error getting team: {e}")

    # Test if the assignment history manager is working
    print("\n=== Testing Assignment History Manager ===")
    try:
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Test adding assignment manually
        success = AssignmentHistoryManager.add_assignment_history(
            volunteer_id="Foppe de Haan",
            assignment_type="Team",
            reference_doctype="Team",
            reference_name="Team Socmed",
            role="Test Role",
            start_date="2025-06-12",
        )
        print(f"Manual assignment add result: {success}")

        if success:
            # Check if it was added
            volunteer.reload()
            print("Updated assignment history:")
            for assignment in volunteer.assignment_history or []:
                if assignment.reference_name == "Team Socmed":
                    print(f"  Found: {assignment.assignment_type} - {assignment.role} ({assignment.status})")

    except Exception as e:
        print(f"Error testing assignment manager: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    debug_team_assignment()
    frappe.destroy()
