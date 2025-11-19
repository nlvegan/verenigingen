#!/usr/bin/env python3
"""Check if Foppe's member record is properly linked to his user account"""

import frappe

def check_foppe_member_link():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    try:
        # Check Foppe's user
        foppe_email = "foppe@devnull.test"
        print(f"Checking user: {foppe_email}")
        
        # Get member record
        member = frappe.db.get_value("Member", 
            {"email": foppe_email}, 
            ["name", "user", "email", "first_name", "last_name"],
            as_dict=True
        )
        
        if member:
            print(f"\nMember found:")
            print(f"  ID: {member.name}")
            print(f"  Name: {member.first_name} {member.last_name}")
            print(f"  Email: {member.email}")
            print(f"  Linked User: {member.user}")
            
            # Check if user field matches email
            if member.user != foppe_email:
                print(f"\n⚠️  WARNING: Member.user field ({member.user}) doesn't match email ({foppe_email})")
                print("This is likely causing the permission issue!")
                
                # Fix it
                print("\nFIXING: Updating member.user to match email...")
                frappe.db.set_value("Member", member.name, "user", foppe_email)
                frappe.db.commit()
                print("✓ Fixed!")
            else:
                print("\n✓ Member.user field correctly linked")
                
        else:
            print(f"\n❌ No member found with email: {foppe_email}")
            
        # Also check by user field
        member_by_user = frappe.db.get_value("Member", {"user": foppe_email}, "name")
        if member_by_user:
            print(f"\n✓ Member {member_by_user} is linked to user {foppe_email}")
            
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        frappe.destroy()

if __name__ == "__main__":
    check_foppe_member_link()