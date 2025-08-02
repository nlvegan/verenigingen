#!/usr/bin/env python3
"""
Migration script for Team Role integration

This script migrates existing Team Member records from the old role_type system
to the new team_role Link field system.
"""

import frappe
from frappe import _


def execute():
    """Main migration function with proper transaction management and validation"""

    # Check if Team Role DocType exists
    if not frappe.db.exists("DocType", "Team Role"):
        print("Team Role DocType not found. Skipping migration.")
        return

    print("=== Team Role Migration Starting ===")

    # Validate migration prerequisites
    if not validate_migration_prerequisites():
        print("Migration prerequisites validation failed. Aborting.")
        return

    # Create role mapping from old role_type to new Team Role names
    role_mapping = get_role_mapping()

    # Validate all Team Roles exist before migration
    if not validate_team_roles_exist(role_mapping):
        print("Team Role validation failed. Aborting migration.")
        return

    # Get all Team Member records that need migration
    team_members = frappe.db.get_all(
        "Team Member",
        fields=["name", "parent", "role_type", "team_role", "volunteer_name"],
        filters={"team_role": ["is", "not set"]},
    )

    print(f"Found {len(team_members)} team members to migrate")

    if not team_members:
        print("No team members require migration. Exiting.")
        return

    # Execute migration with atomic transaction
    migrate_team_members_atomic(team_members, role_mapping)


def migrate_team_members_atomic(team_members, role_mapping):
    """Migrate team members with atomic transaction and rollback capability"""

    migrated_count = 0
    failed_migrations = []
    rollback_data = []

    try:
        # Start atomic transaction
        frappe.db.begin()

        for member in team_members:
            try:
                # Store rollback data
                rollback_data.append({"name": member.name, "original_team_role": member.team_role})

                # Map old role_type to new team_role
                old_role = member.role_type or "Team Member"  # Default fallback
                new_role = role_mapping.get(old_role, "Team Member")  # Default fallback

                # Validate Team Role exists (double-check)
                if not frappe.db.exists("Team Role", new_role):
                    raise frappe.ValidationError(f"Team Role '{new_role}' does not exist")

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
                # Continue with other members instead of aborting entire transaction

        # Check if any critical failures occurred
        if (
            failed_migrations and len(failed_migrations) > len(team_members) * 0.1
        ):  # More than 10% failure rate
            raise frappe.ValidationError(
                f"High failure rate: {len(failed_migrations)} out of {len(team_members)} migrations failed"
            )

        # Validate migration results
        validate_migration_results(team_members, role_mapping)

        # Commit the transaction
        frappe.db.commit()

        # Report results
        print("\nMigration complete:")
        print(f"- Successfully migrated: {migrated_count}")
        print(f"- Failed migrations: {len(failed_migrations)}")

        if failed_migrations:
            print("\nFailed migrations:")
            for failure in failed_migrations:
                print(f"  - {failure['volunteer']}: {failure['error']}")

        # Log successful migration
        frappe.log_error(
            f"Team Role migration completed: {migrated_count} migrated, {len(failed_migrations)} failed",
            "Team Role Migration Success",
        )

    except Exception as e:
        # Rollback transaction on critical failure
        frappe.db.rollback()
        print(f"\nCRITICAL ERROR: Migration failed and rolled back: {e}")

        # Log the error
        frappe.log_error(f"Team Role migration failed and rolled back: {e}", "Team Role Migration Failure")

        # Re-raise to ensure migration script fails
        raise


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
                role_doc.insert()
                print(f"Created missing Team Role: {role_data['name']}")
            except Exception as e:
                print(f"Failed to create Team Role {role_data['name']}: {e}")


def validate_migration_prerequisites():
    """Validate that migration can proceed safely"""

    try:
        # Check Team Member DocType exists
        if not frappe.db.exists("DocType", "Team Member"):
            print("ERROR: Team Member DocType not found")
            return False

        # Check if team_role field exists in Team Member
        team_member_meta = frappe.get_meta("Team Member")
        if not team_member_meta.has_field("team_role"):
            print("ERROR: team_role field not found in Team Member DocType")
            return False

        # Check if Team Role DocType is accessible
        try:
            frappe.get_meta("Team Role")
        except Exception as e:
            print(f"ERROR: Cannot access Team Role DocType: {e}")
            return False

        print("✓ Migration prerequisites validated")
        return True

    except Exception as e:
        print(f"ERROR: Prerequisites validation failed: {e}")
        return False


def validate_team_roles_exist(role_mapping):
    """Validate that all required Team Roles exist before migration"""

    try:
        unique_roles = set(role_mapping.values())
        missing_roles = []

        for role_name in unique_roles:
            if not frappe.db.exists("Team Role", role_name):
                missing_roles.append(role_name)

        if missing_roles:
            print(f"ERROR: Missing Team Roles: {missing_roles}")
            return False

        print(f"✓ All {len(unique_roles)} required Team Roles exist")
        return True

    except Exception as e:
        print(f"ERROR: Team Role validation failed: {e}")
        return False


def validate_migration_results(team_members, role_mapping):
    """Validate that migration results are consistent"""

    try:
        # Check that all migrated members now have valid team_role values
        migrated_members = frappe.db.get_all(
            "Team Member",
            fields=["name", "team_role", "volunteer_name"],
            filters={"name": ["in", [m.name for m in team_members]]},
        )

        validation_errors = []

        for member in migrated_members:
            if not member.team_role:
                validation_errors.append(f"Member {member.volunteer_name} still has no team_role")
            elif not frappe.db.exists("Team Role", member.team_role):
                validation_errors.append(
                    f"Member {member.volunteer_name} has invalid team_role: {member.team_role}"
                )

        if validation_errors:
            error_msg = "Migration validation failed:\n" + "\n".join(validation_errors)
            raise frappe.ValidationError(error_msg)

        print(f"✓ Migration results validated for {len(migrated_members)} members")

    except Exception as e:
        print(f"ERROR: Migration result validation failed: {e}")
        raise


if __name__ == "__main__":
    execute()
