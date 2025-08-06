"""
Chapter Role Migration API
=========================

API endpoint to consolidate Chapter Manager role into Chapter Board Member role
"""

import frappe


@frappe.whitelist()
def consolidate_chapter_roles():
    """Migrate Chapter Manager users to Chapter Board Member and clean up"""

    if not frappe.has_permission("Role", "write"):
        frappe.throw("Insufficient permissions to modify roles")

    print("=== Chapter Role Consolidation Migration ===")

    # 1. Find all users with Chapter Manager role
    chapter_manager_users = frappe.db.sql(
        """
        SELECT DISTINCT parent as user_name
        FROM `tabHas Role`
        WHERE role = 'Verenigingen Chapter Manager'
    """,
        as_dict=True,
    )

    print(f"Found {len(chapter_manager_users)} users with Chapter Manager role")

    migrated_users = 0

    # 2. Migrate each user to Chapter Board Member role
    for user_data in chapter_manager_users:
        user_name = user_data.user_name

        try:
            # Get user document
            user_doc = frappe.get_doc("User", user_name)

            # Check if user already has Chapter Board Member role
            has_board_member_role = any(
                role.role == "Verenigingen Chapter Board Member" for role in user_doc.roles
            )

            if not has_board_member_role:
                # Add Chapter Board Member role
                user_doc.append("roles", {"role": "Verenigingen Chapter Board Member"})
                print(f"  ✅ Adding Board Member role to {user_name}")
            else:
                print(f"  ℹ️  {user_name} already has Board Member role")

            # Remove Chapter Manager role
            roles_to_remove = []
            for role in user_doc.roles:
                if role.role == "Verenigingen Chapter Manager":
                    roles_to_remove.append(role)

            for role in roles_to_remove:
                user_doc.roles.remove(role)
                print(f"  🗑️  Removed Chapter Manager role from {user_name}")

            # Save changes
            user_doc.save(ignore_permissions=True)
            migrated_users += 1

        except Exception as e:
            print(f"  ❌ Error migrating user {user_name}: {e}")

    print(f"\n✅ Successfully migrated {migrated_users} users")

    # 3. Remove Chapter Manager role from any DocType permissions
    print("\n=== Removing Chapter Manager from DocType Permissions ===")

    doctype_perms = frappe.db.sql(
        """
        SELECT parent as doctype, name as perm_name
        FROM `tabDocPerm`
        WHERE role = 'Verenigingen Chapter Manager'
    """,
        as_dict=True,
    )

    print(f"Found Chapter Manager permissions in {len(doctype_perms)} DocTypes")

    removed_perms = 0
    for perm_data in doctype_perms:
        try:
            doctype_name = perm_data.doctype

            # Get DocType and remove the permission
            doctype_doc = frappe.get_doc("DocType", doctype_name)

            perms_to_remove = []
            for perm in doctype_doc.permissions:
                if perm.role == "Verenigingen Chapter Manager":
                    perms_to_remove.append(perm)

            for perm in perms_to_remove:
                doctype_doc.permissions.remove(perm)
                print(f"  🗑️  Removed Chapter Manager permission from {doctype_name}")
                removed_perms += 1

            if perms_to_remove:
                doctype_doc.save(ignore_permissions=True)

        except Exception as e:
            print(f"  ❌ Error removing permission from {perm_data.doctype}: {e}")

    print(f"\n✅ Removed {removed_perms} DocType permissions")

    # 4. Clean up role profile references
    print("\n=== Cleaning Role Profile References ===")

    role_profiles = frappe.get_all("Role Profile", fields=["name"])
    cleaned_profiles = 0

    for profile_data in role_profiles:
        try:
            profile_doc = frappe.get_doc("Role Profile", profile_data.name)

            roles_to_remove = []
            for role in profile_doc.roles:
                if role.role == "Verenigingen Chapter Manager":
                    roles_to_remove.append(role)

            if roles_to_remove:
                for role in roles_to_remove:
                    profile_doc.roles.remove(role)

                profile_doc.save(ignore_permissions=True)
                cleaned_profiles += 1
                print(f"  🗑️  Cleaned Chapter Manager from role profile: {profile_data.name}")

        except Exception as e:
            print(f"  ❌ Error cleaning role profile {profile_data.name}: {e}")

    print(f"\n✅ Cleaned {cleaned_profiles} role profiles")

    # 5. Remove the Chapter Manager role itself
    print("\n=== Removing Chapter Manager Role ===")

    try:
        if frappe.db.exists("Role", "Verenigingen Chapter Manager"):
            frappe.delete_doc("Role", "Verenigingen Chapter Manager", force=True)
            print("  🗑️  Deleted Verenigingen Chapter Manager role")
        else:
            print("  ℹ️  Chapter Manager role already removed")
    except Exception as e:
        print(f"  ❌ Error deleting Chapter Manager role: {e}")

    # 6. Commit changes
    frappe.db.commit()

    print("\n🎉 Chapter Role Consolidation Complete!")
    print("📋 Summary:")
    print(f"   - Migrated {migrated_users} users to Chapter Board Member role")
    print(f"   - Removed {removed_perms} DocType permissions")
    print(f"   - Cleaned {cleaned_profiles} role profiles")
    print("   - Deleted redundant Chapter Manager role")
    print("\n💡 The system now uses only Chapter Board Member for chapter management")

    return {
        "success": True,
        "message": "Chapter role consolidation completed successfully",
        "migrated_users": migrated_users,
        "removed_permissions": removed_perms,
        "cleaned_profiles": cleaned_profiles,
    }
