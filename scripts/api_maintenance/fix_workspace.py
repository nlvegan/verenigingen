"""
Fix E-Boekhouden workspace for existing installations
"""

import json
import os

import frappe


@frappe.whitelist()
def install_eboekhouden_workspace(force_enable=False):
    """Install or update the E-Boekhouden workspace"""
    
    # SAFETY GUARD: Prevent accidental workspace installation
    if not force_enable:
        return {
            "success": False,
            "message": "🛡️ E-BOEKHOUDEN WORKSPACE INSTALL DISABLED FOR SAFETY. Use force_enable=True to override."
        }
        
    try:
        # Path to the workspace JSON file
        workspace_path = frappe.get_app_path(
            "verenigingen", "verenigingen", "workspace", "e_boekhouden", "e_boekhouden.json"
        )

        if not os.path.exists(workspace_path):
            return {"success": False, "message": f"Workspace file not found: {workspace_path}"}

        # Read the workspace configuration
        with open(workspace_path, "r") as f:
            workspace_data = json.load(f)

        workspace_name = workspace_data.get("name", "E-Boekhouden")

        # Check if workspace already exists
        if frappe.db.exists("Workspace", workspace_name):
            # Delete existing to recreate with latest version
            frappe.delete_doc("Workspace", workspace_name, force=True)

        # Create new workspace
        workspace_doc = frappe.get_doc(workspace_data)
        workspace_doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return {"success": True, "message": "Successfully installed E-Boekhouden workspace"}

    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "message": f"Error installing workspace: {str(e)}"}


@frappe.whitelist()
def verify_workspace_links():
    """Verify that all workspace links point to existing DocTypes"""
    workspace_name = "E-Boekhouden"

    if not frappe.db.exists("Workspace", workspace_name):
        return {"success": False, "message": f"Workspace '{workspace_name}' not found"}

    workspace = frappe.get_doc("Workspace", workspace_name)
    broken_links = []
    valid_links = []

    for link in workspace.links:
        if link.type == "Link" and link.link_type == "DocType":
            if not frappe.db.exists("DocType", link.link_to):
                broken_links.append({"label": link.label, "link_to": link.link_to})
            else:
                valid_links.append({"label": link.label, "link_to": link.link_to})

    return {
        "success": len(broken_links) == 0,
        "message": f"Found {len(broken_links)} broken links, {len(valid_links)} valid links",
        "broken_links": broken_links,
        "valid_links": valid_links,
    }


@frappe.whitelist()
def fix_eboekhouden_workspace():
    """Main function to fix workspace issues"""
    results = {"steps": []}

    # Install/update workspace
    install_result = install_eboekhouden_workspace()
    results["steps"].append(f"Install workspace: {install_result['message']}")

    if install_result["success"]:
        # Verify all links work
        verify_result = verify_workspace_links()
        results["steps"].append(f"Verify links: {verify_result['message']}")

        return {
            "success": True,
            "message": "E-Boekhouden workspace fix completed successfully!",
            "details": results,
            "verification": verify_result,
        }
    else:
        return {"success": False, "message": "Failed to fix E-Boekhouden workspace", "details": results}
