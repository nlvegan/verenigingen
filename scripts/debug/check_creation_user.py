#!/usr/bin/env python3
"""Check the current creation user setting"""

import frappe

def check_creation_user():
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    try:
        settings = frappe.get_single("Verenigingen Settings")
        
        print(f"Current creation_user: {settings.creation_user}")
        
        # Check if this user exists
        if settings.creation_user:
            user_exists = frappe.db.exists("User", settings.creation_user)
            print(f"User exists: {user_exists}")
            
            if user_exists:
                user = frappe.get_doc("User", settings.creation_user)
                print(f"User name: {user.full_name}")
                print(f"User roles: {[r.role for r in user.roles]}")
        else:
            print("No creation_user set in settings")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        frappe.destroy()

if __name__ == "__main__":
    check_creation_user()