#!/usr/bin/env python3
"""
Workspace Content Fixer
Fixes workspace content to match Card Break structure
"""

import json

import frappe


def fix_workspace_content(workspace_name, dry_run=True, force_enable=False):
    """Automatically fix content field to match Card Break structure"""

    # SAFETY GUARD: Prevent accidental workspace corruption
    if not force_enable:
        print("🛡️  WORKSPACE AUTO-CORRECTION DISABLED FOR SAFETY")
        print("   To enable, call with force_enable=True")
        print("   This prevents workspace corruption from broken links")
        return False

    from verenigingen.utils.workspace_analyzer import analyze_workspace

    analysis = analyze_workspace(workspace_name)

    if analysis["is_synchronized"]:
        print("✅ Workspace is already synchronized")
        return True

    workspace = frappe.get_doc("Workspace", workspace_name)
    content = json.loads(workspace.content)

    print(f"🔧 Fixing workspace content for {workspace_name}")
    print(f"Content cards to remove: {analysis['content_only']}")
    print(f"Card Breaks to add: {analysis['db_only']}")

    # Remove cards that don't have Card Breaks
    fixed_content = []
    removed_count = 0

    for item in content:
        if item.get("type") == "card" and item.get("data", {}).get("card_name") in analysis["content_only"]:
            print(f"  - Removing card: {item['data']['card_name']}")
            removed_count += 1
            continue
        fixed_content.append(item)

    print(f"Removed {removed_count} orphaned cards")

    # Note: Adding new cards requires manual intervention for proper placement
    if analysis["db_only"]:
        print("\n⚠️  Manual intervention required:")
        print("   Add these cards to the content field in appropriate locations:")
        for card_break in analysis["db_only"]:
            print(f"   - {card_break}")
        print("\n   Example card structure:")
        print('   {"id": "NewCard", "type": "card", "data": {"card_name": "Card Name", "col": 4}}')

    if not dry_run and removed_count > 0:
        # Backup original content
        backup_content = workspace.content

        try:
            workspace.content = json.dumps(fixed_content)
            workspace.flags.ignore_permissions = True
            workspace.flags.ignore_links = True
            workspace.save(ignore_permissions=True)

            frappe.clear_cache()
            frappe.db.commit()

            print("✅ Workspace content updated successfully")
            print(f"   Original items: {len(content)}")
            print(f"   Updated items: {len(fixed_content)}")

        except Exception as e:
            print(f"❌ Error updating workspace: {str(e)}")
            # Restore original content
            workspace.content = backup_content
            workspace.save(ignore_permissions=True)
            frappe.db.commit()
            return False

    elif dry_run:
        print("🚫 Dry run mode - no changes made")
        print(f"   Would remove {removed_count} orphaned cards")

    return True


def create_content_backup(workspace_name):
    """Create a backup of current workspace content"""

    workspace = frappe.get_doc("Workspace", workspace_name)

    backup_data = {
        "workspace_name": workspace_name,
        "content": workspace.content,
        "backup_timestamp": frappe.utils.now(),
        "content_length": len(workspace.content),
        "items_count": len(json.loads(workspace.content)),
    }

    backup_file = (
        f"/tmp/workspace_backup_{workspace_name}_{frappe.utils.now_datetime().strftime('%Y%m%d_%H%M%S')}.json"
    )

    with open(backup_file, "w") as f:
        json.dump(backup_data, f, indent=2)

    print(f"📦 Backup created: {backup_file}")
    return backup_file


def restore_content_backup(backup_file, dry_run=True):
    """Restore workspace content from backup"""

    try:
        with open(backup_file, "r") as f:
            backup_data = json.load(f)

        workspace_name = backup_data["workspace_name"]
        content = backup_data["content"]

        print(f"🔄 Restoring workspace content for {workspace_name}")
        print(f"   Backup timestamp: {backup_data['backup_timestamp']}")
        print(f"   Content length: {backup_data['content_length']}")
        print(f"   Items count: {backup_data['items_count']}")

        if not dry_run:
            workspace = frappe.get_doc("Workspace", workspace_name)
            workspace.content = content
            workspace.flags.ignore_permissions = True
            workspace.flags.ignore_links = True
            workspace.save(ignore_permissions=True)

            frappe.clear_cache()
            frappe.db.commit()

            print("✅ Workspace content restored successfully")
        else:
            print("🚫 Dry run mode - no changes made")

        return True

    except Exception as e:
        print(f"❌ Error restoring backup: {str(e)}")
        return False


def update_content_card_names(workspace_name, card_mapping, dry_run=True):
    """Update card names in content field

    Args:
        workspace_name: Name of the workspace
        card_mapping: Dict mapping old_name -> new_name
        dry_run: If True, don't save changes
    """

    workspace = frappe.get_doc("Workspace", workspace_name)
    content = json.loads(workspace.content)

    updated_count = 0

    for item in content:
        if item.get("type") == "card" and item.get("data", {}).get("card_name") in card_mapping:
            old_name = item["data"]["card_name"]
            new_name = card_mapping[old_name]

            print(f"  Updating: '{old_name}' → '{new_name}'")

            if not dry_run:
                item["data"]["card_name"] = new_name

            updated_count += 1

    if updated_count > 0 and not dry_run:
        workspace.content = json.dumps(content)
        workspace.flags.ignore_permissions = True
        workspace.flags.ignore_links = True
        workspace.save(ignore_permissions=True)

        frappe.clear_cache()
        frappe.db.commit()

        print(f"✅ Updated {updated_count} card names")
    elif dry_run:
        print(f"🚫 Dry run mode - would update {updated_count} card names")
    else:
        print("ℹ️  No cards matched the mapping")

    return updated_count > 0
