#!/usr/bin/env python3
"""
Role Renaming Utility - Add Verenigingen Prefix

This utility systematically renames verenigingen roles to include the "Verenigingen" prefix
for better identification by users.
"""

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

# Role mapping: old_name -> new_name
ROLE_MAPPINGS = {
    "Verenigingen Chapter Board Member": "Verenigingen Chapter Board Member",
    "Verenigingen Chapter Manager": "Verenigingen Chapter Manager",
    "Verenigingen Volunteer": "Verenigingen Volunteer",
    "Verenigingen Volunteer Manager": "Verenigingen Volunteer Manager",
    "Verenigingen Governance Auditor": "Verenigingen Governance Auditor",
}


@frappe.whitelist()
def get_current_role_status():
    """Get current status of roles before renaming"""

    status = {"existing_roles": {}, "role_usage": {}, "recommendations": [], "ready_to_rename": []}

    print("📋 Current Role Status Check:")
    print("=" * 40)

    for old_name, new_name in ROLE_MAPPINGS.items():
        old_exists = frappe.db.exists("Role", old_name)
        new_exists = frappe.db.exists("Role", new_name)

        status["existing_roles"][old_name] = {
            "old_exists": bool(old_exists),
            "new_exists": bool(new_exists),
            "new_name": new_name,
        }

        if old_exists:
            usage = get_role_usage_count(old_name)
            status["role_usage"][old_name] = usage
            print(f"✅ {old_name}: exists (used {usage} times)")

            if new_exists:
                status["recommendations"].append(
                    f"CONFLICT: Both '{old_name}' and '{new_name}' exist - manual review needed"
                )
            else:
                status["recommendations"].append(f"READY: '{old_name}' can be renamed to '{new_name}'")
                status["ready_to_rename"].append({"old": old_name, "new": new_name})
        else:
            print(f"❌ {old_name}: does not exist")

        if new_exists and not old_exists:
            print(f"✅ {new_name}: already renamed")

    print("\n💡 Recommendations:")
    for rec in status["recommendations"]:
        print(f"   - {rec}")

    print(f"\n🎯 Ready to rename: {len(status['ready_to_rename'])} roles")

    return status


def get_role_usage_count(role_name):
    """Get count of how many places a role is used"""
    try:
        # Count in Has Role (User roles)
        user_roles = frappe.db.count("Has Role", {"role": role_name})

        # Count in DocPerm (Document permissions)
        doc_perms = frappe.db.count("DocPerm", {"role": role_name})

        # Count in Custom DocPerm
        custom_perms = frappe.db.count("Custom DocPerm", {"role": role_name})

        # Count in Role Profile
        profile_roles = frappe.db.count("Role Profile Role", {"role": role_name})

        total = user_roles + doc_perms + custom_perms + profile_roles

        return total

    except Exception as e:
        frappe.log_error(f"Error counting role usage for {role_name}: {str(e)}")
        return 0


@frappe.whitelist()
def rename_all_roles():
    """
    Rename all verenigingen roles to have proper prefix

    Returns:
        dict: Results of the renaming operation
    """

    results = {"success": [], "errors": [], "skipped": [], "summary": {}}

    print("🔄 Starting role renaming process...")
    print("=" * 60)

    # Get current status first
    current_status = get_current_role_status()
    roles_to_rename = current_status["ready_to_rename"]

    print(f"\n📊 Found {len(roles_to_rename)} roles ready for renaming")

    if not roles_to_rename:
        print("✅ No roles need renaming!")
        results["summary"] = {
            "total_planned": len(ROLE_MAPPINGS),
            "renamed": 0,
            "skipped": len(ROLE_MAPPINGS),
            "errors": 0,
        }
        return results

    # Perform the renaming
    print("\n🔄 Starting renaming process...")

    for role_info in roles_to_rename:
        old_name = role_info["old"]
        new_name = role_info["new"]

        try:
            print(f"\n📝 Renaming: {old_name} → {new_name}")

            # Check usage before renaming
            usage_count = get_role_usage_count(old_name)
            print(f"   📊 Role is used in {usage_count} places")

            # Perform the rename using Frappe's built-in function
            # This handles all references automatically
            rename_doc("Role", old_name, new_name, merge=False)

            results["success"].append(
                {"old_name": old_name, "new_name": new_name, "usage_count": usage_count}
            )

            print(f"   ✅ Successfully renamed to {new_name}")

        except Exception as e:
            error_msg = str(e)
            results["errors"].append({"role": old_name, "target": new_name, "error": error_msg})
            print(f"   ❌ Error: {error_msg}")
            frappe.log_error(f"Role rename error for {old_name}: {error_msg}", "Role Rename")

    # Generate summary
    results["summary"] = {
        "total_planned": len(ROLE_MAPPINGS),
        "renamed": len(results["success"]),
        "skipped": len(results["skipped"]),
        "errors": len(results["errors"]),
    }

    print("\n" + "=" * 60)
    print("📊 FINAL SUMMARY:")
    print(f"   Total roles planned: {results['summary']['total_planned']}")
    print(f"   Successfully renamed: {results['summary']['renamed']}")
    print(f"   Skipped: {results['summary']['skipped']}")
    print(f"   Errors: {results['summary']['errors']}")

    if results["errors"]:
        print("\n❌ Errors encountered:")
        for error in results["errors"]:
            print(f"   - {error['role']}: {error['error']}")

    if results["success"]:
        print("\n✅ Successfully renamed roles:")
        for success in results["success"]:
            print(f"   - {success['old_name']} → {success['new_name']}")

    print("\n🎉 Role renaming process complete!")

    return results


@frappe.whitelist()
def verify_rename_success():
    """Verify that all expected renames completed successfully"""

    verification = {"all_renamed": True, "details": [], "summary": {}}

    renamed_count = 0

    for old_name, new_name in ROLE_MAPPINGS.items():
        old_exists = frappe.db.exists("Role", old_name)
        new_exists = frappe.db.exists("Role", new_name)

        status = "RENAMED" if new_exists and not old_exists else "NOT_RENAMED"

        if new_exists and not old_exists:
            renamed_count += 1
        elif old_exists and not new_exists:
            verification["all_renamed"] = False
        elif old_exists and new_exists:
            verification["all_renamed"] = False
            status = "CONFLICT"
        else:
            status = "MISSING"

        verification["details"].append(
            {
                "old_name": old_name,
                "new_name": new_name,
                "old_exists": bool(old_exists),
                "new_exists": bool(new_exists),
                "status": status,
            }
        )

        print(f"{status}: {old_name} → {new_name}")

    verification["summary"] = {
        "total_roles": len(ROLE_MAPPINGS),
        "renamed_successfully": renamed_count,
        "all_renamed": verification["all_renamed"],
    }

    return verification
