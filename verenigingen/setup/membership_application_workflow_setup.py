"""
Membership Application Workflow Setup
Creates a formal workflow for membership application process
"""

import frappe

from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


def create_membership_application_workflow():
    """Create membership application workflow"""

    workflow_name = "Membership Application Workflow"

    if frappe.db.exists("Workflow", workflow_name):
        print(f"   ✓ Workflow '{workflow_name}' already exists")
        return True

    print(f"   📋 Creating membership application workflow: {workflow_name}")

    try:
        workflow_doc = frappe.new_doc("Workflow")
        workflow_doc.workflow_name = workflow_name
        workflow_doc.document_type = "Member"
        workflow_doc.is_active = 1
        workflow_doc.workflow_state_field = "application_status"
        workflow_doc.send_email_alert = 1  # Enable email alerts for application workflow

        # State 1: Pending (Initial application)
        workflow_doc.append(
            "states",
            {
                "state": "Pending",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",
                "message": "Application received and awaiting initial review",
            },
        )

        # State 2: Under Review (Being evaluated)
        workflow_doc.append(
            "states",
            {
                "state": "Under Review",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",
                "message": "Application is being reviewed by administration",
            },
        )

        # State 3: Approved (Application approved)
        workflow_doc.append(
            "states",
            {
                "state": "Approved",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",
                "message": "Application approved - awaiting payment or activation",
            },
        )

        # State 4: Payment Pending (Approved but payment needed)
        workflow_doc.append(
            "states",
            {
                "state": "Payment Pending",
                "doc_status": "0",
                "allow_edit": "Verenigingen Administrator",
                "message": "Application approved - payment required to activate membership",
            },
        )

        # State 5: Active (Member activated)
        workflow_doc.append(
            "states",
            {
                "state": "Active",
                "doc_status": "1",
                "allow_edit": "Verenigingen Administrator",
                "message": "Member is active and in good standing",
            },
        )

        # State 6: Rejected (Application denied)
        workflow_doc.append(
            "states",
            {
                "state": "Rejected",
                "doc_status": "0",  # Keep as draft, not cancelled
                "allow_edit": "System Manager",
                "message": "Application has been rejected",
            },
        )

        # TRANSITIONS

        # Pending -> Under Review (Start Review)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Start Review",
                "next_state": "Under Review",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Pending -> Under Review (System Manager)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Start Review",
                "next_state": "Under Review",
                "allowed": "System Manager",
            },
        )

        # Under Review -> Approved (Approve)
        workflow_doc.append(
            "transitions",
            {
                "state": "Under Review",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Under Review -> Approved (System Manager)
        workflow_doc.append(
            "transitions",
            {
                "state": "Under Review",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "System Manager",
            },
        )

        # Under Review -> Rejected (Reject)
        workflow_doc.append(
            "transitions",
            {
                "state": "Under Review",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Under Review -> Rejected (System Manager)
        workflow_doc.append(
            "transitions",
            {
                "state": "Under Review",
                "action": "Reject",
                "next_state": "Rejected",
                "allowed": "System Manager",
            },
        )

        # Approved -> Payment Pending (Request Payment)
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Request Payment",
                "next_state": "Payment Pending",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Approved -> Active (Direct Activation - for free memberships)
        workflow_doc.append(
            "transitions",
            {
                "state": "Approved",
                "action": "Activate",
                "next_state": "Active",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Approved -> Active (System Manager)
        workflow_doc.append(
            "transitions",
            {"state": "Approved", "action": "Activate", "next_state": "Active", "allowed": "System Manager"},
        )

        # Payment Pending -> Active (Confirm Payment)
        workflow_doc.append(
            "transitions",
            {
                "state": "Payment Pending",
                "action": "Confirm Payment",
                "next_state": "Active",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Payment Pending -> Active (System Manager)
        workflow_doc.append(
            "transitions",
            {
                "state": "Payment Pending",
                "action": "Confirm Payment",
                "next_state": "Active",
                "allowed": "System Manager",
            },
        )

        # Direct transitions for fast-track approvals
        # Pending -> Approved (Direct Approve)
        workflow_doc.append(
            "transitions",
            {
                "state": "Pending",
                "action": "Approve",
                "next_state": "Approved",
                "allowed": "Verenigingen Administrator",
            },
        )

        # Pending -> Approved (System Manager)
        workflow_doc.append(
            "transitions",
            {"state": "Pending", "action": "Approve", "next_state": "Approved", "allowed": "System Manager"},
        )

        # Pending -> Rejected (Direct Reject)
        workflow_doc.append(
            "transitions",
            {"state": "Pending", "action": "Reject", "next_state": "Rejected", "allowed": "System Manager"},
        )

        # Save the workflow
        # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
        result = secure_document_operation(
            operation="insert",
            doc=workflow_doc,
            justification="Create membership application workflow - system setup and governance automation",
            required_permissions=["Workflow:create"],
        )

        if not result.success:
            frappe.log_error(f"Failed to create workflow: {'; '.join(result.errors)}")
            return False

        workflow_doc = result.doc

        print(
            f"   ✅ Successfully created membership application workflow with {len(workflow_doc.states)} states and {len(workflow_doc.transitions)} transitions"
        )
        return True

    except Exception as e:
        print(f"   ❌ Failed to create membership application workflow: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def create_membership_workflow_action_masters():
    """Create custom workflow actions for membership application"""

    print("   ⚡ Creating membership workflow action masters...")

    custom_actions = ["Start Review", "Request Payment", "Confirm Payment", "Activate"]

    created_count = 0

    for action in custom_actions:
        from verenigingen.utils.validation_utilities import DocumentExistenceValidator

        if not DocumentExistenceValidator.validate_document_exists(
            "Workflow Action Master", action, throw_on_error=False
        ):
            try:
                action_doc = frappe.get_doc(
                    {"doctype": "Workflow Action Master", "workflow_action_name": action}
                )
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="insert",
                    doc=action_doc,
                    justification=f"Create workflow action {action_data['action']} - membership application workflow setup",
                    required_permissions=["Workflow Action:create"],
                )

                if not result.success:
                    frappe.log_error(
                        f"Failed to create workflow action {action_data['action']}: {'; '.join(result.errors)}"
                    )
                    continue  # Continue with other actions
                created_count += 1
                print(f"      ✓ Created workflow action: {action}")
            except Exception as e:
                print(f"      ⚠️ Could not create action {action}: {str(e)}")
        else:
            print(f"      ✓ Action already exists: {action}")

    return created_count


def create_membership_workflow_state_masters():
    """Create custom workflow states for membership application"""

    print("   🏗️ Creating membership workflow state masters...")

    # Create all states that might not exist
    custom_states = ["Under Review", "Payment Pending", "Active"]

    created_count = 0

    for state in custom_states:
        if not DocumentExistenceValidator.validate_document_exists(
            "Workflow State", state, throw_on_error=False
        ):
            try:
                state_doc = frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state})
                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                result = secure_document_operation(
                    operation="insert",
                    doc=state_doc,
                    justification=f"Create workflow state {state_data['state']} - membership application workflow setup",
                    required_permissions=["Workflow State:create"],
                )

                if not result.success:
                    frappe.log_error(
                        f"Failed to create workflow state {state_data['state']}: {'; '.join(result.errors)}"
                    )
                    continue  # Continue with other states
                created_count += 1
                print(f"      ✓ Created workflow state: {state}")
            except Exception as e:
                print(f"      ⚠️ Could not create state {state}: {str(e)}")
        else:
            print(f"      ✓ State already exists: {state}")

    return created_count


def validate_membership_workflow_prerequisites():
    """Validate prerequisites for membership workflow creation"""

    print("   🔍 Validating membership workflow prerequisites...")

    issues = []

    # Check Member doctype exists
    if not frappe.db.exists("DocType", "Member"):
        issues.append("Missing DocType: Member")
    else:
        # Check that application_status field exists
        member_meta = frappe.get_meta("Member")
        if not member_meta.get_field("application_status"):
            issues.append("Missing field: application_status in Member doctype")

    # Check required roles exist
    required_roles = ["System Manager", "Verenigingen Administrator"]
    for role in required_roles:
        if not frappe.db.exists("Role", role):
            issues.append(f"Missing Role: {role}")

    if issues:
        print("   ❌ Prerequisites validation failed:")
        for issue in issues:
            print(f"      - {issue}")
        return False

    print("   ✅ All membership workflow prerequisites validated")
    return True


def setup_membership_application_workflow():
    """Main function to setup membership application workflow"""

    print("🔄 Setting up Membership Application Workflow...")

    # Step 1: Validate prerequisites
    if not validate_membership_workflow_prerequisites():
        return False

    success_count = 0

    # Step 2: Create workflow masters if needed
    try:
        states_created = create_membership_workflow_state_masters()
        actions_created = create_membership_workflow_action_masters()

        if states_created > 0 or actions_created > 0:
            frappe.db.commit()
            print(f"   ✅ Created {states_created} states and {actions_created} actions")
    except Exception as e:
        print(f"   ⚠️ Warning creating masters: {str(e)}")

    # Step 3: Create membership application workflow
    if create_membership_application_workflow():
        success_count += 1

    # Step 4: Commit all changes
    try:
        frappe.db.commit()
        print("   ✅ Successfully committed membership application workflow")
        return success_count > 0
    except Exception as e:
        print(f"   ❌ Commit failed: {str(e)}")
        frappe.db.rollback()
        return False


# API endpoint
@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def setup_membership_workflow():
    """API endpoint for membership workflow setup"""
    return setup_membership_application_workflow()


# Main execution
if __name__ == "__main__":
    setup_membership_application_workflow()
