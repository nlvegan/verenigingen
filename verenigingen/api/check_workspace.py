import json

import frappe


@frappe.whitelist()
def check_workspace():
    if frappe.db.exists("Workspace", "Verenigingen"):
        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check links
        newsletter_links = [
            link
            for link in workspace.links
            if "Newsletter" in link.label or "Communication" in link.label or "Email" in link.label
        ]

        print(f"Found {len(newsletter_links)} communication-related links:")
        for link in newsletter_links:
            print(f"  - {link.label}: {link.link_to} ({link.link_type})")

        # Check content for Communication card
        has_comm_card = "CommunicationCard" in workspace.content or "CommunicationHeader" in workspace.content
        print(f"\nHas Communication Card in content: {has_comm_card}")

        # Force refresh
        frappe.clear_cache()
        print("\nCache cleared. Please refresh your browser to see the changes.")

        return {
            "newsletter_links": len(newsletter_links),
            "has_communication_card": has_comm_card,
            "message": "Refresh your browser (Ctrl+F5) to see the Communication section in the Verenigingen workspace",
        }
    else:
        return "Workspace not found"
