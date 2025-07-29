"""
Create or update onboarding steps for Verenigingen
"""

import frappe

from verenigingen.utils.security.api_security_framework import OperationType, critical_api


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_test_data_onboarding_step():
    """
    Create an onboarding step for generating test data
    """
    try:
        # Check if Module Onboarding exists
        if not frappe.db.exists("Module Onboarding", "Verenigingen"):
            # Create Module Onboarding
            onboarding = frappe.new_doc("Module Onboarding")
            onboarding.module = "Verenigingen"
            onboarding.title = "Verenigingen Setup"
            onboarding.subtitle = "Get started with association management"
            onboarding.success_message = "Congratulations! Verenigingen is set up and ready to use."
            onboarding.documentation_url = "/generate_test_data"
            onboarding.insert(ignore_permissions=True)
        else:
            onboarding = frappe.get_doc("Module Onboarding", "Verenigingen")

        # Check if test data step exists
        existing_step = frappe.db.exists(
            "Onboarding Step", {"title": "Generate Test Data", "reference_document": "Membership Application"}
        )

        if not existing_step:
            # Create onboarding step
            step = frappe.new_doc("Onboarding Step")
            step.title = "Generate Test Data"
            step.description = "Create sample membership applications to explore the review workflow"
            step.reference_document = "Membership Application"
            step.action = "Go to Page"
            step.action_url = "/generate_test_data"
            step.is_single = 0
            step.is_mandatory = 0
            step.show_full_form = 0
            step.insert(ignore_permissions=True)

            # Link to module onboarding
            onboarding.append("steps", {"step": step.name})
            onboarding.save(ignore_permissions=True)

            return {
                "success": True,
                "message": "Test data onboarding step created successfully",
                "step_name": step.name,
                "onboarding_url": f"/app/module-onboarding/{onboarding.name}",
            }
        else:
            return {
                "success": True,
                "message": "Test data onboarding step already exists",
                "existing_step": existing_step,
                "onboarding_url": f"/app/module-onboarding/{onboarding.name}",
            }

    except Exception as e:
        frappe.log_error(f"Failed to create onboarding step: {str(e)}")
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def add_quick_start_card():
    """
    Add a quick start card to the Verenigingen workspace
    """
    try:
        # Check if workspace exists
        workspace_name = "Verenigingen"
        if not frappe.db.exists("Workspace", workspace_name):
            # Create workspace
            workspace = frappe.new_doc("Workspace")
            workspace.name = workspace_name
            workspace.title = "Verenigingen"
            workspace.module = "Verenigingen"
            workspace.icon = "users"
            workspace.insert(ignore_permissions=True)
        else:
            workspace = frappe.get_doc("Workspace", workspace_name)

        # Check if quick start card exists
        has_test_data_card = False
        for card in workspace.cards:
            if card.label == "Generate Test Data":
                has_test_data_card = True
                break

        if not has_test_data_card:
            # Add quick start card
            workspace.append(
                "cards",
                {
                    "card_name": "Generate Test Data",
                    "label": "Generate Test Data",
                    "type": "Link",
                    "link_to": "/generate_test_data",
                    "icon": "fa fa-database",
                    "description": "Create sample membership applications to test the system",
                },
            )
            workspace.save(ignore_permissions=True)

            return {"success": True, "message": "Quick start card added to workspace"}
        else:
            return {"success": True, "message": "Quick start card already exists"}

    except Exception as e:
        frappe.log_error(f"Failed to add quick start card: {str(e)}")
        return {"success": False, "error": str(e)}
