"""
Fix workspace missing workflow demo link
"""
import frappe


def execute():
    """Add workflow demo link to workspace"""

    try:
        # Get or create workspace
        if not frappe.db.exists("Workspace", "Verenigingen"):
            workspace = frappe.get_doc(
                {
                    "doctype": "Workspace",
                    "name": "Verenigingen",
                    "label": "Verenigingen",
                    "title": "Verenigingen",
                    "module": "Verenigingen",
                    "icon": "non-profit",
                    "public": 1,
                    "is_hidden": 0,
                }
            )
            workspace.insert(ignore_permissions=True)
            print("Created Verenigingen workspace")
        else:
            workspace = frappe.get_doc("Workspace", "Verenigingen")
            print("Found existing Verenigingen workspace")

        # Check if workflow demo link exists
        workflow_demo_exists = False
        for link in workspace.links:
            if getattr(link, "link_to", None) == "/workflow_demo":
                workflow_demo_exists = True
                break

        if not workflow_demo_exists:
            # Add workflow demo link directly to database to avoid validation
            frappe.db.sql(
                """
                INSERT INTO `tabWorkspace Link` (
                    name, parent, parenttype, parentfield, idx, type, label,
                    link_type, link_to, hidden, is_query_report, onboard, link_count
                ) VALUES (
                    %s, 'Verenigingen', 'Workspace', 'links', %s, 'Link',
                    'Membership Application Workflow Demo', 'Page', '/workflow_demo',
                    0, 0, 0, 0
                )
            """,
                (frappe.generate_hash("", 10), len(workspace.links) + 1),
            )

            print("Added workflow demo link to workspace via database")
        else:
            print("Workflow demo link already exists")

        frappe.db.commit()

    except Exception as e:
        print(f"Error fixing workspace: {str(e)}")
        frappe.db.rollback()
        raise
