"""
Workspace Health Migration Patch

Addresses workspace corruption caused by DocType/Report deletions during migrations.
Runs comprehensive workspace health checks and repairs after major structural changes.

This patch ensures that workspace content fields remain synchronized with Card Break
structures even after DocTypes or Reports are removed during application updates.
"""

import frappe
from frappe import _


def execute():
    """Execute workspace health checks and repairs for all workspaces"""

    print("🔍 Running workspace health migration...")

    # Get all application workspaces that might be affected by migrations
    workspace_names = get_application_workspaces()

    if not workspace_names:
        print("ℹ️  No application workspaces found to check")
        return

    print(f"📊 Found {len(workspace_names)} workspaces to check: {', '.join(workspace_names)}")

    # Track results
    results = {"healthy": [], "fixed": [], "failed": []}

    # Process each workspace
    for workspace_name in workspace_names:
        try:
            result = check_and_fix_workspace(workspace_name)

            if result["success"]:
                if result["fixes_applied"] > 0:
                    results["fixed"].append(
                        {
                            "name": workspace_name,
                            "issues": result["issues_found"],
                            "fixes": result["fixes_applied"],
                        }
                    )
                    print(f"✅ Fixed {workspace_name}: {result['fixes_applied']} issues resolved")
                else:
                    results["healthy"].append(workspace_name)
                    print(f"✅ {workspace_name}: Already healthy")
            else:
                results["failed"].append(
                    {"name": workspace_name, "error": result.get("error", "Unknown error")}
                )
                print(f"❌ Failed to fix {workspace_name}: {result.get('error')}")

        except Exception as e:
            results["failed"].append({"name": workspace_name, "error": str(e)})
            print(f"❌ Exception fixing {workspace_name}: {str(e)}")
            frappe.log_error(
                f"Workspace health migration failed for {workspace_name}: {str(e)}",
                "Workspace Health Migration",
            )

    # Summary report
    print("\n📋 Workspace Health Migration Summary:")
    print(f"   ✅ Healthy: {len(results['healthy'])} workspaces")
    print(f"   🔧 Fixed: {len(results['fixed'])} workspaces")
    print(f"   ❌ Failed: {len(results['failed'])} workspaces")

    if results["fixed"]:
        print("\n🔧 Workspaces Fixed:")
        for fixed in results["fixed"]:
            print(f"   - {fixed['name']}: {fixed['fixes']} fixes applied")

    if results["failed"]:
        print("\n❌ Workspaces with Issues:")
        for failed in results["failed"]:
            print(f"   - {failed['name']}: {failed['error']}")

    print("\n✅ Workspace health migration completed")


def get_application_workspaces():
    """Get list of application-specific workspaces to check"""

    # Get workspaces that belong to custom applications (not core Frappe/ERPNext)
    workspaces = frappe.get_all(
        "Workspace",
        filters={
            "module": ["not in", ["Core", "Website", "Desk", "Email", "Printing", "Integrations"]],
            "public": 1,
            "is_hidden": 0,
        },
        fields=["name", "module", "label"],
    )

    # Filter for workspaces that are likely to have Card Break structures
    relevant_workspaces = []
    for workspace in workspaces:
        # Check if workspace has Card Breaks (indicates it uses the card structure)
        card_breaks = frappe.db.count("Workspace Link", {"parent": workspace.name, "type": "Card Break"})

        if card_breaks > 0:
            relevant_workspaces.append(workspace.name)

    return relevant_workspaces


def check_and_fix_workspace(workspace_name):
    """Check and fix a single workspace using the unified health tool"""

    try:
        # Import here to avoid import issues during migration
        from verenigingen.api.workspace_health import WorkspaceHealthManager

        manager = WorkspaceHealthManager(workspace_name)
        result = manager.diagnose_and_fix(auto_fix=True, create_backup=True)

        return result

    except ImportError:
        # Fallback if the workspace health tool isn't available
        print(f"⚠️  Workspace health tool not available, using fallback for {workspace_name}")
        return check_and_fix_workspace_fallback(workspace_name)


def check_and_fix_workspace_fallback(workspace_name):
    """Fallback workspace fix without the unified health tool"""

    try:
        workspace = frappe.get_doc("Workspace", workspace_name)

        # Simple content sync fix
        card_breaks = [link.label for link in workspace.links if link.type == "Card Break"]

        if not card_breaks:
            return {"success": True, "issues_found": 0, "fixes_applied": 0}

        # Check if content needs sync
        import json

        try:
            if workspace.content and workspace.content != "[]":
                content = json.loads(workspace.content)
                content_cards = [
                    item["data"]["card_name"]
                    for item in content
                    if item.get("type") == "card" and "card_name" in item.get("data", {})
                ]
            else:
                content_cards = []
        except json.JSONDecodeError:
            content_cards = []

        # Fix if out of sync
        missing_cards = [cb for cb in card_breaks if cb not in content_cards]

        if missing_cards or len(content_cards) == 0:
            # Generate new content
            new_content = []
            for i, card_name in enumerate(card_breaks):
                new_content.append(
                    {
                        "id": f"card_{i}",
                        "type": "card",
                        "data": {"card_name": card_name, "col": 4 if len(card_breaks) > 2 else 6},
                    }
                )

            workspace.content = json.dumps(new_content)
            workspace.save()
            frappe.db.commit()

            return {
                "success": True,
                "issues_found": 1,
                "fixes_applied": 1,
                "summary": f"Synchronized {len(card_breaks)} Card Breaks",
            }

        return {"success": True, "issues_found": 0, "fixes_applied": 0}

    except Exception as e:
        return {"success": False, "error": str(e)}
