#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def fix_team_assignment_history(team_name=None, volunteer_name=None):
    """Manually fix team assignment history for existing assignments"""

    print(f"Fixing team assignment history for Team: {team_name}, Volunteer: {volunteer_name}")

    try:
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        if team_name and volunteer_name:
            # Fix specific team-volunteer assignment
            team = frappe.get_doc("Team", team_name)

            for member in team.team_members:
                if member.volunteer == volunteer_name and member.is_active:
                    print(f"Found active assignment: {member.volunteer} -> {member.role}")

                    # Check if assignment history already exists
                    volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
                    has_assignment = False

                    for assignment in volunteer_doc.assignment_history or []:
                        if (
                            assignment.reference_doctype == "Team"
                            and assignment.reference_name == team_name
                            and assignment.role == member.role
                            and assignment.status == "Active"
                        ):
                            has_assignment = True
                            print(f"Assignment already exists in history")
                            break

                    if not has_assignment:
                        success = AssignmentHistoryManager.add_assignment_history(
                            volunteer_id=volunteer_name,
                            assignment_type="Team",
                            reference_doctype="Team",
                            reference_name=team_name,
                            role=member.role,
                            start_date=member.from_date,
                        )

                        if success:
                            print(f"✅ Successfully added assignment history for {volunteer_name}")
                        else:
                            print(f"❌ Failed to add assignment history for {volunteer_name}")

                    return {"success": True, "message": "Assignment history updated"}

        else:
            # Fix all team assignments
            teams = frappe.get_all("Team", fields=["name"])
            fixed_count = 0

            for team_doc in teams:
                team = frappe.get_doc("Team", team_doc.name)

                for member in team.team_members:
                    if member.is_active and member.volunteer:
                        volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                        has_assignment = False

                        for assignment in volunteer_doc.assignment_history or []:
                            if (
                                assignment.reference_doctype == "Team"
                                and assignment.reference_name == team.name
                                and assignment.role == member.role
                                and assignment.status == "Active"
                            ):
                                has_assignment = True
                                break

                        if not has_assignment:
                            success = AssignmentHistoryManager.add_assignment_history(
                                volunteer_id=member.volunteer,
                                assignment_type="Team",
                                reference_doctype="Team",
                                reference_name=team.name,
                                role=member.role,
                                start_date=member.from_date,
                            )

                            if success:
                                fixed_count += 1
                                print(f"✅ Fixed assignment for {member.volunteer} in {team.name}")

            return {"success": True, "message": f"Fixed {fixed_count} assignments"}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


# For command line execution
if __name__ == "__main__":
    fix_team_assignment_history("Team Socmed", "Foppe de Haan")
