#!/usr/bin/env python3
"""
Check workspace status and identify issues
"""
import os
import sys

# Add the frappe bench to Python path
sys.path.insert(0, "/home/frappe/frappe-bench/apps/frappe")
sys.path.insert(0, "/home/frappe/frappe-bench")

import frappe  # noqa: E402


def check_workspace():
    # Connect to the site
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Get the workspace from database
        workspace = frappe.get_doc("Workspace", "Verenigingen")

        print(f"Workspace: {workspace.name}")
        print(f"Modified: {workspace.modified}")
        print(f"Number of links: {len(workspace.links)}")
        print(f"Public: {workspace.public}")
        print(f"Hidden: {workspace.is_hidden}")

        # Check for workflow demo link
        workflow_demo_link = None
        for link in workspace.links:
            if link.link_to == "/workflow_demo":
                workflow_demo_link = link
                break

        if workflow_demo_link:
            print(f"✅ Workflow demo link found: {workflow_demo_link.label}")
        else:
            print("❌ Workflow demo link NOT found")
            print("Available page links:")
            for link in workspace.links:
                if link.link_type == "Page":
                    print(f"  - {link.label} -> {link.link_to}")

        # Check for any broken links
        broken_links = []
        for link in workspace.links:
            if link.link_type == "DocType":
                if not frappe.db.exists("DocType", link.link_to):
                    broken_links.append(f"DocType: {link.link_to}")
            elif link.link_type == "Report":
                if not frappe.db.exists("Report", link.link_to):
                    broken_links.append(f"Report: {link.link_to}")

        if broken_links:
            print("❌ Broken links found:")
            for broken in broken_links:
                print(f"  - {broken}")
        else:
            print("✅ No broken links found")

    except Exception as e:
        print(f"❌ Error checking workspace: {str(e)}")
        import traceback

        traceback.print_exc()

    finally:
        frappe.destroy()


if __name__ == "__main__":
    check_workspace()
