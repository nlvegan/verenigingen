#!/usr/bin/env python3
"""
Test Team Role assignment history integration
"""

import frappe


@frappe.whitelist()
def test_team_role_assignment_history():
    """Test that assignment history works with Team Role system"""

    results = ["=== Testing Team Role Assignment History Integration ==="]

    # 1. Check existing assignment history format
    results.append("\n1. Checking existing assignment history format...")

    # Get volunteers and check for assignment history
    volunteers = frappe.db.get_all("Volunteer", fields=["name", "volunteer_name"], limit=5)

    for volunteer in volunteers:
        volunteer_doc = frappe.get_doc("Volunteer", volunteer.name)
        team_assignments = [a for a in volunteer_doc.assignment_history or [] if a.assignment_type == "Team"]

        if team_assignments:
            results.append(f"\n  Volunteer: {volunteer.volunteer_name}")
            for assignment in team_assignments[:2]:  # Show first 2
                results.append(f"    - Role: {assignment.role}")
                results.append(f"    - Status: {assignment.status}")
                results.append(f"    - Team: {assignment.reference_name}")
                results.append(f"    - Dates: {assignment.start_date} to {assignment.end_date or 'Active'}")
            results.append(f"✓ {volunteer.volunteer_name}: {len(team_assignments)} team assignments")
            break

    # 2. Check Team Role integration
    results.append("\n2. Checking Team Role integration...")

    try:
        team_roles = frappe.db.get_all(
            "Team Role", fields=["name", "role_name", "is_team_leader", "is_unique"], order_by="role_name"
        )

        results.append(f"  Found {len(team_roles)} Team Roles:")
        for role in team_roles:
            leader_flag = "Leader" if role.is_team_leader else ""
            unique_flag = "Unique" if role.is_unique else ""
            flags = f"({leader_flag} {unique_flag})".strip("() ")
            results.append(f"    - {role.role_name} {flags}")

    except Exception as e:
        results.append(f"  ✗ Error checking Team Roles: {e}")

    # 3. Test role description generation with actual teams
    results.append("\n3. Testing role description generation...")

    try:
        # Get a team with members
        teams_with_members = frappe.db.sql(
            """
            SELECT DISTINCT t.name, t.team_name
            FROM `tabTeam` t
            INNER JOIN `tabTeam Member` tm ON tm.parent = t.name
            WHERE tm.is_active = 1
            LIMIT 2
        """,
            as_dict=True,
        )

        for team_info in teams_with_members:
            team_doc = frappe.get_doc("Team", team_info.name)
            results.append(f"\n  Team: {team_info.team_name}")

            for member in team_doc.team_members[:3]:  # Show first 3 members
                if member.is_active:
                    description = team_doc.get_role_description_for_history(member)
                    results.append(f"    - {member.volunteer_name}: '{description}'")
                    results.append(
                        f"      Team Role: {member.team_role}, Role Type: {member.role_type}, Role: {member.role}"
                    )

    except Exception as e:
        results.append(f"  ✗ Error testing role descriptions: {e}")

    # 4. Test current team members have team_role values
    results.append("\n4. Checking Team Member data integrity...")

    try:
        # Check how many team members have team_role vs role_type
        total_members = frappe.db.count("Team Member", {"is_active": 1})
        members_with_team_role = frappe.db.count("Team Member", {"is_active": 1, "team_role": ["is", "set"]})
        members_with_role_type = frappe.db.count("Team Member", {"is_active": 1, "role_type": ["is", "set"]})

        results.append(f"  Total active team members: {total_members}")
        results.append(f"  Members with team_role: {members_with_team_role}")
        results.append(f"  Members with role_type: {members_with_role_type}")

        if members_with_team_role == total_members:
            results.append("  ✓ All active members have team_role values")
        else:
            results.append(f"  ⚠ {total_members - members_with_team_role} members missing team_role")

    except Exception as e:
        results.append(f"  ✗ Error checking data integrity: {e}")

    results.append("\n=== Team Role Assignment History Test Complete ===")

    return "\n".join(results)
