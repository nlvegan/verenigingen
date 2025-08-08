import json
import os

import frappe


@frappe.whitelist()
def restore_workspace():
    """Restore the workspace from fixtures"""

    # Path to the fixtures file
    fixtures_path = "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/fixtures/workspace.json"

    if not os.path.exists(fixtures_path):
        return {"success": False, "message": "Fixtures file not found"}

    # Load the fixtures
    with open(fixtures_path, "r") as f:
        fixtures = json.load(f)

    if not fixtures or len(fixtures) == 0:
        return {"success": False, "message": "No workspace data in fixtures"}

    workspace_data = fixtures[0]

    # Delete existing workspace if it exists
    if frappe.db.exists("Workspace", "Verenigingen"):
        frappe.delete_doc("Workspace", "Verenigingen", force=True)
        print("Deleted existing workspace")

    # Create new workspace from fixtures
    workspace = frappe.new_doc("Workspace")

    # Copy all fields from fixtures
    for field, value in workspace_data.items():
        if field not in ["doctype", "modified", "modified_by", "owner", "creation"]:
            setattr(workspace, field, value)

    # Ensure Communication section is in content
    content_str = workspace.content
    if "CommunicationHeader" not in content_str:
        # Add Communication section after Teams section
        content_str = content_str.replace(
            '}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
            '}},{"id":"CommunicationHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Communication & Newsletters</b></span>","col":12}},{"id":"CommunicationCard","type":"card","data":{"card_name":"Communication","col":4}},{"id":"zGoLYG0xRM6","type":"spacer","data":{"col":12}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
        )
        workspace.content = content_str

    # Check if Communication links exist, if not add them
    has_newsletter = any(
        link.get("link_to") == "Newsletter" for link in workspace.links if isinstance(link, dict)
    )

    if not has_newsletter:
        # Add Communication card break and links using append method
        workspace.append("links", {"label": "Communication", "type": "Card Break"})

        workspace.append(
            "links",
            {
                "label": "Newsletter",
                "link_to": "Newsletter",
                "link_type": "DocType",
                "description": "Create and send newsletters to members",
            },
        )

        workspace.append(
            "links",
            {
                "label": "Email Group",
                "link_to": "Email Group",
                "link_type": "DocType",
                "description": "Manage email groups for targeted communication",
            },
        )

        workspace.append(
            "links",
            {
                "label": "Email Group Member",
                "link_to": "Email Group Member",
                "link_type": "DocType",
                "description": "Manage members in email groups",
            },
        )

        workspace.append(
            "links",
            {
                "label": "Communication",
                "link_to": "Communication",
                "link_type": "DocType",
                "description": "View communication history and logs",
            },
        )

        workspace.append(
            "links",
            {
                "label": "Email Template",
                "link_to": "Email Template",
                "link_type": "DocType",
                "description": "Manage email templates for automated communications",
            },
        )

    workspace.flags.ignore_permissions = True
    workspace.insert()

    frappe.db.commit()
    frappe.clear_cache()

    return {
        "success": True,
        "message": "Workspace restored from fixtures with Communication section",
        "links_count": len(workspace.links),
    }
