"""
Post-Migration Hooks

Automatic workspace health maintenance after migrations to prevent
workspace corruption from DocType/Report deletions.
"""

import frappe
from frappe import _

from verenigingen.utils.validation_utilities import QueryBuilder


def run_post_migration_workspace_health():
    """
    Run workspace health checks after migrations complete.

    This function is called automatically after any migration to ensure
    workspace content remains synchronized with database structures.
    """

    try:
        print("🔍 Post-migration workspace health check...")

        # Get workspaces that might be affected by migrations
        affected_workspaces = get_potentially_affected_workspaces()

        if not affected_workspaces:
            print("ℹ️  No workspaces require post-migration health checks")
            return

        print(f"📊 Checking {len(affected_workspaces)} workspaces for migration-related issues")

        fixes_applied = 0

        for workspace_name in affected_workspaces:
            try:
                result = quick_workspace_health_check(workspace_name)
                if result and result.get("fixes_applied", 0) > 0:
                    fixes_applied += result["fixes_applied"]
                    print(f"🔧 Fixed {workspace_name}: {result.get('summary', 'Issues resolved')}")

            except Exception as e:
                print(f"⚠️  Could not check {workspace_name}: {str(e)}")
                frappe.log_error(
                    f"Post-migration workspace check failed: {str(e)}", "Post-Migration Workspace Health"
                )

        if fixes_applied > 0:
            print(
                f"✅ Post-migration workspace health: {fixes_applied} issues fixed across {len(affected_workspaces)} workspaces"
            )
        else:
            print("✅ Post-migration workspace health: All workspaces healthy")

    except Exception as e:
        print(f"⚠️  Post-migration workspace health check failed: {str(e)}")
        frappe.log_error(
            f"Post-migration workspace health failed: {str(e)}", "Post-Migration Workspace Health"
        )


def get_potentially_affected_workspaces():
    """Get workspaces that could be affected by DocType/Report changes"""

    # Focus on application-specific workspaces with Card Break structures
    workspaces = QueryBuilder.get_all_active_records(
        "Workspace",
        additional_filters={
            "public": 1,
            "is_hidden": 0,
            "module": [
                "not in",
                [
                    "Core",
                    "Website",
                    "Desk",
                    "Email",
                    "Printing",
                    "Integrations",
                    "Custom",
                    "Data Migration Tool",
                ],
            ],
        },
        fields=["name"],
    )

    # Filter for workspaces that have Card Break links (these are most vulnerable)
    vulnerable_workspaces = []
    for workspace in workspaces:
        has_card_breaks = frappe.db.exists("Workspace Link", {"parent": workspace.name, "type": "Card Break"})

        if has_card_breaks:
            vulnerable_workspaces.append(workspace.name)

    return vulnerable_workspaces


def quick_workspace_health_check(workspace_name):
    """
    Quick health check focused on migration-related issues

    Prioritizes the most common migration-caused problems:
    1. Broken links to deleted DocTypes/Reports
    2. Content/Card Break synchronization issues
    """

    try:
        # Try using the unified workspace health tool if available
        try:
            from verenigingen.api.workspace_health import quick_fix

            result = quick_fix(workspace_name)
            if result.get("success"):
                return {
                    "fixes_applied": 1 if result.get("cards_synced") else 0,
                    "summary": result.get("message", "Quick fix applied"),
                }
        except ImportError:
            pass

        # Fallback to basic check
        workspace = frappe.get_doc("Workspace", workspace_name)

        # Check for broken links (common after DocType deletions)
        broken_links = []
        for link in workspace.links:
            if link.type == "DocType" and not frappe.db.exists("DocType", link.link_to):
                broken_links.append(link)
            elif link.type == "Report" and not frappe.db.exists("Report", link.link_to):
                broken_links.append(link)

        # Remove broken links
        fixes_applied = 0
        if broken_links:
            for link in broken_links:
                workspace.remove(link)
            workspace.save()
            frappe.db.commit()
            fixes_applied += len(broken_links)
            print(f"🗑️  Removed {len(broken_links)} broken links from {workspace_name}")

        # Basic content sync check
        card_breaks = [link.label for link in workspace.links if link.type == "Card Break"]
        if card_breaks:
            try:
                import json

                content_cards = []
                if workspace.content and workspace.content != "[]":
                    content = json.loads(workspace.content)
                    content_cards = [
                        item["data"]["card_name"]
                        for item in content
                        if item.get("type") == "card" and "card_name" in item.get("data", {})
                    ]

                # Quick sync if major mismatch
                if len(content_cards) == 0 and len(card_breaks) > 0:
                    new_content = []
                    for i, card_name in enumerate(card_breaks):
                        new_content.append(
                            {"id": f"card_{i}", "type": "card", "data": {"card_name": card_name, "col": 4}}
                        )

                    workspace.content = json.dumps(new_content)
                    workspace.save()
                    frappe.db.commit()
                    fixes_applied += 1
                    print(f"🔧 Synchronized content for {workspace_name}")

            except (json.JSONDecodeError, KeyError):
                pass

        return {
            "fixes_applied": fixes_applied,
            "summary": (
                f"{fixes_applied} migration-related issues fixed" if fixes_applied > 0 else "No issues found"
            ),
        }

    except Exception as e:
        frappe.log_error(
            f"Quick workspace health check failed for {workspace_name}: {str(e)}",
            "Quick Workspace Health Check",
        )
        return None


def cleanup_orphaned_workspace_links():
    """
    Clean up workspace links that point to non-existent targets

    This is a focused cleanup for migration-related orphaned references.
    """

    try:
        print("🧹 Cleaning up orphaned workspace links...")

        # Get all workspace links
        links = frappe.get_all(
            "Workspace Link",
            fields=["name", "parent", "label", "type", "link_to"],
            filters={"type": ["in", ["DocType", "Report", "Dashboard"]]},
        )

        orphaned_links = []

        for link in links:
            target_exists = False

            if link.type == "DocType":
                target_exists = frappe.db.exists("DocType", link.link_to)
            elif link.type == "Report":
                target_exists = frappe.db.exists("Report", link.link_to)
            elif link.type == "Dashboard":
                target_exists = frappe.db.exists("Dashboard", link.link_to)

            if not target_exists:
                orphaned_links.append(link)

        if orphaned_links:
            # Group by workspace for better reporting
            workspace_orphans = {}
            for link in orphaned_links:
                if link.parent not in workspace_orphans:
                    workspace_orphans[link.parent] = []
                workspace_orphans[link.parent].append(link)

            # Remove orphaned links
            # Security: Migration hook - runs during bench migrate with elevated privileges
            for link in orphaned_links:
                frappe.delete_doc("Workspace Link", link.name, ignore_permissions=True)

            frappe.db.commit()

            print(
                f"🗑️  Removed {len(orphaned_links)} orphaned links from {len(workspace_orphans)} workspaces"
            )
            for workspace, links in workspace_orphans.items():
                print(f"   - {workspace}: {len(links)} orphaned links removed")
        else:
            print("✅ No orphaned workspace links found")

    except Exception as e:
        print(f"⚠️  Orphaned link cleanup failed: {str(e)}")
        frappe.log_error(f"Orphaned workspace link cleanup failed: {str(e)}", "Workspace Link Cleanup")
