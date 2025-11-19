#!/usr/bin/env python3
"""Investigate why Foppe de Haan cannot view his own member record but can view others"""

import frappe
from frappe.permissions import get_doc_permissions
import json

def investigate_foppe_permissions():
    """Debug permission issues for Foppe de Haan"""
    
    # Get Foppe's user record
    foppe_user = "foppe@devnull.test"
    
    print(f"\n=== Investigating permissions for user: {foppe_user} ===\n")
    
    # Check user details
    user = frappe.get_doc("User", foppe_user)
    print(f"User: {user.full_name}")
    print(f"Roles: {[r.role for r in user.roles]}")
    print(f"Enabled: {user.enabled}")
    
    # Get Foppe's member record
    print("\n=== Finding Foppe's member record ===")
    foppe_member = frappe.db.get_value("Member", 
        {"email": foppe_user}, 
        ["name", "first_name", "last_name", "user", "status"], 
        as_dict=True
    )
    
    if not foppe_member:
        print("ERROR: No member record found for Foppe de Haan!")
        return
    
    print(f"Member ID: {foppe_member.name}")
    print(f"Name: {foppe_member.first_name} {foppe_member.last_name}")
    print(f"Linked User: {foppe_member.user}")
    print(f"Status: {foppe_member.status}")
    
    # Check if member is linked to correct user
    if foppe_member.user != foppe_user:
        print(f"\n⚠️  WARNING: Member is linked to different user: {foppe_member.user}")
    
    # Check permissions on Foppe's own record
    print(f"\n=== Permissions for own record ({foppe_member.name}) ===")
    try:
        frappe.set_user(foppe_user)
        perms = get_doc_permissions(frappe.get_doc("Member", foppe_member.name))
        print(f"Can read: {perms.get('read')}")
        print(f"Can write: {perms.get('write')}")
        
        # Try to actually read the record
        try:
            doc = frappe.get_doc("Member", foppe_member.name)
            print("✓ Can fetch document successfully")
        except frappe.PermissionError as e:
            print(f"✗ Cannot fetch document: {str(e)}")
    finally:
        frappe.set_user("Administrator")
    
    # Check permissions on other member records
    print("\n=== Permissions for other records ===")
    other_members = ["Gerben Zonderland", "test Sipkes"]
    
    for member_name in other_members:
        member_id = frappe.db.get_value("Member", {"full_name": member_name}, "name")
        if member_id:
            print(f"\nChecking {member_name} ({member_id}):")
            try:
                frappe.set_user(foppe_user)
                perms = get_doc_permissions(frappe.get_doc("Member", member_id))
                print(f"  Can read: {perms.get('read')}")
                
                # Try to actually read
                try:
                    doc = frappe.get_doc("Member", member_id)
                    print("  ✓ Can fetch document")
                except frappe.PermissionError:
                    print("  ✗ Cannot fetch document")
            finally:
                frappe.set_user("Administrator")
    
    # Check Member DocType permissions
    print("\n=== Member DocType Permission Rules ===")
    perms = frappe.get_all("DocPerm", 
        filters={"parent": "Member", "parenttype": "DocType"},
        fields=["role", "permlevel", "read", "write", "if_owner"],
        order_by="idx"
    )
    
    for perm in perms:
        if perm.role in [r.role for r in user.roles]:
            print(f"\nRole: {perm.role} (Level {perm.permlevel})")
            print(f"  Read: {perm.read}, Write: {perm.write}")
            print(f"  If Owner: {perm.if_owner}")
    
    # Check if there are any special conditions
    print("\n=== Checking for special conditions ===")
    
    # Check if member has address issues
    member_doc = frappe.get_doc("Member", foppe_member.name)
    print(f"Current Address: {member_doc.current_address}")
    
    # Check if suspension_api is being called
    print("\n=== Analyzing suspension_api error ===")
    print("The console error shows:")
    print("- get_member_suspension_history requires Verenigingen Administrator role")
    print("- check_member_payment_issues requires Verenigingen Administrator role")
    
    # Check if these methods are being called in onload or elsewhere
    print("\nThese admin-only APIs might be called from:")
    print("1. Member.onload() method")
    print("2. Member.js refresh handler")
    print("3. HTML field generation")
    
    return foppe_member

if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    try:
        result = investigate_foppe_permissions()
        print("\n=== Investigation Complete ===")
    except Exception as e:
        print(f"\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        frappe.destroy()