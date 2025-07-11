#!/usr/bin/env python3
"""
Fix E-Boekhouden workspace for existing installations
This script manually installs the E-Boekhouden workspace for sites that already have the app installed
"""

import frappe
import json
import os


def install_eboekhouden_workspace():
    """Install or update the E-Boekhouden workspace"""
    try:
        # Path to the workspace JSON file
        workspace_path = frappe.get_app_path("verenigingen", "verenigingen", "workspace", "e_boekhouden", "e_boekhouden.json")
        
        if not os.path.exists(workspace_path):
            print(f"❌ Workspace file not found: {workspace_path}")
            return False
        
        # Read the workspace configuration
        with open(workspace_path, "r") as f:
            workspace_data = json.load(f)
        
        workspace_name = workspace_data.get("name", "E-Boekhouden")
        
        # Check if workspace already exists
        if frappe.db.exists("Workspace", workspace_name):
            print(f"⚠️  Workspace '{workspace_name}' already exists, updating...")
            # Delete existing to recreate with latest version
            frappe.delete_doc("Workspace", workspace_name, force=True)
        
        # Create new workspace
        workspace_doc = frappe.get_doc(workspace_data)
        workspace_doc.insert(ignore_permissions=True)
        
        frappe.db.commit()
        
        print(f"✅ Successfully installed E-Boekhouden workspace")
        return True
        
    except Exception as e:
        print(f"❌ Error installing workspace: {str(e)}")
        frappe.db.rollback()
        return False


def verify_workspace_links():
    """Verify that all workspace links point to existing DocTypes"""
    workspace_name = "E-Boekhouden"
    
    if not frappe.db.exists("Workspace", workspace_name):
        print(f"❌ Workspace '{workspace_name}' not found")
        return False
    
    workspace = frappe.get_doc("Workspace", workspace_name)
    broken_links = []
    
    for link in workspace.links:
        if link.type == "Link" and link.link_type == "DocType":
            if not frappe.db.exists("DocType", link.link_to):
                broken_links.append({
                    "label": link.label,
                    "link_to": link.link_to
                })
    
    if broken_links:
        print(f"❌ Found {len(broken_links)} broken links:")
        for link in broken_links:
            print(f"   - '{link['label']}' → '{link['link_to']}'")
        return False
    else:
        print(f"✅ All workspace links are valid")
        return True


def main():
    """Main function to fix workspace issues"""
    print("🔧 E-Boekhouden Workspace Fix Tool")
    print("=" * 50)
    
    # Install/update workspace
    if install_eboekhouden_workspace():
        # Verify all links work
        verify_workspace_links()
        print("\n✅ E-Boekhouden workspace fix completed successfully!")
        print("   You should now see the E-Boekhouden workspace with all links working.")
    else:
        print("\n❌ Failed to fix E-Boekhouden workspace")


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    main()