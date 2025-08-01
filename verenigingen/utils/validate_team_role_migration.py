#!/usr/bin/env python3
"""
Validate Team Role migration data integrity
"""

import frappe


@frappe.whitelist()
def validate_migration_data_integrity():
    """Validate that Team Role migration was completed successfully"""

    print("=== Validating Team Role Migration Data Integrity ===\n")

    results = {
        "total_team_members": 0,
        "members_with_team_role": 0,
        "members_without_team_role": 0,
        "team_roles_available": 0,
        "teams_analyzed": 0,
        "validation_errors": [],
        "success": True,
    }

    # Check available Team Roles
    team_roles = frappe.get_all(
        "Team Role", fields=["name", "role_name", "is_team_leader", "is_unique", "is_active"]
    )
    results["team_roles_available"] = len(team_roles)

    print(f"Available Team Roles: {len(team_roles)}")
    for role in team_roles:
        flags = []
        if role.is_team_leader:
            flags.append("Leader")
        if role.is_unique:
            flags.append("Unique")
        if role.is_active:
            flags.append("Active")
        print(f"  - {role.role_name}: {', '.join(flags) if flags else 'Basic'}")

    # Check all Team Member records
    team_members = frappe.get_all(
        "Team Member",
        fields=["name", "parent", "volunteer_name", "team_role", "role_type", "role", "is_active"],
        filters={"is_active": 1},
    )

    results["total_team_members"] = len(team_members)
    print(f"\nTotal active Team Members: {len(team_members)}")

    # Analyze each team member
    teams_processed = set()
    for member in team_members:
        teams_processed.add(member.parent)

        if member.team_role:
            results["members_with_team_role"] += 1

            # Validate that team_role exists
            try:
                team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                if not team_role_doc:
                    results["validation_errors"].append(
                        f"Team Member {member.name}: team_role '{member.team_role}' not found"
                    )
                    results["success"] = False
            except frappe.DoesNotExistError:
                results["validation_errors"].append(
                    f"Team Member {member.name}: team_role '{member.team_role}' does not exist"
                )
                results["success"] = False
        else:
            results["members_without_team_role"] += 1
            results["validation_errors"].append(
                f"Team Member {member.name} ({member.volunteer_name}): missing team_role"
            )

        # Check role description consistency
        if member.role_type and member.team_role:
            try:
                team_role_doc = frappe.get_cached_doc("Team Role", member.team_role)
                if team_role_doc and team_role_doc.role_name != member.role_type:
                    results["validation_errors"].append(
                        f"Team Member {member.name}: role_type '{member.role_type}' doesn't match team_role '{team_role_doc.role_name}'"
                    )
            except frappe.DoesNotExistError:
                pass  # Already logged above

    results["teams_analyzed"] = len(teams_processed)

    print("\nMigration Analysis:")
    print(f"  - Members with team_role: {results['members_with_team_role']}")
    print(f"  - Members without team_role: {results['members_without_team_role']}")
    print(f"  - Teams analyzed: {results['teams_analyzed']}")

    if results["validation_errors"]:
        print(f"\nValidation Errors ({len(results['validation_errors'])}):")
        for error in results["validation_errors"][:10]:  # Show first 10 errors
            print(f"  - {error}")
        if len(results["validation_errors"]) > 10:
            print(f"  ... and {len(results['validation_errors']) - 10} more errors")
        results["success"] = False
    else:
        print("\n✅ All validation checks passed!")

    # Test role description generation for existing teams
    print("\nTesting role description generation...")
    test_role_descriptions(results)

    return results


def test_role_descriptions(results):
    """Test role description generation for existing teams"""

    # Get a few teams to test role description generation
    teams = frappe.get_all("Team", filters={"status": "Active"}, limit=3)

    for team_data in teams:
        try:
            team = frappe.get_doc("Team", team_data.name)
            print(f"\n  Team: {team.team_name}")

            for member in team.team_members:
                if member.is_active:
                    role_description = team.get_role_description_for_history(member)
                    print(f"    - {member.volunteer_name}: '{role_description}'")

                    # Validate role description format
                    if not role_description or role_description == "":
                        results["validation_errors"].append(
                            f"Empty role description for {member.volunteer_name} in team {team.team_name}"
                        )
                        results["success"] = False
        except Exception as e:
            results["validation_errors"].append(
                f"Error testing role descriptions for team {team_data.name}: {str(e)}"
            )
            results["success"] = False


@frappe.whitelist()
def check_team_role_field_references():
    """Check that all team_role references are valid"""

    print("=== Checking Team Role Field References ===\n")

    # Get all unique team_role values from Team Member
    team_role_refs = frappe.db.sql(
        """
        SELECT DISTINCT team_role, COUNT(*) as count
        FROM `tabTeam Member`
        WHERE team_role IS NOT NULL AND team_role != ''
        GROUP BY team_role
        ORDER BY count DESC
    """,
        as_dict=True,
    )

    print(f"Found {len(team_role_refs)} unique team_role references:")

    invalid_refs = []
    for ref in team_role_refs:
        team_role = ref.team_role
        count = ref.count

        # Check if Team Role exists
        if not frappe.db.exists("Team Role", team_role):
            invalid_refs.append({"team_role": team_role, "count": count})
            print(f"  ❌ '{team_role}' (used {count} times) - NOT FOUND")
        else:
            print(f"  ✅ '{team_role}' (used {count} times) - Valid")

    if invalid_refs:
        print(f"\n❌ Found {len(invalid_refs)} invalid team_role references:")
        for ref in invalid_refs:
            print(f"  - '{ref['team_role']}' used {ref['count']} times")
        return {"success": False, "invalid_references": invalid_refs}
    else:
        print("\n✅ All team_role references are valid!")
        return {"success": True, "invalid_references": []}


@frappe.whitelist()
def test_enhanced_factory_email_generation():
    """Test Enhanced Test Factory email generation to identify issues"""

    results = ["=== Testing Enhanced Test Factory Email Generation ==="]

    try:
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

        # Initialize factory
        factory = EnhancedTestDataFactory(seed=12345, use_faker=True)
        results.append("✅ Factory initialized successfully")

        # Test basic email generation
        results.append("\n1. Testing basic email generation...")
        try:
            email1 = factory.generate_test_email("member")
            email2 = factory.generate_test_email("member")
            email3 = factory.generate_test_email("volunteer")

            results.append(f"  Email 1: {email1}")
            results.append(f"  Email 2: {email2}")
            results.append(f"  Email 3: {email3}")

            # Check uniqueness
            if email1 == email2:
                results.append("  ❌ ISSUE: Duplicate emails generated!")
            else:
                results.append("  ✅ Emails are unique")

        except Exception as e:
            results.append(f"  ❌ ERROR in email generation: {e}")
            import traceback

            results.append(f"  Traceback: {traceback.format_exc()}")

        # Test member creation
        results.append("\n2. Testing member creation with email...")
        try:
            member = factory.create_member(first_name="Test", last_name="User", birth_date="1990-01-01")
            results.append(f"  ✅ Member created: {member.name}")
            results.append(f"  Member email: {member.email}")

        except Exception as e:
            results.append(f"  ❌ ERROR in member creation: {e}")
            import traceback

            results.append(f"  Traceback: {traceback.format_exc()}")

        # Test multiple member creation to check for duplicate email conflicts
        results.append("\n3. Testing multiple member creation...")
        try:
            members = []
            for i in range(3):
                member = factory.create_member(
                    first_name=f"Test{i}", last_name=f"User{i}", birth_date="1990-01-01"
                )
                members.append(member)
                results.append(f"  Member {i + 1}: {member.name} - {member.email}")

            # Check for duplicate emails
            emails = [m.email for m in members]
            if len(emails) != len(set(emails)):
                results.append("  ❌ ISSUE: Duplicate emails found in members!")
                for i, email in enumerate(emails):
                    results.append(f"    {i}: {email}")
            else:
                results.append("  ✅ All member emails are unique")

        except Exception as e:
            results.append(f"  ❌ ERROR in multiple member creation: {e}")
            import traceback

            results.append(f"  Traceback: {traceback.format_exc()}")

    except Exception as e:
        results.append(f"❌ FATAL ERROR: {e}")
        import traceback

        results.append(f"Traceback: {traceback.format_exc()}")

    results.append("\n=== Email Generation Test Complete ===")
    return "\n".join(results)


@frappe.whitelist()
def test_unique_role_validation_debug():
    """Debug the unique role validation issue"""

    results = ["=== Testing Unique Role Validation Debug ==="]

    try:
        # Get volunteers
        volunteers = frappe.get_all("Volunteer", limit=2)
        if len(volunteers) < 2:
            return "Need at least 2 volunteers for testing"

        results.append(f"Using volunteers: {volunteers[0].name}, {volunteers[1].name}")

        # Create team with unique name
        import time

        team_name = f"Debug Team Role Unique {int(time.time())}"
        team = frappe.get_doc(
            {
                "doctype": "Team",
                "team_name": team_name,
                "status": "Active",
                "team_type": "Project Team",
                "start_date": frappe.utils.today(),
            }
        )
        team.insert()
        results.append(f"Created team: {team.name}")

        # Add first team leader
        team.append(
            "team_members",
            {
                "volunteer": volunteers[0].name,
                "team_role": "Team Leader",
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team.save()
        results.append(f"Added first team leader: {volunteers[0].name}")

        # Check Team Role exists and is unique
        team_leader_role = frappe.get_doc("Team Role", "Team Leader")
        results.append(
            f"Team Leader role - is_unique: {team_leader_role.is_unique}, is_team_leader: {team_leader_role.is_team_leader}"
        )

        # Count existing team leaders in this team
        existing_count = frappe.db.count(
            "Team Member", {"parent": team.name, "team_role": "Team Leader", "is_active": 1}
        )
        results.append(f"Existing Team Leader count in team: {existing_count}")

        # Try adding second team leader
        results.append("Attempting to add second team leader...")
        team.append(
            "team_members",
            {
                "volunteer": volunteers[1].name,
                "team_role": "Team Leader",
                "from_date": frappe.utils.today(),
                "is_active": 1,
                "status": "Active",
            },
        )

        try:
            team.save()
            results.append("❌ ERROR: Second team leader was saved without validation error!")

            # Check final count
            final_count = frappe.db.count(
                "Team Member", {"parent": team.name, "team_role": "Team Leader", "is_active": 1}
            )
            results.append(f"Final Team Leader count: {final_count}")

        except frappe.ValidationError as e:
            results.append(f"✅ Validation error correctly raised: {e}")
        except Exception as e:
            results.append(f"❌ Unexpected error: {e}")

        # Clean up
        try:
            frappe.delete_doc("Team", team.name)
        except:
            pass

    except Exception as e:
        results.append(f"❌ Test setup error: {e}")
        import traceback

        results.append(f"Traceback: {traceback.format_exc()}")

    return "\n".join(results)


@frappe.whitelist()
def full_migration_validation():
    """Run full migration validation"""

    print("=== Full Team Role Migration Validation ===\n")

    # Run data integrity validation
    integrity_results = validate_migration_data_integrity()

    print("\n" + "=" * 50 + "\n")

    # Run field reference validation
    reference_results = check_team_role_field_references()

    # Combine results
    overall_success = integrity_results["success"] and reference_results["success"]

    print("\n=== Overall Migration Validation Results ===")
    print(f"Data Integrity: {'✅ PASSED' if integrity_results['success'] else '❌ FAILED'}")
    print(f"Field References: {'✅ PASSED' if reference_results['success'] else '❌ FAILED'}")
    print(f"Overall Status: {'✅ MIGRATION SUCCESSFUL' if overall_success else '❌ MIGRATION ISSUES FOUND'}")

    return {
        "overall_success": overall_success,
        "integrity_results": integrity_results,
        "reference_results": reference_results,
    }
