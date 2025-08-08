import frappe


@frappe.whitelist()
def fix_workspace_links():
    """Fix broken workspace links and add Communication section"""

    if not frappe.db.exists("Workspace", "Verenigingen"):
        return {"success": False, "message": "Workspace does not exist"}

    workspace = frappe.get_doc("Workspace", "Verenigingen")

    # Remove broken links (keep only DocType and Report links)
    valid_links = []
    removed_links = []

    for link in workspace.links:
        # Keep DocType and Report links
        if link.link_type in ["DocType", "Report"]:
            # Verify the DocType/Report exists
            if link.link_type == "DocType":
                if frappe.db.exists("DocType", link.link_to):
                    valid_links.append(link)
                else:
                    removed_links.append(f"DocType: {link.link_to}")
            elif link.link_type == "Report":
                if frappe.db.exists("Report", link.link_to):
                    valid_links.append(link)
                else:
                    removed_links.append(f"Report: {link.link_to}")
        # Keep Card Breaks
        elif link.type == "Card Break":
            valid_links.append(link)
        # Remove Page links as they're causing issues
        elif link.link_type == "Page":
            removed_links.append(f"Page: {link.link_to}")

    # Replace links with valid ones
    workspace.links = []
    for link in valid_links:
        workspace.append("links", link.as_dict())

    # Add Communication section if not present
    has_newsletter = any(link.link_to == "Newsletter" for link in workspace.links if hasattr(link, "link_to"))

    if not has_newsletter:
        # Add Communication card break
        workspace.append("links", {"label": "Communication", "type": "Card Break"})

        # Add newsletter links
        newsletter_doctypes = [
            ("Newsletter", "Create and send newsletters to members"),
            ("Email Group", "Manage email groups for targeted communication"),
            ("Email Group Member", "Manage members in email groups"),
            ("Communication", "View communication history and logs"),
            ("Email Template", "Manage email templates for automated communications"),
        ]

        for doctype, description in newsletter_doctypes:
            if frappe.db.exists("DocType", doctype):
                workspace.append(
                    "links",
                    {
                        "label": doctype,
                        "link_to": doctype,
                        "link_type": "DocType",
                        "description": description,
                    },
                )

    # Update content to include Communication section
    content_str = workspace.content
    if "CommunicationHeader" not in content_str:
        new_content = content_str.replace(
            '}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
            '}},{"id":"CommunicationHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Communication & Newsletters</b></span>","col":12}},{"id":"CommunicationCard","type":"card","data":{"card_name":"Communication","col":4}},{"id":"zGoLYG0xRM6","type":"spacer","data":{"col":12}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
        )
        workspace.content = new_content

    workspace.flags.ignore_permissions = True
    workspace.flags.ignore_validate = True
    workspace.save()
    frappe.db.commit()
    frappe.clear_cache()

    return {
        "success": True,
        "message": "Workspace links fixed and Communication section added",
        "valid_links": len(workspace.links),
        "removed_links": removed_links,
    }
