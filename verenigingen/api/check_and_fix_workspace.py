import frappe


@frappe.whitelist()
def check_and_fix_workspace():
    """Check workspace and add Communication section"""

    if not frappe.db.exists("Workspace", "Verenigingen"):
        return {"success": False, "message": "Workspace does not exist. Run bench migrate first."}

    workspace = frappe.get_doc("Workspace", "Verenigingen")

    # Check if Communication section exists in content
    content_str = workspace.content
    has_comm_section = "CommunicationHeader" in content_str or "CommunicationCard" in content_str

    if not has_comm_section:
        # Add Communication section after Teams section
        new_content = content_str.replace(
            '}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
            '}},{"id":"CommunicationHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Communication & Newsletters</b></span>","col":12}},{"id":"CommunicationCard","type":"card","data":{"card_name":"Communication","col":4}},{"id":"zGoLYG0xRM6","type":"spacer","data":{"col":12}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
        )
        workspace.content = new_content

    # Check if Newsletter links exist
    has_newsletter = any(link.link_to == "Newsletter" for link in workspace.links if hasattr(link, "link_to"))

    if not has_newsletter:
        # Add Communication card break
        workspace.append("links", {"label": "Communication", "type": "Card Break"})

        # Newsletter links
        newsletter_links = [
            {
                "label": "Newsletter",
                "link_to": "Newsletter",
                "link_type": "DocType",
                "description": "Create and send newsletters to members",
            },
            {
                "label": "Email Group",
                "link_to": "Email Group",
                "link_type": "DocType",
                "description": "Manage email groups for targeted communication",
            },
            {
                "label": "Email Group Member",
                "link_to": "Email Group Member",
                "link_type": "DocType",
                "description": "Manage members in email groups",
            },
            {
                "label": "Communication",
                "link_to": "Communication",
                "link_type": "DocType",
                "description": "View communication history and logs",
            },
            {
                "label": "Email Template",
                "link_to": "Email Template",
                "link_type": "DocType",
                "description": "Manage email templates for automated communications",
            },
        ]

        for link in newsletter_links:
            workspace.append("links", link)

    workspace.flags.ignore_permissions = True
    workspace.save()
    frappe.db.commit()
    frappe.clear_cache()

    return {
        "success": True,
        "message": "Workspace updated with Communication section",
        "has_comm_section": has_comm_section or True,
        "has_newsletter": has_newsletter or True,
        "total_links": len(workspace.links),
    }
