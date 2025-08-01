#!/usr/bin/env python3
"""
Migration script for Team Role integration

This script migrates existing Team Member records from the old role_type system
to the new team_role Link field system.
"""

import frappe
from frappe import _


def execute():
    """Main migration function"""

    # Check if Team Role DocType exists
    if not frappe.db.exists("DocType", "Team Role"):
        print("Team Role DocType not found. Skipping migration.")
        return

    # Create role mapping from old role_type to new Team Role names
    role_mapping = get_role_mapping()

    # Get all Team Member records that need migration
    team_members = frappe.db.get_all(
        "Team Member",
        fields=["name", "parent", "role_type", "team_role", "volunteer_name"],
        filters={"team_role": ["is", "not set"]},
    )

    print(f"Found {len(team_members)} team members to migrate")

    migrated_count = 0
    failed_migrations = []

    for member in team_members:
        try:
            # Map old role_type to new team_role
            old_role = member.role_type or "Team Member"  # Default fallback
            new_role = role_mapping.get(old_role, "Team Member")  # Default fallback

            # Update the team member record
            frappe.db.set_value("Team Member", member.name, "team_role", new_role)

            migrated_count += 1
            print(f"Migrated {member.volunteer_name}: '{old_role}' -> '{new_role}'")

        except Exception as e:
            failed_migrations.append(
                {
                    "name": member.name,
                    "volunteer": member.volunteer_name,
                    "old_role": member.role_type,
                    "error": str(e),
                }
            )
            print(f"Failed to migrate {member.volunteer_name}: {e}")

    # Report results
    print("\nMigration complete:")
    print(f"- Successfully migrated: {migrated_count}")
    print(f"- Failed migrations: {len(failed_migrations)}")

    if failed_migrations:
        print("\nFailed migrations:")
        for failure in failed_migrations:
            print(f"  - {failure['volunteer']}: {failure['error']}")

    # Commit the transaction
    frappe.db.commit()


def get_role_mapping():
    """Get mapping from old role_type to new Team Role names"""

    # First, ensure all required Team Roles exist
    ensure_team_roles_exist()

    # Map old role types to new Team Role names
    role_mapping = {
        "Team Leader": "Team Leader",
        "Team Member": "Team Member",
        "Coordinator": "Coordinator",
        "Secretary": "Secretary",
        "Treasurer": "Treasurer",
        # Handle variations and legacy values
        "team leader": "Team Leader",
        "team member": "Team Member",
        "coordinator": "Coordinator",
        "secretary": "Secretary",
        "treasurer": "Treasurer",
        "Leader": "Team Leader",
        "Member": "Team Member",
    }

    return role_mapping


def ensure_team_roles_exist():
    """Ensure all required Team Role records exist"""

    required_roles = [
        {
            "name": "Team Leader",
            "role_name": "Team Leader",
            "description": "Leads the team and coordinates activities",
            "permissions_level": "Leader",
            "is_team_leader": 1,
            "is_unique": 1,
            "is_active": 1,
        },
        {
            "name": "Team Member",
            "role_name": "Team Member",
            "description": "General team member participating in activities",
            "permissions_level": "Basic",
            "is_team_leader": 0,
            "is_unique": 0,
            "is_active": 1,
        },
    ]

    for role_data in required_roles:
        if not frappe.db.exists("Team Role", role_data["name"]):
            try:
                role_doc = frappe.new_doc("Team Role")
                for key, value in role_data.items():
                    setattr(role_doc, key, value)
                role_doc.insert(ignore_permissions=True)
                print(f"Created missing Team Role: {role_data['name']}")
            except Exception as e:
                print(f"Failed to create Team Role {role_data['name']}: {e}")


if __name__ == "__main__":
    execute()
