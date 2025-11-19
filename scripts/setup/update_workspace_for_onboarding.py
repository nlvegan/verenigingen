#!/usr/bin/env python3


def update_workspace_onboarding():
    """Update workspace to include onboarding"""
    import frappe

    frappe.init(site="dev.veganisme.net")
    frappe.connect()

    try:
        # Get workspace
        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if setup guide shortcut exists
        setup_exists = False
        for shortcut in workspace.shortcuts:
            if "setup" in (shortcut.label or "").lower():
                setup_exists = True
                break

        if not setup_exists:
            # Create new shortcut document
            shortcut_doc = frappe.get_doc(
                {
                    "doctype": "Workspace Shortcut",
                    "label": "🚀 Setup Guide",
                    "type": "DocType",
                    "link_to": "Module Onboarding",
                    "color": "Green",
                }
            )

            # Insert at beginning of shortcuts
            workspace.shortcuts.insert(0, shortcut_doc)
            workspace.save()
            frappe.db.commit()

            print("✅ Added Setup Guide shortcut to Verenigingen workspace")
            return True
        else:
            print("ℹ️ Setup guide shortcut already exists")
            return True

    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

    finally:
        frappe.destroy()


if __name__ == "__main__":
    update_workspace_onboarding()
