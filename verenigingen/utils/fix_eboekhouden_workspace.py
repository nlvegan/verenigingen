#!/usr/bin/env python3
"""Fix E-Boekhouden workspace broken links"""

import frappe


@frappe.whitelist()
def get_eboekhouden_workspace_status():
    """Get detailed status of E-Boekhouden workspace"""

    workspace_name = "E-Boekhouden"

    # Get all links
    all_links = frappe.db.sql(
        """
        SELECT label, link_to, link_type, type, hidden, idx
        FROM `tabWorkspace Link`
        WHERE parent = %s
        ORDER BY idx
    """,
        workspace_name,
        as_dict=True,
    )

    # Check workspace visibility
    workspace_info = frappe.db.get_value(
        "Workspace", workspace_name, ["name", "public", "is_hidden", "module"], as_dict=True
    )

    return {
        "workspace_info": workspace_info,
        "total_links": len(all_links),
        "links": all_links,
        "payment_mapping_links": [link for link in all_links if "payment mapping" in link.label.lower()],
    }


@frappe.whitelist()
def fix_eboekhouden_payment_mapping_link():
    """Fix the broken Payment Mapping link in E-Boekhouden workspace"""

    workspace_name = "E-Boekhouden"
    old_link_to = "EBoekhouden Payment Mapping"
    new_link_to = "E-Boekhouden Payment Mapping"

    print(f"🔧 Fixing broken link in {workspace_name} workspace")
    print(f'   Changing "{old_link_to}" → "{new_link_to}"')

    # Check if the target DocType exists
    if not frappe.db.exists("DocType", new_link_to):
        print(f'❌ Target DocType "{new_link_to}" does not exist')
        return {"success": False, "error": f"DocType {new_link_to} not found"}

    # Update the workspace link
    frappe.db.sql(
        """
        UPDATE `tabWorkspace Link`
        SET link_to = %s
        WHERE parent = %s AND link_to = %s
    """,
        (new_link_to, workspace_name, old_link_to),
    )

    # Commit the change
    frappe.db.commit()

    # Verify the fix
    updated_links = frappe.db.sql(
        """
        SELECT label, link_to, link_type
        FROM `tabWorkspace Link`
        WHERE parent = %s AND link_to = %s
    """,
        (workspace_name, new_link_to),
        as_dict=True,
    )

    if updated_links:
        print("✅ Successfully updated link:")
        for link in updated_links:
            print(f"   Label: {link.label} → {link.link_to} ({link.link_type})")
        return {"success": True, "links_updated": updated_links}
    else:
        print("❌ No links were updated - link may not exist or already correct")
        return {"success": False, "error": "No links updated"}
