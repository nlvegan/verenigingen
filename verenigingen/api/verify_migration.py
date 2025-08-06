"""
Verify Chapter Role Migration
"""

import frappe


@frappe.whitelist()
def verify_chapter_role_cleanup():
    """Verify the chapter role consolidation worked"""

    # Clean up any remaining Chapter Manager permissions in the database
    orphaned_perms = frappe.db.sql(
        """
        DELETE FROM `tabDocPerm`
        WHERE role = 'Verenigingen Chapter Manager'
    """
    )

    if orphaned_perms:
        frappe.db.commit()
        print(f"🗑️  Cleaned up {orphaned_perms} orphaned Chapter Manager permissions")

    # Check if Chapter Manager role still exists
    role_exists = frappe.db.exists("Role", "Verenigingen Chapter Manager")

    # Check remaining permissions
    perms = frappe.db.sql(
        """
        SELECT parent, role
        FROM `tabDocPerm`
        WHERE role LIKE '%Chapter%'
        ORDER BY role, parent
    """,
        as_dict=True,
    )

    # Group by role
    role_perms = {}
    for p in perms:
        if p.role not in role_perms:
            role_perms[p.role] = []
        role_perms[p.role].append(p.parent)

    print("=== Chapter Role Migration Verification ===")
    print(f"Chapter Manager role still exists: {role_exists}")
    print(f"Total Chapter-related permissions: {len(perms)}")

    for role, doctypes in role_perms.items():
        print(f"\n{role}: {len(doctypes)} DocTypes")
        for dt in doctypes:
            print(f"  - {dt}")

    return {
        "chapter_manager_exists": role_exists,
        "total_permissions": len(perms),
        "role_permissions": role_perms,
        "success": not role_exists,  # Success if Chapter Manager no longer exists
    }
