#!/usr/bin/env python3
"""
Role Renaming Script - Add Verenigingen Prefix

This script systematically renames verenigingen roles to include the "Verenigingen" prefix
for better identification by users. It handles all database references, permissions, 
and related configurations.

Created: 2025-08-06
Purpose: Rename roles for better user identification and system organization
"""

import frappe
from frappe.model.rename_doc import rename_doc
from frappe import _

# Role mapping: old_name -> new_name
ROLE_MAPPINGS = {
    "Verenigingen Chapter Board Member": "Verenigingen Chapter Board Member",
    "Verenigingen Chapter Manager": "Verenigingen Chapter Manager", 
    "Verenigingen Volunteer": "Verenigingen Volunteer",
    "Verenigingen Volunteer Manager": "Verenigingen Volunteer Manager",
    "Verenigingen Governance Auditor": "Verenigingen Governance Auditor"
}

@frappe.whitelist()
def rename_verenigingen_roles():
    """
    Rename all verenigingen roles to have proper prefix
    
    Returns:
        dict: Results of the renaming operation
    """
    
    results = {
        "success": [],
        "errors": [],
        "skipped": [],
        "summary": {}
    }
    
    print("🔄 Starting role renaming process...")
    print("=" * 60)
    
    # Step 1: Check which roles actually exist and need renaming
    roles_to_rename = []
    
    for old_name, new_name in ROLE_MAPPINGS.items():
        if frappe.db.exists("Role", old_name):
            if frappe.db.exists("Role", new_name):
                results["skipped"].append({
                    "role": old_name,
                    "reason": f"Target role '{new_name}' already exists"
                })
                print(f"⚠️  Skipping {old_name} - target already exists")
            else:
                roles_to_rename.append((old_name, new_name))
                print(f"📝 Will rename: {old_name} → {new_name}")
        else:
            results["skipped"].append({
                "role": old_name, 
                "reason": "Role does not exist"
            })
            print(f"⚠️  Skipping {old_name} - does not exist")
    
    print(f"\n📊 Found {len(roles_to_rename)} roles to rename")
    
    if not roles_to_rename:
        print("✅ No roles need renaming!")
        results["summary"] = {
            "total_planned": len(ROLE_MAPPINGS),
            "renamed": 0,
            "skipped": len(results["skipped"]),
            "errors": 0
        }
        return results
    
    # Step 2: Perform the renaming
    print("\n🔄 Starting renaming process...")
    
    for old_name, new_name in roles_to_rename:
        try:
            print(f"\n📝 Renaming: {old_name} → {new_name}")
            
            # Check usage before renaming
            usage_count = get_role_usage_count(old_name)
            print(f"   📊 Role is used in {usage_count} places")
            
            # Perform the rename using Frappe's built-in function
            # This handles all references automatically
            rename_doc("Role", old_name, new_name, merge=False)
            
            results["success"].append({
                "old_name": old_name,
                "new_name": new_name,
                "usage_count": usage_count
            })
            
            print(f"   ✅ Successfully renamed to {new_name}")
            
        except Exception as e:
            error_msg = str(e)
            results["errors"].append({
                "role": old_name,
                "target": new_name,
                "error": error_msg
            })
            print(f"   ❌ Error: {error_msg}")
            frappe.log_error(f"Role rename error for {old_name}: {error_msg}", "Role Rename")
    
    # Step 3: Verify results
    print(f"\n🔍 Verifying results...")
    
    verification_results = verify_role_rename_success(results["success"])
    
    # Step 4: Generate summary
    results["summary"] = {
        "total_planned": len(ROLE_MAPPINGS),
        "renamed": len(results["success"]),
        "skipped": len(results["skipped"]),
        "errors": len(results["errors"])
    }
    
    results["verification"] = verification_results
    
    print("\n" + "=" * 60)
    print("📊 FINAL SUMMARY:")
    print(f"   Total roles planned: {results['summary']['total_planned']}")
    print(f"   Successfully renamed: {results['summary']['renamed']}")
    print(f"   Skipped: {results['summary']['skipped']}")
    print(f"   Errors: {results['summary']['errors']}")
    
    if results["errors"]:
        print(f"\n❌ Errors encountered:")
        for error in results["errors"]:
            print(f"   - {error['role']}: {error['error']}")
    
    if results["success"]:
        print(f"\n✅ Successfully renamed roles:")
        for success in results["success"]:
            print(f"   - {success['old_name']} → {success['new_name']}")
    
    print("\n🎉 Role renaming process complete!")
    
    return results

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

def verify_role_rename_success(renamed_roles):
    """Verify that renamed roles exist and old ones don't"""
    verification = {
        "all_new_exist": True,
        "no_old_exist": True,
        "details": []
    }
    
    for role_info in renamed_roles:
        old_name = role_info["old_name"]
        new_name = role_info["new_name"]
        
        # Check new role exists
        new_exists = frappe.db.exists("Role", new_name)
        # Check old role doesn't exist
        old_exists = frappe.db.exists("Role", old_name)
        
        detail = {
            "old_name": old_name,
            "new_name": new_name,
            "new_exists": bool(new_exists),
            "old_still_exists": bool(old_exists),
            "success": bool(new_exists) and not bool(old_exists)
        }
        
        verification["details"].append(detail)
        
        if not new_exists:
            verification["all_new_exist"] = False
        if old_exists:
            verification["no_old_exist"] = False
    
    verification["overall_success"] = verification["all_new_exist"] and verification["no_old_exist"]
    
    return verification

@frappe.whitelist()
def get_current_role_status():
    """Get current status of roles before renaming"""
    
    status = {
        "existing_roles": {},
        "role_usage": {},
        "recommendations": []
    }
    
    print("📋 Current Role Status Check:")
    print("=" * 40)
    
    for old_name, new_name in ROLE_MAPPINGS.items():
        old_exists = frappe.db.exists("Role", old_name)
        new_exists = frappe.db.exists("Role", new_name)
        
        status["existing_roles"][old_name] = {
            "old_exists": bool(old_exists),
            "new_exists": bool(new_exists),
            "new_name": new_name
        }
        
        if old_exists:
            usage = get_role_usage_count(old_name)
            status["role_usage"][old_name] = usage
            print(f"✅ {old_name}: exists (used {usage} times)")
            
            if new_exists:
                status["recommendations"].append(f"Role '{old_name}' and '{new_name}' both exist - manual review needed")
            else:
                status["recommendations"].append(f"Role '{old_name}' ready for rename to '{new_name}'")
        else:
            print(f"❌ {old_name}: does not exist")
            
        if new_exists and not old_exists:
            print(f"✅ {new_name}: already renamed")
    
    return status

@frappe.whitelist() 
def rollback_role_rename(role_mappings=None):
    """
    Rollback role renames if needed
    
    Args:
        role_mappings: Dict of new_name -> old_name mappings to rollback
    """
    
    if not role_mappings:
        # Default rollback mappings (reverse of ROLE_MAPPINGS)
        role_mappings = {new_name: old_name for old_name, new_name in ROLE_MAPPINGS.items()}
    
    results = {
        "success": [],
        "errors": [],
        "skipped": []
    }
    
    print("🔄 Starting role rename rollback...")
    
    for new_name, old_name in role_mappings.items():
        try:
            if frappe.db.exists("Role", new_name):
                if frappe.db.exists("Role", old_name):
                    results["skipped"].append(f"Cannot rollback {new_name} - {old_name} already exists")
                    continue
                    
                rename_doc("Role", new_name, old_name, merge=False)
                results["success"].append(f"Rolled back {new_name} → {old_name}")
                print(f"✅ Rolled back: {new_name} → {old_name}")
            else:
                results["skipped"].append(f"Role {new_name} does not exist")
                
        except Exception as e:
            error_msg = str(e)
            results["errors"].append(f"Error rolling back {new_name}: {error_msg}")
            print(f"❌ Error rolling back {new_name}: {error_msg}")
    
    return results

if __name__ == "__main__":
    # When run directly, show current status
    frappe.init(site='dev.veganisme.net')
    frappe.connect()
    
    print("🔍 Checking current role status...")
    status = get_current_role_status()
    
    print(f"\n💡 Recommendations:")
    for rec in status["recommendations"]:
        print(f"   - {rec}")
    
    print(f"\n🚀 To rename roles, run:")
    print(f"   bench --site dev.veganisme.net execute verenigingen.scripts.maintenance.rename_roles_with_prefix.rename_verenigingen_roles")