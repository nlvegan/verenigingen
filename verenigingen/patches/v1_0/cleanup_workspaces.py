"""
Migration to clean up unnecessary workspaces and modules
"""

import frappe


def execute():
    """Execute workspace cleanup migration"""

    try:
        from verenigingen.setup.workspace_setup import setup_clean_workspace

        # Run the workspace cleanup
        result = setup_clean_workspace()

        if result.get("success"):
            print("✅ Workspace cleanup completed successfully")
        else:
            print(f"❌ Workspace cleanup failed: {result.get('message')}")

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Workspace Cleanup Migration Error")
        print(f"❌ Error during workspace cleanup migration: {str(e)}")
