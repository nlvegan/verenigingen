#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def test_team_member_removal():
    """Test that removing a team member properly updates assignment history"""

    print("=== Testing Team Member Removal ===")

    try:
        # Create a test team with a member
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Removal Test Team {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today()}
        )
        test_team.insert()

        # Get Foppe de Haan as our test volunteer
        volunteer_name = "Foppe de  Haan"  # Note the double space

        # Add him to the team
        test_team.append(
            "team_members",
            {
                "volunteer": volunteer_name,
                "volunteer_name": volunteer_name,
                "role": "Test Removal Role",
                "role_type": "Team Member",
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active"},
        )

        print(f"1. Adding {volunteer_name} to team {test_team.name}")
        test_team.save()

        # Check if assignment history was created
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_name)
        active_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name and assignment.status == "Active":
                active_assignment = assignment
                break

        if active_assignment:
            print(f"✅ Active assignment created: {active_assignment.role}")
        else:
            print("❌ No active assignment found")
            return {"success": False, "error": "No active assignment created"}

        # Now test removal by deactivating the member
        print(f"2. Deactivating {volunteer_name} from team")
        team_member = test_team.team_members[0]
        team_member.is_active = 0
        team_member.to_date = frappe.utils.today()
        team_member.status = "Completed"

        test_team.save()

        # Check if assignment history was completed
        volunteer_doc.reload()
        completed_assignment = None
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name and assignment.status == "Completed":
                completed_assignment = assignment
                break

        if completed_assignment:
            print(f"✅ Assignment completed with end date: {completed_assignment.end_date}")

            # Now test complete removal
            print(f"3. Completely removing {volunteer_name} from team")
            test_team.team_members = []  # Remove all members
            test_team.save()

            # Check that assignment history is still completed (not removed)
            volunteer_doc.reload()
            still_completed = None
            for assignment in volunteer_doc.assignment_history or []:
                if assignment.reference_name == test_team.name and assignment.status == "Completed":
                    still_completed = assignment
                    break

            if still_completed:
                print(f"✅ Assignment history preserved after complete removal")
            else:
                print("❌ Assignment history lost after complete removal")
        else:
            print("❌ Assignment was not completed")
            return {"success": False, "error": "Assignment not completed"}

        # Clean up - remove assignment history and delete team
        print("4. Cleaning up test data")
        volunteer_doc.reload()
        assignments_to_remove = []
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == test_team.name:
                assignments_to_remove.append(assignment)

        for assignment in assignments_to_remove:
            volunteer_doc.assignment_history.remove(assignment)

        if assignments_to_remove:
            volunteer_doc.save()

        frappe.delete_doc("Team", test_team.name)

        print("✅ Test completed successfully!")
        return {"success": True, "message": "Team member removal test passed"}

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    test_team_member_removal()
