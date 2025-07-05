#!/usr/bin/env python3
"""
Auto-assign Role Profiles to Existing Users

This script analyzes existing users and assigns appropriate role profiles
based on their current roles and associations.
"""

import frappe


def auto_assign_enhanced_profiles():
    """Auto-assign role profiles with enhanced logic"""

    print("=== Auto-Assigning Role Profiles to Users ===\n")

    # Statistics
    stats = {"analyzed": 0, "assigned": 0, "skipped": 0, "errors": 0, "assignments": {}}

    # Get all active users with member records
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "name": ["not in", ["Administrator", "Guest"]]},
        fields=["name", "full_name", "role_profile_name"],
    )

    print(f"Found {len(users)} active users to analyze\n")

    for user in users:
        stats["analyzed"] += 1
        try:
            # Check if user already has a Verenigingen role profile
            existing_profiles = frappe.db.sql(
                """
                SELECT role_profile
                FROM `tabHas Role Profile`
                WHERE parent = %s
                AND role_profile LIKE 'Verenigingen%%'
            """,
                user.name,
                as_dict=True,
            )

            if existing_profiles:
                print(f"⏭️  {user.name} - Already has profile: {existing_profiles[0].role_profile}")
                stats["skipped"] += 1
                continue

            # Determine appropriate profile
            recommended_profile = determine_user_profile(user.name)

            if recommended_profile:
                # Assign the profile
                assign_profile_to_user(user.name, recommended_profile)
                print(f"✅ {user.name} - Assigned: {recommended_profile}")
                stats["assigned"] += 1

                # Track assignment
                if recommended_profile not in stats["assignments"]:
                    stats["assignments"][recommended_profile] = 0
                stats["assignments"][recommended_profile] += 1
            else:
                print(f"❓ {user.name} - No suitable profile found")
                stats["skipped"] += 1

        except Exception as e:
            print(f"❌ {user.name} - Error: {str(e)}")
            stats["errors"] += 1

    # Print summary
    print_summary(stats)


def determine_user_profile(user_email):
    """Enhanced logic to determine appropriate role profile"""

    # Get user's current roles
    user_roles = frappe.get_roles(user_email)

    # Check if user is linked to a member
    member = frappe.db.get_value("Member", {"user": user_email}, ["name", "status"], as_dict=True)

    # Priority-based assignment

    # 1. System-level roles
    if "System Manager" in user_roles or "Administrator" in user_roles:
        return "Verenigingen System Administrator"

    # 2. Manager roles
    if "Verenigingen Manager" in user_roles:
        # Check for finance focus
        if "Accounts Manager" in user_roles:
            return "Verenigingen Finance Manager"
        return "Verenigingen Manager"

    # 3. Audit roles
    if "Governance Auditor" in user_roles or "Auditor" in user_roles:
        return "Verenigingen Auditor"

    # 4. Staff roles
    if "Verenigingen Staff" in user_roles:
        # Check specializations
        if "Accounts User" in user_roles or "Accounts Manager" in user_roles:
            return "Verenigingen Treasurer"
        elif "Website Manager" in user_roles and "Newsletter Manager" in user_roles:
            return "Verenigingen Communications Officer"
        else:
            return "Verenigingen Chapter Administrator"

    # 5. Board roles
    if "Chapter Board Member" in user_roles:
        # Check if also treasurer
        if "Accounts User" in user_roles:
            return "Verenigingen Treasurer"
        return "Verenigingen Chapter Board"

    # 6. Volunteer-based assignment
    if member:
        volunteer = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        if volunteer:
            # Check team leadership
            team_leader = frappe.db.get_value(
                "Team Member",
                {"volunteer": volunteer, "role_type": ["in", ["Team Leader", "Leader"]], "is_active": 1},
                "name",
            )

            if team_leader:
                return "Verenigingen Team Leader"

            # Check event coordination
            event_teams = frappe.db.count(
                "Team Member", {"volunteer": volunteer, "is_active": 1, "role": ["like", "%event%"]}
            )

            if event_teams > 0:
                return "Verenigingen Event Coordinator"

            # Regular volunteer
            return "Verenigingen Volunteer"

    # 7. Basic member
    if member and member.status == "Active":
        return "Verenigingen Member"

    # 8. Guest/Customer
    if "Customer" in user_roles and not member:
        return "Verenigingen Guest"

    # No suitable profile found
    return None


def assign_profile_to_user(user_email, role_profile):
    """Assign a role profile to a user"""
    user_doc = frappe.get_doc("User", user_email)

    # Check if already assigned
    existing = [rp.role_profile for rp in user_doc.role_profiles]
    if role_profile not in existing:
        user_doc.append("role_profiles", {"role_profile": role_profile})
        user_doc.save(ignore_permissions=True)
        frappe.db.commit()


def print_summary(stats):
    """Print assignment summary"""
    print("\n" + "=" * 50)
    print("📊 ASSIGNMENT SUMMARY")
    print("=" * 50)
    print(f"Total users analyzed: {stats['analyzed']}")
    print(f"✅ Profiles assigned: {stats['assigned']}")
    print(f"⏭️  Users skipped: {stats['skipped']}")
    print(f"❌ Errors: {stats['errors']}")

    if stats["assignments"]:
        print("\n📈 Profile Distribution:")
        for profile, count in sorted(stats["assignments"].items()):
            print(f"  {profile}: {count}")

    print("\n💡 Next Steps:")
    print("1. Review the assignments in User List")
    print("2. Clear cache: bench --site [sitename] clear-cache")
    print("3. Test with sample users from each profile")
    print("4. Adjust individual assignments as needed")


def show_profile_analysis():
    """Show analysis of current role distribution"""
    print("\n📊 Current Role Profile Analysis:")

    # Get all Verenigingen role profiles
    profiles = frappe.get_all("Role Profile", filters={"name": ["like", "Verenigingen%"]}, fields=["name"])

    print(f"\nAvailable Verenigingen Role Profiles: {len(profiles)}")

    for profile in profiles:
        # Count users with this profile
        user_count = frappe.db.sql(
            """
            SELECT COUNT(DISTINCT parent) as count
            FROM `tabHas Role Profile`
            WHERE role_profile = %s
        """,
            profile.name,
        )[0][0]

        print(f"  {profile.name}: {user_count} users")


if __name__ == "__main__":
    frappe.connect(site=frappe.get_site())

    try:
        # Show current state
        show_profile_analysis()

        # Run auto-assignment
        print("\n" + "=" * 50)
        auto_assign_enhanced_profiles()

    except Exception as e:
        print(f"\n❌ Auto-assignment failed: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        frappe.destroy()
