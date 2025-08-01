#!/usr/bin/env python3
"""
Test Team Role integration functionality
"""

import frappe


@frappe.whitelist()
def test_team_role_integration():
    """Test the Team Role DocType and integration with Team Member"""

    results = ["=== Testing Team Role Integration ==="]

    # 1. Check if Team Role fixtures were installed
    team_roles = frappe.db.get_all(
        "Team Role", fields=["name", "role_name", "is_team_leader", "is_unique", "is_active"], order_by="name"
    )

    results.append(f"\n1. Team Role fixtures installed: {len(team_roles)} roles found")
    for role in team_roles:
        leader_flag = "✓" if role.is_team_leader else "✗"
        unique_flag = "✓" if role.is_unique else "✗"
        active_flag = "✓" if role.is_active else "✗"
        results.append(f"   - {role.name}: Leader={leader_flag}, Unique={unique_flag}, Active={active_flag}")

    # 2. Test Team Role validation logic
    results.append("\n2. Testing Team Role validation logic...")
    try:
        team_leader_role = frappe.get_doc("Team Role", "Team Leader")
        results.append(f"   ✓ Team Leader role loaded: {team_leader_role.role_name}")
        results.append(f"     - Is Team Leader: {team_leader_role.is_team_leader}")
        results.append(f"     - Is Unique: {team_leader_role.is_unique}")
        results.append(f"     - Permissions Level: {team_leader_role.permissions_level}")
    except Exception as e:
        results.append(f"   ✗ Error loading Team Leader role: {e}")

    # 3. Check Team Member DocType structure
    results.append("\n3. Checking Team Member DocType structure...")
    try:
        team_member_meta = frappe.get_meta("Team Member")
        fields = [f.fieldname for f in team_member_meta.fields]

        if "team_role" in fields:
            results.append("   ✓ team_role field found in Team Member")
            team_role_field = team_member_meta.get_field("team_role")
            results.append(f"     - Field type: {team_role_field.fieldtype}")
            results.append(f"     - Options: {team_role_field.options}")
            results.append(f"     - Required: {team_role_field.reqd}")
        else:
            results.append("   ✗ team_role field NOT found in Team Member")

        if "role_type" in fields:
            results.append("   ✓ role_type field found in Team Member")
            role_type_field = team_member_meta.get_field("role_type")
            results.append(f"     - Field type: {role_type_field.fieldtype}")
            results.append(f"     - Fetch from: {getattr(role_type_field, 'fetch_from', 'N/A')}")
            results.append(f"     - Read only: {role_type_field.read_only}")
        else:
            results.append("   ✗ role_type field NOT found in Team Member")

    except Exception as e:
        results.append(f"   ✗ Error checking Team Member DocType: {e}")

    # 4. Test creating a Team Role programmatically
    results.append("\n4. Testing Team Role creation...")
    try:
        test_role_name = "Test Coordinator"

        # Check if role already exists and delete it
        if frappe.db.exists("Team Role", test_role_name):
            frappe.delete_doc("Team Role", test_role_name)
            results.append(f"   - Deleted existing test role: {test_role_name}")

        # Create new test role
        test_role = frappe.new_doc("Team Role")
        test_role.role_name = test_role_name
        test_role.description = "Test coordinator role for integration testing"
        test_role.permissions_level = "Coordinator"
        test_role.is_team_leader = 0
        test_role.is_unique = 1  # Make it unique to test validation
        test_role.is_active = 1

        test_role.save()
        results.append(f"   ✓ Successfully created test role: {test_role_name}")

        # Clean up
        frappe.delete_doc("Team Role", test_role_name)
        results.append(f"   ✓ Successfully deleted test role: {test_role_name}")

    except Exception as e:
        results.append(f"   ✗ Error creating test role: {e}")

    # 5. Test if existing teams can use the new roles
    results.append("\n5. Checking existing teams and members...")
    teams = frappe.db.get_all("Team", fields=["name", "team_name"], limit=3)
    results.append(f"   Found {len(teams)} teams in system")

    for team in teams:
        members = frappe.db.get_all(
            "Team Member",
            filters={"parent": team.name},
            fields=["volunteer_name", "role_type", "team_role"],
            limit=3,
        )
        results.append(f"   - {team.team_name}: {len(members)} members")
        for member in members:
            role_status = f"Old: {member.role_type}" if member.role_type else "No role_type"
            team_role_status = f"New: {member.team_role}" if member.team_role else "No team_role"
            results.append(f"     * {member.volunteer_name}: {role_status}, {team_role_status}")

    results.append("\n=== Team Role Integration Test Complete ===")

    return "\n".join(results)
