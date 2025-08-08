import frappe


@frappe.whitelist()
def fix_workspace():
    # Check if Verenigingen workspace exists
    if frappe.db.exists("Workspace", "Verenigingen"):
        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if Newsletter link already exists
        has_newsletter = any(link.link_to == "Newsletter" for link in workspace.links)

        if not has_newsletter:
            print("Adding Communication links to workspace...")

            # Add Communication section to content
            content_str = workspace.content
            if "CommunicationHeader" not in content_str:
                # Insert Communication section after Teams section
                new_content = content_str.replace(
                    '}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
                    '}},{"id":"CommunicationHeader","type":"header","data":{"text":"<span class=\\"h4\\"><b>Communication & Newsletters</b></span>","col":12}},{"id":"CommunicationCard","type":"card","data":{"card_name":"Communication","col":4}},{"id":"zGoLYG0xRM6","type":"spacer","data":{"col":12}},{"id":"jMy1CTqEJS3","type":"header","data":{"text":"<span class=\\"h4\\"><b>Financial</b></span>"',
                )
                workspace.content = new_content

            # Add Newsletter links
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
            workspace.save()
            frappe.db.commit()

            # Clear cache
            frappe.clear_cache()

            return "Workspace updated successfully! Newsletter links added."
        else:
            return "Newsletter links already exist in workspace."
    else:
        return "Verenigingen workspace not found!"
