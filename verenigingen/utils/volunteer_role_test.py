#!/usr/bin/env python3
"""
Test utilities for volunteer role assignment
"""
import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, development_only_api
from verenigingen.utils.validation_utilities import DocumentExistenceValidator, QueryBuilder


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_volunteer_role_assignment():
    """Test that Volunteer role is automatically assigned when volunteer record is created"""

    print("=== TESTING VOLUNTEER ROLE ASSIGNMENT ===\n")

    try:
        # Create a test user first
        test_email = "test.volunteer.role@example.com"

        # Delete if exists (cleanup from previous tests)
        existing_volunteers = frappe.get_all("Volunteer", filters={"email": test_email}, pluck="name")
        for vol in existing_volunteers:
            frappe.delete_doc("Volunteer", vol, force=True)

        existing_members = frappe.get_all("Member", filters={"email": test_email}, pluck="name")
        for mem in existing_members:
            frappe.delete_doc("Member", mem, force=True)

        if DocumentExistenceValidator.check_document_exists("User", test_email):
            frappe.delete_doc("User", test_email, force=True)

        frappe.db.commit()

        # Create user
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": test_email,
                "first_name": "Test",
                "last_name": "Verenigingen Volunteer",
                "enabled": 1,
                "user_type": "System User",
            }
        )
        user.insert()

        print(f"✅ Created test user: {test_email}")

        # Check initial roles
        initial_roles = [r.role for r in user.roles]
        print(f"Initial roles: {initial_roles}")
        print(f"Has Volunteer role initially: {'Verenigingen Volunteer' in initial_roles}")

        # Create member
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "Test",
                "last_name": "Verenigingen Volunteer",
                "email": test_email,
                "birth_date": "1990-01-01",
                "user": test_email,
                "application_status": "Approved",
            }
        )
        member.insert()

        print(f"✅ Created member: {member.name}")

        # Create volunteer record - this should trigger role assignment
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": "Test Volunteer",
                "member": member.name,
                "email": test_email,
                "status": "Active",
            }
        )
        volunteer.insert()

        print(f"✅ Created volunteer: {volunteer.name}")

        # Check if role was assigned
        user.reload()
        final_roles = [r.role for r in user.roles]
        has_volunteer_role = "Verenigingen Volunteer" in final_roles

        print(f"Final roles: {final_roles}")
        print(f"Has Volunteer role after creation: {has_volunteer_role}")

        result = {
            "success": has_volunteer_role,
            "initial_roles": initial_roles,
            "final_roles": final_roles,
            "volunteer_created": volunteer.name,
            "member_created": member.name,
        }

        if has_volunteer_role:
            print("\n🎉 SUCCESS: Volunteer role was automatically assigned!")
        else:
            print("\n❌ FAILURE: Volunteer role was NOT assigned automatically")

        # Cleanup
        frappe.delete_doc("Volunteer", volunteer.name, force=True)
        frappe.delete_doc("Member", member.name, force=True)
        frappe.delete_doc("User", test_email, force=True)
        frappe.db.commit()

        return result

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(f"Volunteer role test error: {str(e)}", "Volunteer Role Test")
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_project_team_access():
    """Test project access through team membership"""

    print("=== TESTING PROJECT TEAM ACCESS ===\n")

    try:
        # Get some existing teams and volunteers to test with
        teams = QueryBuilder.get_all_active_records("Team", fields=["name", "team_name"], limit=2)

        print(f"Found {len(teams)} active teams for testing")

        if not teams:
            print("❌ No active teams found - cannot test project access")
            return {"success": False, "error": "No teams available"}

        # Get some volunteers
        volunteers = frappe.get_all(
            "Verenigingen Volunteer",
            filters={"status": "Active"},
            fields=["name", "email", "member"],
            limit=3,
        )

        print(f"Found {len(volunteers)} active volunteers")

        if not volunteers:
            print("❌ No active volunteers found - cannot test project access")
            return {"success": False, "error": "No volunteers available"}

        # Check existing projects
        projects = frappe.get_all("Project", fields=["name", "project_name"], limit=5)

        print(f"Found {len(projects)} projects in system")

        # Test the permission functions
        from verenigingen.utils.project_permissions import get_user_project_teams, user_has_any_team_projects

        test_results = []

        for volunteer in volunteers[:2]:  # Test first 2 volunteers
            if volunteer.email:
                print(f"\n--- Testing volunteer: {volunteer.email} ---")

                # Test team projects access
                team_access = get_user_project_teams(volunteer.email)
                print(f"Team access result: {team_access}")

                # Test any team projects
                has_any_access = user_has_any_team_projects(volunteer.email)
                print(f"Has any team project access: {has_any_access}")

                test_results.append(
                    {
                        "volunteer": volunteer.email,
                        "teams": len(team_access.get("teams", [])),
                        "projects": len(team_access.get("projects", [])),
                        "has_access": has_any_access,
                    }
                )

        return {
            "success": True,
            "teams_found": len(teams),
            "volunteers_tested": len(test_results),
            "projects_in_system": len(projects),
            "test_results": test_results,
        }

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        frappe.log_error(f"Project team access test error: {str(e)}", "Project Access Test")
        return {"success": False, "error": str(e)}
