"""
Fix Onboarding Visibility by linking Module Onboarding to Workspace
"""

import frappe


def execute():
    """Link Module Onboarding to Verenigingen workspace to show setup banner"""

    try:
        if not frappe.db.exists("Workspace", "Verenigingen"):
            print("⚠️ Verenigingen workspace doesn't exist - skipping onboarding fix")
            return

        workspace = frappe.get_doc("Workspace", "Verenigingen")

        # Check if module_onboarding field is set
        if not hasattr(workspace, "module_onboarding") or not workspace.module_onboarding:
            workspace.module_onboarding = "Verenigingen"
            workspace.save(ignore_permissions=True)
            print("✅ Fixed: Linked Module Onboarding to workspace")

            # Commit the change
            frappe.db.commit()

        else:
            print("✅ Module Onboarding already linked to workspace")

        # Check if Module Onboarding document exists
        if not frappe.db.exists("Module Onboarding", "Verenigingen"):
            print("⚠️ Warning: Module Onboarding 'Verenigingen' document not found")
            print(
                "   Run: bench --site your-site execute verenigingen.install_onboarding.install_module_onboarding"
            )
        else:
            print("✅ Module Onboarding document exists")

    except Exception as e:
        print(f"❌ Failed to fix onboarding visibility: {str(e)}")
        # Don't raise the exception to avoid breaking the migration
        frappe.log_error(f"Onboarding visibility fix failed: {str(e)}", "Onboarding Fix Error")
