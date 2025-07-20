"""
Add Membership Application Workflow Demo link to Verenigingen workspace
"""
import frappe


def execute():
    """Add workflow demo link to workspace and reload workspace from fixtures"""

    try:
        print("🔄 Adding Membership Application Workflow Demo to workspace...")

        # First reload the workspace from fixtures to get the latest structure
        print("   📋 Reloading workspace from fixtures...")
        frappe.reload_doc("verenigingen", "workspace", "verenigingen", force=True)

        # Verify workspace exists
        if not frappe.db.exists("Workspace", "Verenigingen"):
            print("   ❌ Workspace not found after reload")
            return

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if workflow demo link already exists
        workflow_demo_exists = False
        for link in workspace.links:
            if getattr(link, "link_to", None) == "/workflow_demo":
                workflow_demo_exists = True
                break

        if workflow_demo_exists:
            print("   ✅ Workflow demo link already exists in workspace")
        else:
            print("   ⚠️ Workflow demo link missing - adding directly to database")

            # Add workflow demo link directly to database to avoid validation issues
            name = frappe.generate_hash("", 10)
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
                (name, len(workspace.links) + 1),
            )

            print("   ✅ Added workflow demo link to workspace")

        # Update the Reports card break link count if needed
        reports_card = None
        for link in workspace.links:
            if link.type == "Card Break" and link.label == "Reports":
                reports_card = link
                break

        if reports_card and reports_card.link_count < 9:
            frappe.db.sql(
                """
                UPDATE `tabWorkspace Link`
                SET link_count = 9
                WHERE parent = 'Verenigingen' AND type = 'Card Break' AND label = 'Reports'
            """
            )
            print("   ✅ Updated Reports section link count")

        frappe.db.commit()
        print("   ✅ Workspace update completed successfully")

    except Exception as e:
        print(f"   ❌ Error updating workspace: {str(e)}")
        frappe.db.rollback()
        raise
