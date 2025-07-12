#!/usr/bin/env python3
"""
Cleanup script for test roles created during testing.
Removes test roles that may be left behind after test runs.
"""

import frappe

def cleanup_test_roles():
    """Remove test roles from the database"""
    test_role_patterns = [
        "_Test Role",
        "_Test Role 2", 
        "_Test Role 3",
        "_Test Role 4"
    ]
    
    # Also clean up Chapter Roles that might be test-related
    chapter_role_patterns = [
        "Test Role%",
        "Board Role%", 
        "Chair Role%",
        "Test Admin Role%",
        "Test Board Role%"
    ]
    
    deleted_roles = []
    
    # Clean up standard test roles
    for role_name in test_role_patterns:
        try:
            if frappe.db.exists("Role", role_name):
                # First, remove any user role assignments
                frappe.db.delete("Has Role", {"role": role_name})
                
                # Then delete the role itself
                frappe.delete_doc("Role", role_name, ignore_permissions=True)
                deleted_roles.append(role_name)
                print(f"Deleted test role: {role_name}")
                
        except Exception as e:
            print(f"Error deleting role {role_name}: {str(e)}")
    
    # Clean up Chapter Roles with test patterns
    for pattern in chapter_role_patterns:
        try:
            chapter_roles = frappe.get_all("Chapter Role", 
                filters={"role_name": ["like", pattern]}, 
                fields=["name", "role_name"])
            
            for role in chapter_roles:
                try:
                    frappe.delete_doc("Chapter Role", role.name, ignore_permissions=True)
                    deleted_roles.append(f"Chapter Role: {role.role_name}")
                    print(f"Deleted test chapter role: {role.role_name}")
                except Exception as e:
                    print(f"Error deleting chapter role {role.role_name}: {str(e)}")
                    
        except Exception as e:
            print(f"Error querying chapter roles with pattern {pattern}: {str(e)}")
    
    # Commit the transaction
    frappe.db.commit()
    
    return deleted_roles

if __name__ == "__main__":
    frappe.init()
    deleted = cleanup_test_roles()
    print(f"Cleanup completed. Deleted {len(deleted)} test roles.")
    frappe.destroy()