#!/usr/bin/env python3

import frappe


@frappe.whitelist()
def check_workspace_status():
    """Check workspace status in database vs file"""

    result = {}

    # Check if workspace exists in database
    db_workspace = frappe.db.sql(
        """
        SELECT name, public, is_hidden, modified, modified_by, for_user
        FROM `tabWorkspace`
        WHERE name = 'Verenigingen'
    """,
        as_dict=True,
    )

    result["db_workspace"] = db_workspace[0] if db_workspace else None

    # Get workspace links from database
    db_links = frappe.db.sql(
        """
        SELECT link_to, label, hidden, link_type, type
        FROM `tabWorkspace Link`
        WHERE parent = 'Verenigingen'
        ORDER BY idx
    """,
        as_dict=True,
    )

    result["db_links_count"] = len(db_links)
    result["db_links"] = db_links[:10]  # First 10 for brevity

    # Check if we can get the workspace document
    try:
        workspace_doc = frappe.get_doc("Workspace", "Verenigingen")
        result["doc_links_count"] = len(workspace_doc.links)
        result["doc_source"] = "database" if workspace_doc.is_saved() else "file"
    except Exception as e:
        result["doc_error"] = str(e)

    return result


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    result = check_workspace_status()
    print("=== Workspace Status Check ===")

    if result.get("db_workspace"):
        print(f"✅ Database workspace found:")
        print(f"   Modified: {result['db_workspace']['modified']}")
        print(f"   Modified by: {result['db_workspace']['modified_by']}")
        print(f"   Public: {result['db_workspace']['public']}")
        print(f"   For user: {result['db_workspace']['for_user']}")
    else:
        print("❌ No database workspace found")

    print(f"\n📊 Links in database: {result['db_links_count']}")
    print(f"📄 Document links count: {result.get('doc_links_count', 'N/A')}")
    print(f"🗂️ Document source: {result.get('doc_source', 'N/A')}")

    if result.get("db_links"):
        print("\nFirst 10 database links:")
        for link in result["db_links"]:
            print(f"  - {link['label']} ({link['link_type']}) - Hidden: {link['hidden']}")

    frappe.destroy()
