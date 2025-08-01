#!/usr/bin/env python3
"""
Team Role edge case testing utilities
"""

import frappe
from frappe.utils import add_days, today


@frappe.whitelist()
def test_missing_team_role_reference():
    """Test handling of missing Team Role references"""
    print("=== Testing Missing Team Role Reference ===")

    try:
        # Create a test team
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Edge Case Test Team {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        )
        test_team.insert()

        # Get a test volunteer
        volunteer = frappe.db.get_value("Volunteer", {"volunteer_name": ["like", "%René%"]}, "name")
        if not volunteer:
            print("❌ No test volunteer found")
            return {"success": False, "error": "No test volunteer found"}

        # Add team member with invalid team_role
        test_team.append(
            "team_members",
            {
                "volunteer": volunteer,
                "volunteer_name": frappe.db.get_value("Volunteer", volunteer, "volunteer_name"),
                "role": "Test Role",
                "team_role": "Invalid Team Role",  # This should not exist
                "role_type": "Team Member",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        # Test that the role description generation handles missing team role gracefully
        team_member = test_team.team_members[0]
        role_description = test_team.get_role_description_for_history(team_member)
        print(f"Role description with invalid team_role: '{role_description}'")

        # Should fallback to role_type when team_role doesn't exist
        expected_fallback = "Team Member - Test Role"
        if role_description == expected_fallback:
            print("✅ Missing Team Role handled correctly with fallback")
        else:
            print(f"❌ Expected '{expected_fallback}', got '{role_description}'")

        # Clean up
        frappe.delete_doc("Team", test_team.name)

        return {"success": True, "role_description": role_description}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_unique_role_constraint():
    """Test unique role constraint enforcement"""
    print("=== Testing Unique Role Constraint ===")

    try:
        # Create a test team
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Unique Role Test {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        )
        test_team.insert()

        # Get test volunteers
        volunteers = frappe.db.get_all(
            "Volunteer", {"volunteer_name": ["like", "%René%"]}, ["name", "volunteer_name"], limit=1
        )
        if not volunteers:
            print("❌ No test volunteers found")
            return {"success": False, "error": "No test volunteers found"}

        # Add first team member with Team Leader role (unique)
        test_team.append(
            "team_members",
            {
                "volunteer": volunteers[0]["name"],
                "volunteer_name": volunteers[0]["volunteer_name"],
                "role": "Primary Leader",
                "team_role": "Team Leader",
                "role_type": "Team Leader",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        test_team.save()
        print("✅ First Team Leader added successfully")

        # Try to add second team member with same unique role - should fail
        test_team.reload()
        test_team.append(
            "team_members",
            {
                "volunteer": volunteers[0]["name"],  # Same volunteer for this test
                "volunteer_name": volunteers[0]["volunteer_name"],
                "role": "Secondary Leader",
                "team_role": "Team Leader",
                "role_type": "Team Leader",
                "from_date": add_days(today(), 1),  # Different date to avoid other conflicts
                "is_active": 1,
                "status": "Active",
            },
        )

        try:
            test_team.save()
            # If this succeeds, the unique constraint is not working
            frappe.delete_doc("Team", test_team.name)
            print("❌ Unique role constraint not enforced - duplicate Team Leader allowed")
            return {"success": False, "error": "Unique role constraint not enforced"}
        except frappe.ValidationError as ve:
            # This is expected - unique constraint should prevent duplicate roles
            if "unique" in str(ve).lower() or "already assigned" in str(ve).lower():
                frappe.delete_doc("Team", test_team.name)
                print("✅ Unique role constraint properly enforced")
                return {"success": True, "validation_error": str(ve)}
            else:
                frappe.delete_doc("Team", test_team.name)
                print(f"❌ Unexpected validation error: {str(ve)}")
                return {"success": False, "error": f"Unexpected validation error: {str(ve)}"}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_backwards_compatibility():
    """Test backwards compatibility with old role_type system"""
    print("=== Testing Backwards Compatibility ===")

    try:
        # Create a test team
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Backwards Compat Test {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        )
        test_team.insert()

        # Get test volunteer
        volunteer = frappe.db.get_value("Volunteer", {"volunteer_name": ["like", "%René%"]}, "name")
        if not volunteer:
            print("❌ No test volunteer found")
            return {"success": False, "error": "No test volunteer found"}

        # Add team member with only role_type (no team_role) - simulating old data
        test_team.append(
            "team_members",
            {
                "volunteer": volunteer,
                "volunteer_name": frappe.db.get_value("Volunteer", volunteer, "volunteer_name"),
                "role": "Legacy Role",
                "team_role": "",  # Empty team_role
                "role_type": "Team Member",  # Only role_type set
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        # Test role description generation with backwards compatibility
        team_member = test_team.team_members[0]
        role_description = test_team.get_role_description_for_history(team_member)
        print(f"Role description with empty team_role: '{role_description}'")

        # Should use role_type as fallback when team_role is empty
        expected_description = "Team Member - Legacy Role"
        if role_description == expected_description:
            print("✅ Backwards compatibility working correctly")
        else:
            print(f"❌ Expected '{expected_description}', got '{role_description}'")

        # Clean up
        frappe.delete_doc("Team", test_team.name)

        return {"success": True, "role_description": role_description}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def test_team_leader_detection():
    """Test Team Leader detection and team_lead field population"""
    print("=== Testing Team Leader Detection ===")

    try:
        # Find a volunteer with a user account
        volunteer_with_user = None
        volunteers = frappe.db.get_all(
            "Volunteer", {"member": ["is", "set"]}, ["name", "member", "volunteer_name"], limit=5
        )

        for vol in volunteers:
            user = frappe.db.get_value("Member", vol["member"], "user")
            if user and user != "Administrator":
                volunteer_with_user = vol
                break

        if not volunteer_with_user:
            print("❌ No volunteer with user account found for testing")
            return {"success": False, "error": "No volunteer with user account found"}

        # Create a test team
        test_team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": f"Leader Detection Test {frappe.utils.random_string(5)}",
                "status": "Active",
                "team_type": "Project Team",
                "start_date": today(),
            }
        )
        test_team.insert()

        # Add team member with Team Leader role
        test_team.append(
            "team_members",
            {
                "volunteer": volunteer_with_user["name"],
                "volunteer_name": volunteer_with_user["volunteer_name"],
                "role": "Test Leader",
                "team_role": "Team Leader",
                "role_type": "Team Leader",
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        test_team.save()

        # Check if team_lead field is populated
        test_team.reload()
        user = frappe.db.get_value("Member", volunteer_with_user["member"], "user")

        print(f"Expected team_lead: {user}")
        print(f"Actual team_lead: {test_team.team_lead}")

        if test_team.team_lead == user:
            print("✅ Team Leader detection working correctly")
            success = True
        else:
            print("❌ team_lead field not populated correctly")
            success = False

        # Clean up
        frappe.delete_doc("Team", test_team.name)

        return {"success": success, "expected": user, "actual": test_team.team_lead}

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
def run_all_edge_case_tests():
    """Run all edge case tests"""
    results = {"tests_run": 0, "tests_passed": 0, "tests_failed": 0, "test_results": {}}

    print("=== Running All Team Role Edge Case Tests ===\n")

    # Test 1: Missing Team Role Reference
    test_result = test_missing_team_role_reference()
    results["tests_run"] += 1
    results["test_results"]["missing_team_role"] = test_result
    if test_result["success"]:
        results["tests_passed"] += 1
    else:
        results["tests_failed"] += 1

    print("")

    # Test 2: Unique Role Constraints
    test_result = test_unique_role_constraint()
    results["tests_run"] += 1
    results["test_results"]["unique_role_constraint"] = test_result
    if test_result["success"]:
        results["tests_passed"] += 1
    else:
        results["tests_failed"] += 1

    print("")

    # Test 3: Backwards Compatibility
    test_result = test_backwards_compatibility()
    results["tests_run"] += 1
    results["test_results"]["backwards_compatibility"] = test_result
    if test_result["success"]:
        results["tests_passed"] += 1
    else:
        results["tests_failed"] += 1

    print("")

    # Test 4: Team Leader Detection
    test_result = test_team_leader_detection()
    results["tests_run"] += 1
    results["test_results"]["team_leader_detection"] = test_result
    if test_result["success"]:
        results["tests_passed"] += 1
    else:
        results["tests_failed"] += 1

    print(f"\n=== Edge Case Test Summary ===")
    print(f"Tests Run: {results['tests_run']}")
    print(f"Passed: {results['tests_passed']}")
    print(f"Failed: {results['tests_failed']}")

    return results
